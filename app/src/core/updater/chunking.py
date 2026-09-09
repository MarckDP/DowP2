# src/core/updater/chunking.py
"""Agrupa los archivos de un build en NUM_CHUNKS grupos, por el hash de la
RUTA de cada archivo (no de su contenido). La asignacion es asi estable entre
versiones -- el mismo relpath siempre cae en el mismo chunk -- sin depender de
la estructura de carpetas del build.

Por que esto y no un archivo por objeto (como la v1 de este sistema) ni un
solo paquete con todo: con ~2600 archivos en un build de Windows, un objeto
por archivo choca con el limite duro de GitHub de 1000 assets por release (ver
ACTUALIZACIONES.md), y un solo paquete completo por plataforma obliga a bajar
los ~150-200MB enteros en cada actualizacion aunque haya cambiado un solo
archivo. Agrupando en ~200 chunks parejos: un release nunca se acerca al
limite de GitHub, y una actualizacion tipica (unos pocos archivos propios
cambiados) solo invalida un puñado de chunks -- el resto de los archivos de
ese chunk se vuelven a bajar de mas (efecto colateral aceptado, acotado al
tamano de un chunk), pero jamas el build entero.

Vive en app/src (no en tools/updater) porque el CLIENTE necesita recalcular a
que chunk pertenece cada archivo instalado para poder compararlo contra el
manifiesto -- tools/updater/publish.py la importa por ruta, mismo patron ya
usado con platform_key.py y hash_tree.py.
"""
import hashlib

NUM_CHUNKS = 200


def chunk_id_for(relpath: str) -> str:
    """Chunk estable para una ruta relativa -- puro por texto, nunca cambia
    aunque cambie el contenido del archivo (si cambiara con el contenido, un
    archivo modificado saltaria de chunk entre versiones y no habria forma de
    saber cual chunk viejo invalidar)."""
    digest = hashlib.blake2b(relpath.encode("utf-8"), digest_size=4).digest()
    return f"{int.from_bytes(digest, 'big') % NUM_CHUNKS:04d}"


def compute_chunk_hash(file_hashes) -> str:
    """Hash combinado de TODOS los archivos asignados a un chunk (file_hashes:
    iterable de (relpath, hash_hex)). Cambia si cambia el contenido de
    cualquiera de ellos, si se agrega uno nuevo o si se saca uno -- es
    exactamente la señal de "hay que volver a bajar este chunk entero"."""
    h = hashlib.blake2b(digest_size=32)
    for relpath, file_hash in sorted(file_hashes):
        h.update(relpath.encode("utf-8"))
        h.update(b"\0")
        h.update(file_hash.encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()
