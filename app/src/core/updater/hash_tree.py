# src/core/updater/hash_tree.py
"""Hasheo del arbol instalado, para comparar contra el manifiesto remoto.

Duplicado a proposito de tools/updater/objectstore.hash_tree(): ese modulo
vive fuera de src/ y no se empaqueta con la app, asi que el cliente (que SI
viaja dentro del bundle) no puede importarlo. Mismo caso ya documentado en
ACTUALIZACIONES.md con manifest.py -- la duplicacion es minima (una funcion) y
vale mas que acoplar el paquete distribuible a una carpeta que nunca llega a
la maquina del usuario.
"""
import hashlib
import os

CHUNK_SIZE = 1 << 20  # 1 MiB


def hash_file(path: str) -> str:
    """blake2b-256 (digest_size=32) de un archivo, en hex, en streaming."""
    h = hashlib.blake2b(digest_size=32)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_tree(root: str) -> dict:
    """{ruta_relativa_posix: {"hash": blake2b_hex, "size": int}} -- mismo
    formato que produce tools/updater/objectstore.hash_tree(), asi el manifiesto
    que firma el publicador y lo que calcula el cliente son directamente
    comparables."""
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace("\\", "/")
            out[rel] = {"hash": hash_file(full), "size": os.path.getsize(full)}
    return out
