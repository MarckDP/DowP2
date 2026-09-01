# src/core/tabs/editing_media/thumbnail_cache_manager.py
import os
import hashlib
import subprocess
import re
from PySide6.QtCore import QObject, Signal, QRunnable, Qt
from PySide6.QtGui import QImage, QPixmap, QIcon, QImageReader, QPainter, QColor
from core.logger.logger_manager import logger
from core.setup.ffmpeg_setup import get_ffmpeg_dir, get_platform_info, check_ffmpeg
from core.utils.paths import get_thumbnail_cache_dir
from core.utils.media_task_pools import (
    get_background_pool,
    get_interactive_pool,
    PRIORITY_BACKGROUND,
    PRIORITY_INTERACTIVE,
)

CACHE_DIR = get_thumbnail_cache_dir()

def make_square_thumbnail_pixmap(src_pixmap: QPixmap, size=256) -> QPixmap:
    """Garantiza que la miniatura sea un lienzo cuadrado uniforme de 256x256 px centrado."""
    if src_pixmap.isNull():
        return src_pixmap
    if src_pixmap.width() == size and src_pixmap.height() == size:
        return src_pixmap

    out = QPixmap(size, size)
    out.fill(QColor("#1c1c1e"))

    scaled = src_pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.Antialiasing)
    x = (size - scaled.width()) // 2
    y = (size - scaled.height()) // 2
    painter.drawPixmap(x, y, scaled)
    painter.end()

    return out

class ThumbnailWorkerSignals(QObject):
    """Señales para el trabajador de miniaturas en segundo plano."""
    finished = Signal(str, str)  # (file_path, thumbnail_path)
    failed = Signal(str)        # (file_path)

class ThumbnailRunnable(QRunnable):
    """Tarea ejecutable en QThreadPool para generar miniaturas sin congelar la interfaz."""
    def __init__(self, file_path: str, media_type: str, manager: "ThumbnailCacheManager"):
        super().__init__()
        self.file_path = file_path
        self.media_type = media_type
        self.manager = manager
        self.signals = ThumbnailWorkerSignals()

    def run(self):
        try:
            thumb_path = self.manager._create_thumbnail(self.file_path, self.media_type)
            if thumb_path and os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
                self.signals.finished.emit(self.file_path, thumb_path)
            else:
                self.signals.failed.emit(self.file_path)
        except Exception as e:
            logger.error(f"ThumbnailRunnable: Error procesando {self.file_path}: {e}")
            self.signals.failed.emit(self.file_path)
        finally:
            self.manager._task_finished(self.file_path, self)

def _make_multi_state_icon(pix: QPixmap) -> QIcon:
    if pix.isNull():
        return QIcon()
    icon = QIcon()
    icon.addPixmap(pix, QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(pix, QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(pix, QIcon.Mode.Selected, QIcon.State.Off)
    icon.addPixmap(pix, QIcon.Mode.Selected, QIcon.State.On)
    icon.addPixmap(pix, QIcon.Mode.Active, QIcon.State.Off)
    icon.addPixmap(pix, QIcon.Mode.Active, QIcon.State.On)
    return icon

class ThumbnailCacheManager(QObject):
    """Gestor de caché de miniaturas en disco y memoria (RAM) con cola optimizada."""
    thumbnail_loaded = Signal(str, str)  # (file_path, thumbnail_path)

    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = ThumbnailCacheManager()
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        os.makedirs(CACHE_DIR, exist_ok=True)

        # Caché en RAM para acceso instantáneo (0ms I/O)
        self._qicon_cache: dict[str, QIcon] = {}
        self._hash_cache: dict[str, str] = {}
        # Separados a propósito (no un solo set compartido): si una miniatura ya está
        # pendiente en el pool de fondo y luego el usuario selecciona ese mismo archivo,
        # la solicitud interactiva NO debe descartarse solo porque "ya hay algo pendiente"
        # — si lo hiciera, quedaría atada a la cola de fondo, que además puede estar
        # pausada por completo mientras hay reproducción activa (ver set_background_throttled).
        self._pending_background = set()
        self._pending_interactive = set()
        self._failed_files = set()
        # Referencias fuertes a los workers en curso, igual que WaveformCacheManager: sin
        # esto nada en el lado Python los mantiene vivos una vez que request_thumbnail()
        # retorna, y también hace falta tener el objeto worker a mano para poder cancelarlo
        # con QThreadPool.tryTake() en purge_stale_background() si todavía no arrancó.
        self._active_workers: dict[str, set] = {}

    def _get_hash_key(self, file_path: str) -> str:
        """Genera un hash SHA256 único y lo mantiene en memoria para evitar os.stat repetidos."""
        if file_path in self._hash_cache:
            return self._hash_cache[file_path]

        try:
            stat = os.stat(file_path)
            raw = f"{os.path.abspath(file_path)}_{stat.st_mtime}_{stat.st_size}_v3"
        except Exception:
            raw = f"{os.path.abspath(file_path)}_v3"
        hash_val = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        self._hash_cache[file_path] = hash_val
        return hash_val

    def get_cached_qicon(self, file_path: str, size: int = 256) -> QIcon | None:
        """Obtiene directamente el QIcon desde la memoria RAM (super rápido y 100% cuadrado).
        `size` permite pedir una miniatura pequeña (p.ej. en modo lista) sin inflar la altura
        de la fila con el ícono de 256px pensado para la cuadrícula."""
        cache_key = (file_path, size)
        if cache_key in self._qicon_cache:
            return self._qicon_cache[cache_key]

        thumb_path = self.get_cached_thumbnail_path(file_path)
        if thumb_path:
            pix = QPixmap(thumb_path)
            if not pix.isNull():
                sq_pix = make_square_thumbnail_pixmap(pix, size)
                icon = _make_multi_state_icon(sq_pix)
                self._qicon_cache[cache_key] = icon
                return icon

        return None

    def get_cached_thumbnail_path(self, file_path: str) -> str | None:
        """Devuelve la ruta de la miniatura en disco si ya existe y es válida."""
        hash_key = self._get_hash_key(file_path)
        target_path = os.path.join(CACHE_DIR, f"{hash_key}.jpg")
        if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
            return target_path
        return None

    def request_thumbnail(self, file_path: str, media_type: str, size: int = 256, interactive: bool = False):
        """Solicita una miniatura de forma no bloqueante.

        `interactive=True` indica que el usuario está esperando este resultado ahora
        mismo (p.ej. la carátula del audio recién seleccionado): se ejecuta en un pool
        dedicado, separado del de generación masiva por scroll, para que nunca quede
        esperando detrás de una cola de tareas de fondo."""
        cache_key = (file_path, size)
        if cache_key in self._qicon_cache:
            return

        if file_path in self._failed_files:
            return

        # Deduplicar dentro del MISMO carril: una solicitud interactiva repetida no debe
        # lanzar un segundo worker interactivo, pero SÍ debe proceder aunque ya haya una
        # tarea de fondo pendiente para ese archivo (ver comentario en __init__).
        pending_set = self._pending_interactive if interactive else self._pending_background
        if file_path in pending_set:
            return

        cached_path = self.get_cached_thumbnail_path(file_path)
        if cached_path:
            pix = QPixmap(cached_path)
            if not pix.isNull():
                sq_pix = make_square_thumbnail_pixmap(pix, size)
                icon = _make_multi_state_icon(sq_pix)
            else:
                icon = _make_multi_state_icon(QPixmap(cached_path))
            self._qicon_cache[cache_key] = icon
            self.thumbnail_loaded.emit(file_path, cached_path)
            return

        pending_set.add(file_path)
        worker = ThumbnailRunnable(file_path, media_type, self)
        # Set en vez de asignación directa: con los carriles separados, un mismo file_path
        # puede tener a la vez un worker de fondo y uno interactivo corriendo en paralelo
        # (duplicado inofensivo, ver comentario en __init__); una asignación simple perdería
        # la referencia del primero en cuanto arrancara el segundo.
        self._active_workers.setdefault(file_path, set()).add(worker)
        worker.signals.finished.connect(self._on_worker_finished)
        worker.signals.failed.connect(self._on_worker_failed)
        if interactive:
            get_interactive_pool().start(worker, PRIORITY_INTERACTIVE)
        else:
            get_background_pool().start(worker, PRIORITY_BACKGROUND)

    def _on_worker_finished(self, file_path: str, thumb_path: str):
        pix = QPixmap(thumb_path)
        if not pix.isNull():
            sq_pix = make_square_thumbnail_pixmap(pix, 256)
            icon = _make_multi_state_icon(sq_pix)
        else:
            icon = _make_multi_state_icon(QPixmap(thumb_path))
        self._qicon_cache[(file_path, 256)] = icon
        self.thumbnail_loaded.emit(file_path, thumb_path)

    def _on_worker_failed(self, file_path: str):
        self._failed_files.add(file_path)

    def _task_finished(self, file_path: str, worker=None):
        # Se limpia de ambos carriles sin condicional: discard() no falla si no está
        # presente, y como mucho un archivo pudo quedar pendiente en los dos a la vez
        # (una tarea de fondo y otra interactiva corriendo en paralelo para el mismo
        # archivo — duplicado inofensivo, ver comentario en __init__).
        self._pending_background.discard(file_path)
        self._pending_interactive.discard(file_path)
        workers = self._active_workers.get(file_path)
        if workers is not None:
            workers.discard(worker)
            if not workers:
                self._active_workers.pop(file_path, None)

    def purge_stale_background(self):
        """Cancela las tareas de fondo aún NO iniciadas para archivos que ya no son
        relevantes tras un cambio real de carpeta/colección/filtro/búsqueda (no una carga
        incremental de más del mismo listado).

        Usa QThreadPool.tryTake() en vez de QThreadPool.clear(): el pool de fondo lo
        comparten ThumbnailCacheManager y WaveformCacheManager (ver media_task_pools.py),
        así que un .clear() a secas también borraría de golpe las tareas del otro gestor
        sin que este se entere, dejando sus propios diccionarios de seguimiento (y sus
        referencias fuertes a workers) apuntando a runnables ya destruidos por Qt.
        tryTake() en cambio cancela un worker puntual (y devuelve False sin tocar nada si
        ya arrancó a correr o si pertenece a otro pool/gestor), así que es seguro llamarlo
        aquí sin coordinarse con WaveformCacheManager. Las tareas que ya estaban corriendo
        (como mucho las que ocupan los hilos del pool ahora mismo) se dejan terminar solas
        — nada se pierde en disco, y si el archivo vuelve a ser visible más adelante
        simplemente se vuelve a pedir."""
        pool = get_background_pool()
        for file_path in list(self._pending_background):
            workers = self._active_workers.get(file_path)
            if workers:
                for w in list(workers):
                    if pool.tryTake(w):
                        workers.discard(w)
                if not workers:
                    self._active_workers.pop(file_path, None)
            self._pending_background.discard(file_path)

    def _create_thumbnail(self, file_path: str, media_type: str) -> str | None:
        """Genera la miniatura según el tipo de medio y la guarda en CACHE_DIR."""
        hash_key = self._get_hash_key(file_path)
        target_path = os.path.join(CACHE_DIR, f"{hash_key}.jpg")
        ext = os.path.splitext(file_path)[1].lower()

        if ext == ".svg":
            return self._generate_svg_thumbnail(file_path, target_path)
        elif ext in (".pdf", ".ai"):
            return self._generate_pdf_thumbnail(file_path, target_path)
        elif ext in (".eps", ".ps"):
            return self._generate_eps_thumbnail(file_path, target_path)
        elif media_type == "imagen":
            return self._generate_image_thumbnail(file_path, target_path)
        elif media_type == "video":
            return self._generate_video_thumbnail(file_path, target_path)
        elif media_type == "audio":
            return self._generate_audio_thumbnail(file_path, target_path)
        return None

    def _generate_svg_thumbnail(self, src_path: str, target_path: str) -> str | None:
        try:
            from PySide6.QtSvg import QSvgRenderer
            from PySide6.QtCore import QRectF, QSize
            renderer = QSvgRenderer(src_path)
            if not renderer.isValid():
                return None

            default_size = renderer.defaultSize()
            if default_size.isEmpty() or default_size.width() <= 0 or default_size.height() <= 0:
                default_size = QSize(256, 256)

            scaled_size = default_size.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio)
            img = QImage(256, 256, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(QColor("#1c1c1e"))

            painter = QPainter(img)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            x = (256 - scaled_size.width()) // 2
            y = (256 - scaled_size.height()) // 2
            renderer.render(painter, QRectF(x, y, scaled_size.width(), scaled_size.height()))
            painter.end()

            if img.save(target_path, "JPG", 85):
                return target_path
        except Exception as e:
            logger.error(f"ThumbnailCacheManager: Error en miniatura SVG {src_path}: {e}")
        return None

    def _generate_pdf_thumbnail(self, src_path: str, target_path: str) -> str | None:
        try:
            from PySide6.QtPdf import QPdfDocument
            from PySide6.QtCore import QSize
            doc = QPdfDocument(self)
            doc.load(src_path)
            if doc.pageCount() > 0:
                page_size = doc.pageSize(0)
                if page_size.isValid() and page_size.width() > 0 and page_size.height() > 0:
                    w, h = page_size.width(), page_size.height()
                    scale = min(256.0 / w, 256.0 / h)
                    render_w = max(1, int(w * scale))
                    render_h = max(1, int(h * scale))
                    page_img = doc.render(0, QSize(render_w, render_h))
                    if not page_img.isNull():
                        out_img = QImage(256, 256, QImage.Format.Format_RGB32)
                        out_img.fill(QColor("#1c1c1e"))
                        painter = QPainter(out_img)
                        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                        x = (256 - render_w) // 2
                        y = (256 - render_h) // 2
                        painter.drawImage(x, y, page_img)
                        painter.end()
                        if out_img.save(target_path, "JPG", 85):
                            return target_path
        except Exception as e:
            logger.error(f"ThumbnailCacheManager: Error en miniatura PDF/AI {src_path}: {e}")
        return None

    def _generate_eps_thumbnail(self, src_path: str, target_path: str) -> str | None:
        try:
            import struct
            # 1. Intentar extraer preview TIFF incrustado en cabecera binaria DOS EPS
            with open(src_path, "rb") as f:
                header = f.read(32)
                if len(header) >= 28 and header[:4] in (b'\xC5\xD0\xD3\xC6', b'\xC6\xD3\xD0\xC5'):
                    tiff_start, tiff_len = struct.unpack("<II", header[20:28])
                    if tiff_len > 0:
                        f.seek(tiff_start)
                        tiff_bytes = f.read(tiff_len)
                        if tiff_bytes:
                            tiff_img = QImage.fromData(tiff_bytes)
                            if not tiff_img.isNull():
                                scaled = tiff_img.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                                out_img = QImage(256, 256, QImage.Format.Format_RGB32)
                                out_img.fill(QColor("#1c1c1e"))
                                painter = QPainter(out_img)
                                x = (256 - scaled.width()) // 2
                                y = (256 - scaled.height()) // 2
                                painter.drawImage(x, y, scaled)
                                painter.end()
                                if out_img.save(target_path, "JPG", 85):
                                    return target_path

            # 2. Fallback con lector de imágenes habitual
            fallback = self._generate_image_thumbnail(src_path, target_path)
            if fallback:
                return fallback
        except Exception as e:
            logger.error(f"ThumbnailCacheManager: Error en miniatura EPS {src_path}: {e}")
        return None

    def _generate_image_thumbnail(self, src_path: str, target_path: str) -> str | None:
        try:
            reader = QImageReader(src_path)
            reader.setAutoTransform(True)
            orig_size = reader.size()
            if orig_size.isValid() and orig_size.width() > 0 and orig_size.height() > 0:
                # Escalar durante la lectura para ahorrar memoria y tiempo de procesamiento
                if orig_size.width() > 256 or orig_size.height() > 256:
                    scaled_size = orig_size.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio)
                    reader.setScaledSize(scaled_size)
            
            img = reader.read()
            if img.isNull():
                return None
            if img.save(target_path, "JPG", 85):
                return target_path
        except Exception as e:
            logger.error(f"ThumbnailCacheManager: Error en miniatura de imagen {src_path}: {e}")
        return None

    def _generate_video_thumbnail(self, src_path: str, target_path: str) -> str | None:
        """Extrae una miniatura de video en el 10% de su duración usando FFmpeg."""
        if not check_ffmpeg():
            return None

        try:
            info = get_platform_info()
            ffmpeg_exe = os.path.join(get_ffmpeg_dir(), info["binary_name"])

            duration_secs = self._get_video_duration_seconds(ffmpeg_exe, src_path)
            target_time = max(0.0, duration_secs * 0.10) if duration_secs > 0 else 0.0

            hours = int(target_time // 3600)
            mins = int((target_time % 3600) // 60)
            secs = target_time % 60
            timestamp_str = f"{hours:02d}:{mins:02d}:{secs:06.3f}"

            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            cmd = [
                ffmpeg_exe,
                "-ss", timestamp_str,
                "-i", src_path,
                "-vframes", "1",
                "-vf", "scale=256:256:force_original_aspect_ratio=decrease",
                "-y", target_path
            ]

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )
            process.communicate(timeout=8)

            if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
                return target_path

            # Fallback: si el salto temporal al 10% no produjo fotograma (video ultra-corto o sin keyframe intermedio), capturar el primer fotograma (0.0s)
            if target_time > 0:
                fallback_cmd = [
                    ffmpeg_exe,
                    "-ss", "00:00:00.000",
                    "-i", src_path,
                    "-vframes", "1",
                    "-vf", "scale=256:256:force_original_aspect_ratio=decrease",
                    "-y", target_path
                ]
                fallback_proc = subprocess.Popen(
                    fallback_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    startupinfo=startupinfo,
                    text=True,
                    encoding='utf-8',
                    errors='ignore'
                )
                fallback_proc.communicate(timeout=6)

                if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
                    return target_path
        except Exception as e:
            logger.error(f"ThumbnailCacheManager: Error extrayendo fotograma de video {src_path}: {e}")
        return None

    def _get_video_duration_seconds(self, ffmpeg_exe: str, src_path: str) -> float:
        """Obtiene la duración aproximada en segundos de un archivo mediante FFmpeg."""
        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            cmd = [ffmpeg_exe, "-hide_banner", "-i", src_path]
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )
            _, stderr = process.communicate(timeout=3)
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
            if match:
                hours = float(match.group(1))
                mins = float(match.group(2))
                secs = float(match.group(3))
                return hours * 3600 + mins * 60 + secs
        except Exception:
            pass
        return 0.0

    def _generate_audio_thumbnail(self, src_path: str, target_path: str) -> str | None:
        """Extrae la portada incrustada del archivo de audio si existe mediante Mutagen."""
        try:
            from mutagen import File as MutagenFile
            audio = MutagenFile(src_path)
            if audio is not None and hasattr(audio, 'tags') and audio.tags:
                image_data = None
                for key in audio.tags.keys():
                    if key.startswith("APIC"):
                        image_data = audio.tags[key].data
                        break
                if not image_data and hasattr(audio, 'pictures') and audio.pictures:
                    image_data = audio.pictures[0].data

                if image_data:
                    img = QImage.fromData(image_data)
                    if not img.isNull():
                        scaled = img.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        if scaled.save(target_path, "JPG", 85):
                            return target_path
        except Exception as e:
            logger.debug(f"ThumbnailCacheManager: Sin portada incrustada para audio {src_path}: {e}")
        return None

    def clear_cache(self) -> int:
        """Borra todos los archivos de caché de miniaturas y vacía las memorias en RAM."""
        count = 0
        self._qicon_cache.clear()
        self._hash_cache.clear()
        self._failed_files.clear()
        if os.path.exists(CACHE_DIR):
            for fname in os.listdir(CACHE_DIR):
                fpath = os.path.join(CACHE_DIR, fname)
                if os.path.isfile(fpath):
                    try:
                        os.remove(fpath)
                        count += 1
                    except Exception as e:
                        logger.error(f"ThumbnailCacheManager: Error eliminando {fpath}: {e}")
        logger.info(f"ThumbnailCacheManager: Se eliminaron {count} miniaturas en caché.")
        return count
