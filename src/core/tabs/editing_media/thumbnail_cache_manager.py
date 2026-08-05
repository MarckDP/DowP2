# src/core/tabs/editing_media/thumbnail_cache_manager.py
import os
import hashlib
import subprocess
import re
from PySide6.QtCore import QObject, Signal, QRunnable, QThreadPool, Qt
from PySide6.QtGui import QImage, QPixmap
from core.logger.logger_manager import logger
from core.setup.ffmpeg_setup import get_ffmpeg_dir, get_platform_info, check_ffmpeg

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CACHE_DIR = os.path.join(BASE_DIR, "bin", "cache", "thumbnails")

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
            self.manager._task_finished(self.file_path)


class ThumbnailCacheManager(QObject):
    """Gestor de caché de miniaturas en disco y cola de subprocesos."""
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
        self.thread_pool = QThreadPool.globalInstance()
        # Limitar hilos para mantener uso de CPU optimizado
        if self.thread_pool.maxThreadCount() > 4:
            self.thread_pool.setMaxThreadCount(4)
        self._pending_files = set()

    def _get_hash_key(self, file_path: str) -> str:
        """Genera un hash SHA256 único basado en la ruta, tiempo de modificación y tamaño."""
        try:
            stat = os.stat(file_path)
            raw = f"{os.path.abspath(file_path)}_{stat.st_mtime}_{stat.st_size}_v2"
        except Exception:
            raw = f"{os.path.abspath(file_path)}_v2"
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    def get_cached_thumbnail_path(self, file_path: str) -> str | None:
        """Devuelve la ruta de la miniatura en disco si ya existe y es válida."""
        hash_key = self._get_hash_key(file_path)
        target_path = os.path.join(CACHE_DIR, f"{hash_key}.jpg")
        if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
            return target_path
        return None

    def request_thumbnail(self, file_path: str, media_type: str):
        """Solicita una miniatura. Si existe en disco emite la señal; si no, la encola en background."""
        cached_path = self.get_cached_thumbnail_path(file_path)
        if cached_path:
            self.thumbnail_loaded.emit(file_path, cached_path)
            return

        if file_path in self._pending_files:
            return

        self._pending_files.add(file_path)
        worker = ThumbnailRunnable(file_path, media_type, self)
        worker.signals.finished.connect(self._on_worker_finished)
        worker.signals.failed.connect(self._on_worker_failed)
        self.thread_pool.start(worker)

    def _on_worker_finished(self, file_path: str, thumb_path: str):
        self.thumbnail_loaded.emit(file_path, thumb_path)

    def _on_worker_failed(self, file_path: str):
        pass

    def _task_finished(self, file_path: str):
        self._pending_files.discard(file_path)

    def _create_thumbnail(self, file_path: str, media_type: str) -> str | None:
        """Genera la miniatura según el tipo de medio y la guarda en CACHE_DIR."""
        hash_key = self._get_hash_key(file_path)
        target_path = os.path.join(CACHE_DIR, f"{hash_key}.jpg")

        if media_type == "imagen":
            return self._generate_image_thumbnail(file_path, target_path)
        elif media_type == "video":
            return self._generate_video_thumbnail(file_path, target_path)
        elif media_type == "audio":
            return self._generate_audio_thumbnail(file_path, target_path)
        return None

    def _generate_image_thumbnail(self, src_path: str, target_path: str) -> str | None:
        try:
            img = QImage(src_path)
            if img.isNull():
                return None
            scaled = img.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            if scaled.save(target_path, "JPG", 85):
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

            # 1. Obtener duración del video usando FFmpeg -i
            duration_secs = self._get_video_duration_seconds(ffmpeg_exe, src_path)
            target_time = max(0.5, duration_secs * 0.10) if duration_secs > 0 else 1.0

            # Formatear timestamp HH:MM:SS.mmm
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
            process.communicate(timeout=10)

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
            _, stderr = process.communicate(timeout=4)
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", stderr)
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
                # ID3 (MP3)
                for key in audio.tags.keys():
                    if key.startswith("APIC"):
                        image_data = audio.tags[key].data
                        break
                # FLAC / MP4
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
        """Borra todos los archivos de caché de miniaturas y retorna la cantidad de archivos eliminados."""
        count = 0
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
