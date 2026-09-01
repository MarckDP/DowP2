# src/core/tabs/editing_media/remote_thumbnail_cache_manager.py
import os
import time
import hashlib
import requests
from PySide6.QtCore import QObject, Signal, QRunnable, QThreadPool
from PySide6.QtGui import QPixmap, QIcon
from core.logger.logger_manager import logger
from core.utils.paths import get_remote_thumbnail_cache_dir
from core.tabs.editing_media.thumbnail_cache_manager import make_square_thumbnail_pixmap, _make_multi_state_icon

MAX_REMOTE_THUMBNAIL_FILES = 50

# El CDN de miniaturas de Wikimedia (thumb.wikimedia.org) devuelve 403 a peticiones sin un
# User-Agent descriptivo (aplican de verdad la política de etiqueta de su API, no es solo
# documentación) — ver USER_AGENT en web_sources/wikimedia_provider.py.
_DOWNLOAD_HEADERS = {"User-Agent": "DowP/2.0 (https://github.com/dowp-project; gestor de medios de escritorio)"}


class RemoteThumbnailWorkerSignals(QObject):
    """Señales para la descarga de una miniatura remota en segundo plano."""
    finished = Signal(str, str)  # (url, local_path)
    failed = Signal(str)         # (url)


class RemoteThumbnailRunnable(QRunnable):
    """Tarea ejecutable en QThreadPool: baja una miniatura ya renderizada por el origen web
    (ej. thumburl de Wikimedia) tal cual — sin ffmpeg, es solo un archivo de imagen chico."""

    def __init__(self, url: str, target_path: str, manager: "RemoteThumbnailCacheManager"):
        super().__init__()
        self.url = url
        self.target_path = target_path
        self.manager = manager
        self.signals = RemoteThumbnailWorkerSignals()

    def run(self):
        temp_path = self.target_path + ".tmp"
        try:
            response = requests.get(self.url, stream=True, timeout=15, headers=_DOWNLOAD_HEADERS)
            response.raise_for_status()

            with open(temp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=16384):
                    if chunk:
                        f.write(chunk)

            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                if os.path.exists(self.target_path):
                    try:
                        os.remove(self.target_path)
                    except Exception:
                        pass
                os.rename(temp_path, self.target_path)
                self.manager._on_download_success(self.url, self.target_path)
                try:
                    self.signals.finished.emit(self.url, self.target_path)
                except (RuntimeError, AttributeError):
                    pass
            else:
                try:
                    self.signals.failed.emit(self.url)
                except (RuntimeError, AttributeError):
                    pass
        except Exception as e:
            logger.error(f"RemoteThumbnailRunnable: Error descargando {self.url}: {e}")
            try:
                self.signals.failed.emit(self.url)
            except (RuntimeError, AttributeError):
                pass
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            self.manager._task_finished(self.url)


class RemoteThumbnailCacheManager(QObject):
    """Gestor de caché LRU (máximo 50 archivos) para miniaturas ya pre-renderizadas por un
    origen web (Wikimedia thumburl, y a futuro Pixabay/Pexels). Genérico a propósito: no
    depende de ffmpeg ni de ningún provider concreto, solo baja bytes de una URL y los cachea."""

    thumbnail_ready = Signal(str, str)  # (url, local_path)

    _instance = None

    @classmethod
    def get_instance(cls) -> "RemoteThumbnailCacheManager":
        if cls._instance is None:
            cls._instance = RemoteThumbnailCacheManager()
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cache_dir = get_remote_thumbnail_cache_dir()
        self.thread_pool = QThreadPool.globalInstance()
        self._pending_urls: set[str] = set()
        self._access_history: dict[str, float] = {}
        self._qicon_cache: dict[tuple[str, int], QIcon] = {}
        self._init_history()

    def _init_history(self):
        if os.path.exists(self.cache_dir):
            for entry in os.scandir(self.cache_dir):
                if entry.is_file() and not entry.name.endswith(".tmp"):
                    try:
                        self._access_history[entry.name] = entry.stat().st_mtime
                    except Exception:
                        self._access_history[entry.name] = time.time()
            self._evict_oldest_files()

    def _get_filename_for_url(self, url: str) -> str:
        hash_str = hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]
        return f"thumb_{hash_str}.jpg"

    def get_cached_path(self, url: str) -> str | None:
        """Ruta local si la miniatura ya está en caché. Actualiza su marca LRU."""
        filename = self._get_filename_for_url(url)
        target_path = os.path.join(self.cache_dir, filename)
        if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
            self._access_history[filename] = time.time()
            return target_path
        return None

    def get_cached_qicon(self, url: str, size: int = 256) -> QIcon | None:
        """QIcon cuadrado listo para usar (grilla o lista), derivado del único archivo
        cacheado en disco — igual patrón que ThumbnailCacheManager para archivos locales."""
        cache_key = (url, size)
        if cache_key in self._qicon_cache:
            return self._qicon_cache[cache_key]

        local_path = self.get_cached_path(url)
        if not local_path:
            return None

        pix = QPixmap(local_path)
        if pix.isNull():
            return None

        sq_pix = make_square_thumbnail_pixmap(pix, size)
        icon = _make_multi_state_icon(sq_pix)
        self._qicon_cache[cache_key] = icon
        return icon

    def request_thumbnail(self, url: str):
        """Pide la miniatura de forma no bloqueante. Si ya está en caché, no hace nada (usar
        get_cached_path/get_cached_qicon primero); si no, descarga en segundo plano y emite
        thumbnail_ready al terminar."""
        if not url:
            return
        if self.get_cached_path(url):
            self.thumbnail_ready.emit(url, self.get_cached_path(url))
            return
        if url in self._pending_urls:
            return

        self._pending_urls.add(url)
        filename = self._get_filename_for_url(url)
        target_path = os.path.join(self.cache_dir, filename)

        worker = RemoteThumbnailRunnable(url, target_path, self)
        worker.signals.finished.connect(self._on_worker_finished)
        worker.signals.failed.connect(self._on_worker_failed)
        self.thread_pool.start(worker)

    def _on_download_success(self, url: str, local_path: str):
        filename = os.path.basename(local_path)
        self._access_history[filename] = time.time()
        self._evict_oldest_files(exclude_filename=filename)

    def _on_worker_finished(self, url: str, local_path: str):
        self.thumbnail_ready.emit(url, local_path)

    def _on_worker_failed(self, url: str):
        logger.warning(f"RemoteThumbnailCacheManager: Falló la descarga de {url}")

    def _task_finished(self, url: str):
        self._pending_urls.discard(url)

    def _evict_oldest_files(self, exclude_filename: str = ""):
        """Mantiene estrictamente un máximo de MAX_REMOTE_THUMBNAIL_FILES archivos (LRU)."""
        if not os.path.exists(self.cache_dir):
            return

        files = [
            f for f in os.listdir(self.cache_dir)
            if os.path.isfile(os.path.join(self.cache_dir, f)) and not f.endswith(".tmp")
        ]
        if len(files) <= MAX_REMOTE_THUMBNAIL_FILES:
            return

        def get_access_time(filename: str) -> float:
            if filename in self._access_history:
                return self._access_history[filename]
            try:
                return os.path.getmtime(os.path.join(self.cache_dir, filename))
            except Exception:
                return 0.0

        sorted_files = sorted(files, key=get_access_time)
        files_to_remove = len(sorted_files) - MAX_REMOTE_THUMBNAIL_FILES
        removed = 0
        for f in sorted_files:
            if removed >= files_to_remove:
                break
            if f == exclude_filename:
                continue
            try:
                os.remove(os.path.join(self.cache_dir, f))
                self._access_history.pop(f, None)
                removed += 1
                logger.info(f"RemoteThumbnailCacheManager: Evicción LRU eliminó {f}")
            except Exception as e:
                logger.error(f"RemoteThumbnailCacheManager: Error eliminando archivo LRU {f}: {e}")

    def clear_cache(self) -> int:
        count = 0
        self._access_history.clear()
        self._qicon_cache.clear()
        if os.path.exists(self.cache_dir):
            for fname in os.listdir(self.cache_dir):
                fpath = os.path.join(self.cache_dir, fname)
                if os.path.isfile(fpath):
                    try:
                        os.remove(fpath)
                        count += 1
                    except Exception as e:
                        logger.error(f"RemoteThumbnailCacheManager: Error eliminando {fpath}: {e}")
        logger.info(f"RemoteThumbnailCacheManager: Se eliminaron {count} miniaturas en caché.")
        return count
