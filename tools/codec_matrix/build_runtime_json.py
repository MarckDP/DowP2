# tools/codec_matrix/build_runtime_json.py
"""
Convierte una corrida cruda de run_matrix.py (runs/<version>.json) en el JSON final,
pensado para que la app lo consulte en runtime: claves = codec_id de ffmpeg (h264, hevc,
aac...) en vez de nombres de Wikipedia, y el motivo de fallo es el error real de ffmpeg,
no una nota editorializada.

No tiene relacion con codec_container_compatibility.json (el de Wikipedia) - son fuentes
independientes a proposito. Este es el que deberia usar el "colchon" para bloquear o
advertir; el de Wikipedia queda como referencia historica aparte.

Uso:
    python tools/codec_matrix/build_runtime_json.py
    python tools/codec_matrix/build_runtime_json.py --run runs/8.0.1-full_build-www.gyan.dev.json --out ../../src/assets/data/ffmpeg_codec_matrix.json
"""
import argparse
import json
import os

HERE = os.path.dirname(__file__)
DEFAULT_RUN = os.path.join(HERE, "runs", "latest.json")
DEFAULT_OUT = os.path.join(HERE, "..", "..", "src", "assets", "data", "ffmpeg_codec_matrix.json")


def build(run_path, out_path):
    with open(run_path, "r", encoding="utf-8") as f:
        run = json.load(f)

    codecs = {}
    for kind in ("video_codecs", "audio_codecs"):
        for name, entry in run["results"][kind].items():
            codec_id = entry.get("codec_id", name)
            kind_short = "video" if kind == "video_codecs" else "audio"

            if not entry.get("testable"):
                codecs[codec_id] = {
                    "kind": kind_short,
                    "display_name": entry.get("display_name", codec_id),
                    "wikipedia_name": entry.get("wiki"),
                    "encoder": entry.get("encoder"),
                    "verified": False,
                    "skip_reason": entry.get("skip_reason"),
                    "containers": None,
                }
                continue

            containers = {}
            for cont_id, c in entry["containers"].items():
                cont_out = {
                    "supported": c["result"] == "pass",
                    "ffmpeg_error": c.get("error"),
                }
                if "channels" in c:
                    cont_out["channels"] = {
                        ch: {"supported": c_res["result"] == "pass", "ffmpeg_error": c_res.get("error")}
                        for ch, c_res in c["channels"].items()
                    }
                containers[cont_id] = cont_out

            codecs[codec_id] = {
                "kind": kind_short,
                "display_name": entry.get("display_name", codec_id),
                "wikipedia_name": entry.get("wiki"),
                "encoder": entry.get("encoder"),
                "verified": True,
                "skip_reason": None,
                "containers": containers,
            }
            if "channels" in entry:
                channels_data = {}
                for ch, c_res in entry["channels"].items():
                    channels_data[ch] = {
                        "supported": c_res["result"] == "pass",
                        "ffmpeg_error": c_res.get("error"),
                    }
                codecs[codec_id]["channels"] = channels_data

            if entry.get("note"):
                codecs[codec_id]["note"] = entry["note"]

            if kind_short == "video" and entry.get("dimension_alignment"):
                codecs[codec_id]["dimension_alignment"] = entry["dimension_alignment"]

    output = {
        "schema_version": "1.0",
        "source": "empirico: mux real contra el ffmpeg empaquetado, ver tools/codec_matrix/",
        "ffmpeg_version": run["meta"]["ffmpeg_version"],
        "ffmpeg_version_full": run["meta"]["ffmpeg_version_full"],
        "generated_at": run["meta"]["generated_at"],
        "containers": list(next(iter(codecs.values()))["containers"].keys()) if codecs else [],
        "codecs": codecs,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Escrito: {out_path}")
    verified = sum(1 for c in codecs.values() if c["verified"])
    print(f"Codecs verificados: {verified}/{len(codecs)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default=DEFAULT_RUN)
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args()
    build(args.run, args.out)
