# src/core/updater/chunking.py
"""Agrupa los archivos UNICOS (por contenido) de un build en NUM_CHUNKS
grupos, por el hash del propio contenido -- no de la ruta.

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

Por que por CONTENIDO y no por ruta (como la v1 de este diseño, dentro de la
misma sesion): en un build de macOS, `Contents/Frameworks` y
`Contents/Resources` quedan cruzados por symlinks (ver ACTUALIZACIONES.md) --
el mismo contenido aparece bajo dos rutas distintas. Agrupando por hash de
RUTA, esas dos copias caian en chunks distintos y se subian/bajaban dos veces
(~435MB de puro desperdicio, medido en un publish real). Agrupando por hash de
CONTENIDO, las dos rutas apuntan al mismo chunk, y ese contenido se empaqueta
y transfiere una sola vez sin importar cuantas rutas lo referencien -- mismo
comportamiento de deduplicacion que ya tenia la v1 "un objeto por archivo",
sin volver a pagar el costo del limite de 1000 assets/release.

Vive en app/src (no en tools/updater) porque el CLIENTE necesita recalcular a
que chunk pertenece cada archivo instalado para poder compararlo contra el
manifiesto -- tools/updater/publish.py la importa por ruta, mismo patron ya
usado con platform_key.py y hash_tree.py.
"""
import hashlib

NUM_CHUNKS = 200


def chunk_id_for(file_hash: str) -> str:
    """Chunk estable para un CONTENIDO -- puro por el hash del archivo (ya
    viene en hex, blake2b-256), nunca por su ruta. Dos relpaths distintos con
    el mismo contenido caen siempre en el mismo chunk."""
    return f"{int(file_hash[:8], 16) % NUM_CHUNKS:04d}"


def compute_chunk_hash(file_hashes) -> str:
    """Hash combinado de todos los CONTENIDOS UNICOS asignados a un chunk
    (file_hashes: iterable de hashes hex, pueden venir repetidos -- se
    dedupean aca). Cambia si cambia cualquiera de ellos, si se agrega uno
    nuevo o si se saca uno -- es exactamente la señal de "hay que volver a
    bajar este chunk entero"."""
    h = hashlib.blake2b(digest_size=32)
    for file_hash in sorted(set(file_hashes)):
        h.update(file_hash.encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()
