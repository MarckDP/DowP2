# src/core/utils/recode_guard.py
"""
"Colchon" de recodificacion: evalua si una combinacion (codec de video, codec de audio,
contenedor) es viable ANTES de lanzar un proceso de ffmpeg, para advertir o bloquear en
vez de dejar que el usuario se encuentre con un error de ffmpeg a mitad de un render.

Cuatro categorias de resultado por combinacion:
  - "ok":         verificado empiricamente, sin objeciones.
  - "warning":    o bien ffmpeg acepta el mux pero el estandar (Wikipedia) lo marca como
                  no estandar/parcial/privado (riesgo de que no reproduzca en todos lados),
                  o bien el codec de video solo tiene encoder por software en este equipo
                  (funciona, pero mas lento).
  - "unverified": no hay encoder en este ffmpeg para probarlo empiricamente; el dato es
                  documental (de Wikipedia) o directamente no existe.
  - "blocked":    ffmpeg rechaza el mux, o no hay ningun encoder (ni hardware ni software)
                  para ese codec en este equipo. No se debe permitir iniciar el proceso.

Combina tres fuentes independientes, cada una con su propio rol, sin fusionarlas en un
solo campo:
  - ffmpeg_codec_matrix.json: verificado empiricamente contra el ffmpeg empaquetado (ver
    tools/codec_matrix/). Fuente primaria: "¿este contenedor acepta este codec aca?".
  - codec_container_compatibility.json (Wikipedia): NO se usa para decidir bloqueo. Solo
    se consulta como señal secundaria de "riesgo de reproduccion" cuando ffmpeg ya acepto
    el mux, para casos donde el contenedor es permisivo (acepta cualquier FourCC) pero el
    estandar nunca contemplo esa combinacion.
  - hardware_detector.codec_status: verificado por probe-encode real en ESTE equipo.
    Responde "¿hay un encoder que funcione (hardware o software) para este codec aca?".
"""
import json
import os

from core.logger.logger_manager import logger
from core.utils.hardware_detector import detect_hardware

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_MATRIX_PATH = os.path.join(_REPO_ROOT, "ffmpeg_codec_matrix.json")
_WIKI_PATH = os.path.join(_REPO_ROOT, "codec_container_compatibility.json")
# NOTA: rutas relativas al arbol de codigo fuente. Cuando el proyecto tenga empaquetador
# (hoy no lo tiene, ver AGENTS.md), esta resolucion va a necesitar revisarse para leer
# desde el recurso empaquetado en vez del repo.

CONTAINER_ALIASES = {
    "mkv": "mkv", "mk3d": "mkv", "mka": "mkv", "mks": "mkv",
    "mp4": "mp4", "m4v": "mp4", "m4a": "mp4",
    "mov": "qtff", "qt": "qtff",
    "asf": "asf", "wmv": "asf", "wma": "asf",
    "avi": "avi",
    "mxf": "mxf",
    "mpg": "ps", "mpeg": "ps", "m2p": "ps", "ps": "ps",
    "ts": "ts", "m2ts": "ts", "mts": "ts", "tsv": "ts",
    "3gp": "3gp",
    "3g2": "3g2",
}
# id de contenedor nuestro -> id de contenedor en el JSON de Wikipedia (que fusiona ps/ts).
_WIKI_CONTAINER_ID = {
    "ps": "ps_ts", "ts": "ps_ts",
    "mkv": "mkv", "mp4": "mp4", "qtff": "qtff", "asf": "asf",
    "avi": "avi", "mxf": "mxf", "3gp": "3gp", "3g2": "3g2",
}

_HARDWARE_TRACKED_CODECS = {"h264", "hevc", "av1", "vp9"}

_matrix_cache = None
_wiki_cache = None


def _load_json(path, cache_attr):
    global _matrix_cache, _wiki_cache
    cached = globals()[cache_attr]
    if cached is not None:
        return cached
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"RecodeGuard: No se pudo cargar {path}: {e}")
        data = {}
    globals()[cache_attr] = data
    return data


def _load_matrix():
    return _load_json(_MATRIX_PATH, "_matrix_cache") or {"codecs": {}, "containers": []}


def _load_wiki():
    return _load_json(_WIKI_PATH, "_wiki_cache") or {}


def normalize_container(container: str) -> str:
    """Convierte una extension/alias de UI (ej. '.mov', 'MOV', 'mov') al id de la matriz."""
    key = container.lower().lstrip(".")
    return CONTAINER_ALIASES.get(key, key)



VIDEO_CATEGORIES = {
    "h264": "Distribución / Web", "hevc": "Distribución / Web", "av1": "Distribución / Web", "vp9": "Distribución / Web",
    "prores": "Edición Profesional", "dnxhd": "Edición Profesional", "cfhd": "Edición Profesional",
    "ffv1": "Sin Pérdida (Lossless)", "utvideo": "Sin Pérdida (Lossless)", "huffyuv": "Sin Pérdida (Lossless)",
    "mpeg4": "Formatos Antiguos", "mpeg2video": "Formatos Antiguos", "msmpeg4v3": "Formatos Antiguos",
    "wmv2": "Formatos Antiguos", "wmv1": "Formatos Antiguos", "theora": "Formatos Antiguos", "vp8": "Formatos Antiguos",
    "gif": "Animaciones", "apng": "Animaciones", "webp": "Animaciones",
}
VIDEO_CATEGORY_ORDER = {"Distribución / Web": 1, "Edición Profesional": 2, "Sin Pérdida (Lossless)": 3, "Animaciones": 4, "Formatos Antiguos": 5, "Otros": 6}

AUDIO_CATEGORIES = {
    "aac": "Distribución / Web", "libopus": "Distribución / Web", "opus": "Distribución / Web",
    "mp3": "Distribución / Web", "libmp3lame": "Distribución / Web", "vorbis": "Distribución / Web",
    "flac": "Alta Calidad (Sin pérdida)", "alac": "Alta Calidad (Sin pérdida)",
    "pcm_s16le": "Alta Calidad (Sin pérdida)", "pcm_s24le": "Alta Calidad (Sin pérdida)", "pcm_s32le": "Alta Calidad (Sin pérdida)",
    "wavpack": "Alta Calidad (Sin pérdida)",
    "ac3": "Cine / TV (Surround)", "eac3": "Cine / TV (Surround)", "dts": "Cine / TV (Surround)", "truehd": "Cine / TV (Surround)",
    "wmav2": "Antiguos", "mp2": "Antiguos",
}
AUDIO_CATEGORY_ORDER = {"Distribución / Web": 1, "Alta Calidad (Sin pérdida)": 2, "Cine / TV (Surround)": 3, "Antiguos": 4, "Otros": 5}

def get_video_codecs(only_verified: bool = True) -> list[dict]:
    matrix = _load_matrix()
    out = []
    for codec_id, entry in matrix.get("codecs", {}).items():
        if entry.get("kind") != "video": continue
        if only_verified and not entry.get("verified"): continue
        cat = VIDEO_CATEGORIES.get(codec_id, "Otros")
        out.append({
            "codec_id": codec_id, 
            "display_name": entry.get("display_name", codec_id), 
            "verified": entry.get("verified", False),
            "category": cat,
            "cat_order": VIDEO_CATEGORY_ORDER.get(cat, 99)
        })
    return sorted(out, key=lambda c: (c["cat_order"], c["display_name"].lower()))

def get_audio_codecs(only_verified: bool = True) -> list[dict]:
    matrix = _load_matrix()
    out = []
    for codec_id, entry in matrix.get("codecs", {}).items():
        if entry.get("kind") != "audio": continue
        if only_verified and not entry.get("verified"): continue
        cat = AUDIO_CATEGORIES.get(codec_id, "Otros")
        out.append({
            "codec_id": codec_id, 
            "display_name": entry.get("display_name", codec_id), 
            "verified": entry.get("verified", False),
            "category": cat,
            "cat_order": AUDIO_CATEGORY_ORDER.get(cat, 99)
        })
    return sorted(out, key=lambda c: (c["cat_order"], c["display_name"].lower()))

def resolve_encoder(codec_id: str) -> str | None:
    """
    Devuelve el encoder de ffmpeg efectivo para un codec_id en ESTE equipo: para los
    codecs que hardware_detector.py rastrea (h264/hevc/av1/vp9) usa el backend elegido
    por probe-encode real (nvenc/qsv/amf/vaapi/software); para el resto, el encoder de
    software por defecto verificado en ffmpeg_codec_matrix.json.
    """
    if codec_id in _HARDWARE_TRACKED_CODECS:
        hw_info = detect_hardware()
        status = hw_info.get("codec_status", {}).get(codec_id)
        if status and status.get("encoder"):
            return status["encoder"]

    matrix = _load_matrix()
    entry = matrix.get("codecs", {}).get(codec_id)
    return entry.get("encoder") if entry else None


def get_compatible_containers(codec_ids: list[str]) -> list[str]:
    """Interseccion de contenedores soportados por todos los codec_id dados (ya verificados)."""
    matrix = _load_matrix()
    all_containers = set(matrix.get("containers", []))
    result = None
    for codec_id in codec_ids:
        entry = matrix.get("codecs", {}).get(codec_id)
        if not entry or not entry.get("verified"):
            continue
        supported = {c for c, info in entry["containers"].items() if info["supported"]}
        result = supported if result is None else (result & supported)
    if result is None:
        return sorted(all_containers)
    return sorted(result)


def _check_container_support(codec_id: str) -> dict:
    matrix = _load_matrix()
    codec_entry = matrix.get("codecs", {}).get(codec_id)
    if codec_entry is None:
        return {"level": "unverified", "reason": f"'{codec_id}' no esta en la matriz verificada."}
    if not codec_entry.get("verified"):
        return {"level": "unverified", "reason": codec_entry.get("skip_reason") or "No se pudo verificar empiricamente con este ffmpeg."}
    return {"level": "verified", "reason": None, "entry": codec_entry}


def _check_playback_risk(codec_entry: dict, container_id: str) -> str | None:
    """Solo se llama cuando ffmpeg YA acepto el mux. Cruza con Wikipedia para detectar
    casos donde el contenedor fue permisivo (acepto cualquier FourCC) pero el estandar
    nunca contemplo esa combinacion. Devuelve un mensaje de advertencia, o None si no hay
    objecion (o no hay dato de Wikipedia para cruzar)."""
    wiki_name = codec_entry.get("wikipedia_name")
    if not wiki_name:
        return None

    wiki = _load_wiki()
    wiki_cont_id = _WIKI_CONTAINER_ID.get(container_id, container_id)
    kind = codec_entry.get("kind")
    wiki_section = wiki.get("video_codecs" if kind == "video" else "audio_codecs", {})
    wiki_codec = wiki_section.get(wiki_name)
    if not wiki_codec:
        return None

    support = wiki_codec.get("container_support", {}).get(wiki_cont_id)
    if not support:
        return None

    level = support.get("level")
    if level == "full":
        return None

    level_desc = wiki.get("support_levels", {}).get(level, level)
    note = support.get("note")
    msg = f"ffmpeg acepta este mux, pero no es un uso estandar del contenedor ({level_desc})"
    if note:
        msg += f" — {note}"
    msg += ". Podria no reproducirse en todos los reproductores/dispositivos."
    return msg


def _check_hardware_support(codec_id: str) -> dict:
    if codec_id not in _HARDWARE_TRACKED_CODECS:
        return {"level": "not_tracked", "reason": None}

    hw_info = detect_hardware()
    status = hw_info.get("codec_status", {}).get(codec_id)
    if status is None:
        return {"level": "unverified", "reason": "Sin datos de hardware para este codec (correr deteccion de hardware)."}

    if status["status"] == "none":
        return {"level": "blocked", "reason": status["note"]}
    if status["status"] == "partial":
        return {"level": "warning", "reason": status["note"]}
    return {"level": "ok", "reason": None}


_SEVERITY_ORDER = {"blocked": 3, "warning": 2, "unverified": 1, "ok": 0}


def evaluate_recode(video_codec: str | None, audio_codec: str | None, container: str) -> dict:
    """
    Evalua una combinacion de recodificacion antes de lanzar ffmpeg.

    Args:
        video_codec: codec_id (ej. "h264") o None si el video se copia / no hay video.
        audio_codec: codec_id (ej. "aac") o None si el audio se copia / no hay audio.
        container: extension o alias de contenedor (ej. "mp4", ".mov", "mkv").

    Returns:
        {
            "verdict": "ok" | "warning" | "unverified" | "blocked",
            "container": <id normalizado>,
            "issues": [ {"scope": "video"/"audio", "check": "container"/"playback_risk"/"hardware",
                          "severity": "warning"/"unverified"/"blocked", "message": str}, ... ]
        }

    Nota: si video_codec/audio_codec es None (stream copiado o ausente), no se evalua ese
    stream — quien llame debe resolver el codec real del archivo fuente (ej. via ffprobe)
    si quiere validar un stream en modo "copiar".
    """
    container_id = normalize_container(container)
    issues = []

    for scope, codec_id in (("video", video_codec), ("audio", audio_codec)):
        if not codec_id:
            continue

        container_check = _check_container_support(codec_id)
        if container_check["level"] == "unverified":
            issues.append({"scope": scope, "check": "container", "severity": "unverified", "message": container_check["reason"]})
        else:
            codec_entry = container_check["entry"]
            cont_info = codec_entry["containers"].get(container_id)
            if cont_info is None:
                issues.append({"scope": scope, "check": "container", "severity": "unverified",
                                "message": f"Contenedor '{container_id}' no evaluado para '{codec_id}'."})
            elif not cont_info["supported"]:
                issues.append({"scope": scope, "check": "container", "severity": "blocked",
                                "message": cont_info.get("ffmpeg_error") or "Este contenedor no acepta este codec en el ffmpeg instalado."})
            else:
                risk_msg = _check_playback_risk(codec_entry, container_id)
                if risk_msg:
                    issues.append({"scope": scope, "check": "playback_risk", "severity": "warning", "message": risk_msg})

        if scope == "video":
            hw_check = _check_hardware_support(codec_id)
            if hw_check["level"] in ("blocked", "warning"):
                issues.append({"scope": scope, "check": "hardware", "severity": hw_check["level"], "message": hw_check["reason"]})

    if issues:
        worst = max(issues, key=lambda i: _SEVERITY_ORDER[i["severity"]])
        verdict = worst["severity"]
    else:
        verdict = "ok"

    return {"verdict": verdict, "container": container_id, "issues": issues}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

    cases = [
        ("h264", "aac", "mp4"),
        ("hevc", "aac", "mxf"),
        ("hevc", "pcm_s24le", "mxf"),
        ("av1", "opus", "mov"),
        ("vp8", "vorbis", "mkv"),
        ("h264", "opus", "qtff"),
        ("h264", None, "ts"),
        ("prores", "pcm_s24le", "mkv"),
    ]
    for v, a, c in cases:
        result = evaluate_recode(v, a, c)
        print(f"\n{v} + {a} -> .{c}  =>  {result['verdict'].upper()}")
        for issue in result["issues"]:
            print(f"  [{issue['severity']}] ({issue['scope']}/{issue['check']}) {issue['message']}")
