# src/core/tabs/editing_media/waveform_cache_manager.py
import os
import hashlib
import json
import subprocess
import struct
import array
from PySide6.QtCore import QObject, Signal, QRunnable, QThreadPool, Qt, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor

from core.logger.logger_manager import logger
from core.setup.ffmpeg_setup import get_ffmpeg_dir, get_platform_info, check_ffmpeg
from core.utils.paths import get_waveform_cache_dir
from gui.styles import get_theme_token

CACHE_DIR = get_waveform_cache_dir()

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

def render_waveform_icon(peaks: list, size: QSize = QSize(80, 80)) -> QIcon:
    """Renderiza una lista de picos en un QIcon de estilo waveform."""
    if not peaks:
        return QIcon()
    
    out = QPixmap(size)
    out.fill(Qt.transparent)
    
    painter = QPainter(out)
    painter.setRenderHint(QPainter.Antialiasing)
    
    width = size.width()
    height = size.height()
    acento = get_theme_token('acento_primario', '#B9E640')
    
    num_bars = len(peaks)
    span = width
    step = span / (num_bars - 1) if num_bars > 1 else span
    bar_width = max(1, int(step * 0.7))
    
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(acento))
    
    mid_y = height / 2
    for i, peak in enumerate(peaks):
        val = max(0.05, min(peak, 1.0))
        bar_h = val * height
        x = i * step
        y = mid_y - (bar_h / 2)
        painter.drawRoundedRect(int(x), int(y), int(bar_width), int(bar_h), 1, 1)
        
    painter.end()
    return _make_multi_state_icon(out)


class WaveformWorkerSignals(QObject):
    finished = Signal(str, list)  # (file_path, peaks)
    failed = Signal(str)          # (file_path)

class WaveformRunnable(QRunnable):
    def __init__(self, file_path: str, manager: "WaveformCacheManager", num_peaks: int = 120):
        super().__init__()
        self.file_path = file_path
        self.manager = manager
        self.num_peaks = num_peaks
        self.signals = WaveformWorkerSignals()

    def run(self):
        try:
            peaks = self._extract_peaks()
            if peaks is not None:
                self.manager._save_peaks_to_cache(self.file_path, peaks)
                self.signals.finished.emit(self.file_path, peaks)
            else:
                self.signals.failed.emit(self.file_path)
        except Exception as e:
            logger.error(f"WaveformRunnable: Error {self.file_path}: {e}")
            self.signals.failed.emit(self.file_path)
        finally:
            self.manager._task_finished(self.file_path)

    def _extract_peaks(self) -> list:
        if not check_ffmpeg():
            return []
            
        info = get_platform_info()
        ffmpeg_exe = os.path.join(get_ffmpeg_dir(), info["binary_name"])
        
        # Extraction at 1000 Hz for icon thumbnails (low res)
        sample_rate = 1000
        cmd = [
            ffmpeg_exe, "-y", "-probesize", "32768", "-analyzeduration", "0",
            "-i", self.file_path, "-vn", "-f", "s16le", "-ac", "1", "-ar", str(sample_rate), "-"
        ]
        
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, startupinfo=startupinfo
        )
        
        raw_data = process.stdout.read()
        process.wait()
        
        total_bytes = len(raw_data)
        num_samples = total_bytes // 2
        if num_samples == 0:
            return []
            
        samples = struct.unpack(f"{num_samples}h", raw_data)
        peaks = []
        block_size = num_samples / self.num_peaks
        for i in range(self.num_peaks):
            start_idx = int(i * block_size)
            end_idx = max(start_idx + 1, int((i + 1) * block_size))
            block_samples = samples[start_idx:end_idx]
            if block_samples:
                block_peak = max(abs(s) for s in block_samples)
                peaks.append(block_peak)
            else:
                peaks.append(0.0)
                
        max_val = max(peaks) if peaks else 0
        if max_val > 0:
            return [float(p) / max_val for p in peaks]
        return [0.0] * self.num_peaks


class HiResWaveformWorkerSignals(QObject):
    finished = Signal(str, list, int)  # (file_path, minmax_peaks, audio_track)
    failed = Signal(str, int)          # (file_path, audio_track)

class HiResWaveformRunnable(QRunnable):
    """Extrae forma de onda de alta resolución con pares (min, max) para renderizado profesional.

    `audio_track` (0-based) permite extraer una pista de audio específica en medios
    multipista, en vez de la primera pista por defecto (0)."""
    def __init__(self, file_path: str, manager: "WaveformCacheManager", num_peaks: int = 4000, audio_track: int = 0):
        super().__init__()
        self.file_path = file_path
        self.manager = manager
        self.num_peaks = num_peaks
        self.audio_track = audio_track
        self.signals = HiResWaveformWorkerSignals()

    def run(self):
        try:
            peaks = self._extract_minmax_peaks()
            if peaks:
                self.manager._save_hires_peaks_to_cache(self.file_path, peaks, self.audio_track)

                # Derivar picos de baja resolución (120 puntos) para miniaturas e íconos
                # (solo se cachean/emiten para la pista 0, que es la que usan las listas/íconos).
                if self.audio_track == 0:
                    lowres = self._derive_lowres_peaks(peaks, 120)
                    self.manager._save_peaks_to_cache(self.file_path, lowres)
                    self.manager._peaks_cache[self.file_path] = lowres

                self.signals.finished.emit(self.file_path, peaks, self.audio_track)
            else:
                self.signals.failed.emit(self.file_path, self.audio_track)
        except Exception as e:
            logger.error(f"HiResWaveformRunnable: Error {self.file_path}: {e}")
            self.signals.failed.emit(self.file_path, self.audio_track)
        finally:
            self.manager._hires_task_finished(self.file_path, self.audio_track)

    def _derive_lowres_peaks(self, minmax_peaks: list, target_count: int = 120) -> list:
        if not minmax_peaks:
            return []
        n = len(minmax_peaks)
        resampled = []
        block_size = n / target_count
        for i in range(target_count):
            start_idx = int(i * block_size)
            end_idx = max(start_idx + 1, int((i + 1) * block_size))
            end_idx = min(end_idx, n)
            peak_val = 0.0
            for j in range(start_idx, end_idx):
                mn, mx = minmax_peaks[j]
                v = max(abs(mn), abs(mx))
                if v > peak_val:
                    peak_val = v
            resampled.append(peak_val)
        return resampled

    def _extract_minmax_peaks(self) -> list:
        """Extrae pares (min_normalizado, max_normalizado) de alta resolución."""
        if not check_ffmpeg():
            return []

        info = get_platform_info()
        ffmpeg_exe = os.path.join(get_ffmpeg_dir(), info["binary_name"])

        # Alta resolución optimizada: 8000 Hz mono para velocidad ultra rápida y alta precisión visual
        sample_rate = 8000
        cmd = [ffmpeg_exe, "-y", "-probesize", "32768", "-analyzeduration", "0", "-i", self.file_path]
        if self.audio_track:
            # Pista de audio específica (medios multipista), 0-based igual que QMediaPlayer.audioTracks().
            cmd += ["-map", f"0:a:{self.audio_track}"]
        else:
            cmd += ["-vn"]
        cmd += ["-f", "s16le", "-ac", "1", "-ar", str(sample_rate), "-"]

        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, startupinfo=startupinfo
        )

        raw_data = process.stdout.read()
        process.wait()

        total_bytes = len(raw_data)
        num_samples = total_bytes // 2
        if num_samples == 0:
            return []

        samples = array.array('h')
        samples.frombytes(raw_data)

        # Encontrar el pico absoluto global a velocidad C nativa
        min_s = min(samples)
        max_s = max(samples)
        global_max = max(abs(min_s), abs(max_s), 1)
        inv_gmax = 1.0 / global_max

        # Extraer min/max por bloque (hasta 4000 picos de alta resolución)
        target_num_peaks = max(500, min(num_samples // 4, 4000))
        minmax_peaks = []
        block_size = num_samples / target_num_peaks
        for i in range(target_num_peaks):
            start_idx = int(i * block_size)
            end_idx = max(start_idx + 1, int((i + 1) * block_size))
            block = samples[start_idx:end_idx]
            if block:
                minmax_peaks.append((min(block) * inv_gmax, max(block) * inv_gmax))
            else:
                minmax_peaks.append((0.0, 0.0))

        return minmax_peaks

class WaveformCacheManager(QObject):
    waveform_loaded = Signal(str, list)  # (file_path, peaks) - low res for icons
    hires_waveform_loaded = Signal(str, list, int)  # (file_path, minmax_peaks, audio_track) - high res

    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = WaveformCacheManager()
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        os.makedirs(CACHE_DIR, exist_ok=True)
        self.thread_pool = QThreadPool.globalInstance()
        self._qicon_cache: dict[str, QIcon] = {}
        self._peaks_cache: dict[str, list] = {}
        self._hash_cache: dict[str, str] = {}
        self._pending_files = set()
        self._failed_files = set()
        # Referencias fuertes a los workers en curso: sin esto, nada en el lado Python los
        # mantiene vivos una vez que request_waveform()/request_hires_waveform() retorna (el
        # QThreadPool los posee en C++, pero el wrapper de PySide6 puede recolectarse antes de
        # que el evento de la señal en cola termine de entregarse en el hilo principal). Se
        # limpian en _task_finished()/_hires_task_finished(), cuando el worker ya terminó.
        self._active_workers = {}

    def _get_hash_key(self, file_path: str, audio_track: int = 0) -> str:
        # La pista 0 (la inmensa mayoría de los medios) conserva exactamente el mismo hash de
        # siempre, para no invalidar la caché en disco ya existente. Solo las pistas != 0
        # (medios multipista) reciben un hash distinto, en su propio archivo de caché.
        cache_lookup_key = file_path if not audio_track else f"{file_path}::t{audio_track}"
        if cache_lookup_key in self._hash_cache:
            return self._hash_cache[cache_lookup_key]
        try:
            stat = os.stat(file_path)
            raw = f"{os.path.abspath(file_path)}_{stat.st_mtime}_{stat.st_size}_wf_v2"
        except Exception:
            raw = f"{os.path.abspath(file_path)}_wf_v2"
        if audio_track:
            raw += f"_t{audio_track}"
        hash_val = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        self._hash_cache[cache_lookup_key] = hash_val
        return hash_val

    def get_cached_peaks(self, file_path: str) -> list | None:
        if file_path in self._peaks_cache:
            return self._peaks_cache[file_path]
            
        hash_key = self._get_hash_key(file_path)
        json_path = os.path.join(CACHE_DIR, f"{hash_key}.json")
        if os.path.exists(json_path) and os.path.getsize(json_path) > 0:
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    peaks = json.load(f)
                self._peaks_cache[file_path] = peaks
                return peaks
            except Exception:
                pass
        return None

    def get_cached_qicon(self, file_path: str, size: QSize = QSize(80, 80)) -> QIcon | None:
        cache_key = (file_path, size.width(), size.height())
        if cache_key in self._qicon_cache:
            return self._qicon_cache[cache_key]

        peaks = self.get_cached_peaks(file_path)
        if peaks is not None:
            icon = render_waveform_icon(peaks, size)
            self._qicon_cache[cache_key] = icon
            return icon
        return None

    def request_waveform(self, file_path: str, num_peaks: int = 120, size: QSize = QSize(80, 80)):
        cache_key = (file_path, size.width(), size.height())
        if cache_key in self._qicon_cache:
            return

        cached_peaks = self.get_cached_peaks(file_path)
        if cached_peaks is not None:
            icon = render_waveform_icon(cached_peaks, size)
            self._qicon_cache[cache_key] = icon
            self.waveform_loaded.emit(file_path, cached_peaks)
            return

        if file_path in self._pending_files or file_path in self._failed_files:
            return

        self._pending_files.add(file_path)
        worker = WaveformRunnable(file_path, self, num_peaks)
        self._active_workers[file_path] = worker
        worker.signals.finished.connect(self._on_worker_finished, Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(self._on_worker_failed, Qt.ConnectionType.QueuedConnection)
        self.thread_pool.start(worker)

    def _save_peaks_to_cache(self, file_path: str, peaks: list):
        hash_key = self._get_hash_key(file_path)
        json_path = os.path.join(CACHE_DIR, f"{hash_key}.json")
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(peaks, f)
        except Exception as e:
            logger.error(f"WaveformCacheManager: Error guardando json {json_path}: {e}")

    def _hires_cache_key(self, file_path: str, audio_track: int = 0) -> str:
        return f"{file_path}_hires" if not audio_track else f"{file_path}_hires_t{audio_track}"

    def _save_hires_peaks_to_cache(self, file_path: str, peaks: list, audio_track: int = 0):
        hash_key = self._get_hash_key(file_path, audio_track)
        json_path = os.path.join(CACHE_DIR, f"{hash_key}_hires.json")
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(peaks, f)
        except Exception as e:
            logger.error(f"WaveformCacheManager: Error guardando hires json {json_path}: {e}")

    def get_cached_hires_peaks(self, file_path: str, audio_track: int = 0) -> list | None:
        cache_key = self._hires_cache_key(file_path, audio_track)
        if cache_key in self._peaks_cache:
            return self._peaks_cache[cache_key]
        hash_key = self._get_hash_key(file_path, audio_track)
        json_path = os.path.join(CACHE_DIR, f"{hash_key}_hires.json")
        if os.path.exists(json_path) and os.path.getsize(json_path) > 0:
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    peaks = json.load(f)
                # Convertir listas a tuplas
                peaks = [(p[0], p[1]) for p in peaks]
                self._peaks_cache[cache_key] = peaks
                return peaks
            except Exception:
                pass
        return None

    def request_hires_waveform(self, file_path: str, num_peaks: int = 4000, audio_track: int = 0):
        """`audio_track` (0-based) permite pedir la waveform de una pista de audio específica
        en medios multipista; por defecto usa la primera pista (0), como siempre."""
        cache_key = self._hires_cache_key(file_path, audio_track)
        if cache_key in self._peaks_cache:
            self.hires_waveform_loaded.emit(file_path, self._peaks_cache[cache_key], audio_track)
            return
        cached = self.get_cached_hires_peaks(file_path, audio_track)
        if cached is not None:
            self.hires_waveform_loaded.emit(file_path, cached, audio_track)
            return
        if cache_key in self._pending_files:
            return
        self._pending_files.add(cache_key)
        worker = HiResWaveformRunnable(file_path, self, num_peaks, audio_track)
        self._active_workers[cache_key] = worker
        # Conexión directa a métodos vinculados (en vez de lambdas) con QueuedConnection
        # explícita: al conectar a un lambda "suelto" (no vinculado a un QObject), PySide6 no
        # siempre puede determinar la afinidad de hilo del receptor para decidir si encolar la
        # entrega, lo que puede terminar invocando el slot directamente en el hilo del worker en
        # vez de en el hilo principal — causa muy probable del crash nativo (0xc0000005 en
        # Qt6Core.dll) que se veía al cargar un archivo sin cachear.
        worker.signals.finished.connect(self._on_hires_worker_finished, Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(self._on_hires_worker_failed, Qt.ConnectionType.QueuedConnection)
        self.thread_pool.start(worker)

    def _on_hires_worker_finished(self, file_path: str, peaks: list, audio_track: int = 0):
        cache_key = self._hires_cache_key(file_path, audio_track)
        self._peaks_cache[cache_key] = peaks
        self.hires_waveform_loaded.emit(file_path, peaks, audio_track)

    def _on_hires_worker_failed(self, file_path: str, audio_track: int = 0):
        cache_key = self._hires_cache_key(file_path, audio_track)
        self._failed_files.add(cache_key)

    def _hires_task_finished(self, file_path: str, audio_track: int = 0):
        cache_key = self._hires_cache_key(file_path, audio_track)
        self._pending_files.discard(cache_key)
        self._active_workers.pop(cache_key, None)

    def _on_worker_finished(self, file_path: str, peaks: list):
        self._peaks_cache[file_path] = peaks
        self.waveform_loaded.emit(file_path, peaks)

    def _on_worker_failed(self, file_path: str):
        self._failed_files.add(file_path)

    def _task_finished(self, file_path: str):
        self._pending_files.discard(file_path)
        self._active_workers.pop(file_path, None)
        
    def clear_cache(self) -> int:
        count = 0
        try:
            self._qicon_cache.clear()
            self._peaks_cache.clear()
            self._hash_cache.clear()
            self._failed_files.clear()
            
            if os.path.exists(CACHE_DIR):
                for f in os.listdir(CACHE_DIR):
                    if f.endswith(".json"):
                        fpath = os.path.join(CACHE_DIR, f)
                        os.remove(fpath)
                        count += 1
            logger.info(f"WaveformCacheManager: Se eliminaron {count} waveforms cacheados.")
        except Exception as e:
            logger.error(f"WaveformCacheManager: Error en limpieza global: {e}")
        return count
