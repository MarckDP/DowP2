# src/core/utils/output_artifacts.py
"""
Reúne TODO lo que quedó en disco como resultado de una descarga (o de una descarga +
recodificación) para poder arrastrarlo a otra aplicación como si el usuario hubiera
entrado a la carpeta de salida y hubiera seleccionado esos archivos a mano — necesario
para editores que no exponen ninguna API de importación (CapCut, Filmora), donde el
drag-and-drop nativo del SO es la única vía (ver gui/widgets/native_file_drag.py).

Idea central: NO se intenta predecir qué archivos "debería" haber producido cada
combinación de casillas (conservar originales, conservar completo, miniatura,
subtítulos, fragmentos...). Se parte de las rutas que la app sí conoce, se barren sus
hermanos por nombre base, y se descarta todo lo que ya no existe. Como los caminos que
borran archivos son justamente los que implementan esas casillas
(file_conflict_manager.commit_backup cuando NO se conservan los originales,
DownloaderMaster._handle_local_cuts cuando el modo no es KEEP_FULL), el filtro de
existencia refleja automáticamente lo que el usuario eligió conservar, sin duplicar esa
lógica aquí.

El barrido por hermanos es obligatorio porque yt-dlp nunca reporta los sidecars por el
hook de progreso: la miniatura ('writethumbnail') y los subtítulos ('writesubtitles')
se escriben junto al medio sin pasar por ningún callback, igual que los subtítulos
recortados que genera _handle_subtitle_cuts_local.
"""
import os

from core.utils.file_conflict_manager import BACKUP_SUFFIX

# Acompañantes de un medio: nunca son "el archivo descargado" salvo que no haya otro
# (modo "solo miniatura"). Ver QuickDownloadController._find_actual_downloaded_file.
SIDECAR_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".webp", ".gif",
    ".srt", ".vtt", ".ass", ".ssa", ".ttml", ".lrc",
    ".srv1", ".srv2", ".srv3", ".json3",
)

# Restos de trabajo de yt-dlp/ffmpeg que pueden convivir con los archivos buenos en la
# carpeta de salida y que jamás deben viajar en un arrastre.
_TEMP_SUFFIXES = (
    ".part", ".ytdl", ".temp", ".tmp", ".cut.temp", ".unstd", BACKUP_SUFFIX,
)


def _is_temp_artifact(name: str) -> bool:
    low = name.lower()
    if low.endswith(_TEMP_SUFFIXES):
        return True
    # Fragmentos intermedios de yt-dlp: "video.mp4.part-Frag12", "video.f137.mp4.part".
    return ".part-" in low or low.endswith(".part")


def _relation_score(stem_cmp: str, candidate_cmp: str):
    """Cuán "dueño" es `stem_cmp` del archivo cuyo nombre base es `candidate_cmp`, o None
    si no hay parentesco. Se compara por (rango, longitud): pertenecer exactamente gana
    sobre ser su base, y ser su base gana sobre ser su descendiente. Ese orden es lo que
    permite que en una playlist con 'Cancion' y 'Cancion_2' cada fila se quede solo con
    lo suyo, sin renunciar al parentesco por ancestro que necesita el corte de
    fragmentos."""
    if stem_cmp == candidate_cmp:
        return (3, len(stem_cmp))
    if candidate_cmp.startswith(stem_cmp) and candidate_cmp[len(stem_cmp)] in "._":
        # El candidato cuelga de nuestro nombre base: sidecar o corte.
        return (2, len(stem_cmp))
    if stem_cmp.startswith(candidate_cmp) and stem_cmp[len(candidate_cmp)] in "._":
        # El candidato es nuestro ancestro: el completo conservado o su miniatura.
        return (1, len(stem_cmp))
    return None


def _sibling_artifacts(path: str, foreign_stems=()) -> list:
    """Archivos de la misma carpeta que pertenecen al mismo medio que `path`. Se aceptan
    los dos sentidos del parentesco, y ambos son necesarios:

    - Descendientes (el nombre del archivo empieza con nuestro nombre base):
      'Título.es.srt', 'Título.jpg', 'Título_intro.mp4' a partir de 'Título.mp4'.
    - Ancestros (nuestro nombre base empieza con el del archivo): 'Título_intro.mp4'
      (el completo conservado) y 'Título_intro.jpg' (la miniatura) a partir del corte
      'Título_intro_intro.mp4'. Sin esto se perdían justamente los dos casos que yt-dlp
      nunca reporta por el hook de progreso: el archivo ya fusionado y los sidecars —
      la app solo llega a conocer los nombres DERIVADOS ('...f395.mp4' antes de fusionar,
      '..._intro.mp4' después de cortar), nunca el nombre base del que cuelgan.

    En los dos sentidos se exige que el corte caiga sobre un separador ('.' o '_'), lo
    que evita reclamar la descarga vecina cuyo nombre apenas empieza igual ('Título
    2.mp4' no es pariente de 'Título').

    foreign_stems son las rutas base de OTRAS descargas de la lista: si alguna es dueña
    más directa de un archivo, este no se reclama. Sin eso, en una playlist con
    'Cancion' y 'Cancion_2' (nombres emparentados por el separador) cada fila arrastraba
    también los archivos de la otra.
    """
    directory = os.path.dirname(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    if not directory or not stem:
        return []
    stem_cmp = os.path.normcase(stem)
    rivals = [
        os.path.normcase(os.path.splitext(os.path.basename(f))[0])
        for f in foreign_stems or ()
        if f and os.path.normcase(os.path.dirname(f)) == os.path.normcase(directory)
    ]
    rivals = [r for r in rivals if r and r != stem_cmp]

    found = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                try:
                    if not entry.is_file():
                        continue
                except OSError:
                    continue
                candidate_cmp = os.path.normcase(os.path.splitext(entry.name)[0])
                mine = _relation_score(stem_cmp, candidate_cmp)
                if mine is None:
                    continue
                if any((_relation_score(r, candidate_cmp) or (0, 0)) > mine for r in rivals):
                    continue
                found.append(entry.path)
    except OSError:
        return []
    return found


def collect_output_artifacts(known_paths, stem_paths=None, foreign_stems=None) -> list:
    """
    Devuelve la lista ordenada y sin repetidos de archivos EXISTENTES asociados a una
    descarga.

    known_paths: rutas que la app conoce con certeza (el medio bajado, cada fragmento,
        la salida recodificada). Las que ya no existan se descartan en silencio: es el
        caso normal de un original borrado por no haber marcado "mantener medios
        originales", o de los archivos intermedios pre-fusión que yt-dlp reporta por el
        hook 'finished' y luego elimina.
    stem_paths: subconjunto cuyo nombre base se usa además para barrer hermanos
        (sidecars). Por defecto, todas las de known_paths. Conviene excluir la salida
        recodificada, cuyo nombre lleva prefijo/sufijo del usuario y puede arrastrar
        hermanos ajenos.
    foreign_stems: rutas conocidas de OTRAS descargas de la lista, para que un archivo
        emparentado con las dos se quede con su dueño más directo.
    """
    ordered, seen = [], set()

    def _add(path):
        if not path:
            return
        try:
            if not os.path.isfile(path):
                return
        except OSError:
            return
        if _is_temp_artifact(os.path.basename(path)):
            return
        absolute = os.path.abspath(path)
        key = os.path.normcase(absolute)
        if key in seen:
            return
        seen.add(key)
        ordered.append(absolute)

    known = [p for p in (known_paths or []) if p]
    for path in known:
        _add(path)

    for path in (known if stem_paths is None else [p for p in stem_paths if p]):
        for sibling in _sibling_artifacts(path, foreign_stems=foreign_stems):
            _add(sibling)

    return ordered
