# tools/updater/objectstore.py
"""Hasheo de un arbol de build y almacen de objetos direccionado por contenido.

hash_tree() es la misma logica que ya tenia manifest.py (blake2b por archivo,
para detectar que cambio entre dos builds), extraida aqui para que la comparta
publish.py sin duplicarla. stage_object() es la pieza nueva: comprime un archivo
a zstd y lo deja en el staging con el hash como nombre, listo para subir.
"""
import hashlib
import os

import zstandard

CHUNK_SIZE = 1 << 20  # 1 MiB


def hash_tree(root: str) -> dict:
    """Recorre root y devuelve {ruta_relativa_posix: {"hash": blake2b_hex, "size": int}}."""
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace("\\", "/")
            out[rel] = {"hash": hash_file(full), "size": os.path.getsize(full)}
    return out


def hash_file(path: str) -> str:
    """blake2b-256 (digest_size=32) de un archivo, en hex. Streaming: los archivos
    del bundle pueden pesar cientos de MB (el .exe, modelos), no se cargan enteros."""
    h = hashlib.blake2b(digest_size=32)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def object_name(file_hash: str) -> str:
    """Nombre del asset del release para un objeto: <hash>.zst."""
    return f"{file_hash}.zst"


def stage_object(src_path: str, file_hash: str, staging_dir: str) -> tuple[str, int]:
    """Comprime src_path a zstd dentro de staging_dir, nombrado por su hash.

    Devuelve (ruta_del_objeto_comprimido, tamano_comprimido). Si el objeto ya esta
    en staging (misma corrida re-ejecutada tras un corte), no lo vuelve a comprimir.
    """
    os.makedirs(staging_dir, exist_ok=True)
    dst_path = os.path.join(staging_dir, object_name(file_hash))
    if os.path.exists(dst_path):
        return dst_path, os.path.getsize(dst_path)

    # size= embebe el tamano original en el frame header: permite al cliente
    # descomprimir con decompress() de una sola llamada en vez de tener que
    # leer en streaming solo para saber cuanto buffer reservar.
    compressor = zstandard.ZstdCompressor(level=19)
    with open(src_path, "rb") as src, open(dst_path, "wb") as dst:
        compressor.copy_stream(src, dst, size=os.path.getsize(src_path))
    return dst_path, os.path.getsize(dst_path)


def mb(n: float) -> str:
    return f"{n / 1048576:.1f} MB"
