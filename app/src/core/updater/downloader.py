# src/core/updater/downloader.py
"""Descarga y extrae a un staging local los chunks que update_checker
determino que hacen falta. No aplica nada sobre la instalacion real -- eso es
el helper de swap (journal.py + swap_executor.py).

Cada chunk es un tar comprimido con zstd (ver tools/updater/objectstore.py)
que contiene varios archivos -- se descarga y descomprime en streaming (nunca
se carga entero en memoria) y se extrae directo a staging_dir, verificando el
hash de CADA archivo extraido contra lo que dice el manifiesto antes de
aceptarlo."""
import os
import tarfile
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


def _download_and_extract_chunk(url: str, expected_files: dict, staging_dir: str) -> None:
    """Descarga url en streaming, la descomprime con zstd tambien en streaming y
    extrae cada archivo del tar directo a staging_dir/relpath, verificando su
    hash contra expected_files (relpath -> {"hash", ...}) antes de aceptarlo.
    Escribe a un .part y hace os.replace() al final por archivo -- mismo
    criterio de resistencia a cortes que la v1 de este sistema.

    Lanza si algun archivo esperado no aparece en el tar, o si algun hash no
    coincide -- el llamador decide como tratarlo (todo el chunk se descarta)."""
    decompressor = zstandard.ZstdDecompressor()
    seen = set()
    with requests.get(url, stream=True, timeout=TIMEOUT) as r:
        r.raise_for_status()
        r.raw.decode_content = True
        with decompressor.stream_reader(r.raw) as zstream, tarfile.open(fileobj=zstream, mode="r|") as tar:
            for member in tar:
                if not member.isfile() or member.name not in expected_files:
                    continue
                dest_path = os.path.join(staging_dir, member.name.replace("/", os.sep))
                os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
                tmp_path = dest_path + ".part"
                src = tar.extractfile(member)
                with open(tmp_path, "wb") as out:
                    while True:
                        block = src.read(CHUNK_SIZE)
                        if not block:
                            break
                        out.write(block)

                if hash_file(tmp_path) != expected_files[member.name]["hash"]:
                    os.remove(tmp_path)
                    raise ValueError(f"hash no coincide para {member.name} dentro del chunk")

                os.replace(tmp_path, dest_path)
                seen.add(member.name)

    missing = set(expected_files) - seen
    if missing:
        raise ValueError(f"el chunk no traia {len(missing)} archivo(s) esperado(s): {sorted(missing)}")


def download_update(update_info, staging_dir: str, progress_callback=None) -> "DownloadResult":
    """progress_callback(bytes_completados, bytes_totales), en unidades de
    bytes EN LA RED (compressed_size de cada chunk) -- es lo que de verdad
    avanza mientras se descarga, a diferencia del tamano descomprimido.

    Idempotente: un chunk cuyos archivos ya estan en staging_dir con el hash
    correcto no se vuelve a descargar (permite reanudar tras cerrar la app a
    medias)."""
    total = sum(entry["compressed_size"] for entry in update_info.chunks_to_download.values())
    completed = 0
    failed_relpaths = []

    for chunk_id, chunk_entry in update_info.chunks_to_download.items():
        expected_files = {
            relpath: entry for relpath, entry in update_info.files_to_download.items()
            if entry["chunk"] == chunk_id
        }

        already_ok = all(
            os.path.exists(os.path.join(staging_dir, relpath.replace("/", os.sep)))
            and hash_file(os.path.join(staging_dir, relpath.replace("/", os.sep))) == entry["hash"]
            for relpath, entry in expected_files.items()
        )
        if not already_ok:
            try:
                _download_and_extract_chunk(chunk_entry["url"], expected_files, staging_dir)
            except (requests.RequestException, tarfile.TarError, ValueError, OSError) as e:
                logger.error(f"Updater: fallo descargando el chunk {chunk_id}: {e}")
                failed_relpaths.extend(expected_files)
                completed += chunk_entry["compressed_size"]
                if progress_callback:
                    progress_callback(completed, total)
                continue

        completed += chunk_entry["compressed_size"]
        if progress_callback:
            progress_callback(completed, total)

    if failed_relpaths:
        logger.error(f"Updater: {len(failed_relpaths)} archivo(s) no se pudieron descargar/verificar "
                      f"(via chunks): {failed_relpaths}")
    return DownloadResult(ok=not failed_relpaths, failed_files=failed_relpaths)
