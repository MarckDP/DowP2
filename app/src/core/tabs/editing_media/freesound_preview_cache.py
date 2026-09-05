# src/core/tabs/editing_media/freesound_preview_cache.py
import os
import time
import hashlib
import json
import requests
from PySide6.QtCore import QObject, Signal, QRunnable, QThreadPool
from core.logger.logger_manager import logger
from core.utils.paths import get_freesound_cache_dir

MAX_FREESOUND_CACHE_FILES = 50
MAX_WAVEFORM_CACHE_ITEMS = 500

# Esta caché ahora también baja previews de video/audio de Wikimedia (además de Freesound), y
# el CDN de Wikimedia (upload.wikimedia.org) devuelve 403 a peticiones sin un User-Agent
# descriptivo (aplican de verdad su política de etiqueta, no es solo documentación). Freesound
# no lo exige, pero mandarlo igual no tiene contra.
_DOWNLOAD_HEADERS = {"User-Agent": "DowP/2.0 (https://github.com/dowp-project; gestor de medios de escritorio)"}


class FreesoundPreviewWorkerSignals(QObject):
    """Señales para la descarga de previas de Freesound en segundo plano."""
    finished = Signal(str, str)  # (url, local_path)
    failed = Signal(str)        # (url)


class FreesoundPreviewRunnable(QRunnable):
    """Tarea ejecutable en QThreadPool para descargar un audio de vista previa de Freesound."""

    def __init__(self, url: str, target_path: str, manager: "FreesoundPreviewCacheManager"):
        super().__init__()
        self.url = url
        self.target_path = target_path
        self.manager = manager
        self.signals = FreesoundPreviewWorkerSignals()

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
            logger.error(f"FreesoundPreviewRunnable: Error descargando {self.url}: {e}")
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


class FreesoundPreviewCacheManager(QObject):
    """Gestor de caché LRU para vistas previas de audio de Freesound (máximo 50 archivos)."""

    preview_ready = Signal(str, str)  # (url, local_path)
    waveform_peaks_ready = Signal(str, list) # (url, peaks)

    _instance = None

    @classmethod
    def get_instance(cls) -> "FreesoundPreviewCacheManager":
        if cls._instance is None:
            cls._instance = FreesoundPreviewCacheManager()
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cache_dir = get_freesound_cache_dir()
        self.thread_pool = QThreadPool.globalInstance()
        self._pending_urls: set[str] = set()
        self._access_history: dict[str, float] = {}  # filename -> timestamp
        self._init_history()

    def _init_history(self):
        """Inicializa el historial de acceso escaneando los archivos existentes en el directorio."""
        if os.path.exists(self.cache_dir):
            for entry in os.scandir(self.cache_dir):
                if entry.is_file() and not entry.name.endswith(".tmp"):
                    try:
                        self._access_history[entry.name] = entry.stat().st_mtime
                    except Exception:
                        self._access_history[entry.name] = time.time()
            self._evict_oldest_files()

    def _get_filename_for_url(self, url: str) -> str:
        """Genera un nombre de archivo único basado en el hash SHA256 de la URL del medio.
        Reconoce también contenedores de video/audio de Wikimedia (derivatives .webm/.mov,
        originales .flac/.opus/.m4a) además de los de Freesound (.ogg/.wav/.mp3 por defecto)."""
        url_lower = url.lower()
        ext = ".mp3"
        for candidate in (".webm", ".mp4", ".mov", ".ogg", ".oga", ".wav", ".flac", ".opus", ".m4a"):
            if candidate in url_lower:
                ext = candidate
                break
        hash_str = hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]
        return f"preview_{hash_str}{ext}"

    def get_cached_path(self, url: str) -> str | None:
        """
        Retorna la ruta local del archivo si ya se encuentra en la caché y es válido.
        Actualiza su marca de tiempo LRU.
        """
        filename = self._get_filename_for_url(url)
        target_path = os.path.join(self.cache_dir, filename)

        if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
            self._access_history[filename] = time.time()
            return target_path
        return None

    def request_preview(self, url: str):
        """
        Solicita un audio de previsualización.
        Si ya está en caché, emite preview_ready inmediatamente (0ms).
        Si no, inicia la descarga en segundo plano.
        """
        cached_path = self.get_cached_path(url)
        if cached_path:
            self.preview_ready.emit(url, cached_path)
            return

        if url in self._pending_urls:
            return

        self._pending_urls.add(url)
        filename = self._get_filename_for_url(url)
        target_path = os.path.join(self.cache_dir, filename)

        worker = FreesoundPreviewRunnable(url, target_path, self)
        worker.signals.finished.connect(self._on_worker_finished)
        worker.signals.failed.connect(self._on_worker_failed)
        self.thread_pool.start(worker)

    def _on_download_success(self, url: str, local_path: str):
        filename = os.path.basename(local_path)
        self._access_history[filename] = time.time()
        self._evict_oldest_files(exclude_filename=filename)

    def _on_worker_finished(self, url: str, local_path: str):
        self.preview_ready.emit(url, local_path)

    def _on_worker_failed(self, url: str):
        logger.warning(f"FreesoundPreviewCacheManager: Falló la descarga de {url}")

    def _task_finished(self, url: str):
        self._pending_urls.discard(url)

    def _evict_oldest_files(self, exclude_filename: str = ""):
        """Mantiene estrictamente un máximo de MAX_FREESOUND_CACHE_FILES archivos (LRU)."""
        if not os.path.exists(self.cache_dir):
            return

        files = [
            f for f in os.listdir(self.cache_dir)
            if os.path.isfile(os.path.join(self.cache_dir, f)) and not f.endswith(".tmp")
        ]

        if len(files) <= MAX_FREESOUND_CACHE_FILES:
            return

        # Ordenar archivos por su marca de tiempo de último acceso (el más antiguo primero)
        def get_access_time(filename: str) -> float:
            if filename in self._access_history:
                return self._access_history[filename]
            try:
                return os.path.getmtime(os.path.join(self.cache_dir, filename))
            except Exception:
                return 0.0

        sorted_files = sorted(files, key=get_access_time)

        # Eliminar los archivos más antiguos hasta tener máximo 10
        files_to_remove = len(sorted_files) - MAX_FREESOUND_CACHE_FILES
        removed = 0
        for f in sorted_files:
            if removed >= files_to_remove:
                break
            if f == exclude_filename:
                continue
            file_path = os.path.join(self.cache_dir, f)
            try:
                os.remove(file_path)
                self._access_history.pop(f, None)
                removed += 1
                logger.info(f"FreesoundPreviewCacheManager: Evicción LRU eliminó {f}")
            except Exception as e:
                logger.error(f"FreesoundPreviewCacheManager: Error eliminando archivo LRU {f}: {e}")

    # ---------------- CACHÉ LRU DE WAVEFORMS (Picos) ----------------
    def _get_waveform_json_path(self, waveform_url: str) -> str:
        """Genera una ruta de archivo JSON persistente en disco para los picos de forma de onda."""
        hash_str = hashlib.sha256(waveform_url.encode('utf-8')).hexdigest()[:16]
        return os.path.join(self.cache_dir, f"wf_peaks_{hash_str}.json")

    def get_cached_waveform_peaks(self, waveform_url: str) -> list[float] | None:
        """Retorna los picos de forma de onda procesados desde la RAM o desde el archivo en disco."""
        if not hasattr(self, "_waveform_peaks_cache"):
            self._waveform_peaks_cache: dict[str, list[float]] = {}
            self._waveform_access_order: list[str] = []

        if waveform_url in self._waveform_peaks_cache:
            if waveform_url in self._waveform_access_order:
                self._waveform_access_order.remove(waveform_url)
            self._waveform_access_order.append(waveform_url)
            return self._waveform_peaks_cache[waveform_url]

        # Si no está en la memoria RAM, buscar el archivo JSON persistente en disco
        json_path = self._get_waveform_json_path(waveform_url)
        if os.path.exists(json_path) and os.path.getsize(json_path) > 0:
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    peaks = json.load(f)
                if isinstance(peaks, list) and peaks:
                    self._waveform_peaks_cache[waveform_url] = peaks
                    self._waveform_access_order.append(waveform_url)
                    return peaks
            except Exception as e:
                logger.error(f"FreesoundPreviewCacheManager: Error leyendo json de picos {json_path}: {e}")

        return None

    def cache_waveform_peaks(self, waveform_url: str, peaks: list[float]):
        """Almacena los picos de forma de onda en RAM y en disco de forma persistente."""
        if not hasattr(self, "_waveform_peaks_cache"):
            self._waveform_peaks_cache: dict[str, list[float]] = {}
            self._waveform_access_order: list[str] = []

        if waveform_url in self._waveform_peaks_cache:
            self._waveform_peaks_cache[waveform_url] = peaks
            if waveform_url in self._waveform_access_order:
                self._waveform_access_order.remove(waveform_url)
            self._waveform_access_order.append(waveform_url)
        else:
            if len(self._waveform_access_order) >= MAX_WAVEFORM_CACHE_ITEMS:
                oldest_url = self._waveform_access_order.pop(0)
                self._waveform_peaks_cache.pop(oldest_url, None)

            self._waveform_peaks_cache[waveform_url] = peaks
            self._waveform_access_order.append(waveform_url)

        # Guardar en disco de forma persistente
        json_path = self._get_waveform_json_path(waveform_url)
        try:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(peaks, f)
        except Exception as e:
            logger.error(f"FreesoundPreviewCacheManager: Error guardando json de picos {json_path}: {e}")

        # Notificar al resto de la aplicación (ej. MediaListModel) que los picos de esta URL están listos
        self.waveform_peaks_ready.emit(waveform_url, peaks)

    def clear_cache(self) -> int:
        """Elimina todas las vistas previas de Freesound almacenadas en disco y en memoria."""
        count = 0
        self._access_history.clear()
        if hasattr(self, "_waveform_peaks_cache"):
            self._waveform_peaks_cache.clear()
            self._waveform_access_order.clear()

        if os.path.exists(self.cache_dir):
            for fname in os.listdir(self.cache_dir):
                fpath = os.path.join(self.cache_dir, fname)
                if os.path.isfile(fpath):
                    try:
                        os.remove(fpath)
                        count += 1
                    except Exception as e:
                        logger.error(f"FreesoundPreviewCacheManager: Error eliminando {fpath}: {e}")
        logger.info(f"FreesoundPreviewCacheManager: Se eliminaron {count} audios y formas de onda en caché.")
        return count

