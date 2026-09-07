# src/core/updater/downloader.py
"""Descarga y descomprime a un staging local los archivos que update_checker
determino que hacen falta. No aplica nada sobre la instalacion real -- eso es
el helper de swap (pieza 3, todavia no implementada)."""
import os
from dataclasses import dataclass, field

import requests
import zstandard

from core.logger.logger_manager import logger
from core.updater.hash_tree import hash_file

TIMEOUT = 30
CHUNK_SIZE = 1 << 20  # 1 MiB


@dataclass
class DownloadResult:
    ok: bool
    failed_files: list = field(default_factory=list)


def _download_one(url: str, dest_path: str, expected_hash: str) -> bool:
    """Descarga url en streaming, la descomprime con zstd tambien en streaming
    (nunca carga el objeto comprimido entero en memoria) y verifica el hash del
    resultado antes de aceptarlo. Escribe a un .part y hace os.replace() al
    final -- si se corta a medias, el archivo bueno anterior (si lo habia) no
    se pierde y el .part huerfano no pasa la verificacion de hash de la
    proxima corrida."""
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    tmp_path = dest_path + ".part"

    decompressor = zstandard.ZstdDecompressor()
    with requests.get(url, stream=True, timeout=TIMEOUT) as r:
        r.raise_for_status()
        with open(tmp_path, "wb") as out, decompressor.stream_writer(out) as writer:
            for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    writer.write(chunk)

    if hash_file(tmp_path) != expected_hash:
        logger.error(f"Updater: hash no coincide tras descargar {url} -- descartado.")
        os.remove(tmp_path)
        return False

    os.replace(tmp_path, dest_path)
    return True


def download_update(update_info, staging_dir: str, progress_callback=None) -> "DownloadResult":
    """progress_callback(bytes_completados, bytes_totales), en unidades de
    bytes EN LA RED (compressed_size) -- es lo que de verdad avanza mientras
    se descarga, a diferencia del tamano descomprimido.

    Idempotente: un archivo ya presente en staging_dir con el hash correcto no
    se vuelve a descargar (permite reanudar tras cerrar la app a medias)."""
    total = sum(
        entry.get("compressed_size") or entry["size"]
        for entry in update_info.files_to_download.values()
    )
    completed = 0
    failed = []

    for relpath, entry in update_info.files_to_download.items():
        dest_path = os.path.join(staging_dir, relpath.replace("/", os.sep))
        chunk_size = entry.get("compressed_size") or entry["size"]

        already_ok = os.path.exists(dest_path) and hash_file(dest_path) == entry["hash"]
        if not already_ok:
            try:
                already_ok = _download_one(entry["url"], dest_path, entry["hash"])
            except requests.RequestException as e:
                logger.error(f"Updater: fallo descargando {relpath}: {e}")
                already_ok = False

        if not already_ok:
            failed.append(relpath)

        completed += chunk_size
        if progress_callback:
            progress_callback(completed, total)

    if failed:
        logger.error(f"Updater: {len(failed)} archivo(s) no se pudieron descargar/verificar: {failed}")
    return DownloadResult(ok=not failed, failed_files=failed)
