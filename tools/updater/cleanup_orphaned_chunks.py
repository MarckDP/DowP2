# tools/updater/cleanup_orphaned_chunks.py
"""Borra del release v{version} cualquier asset .tar.zst que NO este
referenciado por el manifest.json actual (restos de builds viejos/descartados
que quedaron subidos pero ya no se usan). Deja intactos manifest.json,
manifest.json.sig, y todo chunk que SI este en uso por alguna plataforma.

    python tools/updater/cleanup_orphaned_chunks.py --repo MarckDP/DowP2 --version 1.9.0
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import github_release as gh

parser = argparse.ArgumentParser()
parser.add_argument("--repo", required=True)
parser.add_argument("--version", required=True)
args = parser.parse_args()

token = os.environ.get("GITHUB_TOKEN", "")
if not token:
    print("ERROR: falta GITHUB_TOKEN.")
    sys.exit(1)

tag = f"v{args.version}"
release = gh.get_release_by_tag(args.repo, tag, token)
if release is None:
    print(f"ERROR: no existe el release {tag}.")
    sys.exit(1)

manifest_asset = next(
    (a for a in gh.list_release_assets(args.repo, release["id"], token) if a["name"] == "manifest.json"),
    None,
)
if manifest_asset is None:
    print("ERROR: el release no tiene manifest.json todavia -- no se puede saber que esta en uso.")
    sys.exit(1)
manifest = json.loads(gh.download_asset_content(manifest_asset, token))

in_use = {"manifest.json", "manifest.json.sig"}
for plat_data in manifest.get("platforms", {}).values():
    for chunk in plat_data.get("chunks", {}).values():
        in_use.add(chunk["url"].rsplit("/", 1)[-1])

all_assets = gh.list_release_assets(args.repo, release["id"], token)
orphaned = [a for a in all_assets if a["name"] not in in_use]

print(f"Assets totales: {len(all_assets)}  |  en uso: {len(all_assets) - len(orphaned)}  |  huerfanos a borrar: {len(orphaned)}")
if not orphaned:
    print("Nada que borrar.")
    sys.exit(0)

done = 0
with ThreadPoolExecutor(max_workers=15) as pool:
    futures = {pool.submit(gh.delete_asset, args.repo, a["id"], token): a["name"] for a in orphaned}
    for future in as_completed(futures):
        name = futures[future]
        try:
            future.result()
        except Exception as e:
            print(f"FALLO borrando {name}: {e}")
            continue
        done += 1
        if done % 50 == 0 or done == len(orphaned):
            print(f"  {done}/{len(orphaned)}")

print("Listo.")
