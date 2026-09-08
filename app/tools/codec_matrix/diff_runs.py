# tools/codec_matrix/diff_runs.py
"""
Compara dos corridas de run_matrix.py (tipicamente: la version de ffmpeg vieja vs la
nueva, despues de actualizar el binario empaquetado) y muestra que combinaciones
codec/contenedor cambiaron de estado. Pensado para correr como parte del checklist antes
de shippear una actualizacion de ffmpeg.

Uso:
    python tools/codec_matrix/diff_runs.py runs/8.0.1-full_build-www.gyan.dev.json runs/8.2.0-full_build-www.gyan.dev.json
"""
import json
import sys


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def flatten(run):
    flat = {}
    for kind in ("video_codecs", "audio_codecs"):
        for name, entry in run["results"][kind].items():
            codec_id = entry.get("codec_id", name)
            if not entry.get("testable"):
                flat[(codec_id, "*")] = ("not_testable", entry.get("skip_reason"))
                continue
            for cont_id, c in entry["containers"].items():
                flat[(codec_id, cont_id)] = (c["result"], c.get("error"))
    return flat


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    sys.stdout.reconfigure(encoding="utf-8")
    old_run, new_run = load(sys.argv[1]), load(sys.argv[2])
    old_v, new_v = old_run["meta"]["ffmpeg_version"], new_run["meta"]["ffmpeg_version"]
    old_flat, new_flat = flatten(old_run), flatten(new_run)

    print(f"Comparando ffmpeg {old_v} -> {new_v}\n")

    changed = []
    for key in sorted(set(old_flat) | set(new_flat)):
        old_val = old_flat.get(key, ("no_existia", None))
        new_val = new_flat.get(key, ("eliminado", None))
        if old_val[0] != new_val[0]:
            changed.append((key, old_val, new_val))

    if not changed:
        print("Sin cambios de estado entre las dos versiones de ffmpeg.")
        return

    regressions = [c for c in changed if c[1][0] == "pass" and c[2][0] == "fail"]
    improvements = [c for c in changed if c[1][0] == "fail" and c[2][0] == "pass"]
    other = [c for c in changed if c not in regressions and c not in improvements]

    def show(title, items):
        if not items:
            return
        print(f"=== {title} ({len(items)}) ===")
        for (codec_id, cont_id), old_val, new_val in items:
            print(f"  {codec_id} en {cont_id}: {old_val[0]} -> {new_val[0]}"
                  + (f"  [{new_val[1]}]" if new_val[1] else ""))
        print()

    show("REGRESIONES (funcionaba, ahora falla)", regressions)
    show("MEJORAS (antes fallaba, ahora funciona)", improvements)
    show("OTROS CAMBIOS", other)


if __name__ == "__main__":
    main()
