# tools/codec_matrix/run_matrix.py
"""
Corre la matriz de compatibilidad codec<->contenedor contra un ffmpeg real, con mux de
prueba (no encode completo). Pensado para re-correrse cada vez que se actualiza el
ffmpeg empaquetado de DowP, o antes de una release grande, para detectar regresiones.

Para audio, ademas de "¿el contenedor acepta el codec?" prueba canales (mono/estereo/
5.1) en dos niveles: a nivel de encoder puro ("channels" del codec) y cruzado con cada
contenedor ("channels" dentro de cada entrada de "containers"), para casos donde el
muxer en si restringe canales aunque el encoder los soporte (ej. 3GP/AMR).

Uso:
    python tools/codec_matrix/run_matrix.py
    python tools/codec_matrix/run_matrix.py --ffmpeg "C:\\ruta\\a\\otro\\ffmpeg.exe"

Guarda el resultado crudo en tools/codec_matrix/runs/<version_ffmpeg>.json (y una copia
en runs/latest.json), listo para build_runtime_json.py o diff_runs.py.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from codec_specs import CONTAINERS, VIDEO_CODECS, AUDIO_CODECS, MXF_COMPANION_VIDEO_ENCODER, MXF_REQUIRED_AUDIO_RATE

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_FFMPEG = os.path.join(REPO_ROOT, "bin", "dependences", "ffmpeg", "ffmpeg.exe")
RUNS_DIR = os.path.join(os.path.dirname(__file__), "runs")
TMP_DIR = os.path.join(os.path.dirname(__file__), "_tmp_probe")

TIMEOUT = 10

_BOILERPLATE_PREFIXES = (
    "Error sending frames to consumers", "Task finished with error code",
    "Terminating thread with return code", "Nothing was written into output file",
    "Could not open encoder before EOF", "encoded 0 frames",
)
# Banners informativos/de progreso de encoders (x265, SVT-AV1, aom, etc.) - formatos
# como "x265 [info]: ...", "Svt[info]: ...", "Svt [config]: ...". Nunca son el motivo
# real de un fallo de mux, asi que se descartan sin importar mayusculas/formato exacto.
_INFO_BANNER_RE = re.compile(r"^[A-Za-z0-9_.\-]*\s?\[(info|warning|config|version|build)\]", re.IGNORECASE)


def _first_meaningful_line(stderr_text):
    for line in stderr_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if _INFO_BANNER_RE.match(line):
            continue
        if any(p in line for p in _BOILERPLATE_PREFIXES):
            continue
        return line
    return stderr_text.splitlines()[0].strip() if stderr_text.strip() else None


def _run(cmd):
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
        return res.returncode, (res.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    except Exception as e:
        return -1, str(e)


def _video_source_cmd(ffmpeg, spec):
    size = spec.get("size", "256x256")
    fps = spec.get("fps", "25")
    cmd = [ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=black:s={size}:r={fps}:d=0.4"]
    if spec.get("pix_fmt"):
        cmd += ["-pix_fmt", spec["pix_fmt"]]
    cmd += ["-frames:v", "5", "-c:v", spec["encoder"]]
    cmd += spec.get("extra", [])
    return cmd


def _audio_source_cmd(ffmpeg, spec, ar_override=None):
    ar = ar_override or spec.get("ar", 44100)
    ac = spec.get("ac", 2)
    cmd = [ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=1000:duration=0.4:sample_rate={ar}", "-ac", str(ac)]
    cmd += ["-c:a", spec["encoder"]]
    cmd += spec.get("extra", [])
    return cmd


def _audio_paired_mxf_cmd(ffmpeg, spec):
    """MXF exige un track de video primero y audio a 48kHz. Se arma un mux con
    companion de video valido para poder juzgar el codec de audio en si."""
    ar = spec.get("ar") or MXF_REQUIRED_AUDIO_RATE
    ac = spec.get("ac", 2)
    cmd = [
        ffmpeg, "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=black:s=256x256:r=25:d=0.4",
        "-f", "lavfi", "-i", f"sine=frequency=1000:duration=0.4:sample_rate={ar}",
        "-map", "0:v", "-map", "1:a",
        "-c:v", MXF_COMPANION_VIDEO_ENCODER,
        "-ac", str(ac), "-c:a", spec["encoder"],
    ]
    cmd += spec.get("extra", [])
    return cmd


_CHANNEL_COUNTS = (1, 2, 6)


def _channels_probe_cmd(ffmpeg, spec, cont_id, muxer, out_path, ac):
    """Arma el comando de mux para un (codec, contenedor, canales) puntual. Reusa el
    companion de video de MXF cuando corresponde, igual que el mux "base" del contenedor."""
    spec_copy = dict(spec)
    spec_copy["ac"] = ac
    if cont_id == "mxf":
        base_cmd = _audio_paired_mxf_cmd(ffmpeg, spec_copy)
    else:
        base_cmd = _audio_source_cmd(ffmpeg, spec_copy)
    return base_cmd + ["-f", muxer, out_path]


def _probe_dimension_alignment(ffmpeg, spec):
    """Prueba si el encoder de un codec de VIDEO acepta ancho impar y alto impar por
    separado (perturbando en -1 el 'size' que ya tiene el spec), directo a '-f null -' sin
    contenedor de por medio — mismo estilo liviano que las pruebas de canales de audio a
    nivel de encoder. Para codecs de tamano fijo obligatorio (QCIF, DV PAL, DNxHD 1080p) el
    encoder va a rechazar el tamano alterado igual (por motivo distinto a paridad), y el
    resultado por defecto queda 'par requerido' - lado seguro, y no importa en la practica
    porque esos codecs no se usan con resolucion Personalizada de todos modos."""
    w, h = (int(x) for x in spec.get("size", "256x256").split("x"))
    odd_w = w if w % 2 == 1 else w - 1
    odd_h = h if h % 2 == 1 else h - 1

    def _accepts(size_str):
        spec_copy = dict(spec)
        spec_copy["size"] = size_str
        cmd = _video_source_cmd(ffmpeg, spec_copy) + ["-f", "null", "-"]
        rc, _ = _run(cmd)
        return rc == 0

    return {
        "width_even_required": not _accepts(f"{odd_w}x{h}"),
        "height_even_required": not _accepts(f"{w}x{odd_h}"),
    }


def probe(ffmpeg, kind, name, spec):
    if not spec.get("encoder"):
        return {"testable": False, "skip_reason": spec.get("skip_reason", "Sin encoder disponible."), "containers": {}}

    # Canales a nivel de ENCODER (sin contenedor de por medio, "-f null -"). Es el limite
    # mas basico: si el encoder no puede producir N canales, ningun contenedor va a poder
    # tampoco, asi que este resultado se usa para saltear pruebas de mux redundantes abajo.
    channels_out = {}
    if kind == "audio":
        for ac in _CHANNEL_COUNTS:
            spec_copy = dict(spec)
            spec_copy["ac"] = ac
            cmd = _audio_source_cmd(ffmpeg, spec_copy) + ["-f", "null", "-"]
            rc, err = _run(cmd)
            ok = (rc == 0)
            channels_out[str(ac)] = {
                "result": "pass" if ok else "fail",
                "error": None if ok else (_first_meaningful_line(err) or f"exit code {rc}"),
            }

    containers_out = {}
    for cont_id, muxer_list in CONTAINERS.items():
        muxer, ext = muxer_list[0]
        out_path = os.path.join(TMP_DIR, f"{kind}_{name}_{cont_id}.{ext}".replace(" ", "_").replace("/", "_"))

        if kind == "audio" and cont_id == "mxf":
            base_cmd = _audio_paired_mxf_cmd(ffmpeg, spec)
        elif kind == "video":
            base_cmd = _video_source_cmd(ffmpeg, spec)
        else:
            base_cmd = _audio_source_cmd(ffmpeg, spec)

        cmd = base_cmd + ["-f", muxer, out_path]
        rc, err = _run(cmd)
        ok = (rc == 0) and os.path.exists(out_path) and os.path.getsize(out_path) > 0
        containers_out[cont_id] = {
            "result": "pass" if ok else "fail",
            "error": None if ok else (_first_meaningful_line(err) or f"exit code {rc}"),
        }
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass

        # Canales por CONTENEDOR: solo tiene sentido probarlo si el mux base ya paso (si el
        # contenedor ni siquiera acepta el codec, ningun conteo de canales lo va a arreglar)
        # y si el encoder ya demostro poder producir ese numero de canales arriba. Esto evita
        # cientos de pruebas de mux inutiles en combinaciones ya descartadas.
        if kind == "audio" and ok:
            per_container_channels = {}
            for ac in _CHANNEL_COUNTS:
                if channels_out.get(str(ac), {}).get("result") != "pass":
                    per_container_channels[str(ac)] = {
                        "result": "fail",
                        "error": "No soportado por el encoder en si (ver 'channels' a nivel de codec).",
                    }
                    continue
                ch_out_path = os.path.join(
                    TMP_DIR, f"{kind}_{name}_{cont_id}_ch{ac}.{ext}".replace(" ", "_").replace("/", "_")
                )
                ch_cmd = _channels_probe_cmd(ffmpeg, spec, cont_id, muxer, ch_out_path, ac)
                ch_rc, ch_err = _run(ch_cmd)
                ch_ok = (ch_rc == 0) and os.path.exists(ch_out_path) and os.path.getsize(ch_out_path) > 0
                per_container_channels[str(ac)] = {
                    "result": "pass" if ch_ok else "fail",
                    "error": None if ch_ok else (_first_meaningful_line(ch_err) or f"exit code {ch_rc}"),
                }
                if os.path.exists(ch_out_path):
                    try:
                        os.remove(ch_out_path)
                    except OSError:
                        pass
            containers_out[cont_id]["channels"] = per_container_channels

    result = {"testable": True, "skip_reason": None, "containers": containers_out, "channels": channels_out}
    if kind == "video":
        result["dimension_alignment"] = _probe_dimension_alignment(ffmpeg, spec)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", default=DEFAULT_FFMPEG, help="Ruta al ejecutable de ffmpeg a verificar.")
    parser.add_argument("--out-dir", default=RUNS_DIR, help="Carpeta donde guardar el resultado.")
    args = parser.parse_args()

    if not os.path.exists(args.ffmpeg):
        print(f"No se encontro ffmpeg en: {args.ffmpeg}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(TMP_DIR, exist_ok=True)
    os.makedirs(args.out_dir, exist_ok=True)

    version_line = subprocess.run([args.ffmpeg, "-version"], capture_output=True, text=True).stdout.splitlines()[0]
    version_match = re.search(r"ffmpeg version (\S+)", version_line)
    version_str = version_match.group(1) if version_match else "unknown"

    results = {"video_codecs": {}, "audio_codecs": {}}
    all_specs = [("video", VIDEO_CODECS), ("audio", AUDIO_CODECS)]
    total = sum(len(specs) for _, specs in all_specs)
    done = 0
    t0 = time.time()

    for kind, specs in all_specs:
        key = f"{kind}_codecs"
        for name, spec in specs.items():
            done += 1
            print(f"[{done}/{total}] {kind}: {name}", file=sys.stderr)
            r = probe(args.ffmpeg, kind, name, spec)
            r["codec_id"] = spec.get("codec_id", name)
            r["wiki"] = spec.get("wiki")
            r["encoder"] = spec.get("encoder")
            r["display_name"] = spec.get("display_name") or spec.get("wiki") or spec.get("codec_id", name)
            if spec.get("note"):
                r["note"] = spec["note"]
            results[key][name] = r

    elapsed = round(time.time() - t0, 1)
    print(f"Listo en {elapsed}s", file=sys.stderr)

    output = {
        "meta": {
            "ffmpeg_version": version_str,
            "ffmpeg_version_full": version_line,
            "ffmpeg_path": args.ffmpeg,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "method": "mux real contra ffmpeg instalado, con encoders de software (agnostico a marca de GPU)",
            "elapsed_sec": elapsed,
        },
        "results": results,
    }

    safe_version = re.sub(r"[^A-Za-z0-9._-]", "_", version_str)
    versioned_path = os.path.join(args.out_dir, f"{safe_version}.json")
    latest_path = os.path.join(args.out_dir, "latest.json")
    for p in (versioned_path, latest_path):
        with open(p, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Escrito: {versioned_path}", file=sys.stderr)
    print(f"Escrito: {latest_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
