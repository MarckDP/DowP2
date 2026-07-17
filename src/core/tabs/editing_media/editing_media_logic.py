import os
import json
import time
import subprocess
import struct
from PySide6.QtCore import QObject, Signal, QThread

from core.logger.logger_manager import logger

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    logger.warning("EditingMediaLogic: Watchdog no está disponible. El monitoreo en tiempo real estará deshabilitado.")

VALID_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
VALID_VIDEO_EXTS = {'.mp4', '.mkv', '.avi', '.mov', '.webm'}
VALID_AUDIO_EXTS = {'.mp3', '.wav', '.flac', '.m4a', '.aac'}
VALID_EXTS = VALID_IMAGE_EXTS | VALID_VIDEO_EXTS | VALID_AUDIO_EXTS


def get_media_type(ext: str) -> str:
    if ext in VALID_IMAGE_EXTS:
        return "imagen"
    elif ext in VALID_VIDEO_EXTS:
        return "video"
    elif ext in VALID_AUDIO_EXTS:
        return "audio"
    return "desconocido"


def format_size(bytes_size: int) -> str:
    if bytes_size < 1024:
        return f"{bytes_size} B"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.1f} KB"
    else:
        return f"{bytes_size / (1024 * 1024):.1f} MB"


def get_media_duration(path: str, ext: str) -> str:
    if ext in VALID_AUDIO_EXTS:
        try:
            from mutagen import File as MutagenFile
            audio = MutagenFile(path)
            if audio is not None and audio.info is not None:
                length = int(audio.info.length)
                mins = length // 60
                secs = length % 60
                return f"{mins:02d}:{secs:02d}"
        except Exception:
            pass
    return "-"


if WATCHDOG_AVAILABLE:
    class MediaFolderWatcherHandler(FileSystemEventHandler):
        """Manejador de eventos de watchdog que notifica cambios al controlador."""
        def __init__(self, callback):
            super().__init__()
            self.callback = callback
            self.last_triggered = 0.0

        def on_created(self, event):
            self._handle_event(event)

        def on_deleted(self, event):
            self._handle_event(event)

        def on_moved(self, event):
            self._handle_event(event)

        def _handle_event(self, event):
            if event.is_directory:
                self._throttle_trigger()
                return

            ext = os.path.splitext(event.src_path)[1].lower()
            if ext in VALID_EXTS:
                self._throttle_trigger()

        def _throttle_trigger(self):
            # Throttle para evitar llamadas repetidas en milisegundos
            now = time.time()
            if now - self.last_triggered > 0.5:
                self.last_triggered = now
                self.callback()
else:
    class MediaFolderWatcherHandler:
        pass


class EditingMediaController(QObject):
    """Controlador que gestiona la lógica de indexación, colecciones y monitoreo en tiempo real."""
    
    disk_changed = Signal()
    collections_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Calcular ruta del archivo de persistencia
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        self.db_path = os.path.join(base_dir, "bin", "indexed_media.json")
        
        self.indexed_folders = []
        self.collections = {
            "Favoritos": [],
            "SFX": [],
            "Música": []
        }
        
        self.observer = None
        self.load_data()
        self.start_watcher()

    def load_data(self):
        """Carga carpetas indexadas y colecciones desde indexed_media.json."""
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.indexed_folders = data.get("indexed_folders", [])
                    self.collections = data.get("collections", {
                        "Favoritos": [],
                        "SFX": [],
                        "Música": []
                    })
                logger.info(f"EditingMediaLogic: Datos cargados desde {self.db_path}")
            except Exception as e:
                logger.error(f"EditingMediaLogic: Error leyendo base de datos: {e}")
        else:
            self.save_data()

    def save_data(self):
        """Guarda carpetas indexadas y colecciones en indexed_media.json."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        try:
            data = {
                "indexed_folders": self.indexed_folders,
                "collections": self.collections
            }
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            logger.debug(f"EditingMediaLogic: Datos guardados en {self.db_path}")
        except Exception as e:
            logger.error(f"EditingMediaLogic: Error guardando datos: {e}")

    # ── Gestión de Monitoreo en Tiempo Real (Watchdog) ───────────────────────
    def start_watcher(self):
        """Inicia el watchdog observer para vigilar las carpetas físicas."""
        if not WATCHDOG_AVAILABLE:
            return

        if self.observer is not None:
            self.stop_watcher()

        self.observer = Observer()
        handler = MediaFolderWatcherHandler(self._on_disk_modified)
        
        active_watches = 0
        for folder in self.indexed_folders:
            if os.path.exists(folder) and os.path.isdir(folder):
                try:
                    self.observer.schedule(handler, path=folder, recursive=True)
                    active_watches += 1
                except Exception as e:
                    logger.error(f"EditingMediaLogic: Error agendando vigilancia para {folder}: {e}")
        
        if active_watches > 0:
            try:
                self.observer.start()
                logger.info(f"EditingMediaLogic: Watchdog iniciado con {active_watches} carpetas vigiladas.")
            except Exception as e:
                logger.error(f"EditingMediaLogic: Error iniciando Watchdog: {e}")

    def stop_watcher(self):
        """Detiene el watchdog observer."""
        if self.observer:
            try:
                self.observer.stop()
                self.observer.join()
            except Exception as e:
                logger.error(f"EditingMediaLogic: Error deteniendo Watchdog: {e}")
            self.observer = None

    def _on_disk_modified(self):
        """Callback ejecutado cuando watchdog detecta cambios en disco."""
        logger.debug("EditingMediaLogic: Cambio detectado en el disco por Watchdog.")
        self._invalidate_media_cache()
        self.disk_changed.emit()

    # ── Operaciones con Carpetas Físicas ─────────────────────────────────────
    def add_folder(self, folder_path: str) -> bool:
        """Agrega una nueva carpeta física al índice."""
        norm_path = os.path.normpath(folder_path).replace("\\", "/")
        if norm_path not in self.indexed_folders:
            self.indexed_folders.append(norm_path)
            self.save_data()
            self.start_watcher()
            self._invalidate_media_cache()
            self.disk_changed.emit()
            return True
        return False

    def remove_folder(self, folder_path: str) -> bool:
        """Remueve una carpeta física del índice."""
        norm_path = os.path.normpath(folder_path).replace("\\", "/")
        if norm_path in self.indexed_folders:
            self.indexed_folders.remove(norm_path)
            self.save_data()
            self.start_watcher()
            self._invalidate_media_cache()
            self.disk_changed.emit()
            return True
        return False

    # ── Operaciones con Colecciones Virtuales ─────────────────────────────────
    def add_collection(self, name: str) -> bool:
        """Crea una nueva colección virtual vacía."""
        name = name.strip()
        if name and name not in self.collections:
            self.collections[name] = []
            self.save_data()
            self._invalidate_media_cache()
            self.collections_changed.emit()
            return True
        return False

    def remove_collection(self, name: str) -> bool:
        """Elimina una colección virtual."""
        if name in self.collections:
            del self.collections[name]
            self.save_data()
            self._invalidate_media_cache()
            self.collections_changed.emit()
            return True
        return False

    def add_to_collection(self, collection_name: str, file_path: str) -> bool:
        """Asocia un archivo (acceso directo) a una colección virtual."""
        norm_path = os.path.normpath(file_path).replace("\\", "/")
        if collection_name in self.collections:
            if norm_path not in self.collections[collection_name]:
                self.collections[collection_name].append(norm_path)
                self.save_data()
                self._invalidate_media_cache()
                self.collections_changed.emit()
                return True
        return False

    def remove_from_collection(self, collection_name: str, file_path: str) -> bool:
        """Quita un archivo de una colección virtual."""
        norm_path = os.path.normpath(file_path).replace("\\", "/")
        if collection_name in self.collections:
            if norm_path in self.collections[collection_name]:
                self.collections[collection_name].remove(norm_path)
                self.save_data()
                self._invalidate_media_cache()
                self.collections_changed.emit()
                return True
        return False

    # ── Lectura de Archivos (Físicos y Virtuales) ────────────────────────────
    # Cache interna de resultados de escaneo para evitar I/O repetitivo.
    # Se invalida cuando watchdog detecta cambios o se agregan/remueven carpetas y colecciones.
    
    def _invalidate_media_cache(self):
        """Invalida la cache de archivos multimedia para forzar un re-escaneo en la próxima consulta."""
        if not hasattr(self, "_media_cache"):
            self._media_cache = {}
        self._media_cache.clear()

    def _build_file_entry(self, path: str, name: str, ext: str) -> dict:
        """Construye un diccionario de archivo multimedia SIN llamar a mutagen (duración diferida)."""
        tipo = get_media_type(ext)
        try:
            size_val = os.path.getsize(path)
        except Exception:
            size_val = 0
        return {
            "nombre": name,
            "ruta": path.replace("\\", "/"),
            "tipo": tipo,
            "tamaño": format_size(size_val),
            "duración": "-"  # Se calcula de forma diferida al seleccionar el archivo
        }

    def get_media_duration_for_file(self, path: str) -> str:
        """Obtiene la duración de un archivo de audio de forma diferida (solo al seleccionarlo)."""
        ext = os.path.splitext(path)[1].lower()
        return get_media_duration(path, ext)

    def get_media_files_in_folder(self, folder_path: str) -> list:
        """Retorna la lista de archivos multimedia contenidos directamente en la carpeta (con cache)."""
        cache_key = f"folder:{folder_path}"
        if hasattr(self, "_media_cache") and cache_key in self._media_cache:
            return self._media_cache[cache_key]
        
        if not hasattr(self, "_media_cache"):
            self._media_cache = {}

        files = []
        if os.path.exists(folder_path) and os.path.isdir(folder_path):
            try:
                with os.scandir(folder_path) as entries:
                    for entry in entries:
                        if entry.is_file(follow_symlinks=False):
                            ext = os.path.splitext(entry.name)[1].lower()
                            if ext in VALID_EXTS:
                                files.append(self._build_file_entry(entry.path, entry.name, ext))
            except Exception as e:
                logger.error(f"EditingMediaLogic: Error listando archivos de {folder_path}: {e}")
        
        self._media_cache[cache_key] = files
        return files

    def get_media_files_in_collection(self, collection_name: str) -> list:
        """Retorna la lista de archivos multimedia asociados a la colección virtual, validando su existencia (con cache)."""
        cache_key = f"collection:{collection_name}"
        if hasattr(self, "_media_cache") and cache_key in self._media_cache:
            return self._media_cache[cache_key]
        
        if not hasattr(self, "_media_cache"):
            self._media_cache = {}

        files = []
        if collection_name in self.collections:
            paths_to_keep = []
            has_changes = False
            
            for path in self.collections[collection_name]:
                if os.path.exists(path) and os.path.isfile(path):
                    paths_to_keep.append(path)
                    name = os.path.basename(path)
                    ext = os.path.splitext(name)[1].lower()
                    files.append(self._build_file_entry(path, name, ext))
                else:
                    has_changes = True
                    logger.info(f"EditingMediaLogic: Removiendo archivo inexistente de la colección: {path}")

            if has_changes:
                self.collections[collection_name] = paths_to_keep
                self.save_data()
                
        self._media_cache[cache_key] = files
        return files

    def get_all_media_files(self) -> list:
        """Escanéa todas las carpetas indexadas recursivamente y colecciones, retornando la lista consolidada (con cache)."""
        cache_key = "__all__"
        if hasattr(self, "_media_cache") and cache_key in self._media_cache:
            return self._media_cache[cache_key]
        
        if not hasattr(self, "_media_cache"):
            self._media_cache = {}

        files = []
        seen_paths = set()
        
        # 1. Escanear carpetas físicas indexadas de forma recursiva
        for folder in self.indexed_folders:
            if os.path.exists(folder) and os.path.isdir(folder):
                try:
                    for root, dirs, filenames in os.walk(folder):
                        for name in filenames:
                            ext = os.path.splitext(name)[1].lower()
                            if ext in VALID_EXTS:
                                path = os.path.join(root, name).replace("\\", "/")
                                if path not in seen_paths:
                                    seen_paths.add(path)
                                    files.append(self._build_file_entry(path, name, ext))
                except Exception as e:
                    logger.error(f"EditingMediaLogic: Error en escaneo general de {folder}: {e}")

        # 2. Agregar archivos en colecciones
        for col_name in self.collections.keys():
            for path in self.collections[col_name]:
                norm_path = path.replace("\\", "/")
                if os.path.exists(norm_path) and os.path.isfile(norm_path):
                    if norm_path not in seen_paths:
                        seen_paths.add(norm_path)
                        name = os.path.basename(norm_path)
                        ext = os.path.splitext(name)[1].lower()
                        files.append(self._build_file_entry(norm_path, name, ext))

        self._media_cache[cache_key] = files
        return files


def extract_waveform_peaks(audio_path: str, num_peaks: int = 150) -> list:
    """Extrae las amplitudes reales de un archivo de audio usando ffmpeg de forma rápida."""
    from core.setup.ffmpeg_setup import get_ffmpeg_dir, get_platform_info, check_ffmpeg
    if not check_ffmpeg():
        logger.warning("EditingMediaLogic: ffmpeg no está instalado, no se puede extraer la forma de onda.")
        return []
    
    info = get_platform_info()
    ffmpeg_exe = os.path.join(get_ffmpeg_dir(), info["binary_name"])
    
    # Decodificar el archivo como mono, 16 bits, y downsamplear a 1000 Hz.
    # Esto reduce la cantidad de datos transmitida enormemente para rapidez (1000 muestras/seg).
    cmd = [
        ffmpeg_exe,
        "-y",
        "-i", audio_path,
        "-f", "s16le",
        "-ac", "1",
        "-ar", "1000",
        "-"
    ]
    
    try:
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo
        )
        
        # Leer el buffer decodificado
        raw_data, _ = process.communicate()
        
        if len(raw_data) < 2:
            return []
            
        # Cada muestra son 2 bytes (16-bit)
        num_samples = len(raw_data) // 2
        samples = struct.unpack(f"{num_samples}h", raw_data)
        
        # Obtener amplitudes absolutas
        abs_samples = [abs(s) for s in samples]
        
        # Agrupar en la cantidad solicitada de picos (num_peaks)
        peaks = []
        chunk_size = max(1, len(abs_samples) // num_peaks)
        for i in range(num_peaks):
            start = i * chunk_size
            end = start + chunk_size
            chunk = abs_samples[start:end]
            if chunk:
                peaks.append(max(chunk))
            else:
                peaks.append(0)
                
        # Normalizar a rango [0.0, 1.0]
        max_val = max(peaks) if peaks else 0
        if max_val > 0:
            peaks = [float(p) / max_val for p in peaks]
        else:
            peaks = [0.0] * num_peaks
            
        return peaks
    except Exception as e:
        logger.error(f"EditingMediaLogic: Error extrayendo amplitudes de onda: {e}")
        return []


class WaveformExtractorThread(QThread):
    """Hilo secundario para extraer de forma asíncrona la forma de onda de audio real sin bloquear la UI."""
    finished_extraction = Signal(list)

    def __init__(self, audio_path: str, num_peaks: int = 150, parent=None):
        super().__init__(parent)
        self.audio_path = audio_path
        self.num_peaks = num_peaks

    def run(self):
        peaks = extract_waveform_peaks(self.audio_path, self.num_peaks)
        self.finished_extraction.emit(peaks)
