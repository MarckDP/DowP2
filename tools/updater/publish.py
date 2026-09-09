# tools/updater/publish.py
"""El publicador real del sistema de actualizaciones: genera el manifiesto firmado
de una plataforma y lo sube, junto con los objetos nuevos, a un GitHub Release.

    python tools/updater/publish.py \
        --dist app/dist/DowP --platform windows-x64 \
        --repo MarckDP/DowP2 --private-key tools/updater/secrets/private_key.pem

    python tools/updater/publish.py --dist app/dist/DowP --platform windows-x64 \
        --private-key tools/updater/secrets/private_key.pem --dry-run

    # macOS: el .app COMPLETO, no Contents/MacOS -- el onedir real de un
    # bundle queda partido entre Contents/Frameworks y Contents/Resources
    # (symlinks cruzados entre ambas), y solo el .app entero cubre las dos
    # sin ambiguedad. Debe coincidir con lo que calcula
    # launcher.install_dir_from_executable() del lado del cliente.
    python tools/updater/publish.py --dist app/dist/DowP.app --platform macos-arm64 \
        --repo MarckDP/DowP2 --private-key tools/updater/secrets/private_key.pem

Ver ACTUALIZACIONES.md y el plan de la sesion para el diseno completo: manifiesto
de hashes + almacen direccionado por contenido, sin bsdiff, URL completa por
objeto. Simplificacion explicita de esta v1: la reutilizacion de objetos ya
subidos solo mira el release inmediatamente anterior (`/releases/latest`), no
todo el historial -- un archivo que cambio y volvio a un valor de hace varias
versiones se resube (correcto, solo suboptimo).
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import github_release as gh
import objectstore
import signing

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
VERSION_FILE = os.path.join(REPO_ROOT, "app", "src", "core", "version.py")
STAGING_DIR = os.path.join(HERE, ".staging")

# Subir un objeto a la vez tardaba del orden de una hora para ~2600 objetos (medido
# en el primer publish real): cada request es un viaje de ida y vuelta a GitHub, y
# en serie eso domina el tiempo total muy por encima de lo que tarda comprimir.
# 10 en simultaneo es conservador a proposito -- GitHub documenta un limite de
# ~100 requests concurrentes antes de aplicar rate limiting secundario, pero el
# techo real para la mayoria de conexiones caseras es el propio ancho de banda de
# subida: pasado cierto punto, mas hilos solo reparten el mismo ancho de banda
# entre mas transferencias en vez de acelerar el total. github_release.upload_asset()
# usa requests.post() a nivel de modulo (una Session efimera por llamada, no
# compartida) -- seguro para llamar desde varios hilos a la vez sin cambios ahi.
MAX_CONCURRENT_UPLOADS = 10

# app/src no se instala como paquete -- se importa por ruta, igual que hace
# main.py en runtime. get_platform_key() vive ahi (no aqui) porque el cliente
# de descarga, que SI viaja dentro del bundle, tambien la necesita: que ambos
# calculen la misma clave de plataforma es lo que evita que un valor tecleado
# a mano en --platform deje un manifiesto que el cliente nunca encuentra.
sys.path.insert(0, os.path.join(REPO_ROOT, "app", "src"))
from core.updater.platform_key import get_platform_key  # noqa: E402


def read_version_module() -> dict:
    """Ejecuta version.py aislado, igual que build_cross_platform.py -- ese archivo
    no tiene imports a proposito para poder leerse asi desde herramientas externas."""
    namespace = {}
    with open(VERSION_FILE, encoding="utf-8") as f:
        exec(compile(f.read(), VERSION_FILE, "exec"), namespace)
    return namespace


def iter_manifest_files(manifest: dict | None):
    """Yield (platform, relpath, entry) para cada archivo de cada plataforma de un
    manifiesto ya cargado. No-op si manifest es None (no habia release anterior)."""
    if not manifest:
        return
    for platform, plat_data in manifest.get("platforms", {}).items():
        for relpath, entry in plat_data.get("files", {}).items():
            yield platform, relpath, entry


def fetch_manifest_json(release: dict | None, token: str) -> dict | None:
    """Descarga y parsea manifest.json de un release, o None si el release no
    existe o no tiene ese asset todavia (release recien creado por otra plataforma
    en la misma corrida de publicacion multi-plataforma)."""
    if release is None:
        return None
    asset = gh.find_asset(release, "manifest.json")
    if asset is None:
        return None
    return json.loads(gh.download_asset_content(asset, token))


def build_platform_manifest(dist_dir: str, reuse_map: dict, staging_dir: str,
                             find_existing_asset, download_url_for) -> tuple[dict, list, int, int]:
    """Hashea dist_dir y arma las entradas de esta plataforma.

    reuse_map: hash -> {"url": ..., "compressed_size": ...} de objetos que ya
    estan subidos en algun release y se pueden referenciar sin volver a comprimir
    ni subir.
    find_existing_asset(obj_name) -> asset dict o None: el objeto ya existe como
    asset del release ACTUAL (idempotencia ante un reintento tras un corte a
    medias) -- a diferencia de reuse_map, aqui la URL se sabe por convencion
    (download_url_for), no viene de un manifiesto ya escrito.
    download_url_for(obj_name) -> URL de descarga por convencion en el release actual.

    Devuelve (files_dict, pendientes_de_subir, cambia_bytes, total_bytes), donde
    pendientes_de_subir es [(hash, ruta_comprimida, nombre_asset), ...].
    """
    local_files = objectstore.hash_tree(dist_dir)
    files, pending, changed_bytes, total_bytes = {}, [], 0, 0
    # hash -> compressed_size de objetos ya vistos EN ESTA MISMA corrida. Necesario
    # porque dos relpaths distintos pueden compartir contenido (DLLs duplicados, o
    # en macOS los symlinks entre Contents/Frameworks y Contents/Resources -- ver
    # ACTUALIZACIONES.md): sin esto, el mismo obj_name se agregaba dos veces a
    # `pending` y la segunda subida fallaba con 422 (GitHub ya lo tenia, subido
    # segundos antes en la misma corrida) -- reuse_map y find_existing_asset solo
    # cubren objetos de OTRA corrida/plataforma, no duplicados dentro de esta.
    staged_this_run = {}

    for relpath, info in sorted(local_files.items()):
        file_hash, size = info["hash"], info["size"]
        total_bytes += size

        if file_hash in reuse_map:
            reused = reuse_map[file_hash]
            files[relpath] = {
                "hash": file_hash, "size": size,
                "compressed_size": reused["compressed_size"], "url": reused["url"],
            }
            continue

        changed_bytes += size
        obj_name = objectstore.object_name(file_hash)

        existing_asset = find_existing_asset(obj_name)
        if existing_asset is not None:
            # Ya subido en un intento anterior de esta misma corrida: no hace
            # falta comprimir de nuevo, solo referenciarlo.
            files[relpath] = {
                "hash": file_hash, "size": size,
                "compressed_size": existing_asset["size"], "url": download_url_for(obj_name),
            }
            continue

        if file_hash in staged_this_run:
            files[relpath] = {
                "hash": file_hash, "size": size,
                "compressed_size": staged_this_run[file_hash], "url": download_url_for(obj_name),
            }
            continue

        full_path = os.path.join(dist_dir, relpath.replace("/", os.sep))
        staged_path, compressed_size = objectstore.stage_object(full_path, file_hash, staging_dir)
        staged_this_run[file_hash] = compressed_size
        files[relpath] = {
            "hash": file_hash, "size": size,
            "compressed_size": compressed_size, "url": download_url_for(obj_name),
        }
        pending.append((file_hash, staged_path, obj_name))

    return files, pending, changed_bytes, total_bytes


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dist", required=True,
                         help="Carpeta del build (ej. app/dist/DowP; en macOS el .app completo, "
                              "ej. app/dist/DowP.app -- no Contents/MacOS)")
    parser.add_argument("--platform", help="ej. windows-x64, macos-arm64, linux-x64. "
                         "Por defecto, autodetectada con get_platform_key() del SO donde corre esto")
    parser.add_argument("--repo", help="owner/repo en GitHub. Obligatorio salvo con --dry-run")
    parser.add_argument("--private-key", required=True, help="Ruta al PEM de la clave privada Ed25519")
    parser.add_argument("--version", help="Por defecto, APP_VERSION de app/src/core/version.py")
    parser.add_argument("--min-updatable", help="Por defecto, MIN_UPDATABLE_VERSION de version.py")
    parser.add_argument("--dry-run", action="store_true",
                         help="No toca GitHub: hashea, comprime y firma en local para validar el flujo")
    parser.add_argument("--prerelease", action="store_true",
                         help="Marca el release como pre-release de GitHub -- invisible para clientes "
                              "en canal 'stable' (usan /releases/latest), solo lo ven quienes tengan "
                              "el canal 'beta' activado en Ajustes. NO es lo mismo que el canal "
                              "'beta' de la app en sí (ver core/version.py IS_BETA) -- esto es "
                              "puramente el flag de GitHub, para builds que no quieres que le lleguen "
                              "a todo el mundo en canal beta automaticamente.")
    args = parser.parse_args()

    if not os.path.isdir(args.dist):
        print(f"ERROR: no existe la carpeta de build {args.dist}")
        sys.exit(1)

    platform_key = args.platform or get_platform_key()

    version_ns = read_version_module()
    version = args.version or version_ns["APP_VERSION"]
    min_updatable = args.min_updatable or version_ns["MIN_UPDATABLE_VERSION"]
    tag = f"v{version}"

    if not args.dry_run and not args.repo:
        print("ERROR: --repo es obligatorio salvo en --dry-run")
        sys.exit(1)

    token = os.environ.get("GITHUB_TOKEN", "") if not args.dry_run else ""
    if not args.dry_run and not token:
        print("ERROR: falta la variable de entorno GITHUB_TOKEN (permiso 'repo' o "
              "'contents: write' en un fine-grained token). No se loggea ni se pide por otro medio.")
        sys.exit(1)

    staging_dir = os.path.join(STAGING_DIR, tag)
    os.makedirs(staging_dir, exist_ok=True)

    current_release, prev_release = None, None
    current_manifest, prev_manifest = None, None

    if not args.dry_run:
        current_release = gh.get_release_by_tag(args.repo, tag, token)
        current_manifest = fetch_manifest_json(current_release, token)

        prev_release = gh.get_latest_release(args.repo, token)
        if prev_release and prev_release.get("tag_name") != tag:
            prev_manifest = fetch_manifest_json(prev_release, token)

    # hash -> {url, compressed_size} de objetos ya subidos en algun release (esta
    # version parcialmente publicada por otra plataforma, o la version anterior).
    reuse_map = {}
    for _plat, _rel, entry in iter_manifest_files(current_manifest):
        reuse_map[entry["hash"]] = {"url": entry["url"], "compressed_size": entry["compressed_size"]}
    prev_hashes = set()
    for _plat, _rel, entry in iter_manifest_files(prev_manifest):
        prev_hashes.add(entry["hash"])
        reuse_map.setdefault(entry["hash"], {"url": entry["url"], "compressed_size": entry["compressed_size"]})

    def find_existing_asset(obj_name: str):
        if args.dry_run or current_release is None:
            return None
        return gh.find_asset(current_release, obj_name)

    def download_url_for(obj_name: str) -> str:
        # Predecible por convencion de GitHub: no hace falta que el release
        # exista todavia para saber que URL tendra un asset una vez subido.
        repo = args.repo or "<repo>"
        return f"https://github.com/{repo}/releases/download/{tag}/{obj_name}"

    files, pending, changed_bytes, total_bytes = build_platform_manifest(
        args.dist, reuse_map, staging_dir, find_existing_asset, download_url_for,
    )

    # Reutilizados-de-verdad (sin cambios respecto a la version anterior) vs el
    # resto, para el resumen -- distinto de "esta en reuse_map", que tambien
    # cuenta objetos compartidos con otra plataforma de esta MISMA version.
    unchanged = sum(1 for e in files.values() if e["hash"] in prev_hashes)
    download_bytes = sum(e["size"] for e in files.values() if e["hash"] not in prev_hashes)

    if not args.dry_run:
        if current_release is None:
            current_release = gh.create_release(args.repo, tag, token, prerelease=args.prerelease)

        # Filtro secuencial primero (barato, en memoria contra el snapshot ya
        # traido) -- lo unico que se paraleliza es la subida en si, que es lo
        # que de verdad tarda (ver MAX_CONCURRENT_UPLOADS mas arriba).
        to_upload = [
            (staged_path, obj_name) for _file_hash, staged_path, obj_name in pending
            if gh.find_asset(current_release, obj_name) is None
        ]

        if to_upload:
            print(f"Subiendo {len(to_upload)} objeto(s) nuevo(s) "
                  f"(hasta {MAX_CONCURRENT_UPLOADS} en simultaneo)...")
            done = 0
            with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_UPLOADS) as pool:
                futures = {
                    pool.submit(gh.upload_asset, current_release, staged_path, obj_name, token): obj_name
                    for staged_path, obj_name in to_upload
                }
                for future in as_completed(futures):
                    future.result()  # relanza cualquier error real de esa subida puntual
                    done += 1
                    if done % 100 == 0 or done == len(to_upload):
                        print(f"  {done}/{len(to_upload)}")

    final_manifest = current_manifest or {}
    final_manifest["format"] = 1
    final_manifest["app_version"] = version
    final_manifest["min_updatable_version"] = min_updatable
    final_manifest.setdefault("platforms", {})[platform_key] = {"files": files}

    manifest_path = os.path.join(staging_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(final_manifest, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")

    signature = signing.sign_file(args.private_key, manifest_path)
    sig_path = manifest_path + ".sig"
    with open(sig_path, "wb") as f:
        f.write(signature)

    print(f"\nPlataforma: {platform_key}  |  Version: {version}  |  Tag: {tag}")
    print(f"  Archivos totales   : {len(files):>6}  ({objectstore.mb(total_bytes)})")
    print(f"  Sin cambios        : {unchanged:>6}")
    print(f"  Nuevos/modificados : {len(files) - unchanged:>6}  ({objectstore.mb(download_bytes)})")
    print(f"  Manifiesto         : {manifest_path}")
    print(f"  Firma              : {sig_path}")

    if args.dry_run:
        print("\n[--dry-run] No se toco GitHub. Objetos comprimidos en:", staging_dir)
        return

    gh.replace_asset(current_release, manifest_path, "manifest.json", args.repo, token,
                      content_type="application/json")
    gh.replace_asset(current_release, sig_path, "manifest.json.sig", args.repo, token)
    print(f"\nPublicado en https://github.com/{args.repo}/releases/tag/{tag}")


if __name__ == "__main__":
    main()
