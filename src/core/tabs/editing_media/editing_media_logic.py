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


def check_file_has_audio(path: str) -> bool:
    """Verifica rápidamente si un archivo multimedia contiene una pista de audio usando ffmpeg."""
    from core.setup.ffmpeg_setup import get_ffmpeg_dir, get_platform_info, check_ffmpeg
    if not check_ffmpeg():
        return False
    try:
        info = get_platform_info()
        ffmpeg_exe = os.path.join(get_ffmpeg_dir(), info["binary_name"])
        cmd = [ffmpeg_exe, "-hide_banner", "-i", path]
        
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
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
        
        # Buscar cualquier stream de audio en la salida de ffmpeg
        import re
        return bool(re.search(r"Stream #\d+:\d+.*Audio:", stderr))
    except Exception as e:
        logger.error(f"EditingMediaLogic: Error verificando audio en {path}: {e}")
        return False


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
        
        from core.utils.paths import get_indexed_media_path
        self.db_path = get_indexed_media_path()
        
        self.indexed_folders = []
        self.collections = {
            "Favoritos": [],
            "SFX": [],
            "Música": []
        }
        self.freesound_auth = {
            "access_token": "",
            "refresh_token": "",
            "expires_at": 0,
            "username": ""
        }
        
        self.observer = None
        self.load_data()
        self.start_watcher()

    def load_data(self):
        """Carga carpetas indexadas, colecciones y auth OAuth2 desde indexed_media.json."""
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
                    # Cargar autenticación OAuth2 (con migración desde formato legacy)
                    saved_auth = data.get("freesound_auth", None)
                    if saved_auth and isinstance(saved_auth, dict):
                        self.freesound_auth.update(saved_auth)
                    self.last_selected_tree_node = data.get("last_selected_tree_node", None)
                logger.info(f"EditingMediaLogic: Datos cargados desde {self.db_path}")
            except Exception as e:
                logger.error(f"EditingMediaLogic: Error leyendo base de datos: {e}")
        else:
            self.save_data()

    def save_data(self):
        """Guarda carpetas indexadas, colecciones, auth OAuth2 y nodo seleccionado en indexed_media.json."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        try:
            data = {
                "indexed_folders": self.indexed_folders,
                "collections": self.collections,
                "freesound_auth": self.freesound_auth,
                "last_selected_tree_node": getattr(self, "last_selected_tree_node", None)
            }
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            logger.debug(f"EditingMediaLogic: Datos guardados en {self.db_path}")
        except Exception as e:
            logger.error(f"EditingMediaLogic: Error guardando datos: {e}")

    @property
    def freesound_token(self) -> str | None:
        """Obtiene un access token OAuth2 válido, refrescando automáticamente si expiró."""
        from core.tabs.editing_media.freesound_auth import FreesoundAuth
        return FreesoundAuth.get_valid_token(self.freesound_auth, save_callback=self.save_data)

    @property
    def freesound_username(self) -> str:
        """Retorna el username de Freesound del usuario autenticado."""
        return self.freesound_auth.get("username", "")

    @property
    def is_freesound_authenticated(self) -> bool:
        """Verifica si hay una sesión de Freesound activa."""
        return bool(self.freesound_auth.get("access_token", ""))

    def clear_freesound_auth(self):
        """Cierra la sesión de Freesound limpiando todos los tokens."""
        self.freesound_auth = {
            "access_token": "",
            "refresh_token": "",
            "expires_at": 0,
            "username": ""
        }
        self.save_data()
        logger.info("EditingMediaLogic: Sesión de Freesound cerrada")

    # ── Gestión de Monitoreo en Tiempo Real (Watchdog) ───────────────────────
    def start_watcher(self):
        """Inicia el watchdog observer para vigilar las carpetas físicas."""
        if not WATCHDOG_AVAILABLE:
            return

        if self.observer is not None:
            self.stop_watcher()

        self.observer = Observer()
        self._observer_started = False
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
                self._observer_started = True
                logger.info(f"EditingMediaLogic: Watchdog iniciado con {active_watches} carpetas vigiladas.")
            except Exception as e:
                self._observer_started = False
                logger.error(f"EditingMediaLogic: Error iniciando Watchdog: {e}")

    def stop_watcher(self):
        """Detiene el watchdog observer de forma segura."""
        if self.observer:
            try:
                if getattr(self, "_observer_started", False):
                    self.observer.stop()
                    self.observer.join(timeout=2.0)
            except RuntimeError as e:
                logger.debug(f"EditingMediaLogic: Watchdog no estaba corriendo: {e}")
            except Exception as e:
                logger.error(f"EditingMediaLogic: Error deteniendo Watchdog: {e}")
            finally:
                self.observer = None
                self._observer_started = False

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
        """Asocia un archivo (acceso directo o URL remota) a una colección virtual."""
        is_remote = file_path.startswith("http://") or file_path.startswith("https://")
        norm_path = file_path if is_remote else os.path.normpath(file_path).replace("\\", "/")
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
        is_remote = file_path.startswith("http://") or file_path.startswith("https://")
        norm_path = file_path if is_remote else os.path.normpath(file_path).replace("\\", "/")
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

    def _build_file_entry(self, path: str, name: str, ext: str, st=None) -> dict:
        """Construye un diccionario de archivo multimedia SIN llamar a mutagen (duración diferida)."""
        tipo = get_media_type(ext)
        is_remote = path.startswith("http://") or path.startswith("https://")
        size_val = 0
        mtime_val = 0.0
        ctime_val = 0.0
        if not is_remote:
            try:
                if st is None:
                    st = os.stat(path)
                size_val = st.st_size
                mtime_val = st.st_mtime
                ctime_val = st.st_ctime
            except Exception:
                pass
        return {
            "nombre": name,
            "ruta": path if is_remote else path.replace("\\", "/"),
            "tipo": tipo,
            "tamaño": "-" if is_remote else format_size(size_val),
            "size_bytes": size_val,
            "mtime": mtime_val,
            "ctime": ctime_val,
            "duración": "-",  # Se calcula de forma diferida al seleccionar el archivo
            "es_remoto": is_remote
        }

    def _scan_folder_fast(self, folder_path: str, recursive: bool = True) -> list:
        """Escanea una carpeta (y opcionalmente sus subcarpetas) iterativamente usando os.scandir."""
        files = []
        if not (os.path.exists(folder_path) and os.path.isdir(folder_path)):
            return files

        dirs_to_visit = [folder_path]
        while dirs_to_visit:
            curr_dir = dirs_to_visit.pop()
            try:
                with os.scandir(curr_dir) as it:
                    for entry in it:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                if recursive:
                                    dirs_to_visit.append(entry.path)
                            elif entry.is_file(follow_symlinks=False):
                                ext = os.path.splitext(entry.name)[1].lower()
                                if ext in VALID_EXTS:
                                    try:
                                        st = entry.stat()
                                    except Exception:
                                        st = None
                                    files.append(self._build_file_entry(entry.path, entry.name, ext, st=st))
                        except Exception:
                            continue
            except Exception:
                continue
        return files

    def get_media_duration_for_file(self, path: str) -> str:
        """Obtiene la duración de un archivo de audio de forma diferida (solo al seleccionarlo)."""
        ext = os.path.splitext(path)[1].lower()
        return get_media_duration(path, ext)

    def get_media_files_in_folder(self, folder_path: str, recursive: bool = True) -> list:
        """Retorna la lista de archivos multimedia en la carpeta (con cache)."""
        cache_key = f"folder:{folder_path}:{recursive}"
        if hasattr(self, "_media_cache") and cache_key in self._media_cache:
            return self._media_cache[cache_key]
        
        if not hasattr(self, "_media_cache"):
            self._media_cache = {}

        files = self._scan_folder_fast(folder_path, recursive=recursive)
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
                is_remote = path.startswith("http://") or path.startswith("https://")
                if is_remote or (os.path.exists(path) and os.path.isfile(path)):
                    paths_to_keep.append(path)
                    
                    if is_remote:
                        clean_path = path.split('?')[0]
                        name = os.path.basename(clean_path)
                        if not os.path.splitext(name)[1]:
                            name = name + ".mp3"
                    else:
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
        
        # 1. Escanear carpetas físicas indexadas de forma recursiva con os.scandir
        for folder in self.indexed_folders:
            folder_files = self._scan_folder_fast(folder)
            for f_entry in folder_files:
                norm = f_entry["ruta"]
                if norm not in seen_paths:
                    seen_paths.add(norm)
                    files.append(f_entry)

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


class WaveformExtractorThread(QThread):
    """Hilo secundario para extraer de forma asíncrona la forma de onda de audio real progresivamente sin bloquear la UI."""
    finished_extraction = Signal(list)
    peaks_updated = Signal(list)

    def __init__(self, audio_path: str, num_peaks: int = 150, duration_sec: float = 0.0, parent=None):
        super().__init__(parent)
        self.audio_path = audio_path
        self.num_peaks = num_peaks
        self.duration_sec = duration_sec
        self.process = None
        self._is_cancelled = False

    def run(self):
        from core.setup.ffmpeg_setup import get_ffmpeg_dir, get_platform_info, check_ffmpeg
        if not check_ffmpeg():
            logger.warning("EditingMediaLogic: ffmpeg no está instalado, no se puede extraer la forma de onda.")
            self.finished_extraction.emit([])
            return

        info = get_platform_info()
        ffmpeg_exe = os.path.join(get_ffmpeg_dir(), info["binary_name"])

        # Si la duración es 0 o desconocida, usamos 120 segundos por defecto
        dur = self.duration_sec if self.duration_sec > 0 else 120.0

        # Muestreo dinámico: asegurar que total_samples_est // num_peaks >= 64
        # Para lograr esto, el sample_rate mínimo debe ser (num_peaks * 64) / dur
        min_sr = int((self.num_peaks * 64) / dur) + 1
        sample_rate = max(1000, min(11025, min_sr))

        # Optimizar el arranque y streaming de FFmpeg
        cmd = [
            ffmpeg_exe,
            "-y",
            "-probesize", "32768",
            "-analyzeduration", "0",
            "-i", self.audio_path,
            "-vn",                     # Desactivar decodificación de video para ir mucho más rápido
            "-f", "s16le",
            "-ac", "1",
            "-ar", str(sample_rate),
            "-"
        ]

        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                startupinfo=startupinfo
            )

            # Leer todo el stream decodificado de una vez
            raw_data = self.process.stdout.read()
            self.process.wait()

            if self._is_cancelled:
                return

            total_bytes = len(raw_data)
            num_samples = total_bytes // 2
            if num_samples == 0:
                self.finished_extraction.emit([])
                return

            # Desempaquetar todas las muestras
            samples = struct.unpack(f"{num_samples}h", raw_data)

            # Dividir exactamente en self.num_peaks bloques usando indexación float
            peaks = []
            block_size = num_samples / self.num_peaks
            for i in range(self.num_peaks):
                if self._is_cancelled:
                    return
                start_idx = int(i * block_size)
                end_idx = max(start_idx + 1, int((i + 1) * block_size))
                
                block_samples = samples[start_idx:end_idx]
                if block_samples:
                    block_peak = max(abs(s) for s in block_samples)
                    peaks.append(block_peak)
                else:
                    peaks.append(0.0)

            # Normalizar los picos
            max_val = max(peaks) if peaks else 0
            if max_val > 0:
                final_peaks = [float(p) / max_val for p in peaks]
            else:
                final_peaks = [0.0] * self.num_peaks

            # Emitir picos actualizados e indicar finalización
            self.peaks_updated.emit(final_peaks)
            self.finished_extraction.emit(final_peaks)

        except Exception as e:
            logger.error(f"EditingMediaLogic: Error extrayendo amplitudes de onda: {e}")
            self.finished_extraction.emit([])
        finally:
            self.cleanup()

    def cleanup(self):
        if self.process:
            try:
                self.process.stdout.close()
            except Exception:
                pass
            try:
                self.process.terminate()
                self.process.wait(timeout=1.0)
            except Exception:
                pass
            self.process = None

    def stop(self):
        self._is_cancelled = True
        self.cleanup()


class RemoteWaveformLoaderThread(QThread):
    """Hilo secundario para descargar una imagen de waveform de Freesound y extraer sus picos en milisegundos."""
    finished = Signal(list)

    def __init__(self, url: str, num_peaks: int, parent=None):
        super().__init__(parent)
        self.url = url
        self.num_peaks = num_peaks

    def run(self):
        try:
            import requests
            from PySide6.QtGui import QImage
            
            # Descargar imagen (pequeña y rápida)
            response = requests.get(self.url, timeout=10)
            response.raise_for_status()

            # QImage es seguro de utilizar y manipular en hilos secundarios
            img = QImage.fromData(response.content)
            if img.isNull():
                self.finished.emit([])
                return

            img_w = img.width()
            img_h = img.height()
            if img_w <= 0 or img_h <= 0:
                self.finished.emit([])
                return

            # Detectar el color de fondo muestreando las esquinas
            corners = [
                img.pixelColor(0, 0),
                img.pixelColor(img_w - 1, 0),
                img.pixelColor(0, img_h - 1),
                img.pixelColor(img_w - 1, img_h - 1)
            ]
            bg = corners[0]
            bg_r, bg_g, bg_b, bg_a = bg.red(), bg.green(), bg.blue(), bg.alpha()

            peaks = []
            for i in range(self.num_peaks):
                col_x = int(i * (img_w - 1) / (self.num_peaks - 1)) if self.num_peaks > 1 else 0

                y_min = -1
                y_max = -1
                for y in range(img_h):
                    color = img.pixelColor(col_x, y)
                    # Heurística para ver si el píxel pertenece al waveform (no es fondo)
                    is_fg = False
                    if bg_a < 20:  # Fondo transparente
                        is_fg = color.alpha() > 30
                    else:  # Fondo sólido
                        # Distancia euclidiana en el espacio RGB
                        dist = ((color.red() - bg_r)**2 + (color.green() - bg_g)**2 + (color.blue() - bg_b)**2)**0.5
                        is_fg = dist > 35

                    if is_fg:
                        if y_min == -1:
                            y_min = y
                        y_max = y

                if y_min != -1 and y_max != -1:
                    peaks.append(float(y_max - y_min + 1))
                else:
                    peaks.append(0.0)

            # Normalizar valores a rango [0.0, 1.0]
            max_val = max(peaks) if peaks else 0
            if max_val > 0:
                normalized_peaks = [p / max_val for p in peaks]
            else:
                normalized_peaks = [0.0] * self.num_peaks

            self.finished.emit(normalized_peaks)
        except Exception as e:
            logger.error(f"RemoteWaveformLoaderThread: Error cargando waveform remoto: {e}")
            self.finished.emit([])

