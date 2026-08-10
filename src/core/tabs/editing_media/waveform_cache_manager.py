# src/core/tabs/editing_media/waveform_cache_manager.py
import os
import hashlib
import json
import subprocess
import struct
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
    def __init__(self, file_path: str, manager: "WaveformCacheManager", num_peaks: int = 80):
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
    finished = Signal(str, list)  # (file_path, minmax_peaks)
    failed = Signal(str)

class HiResWaveformRunnable(QRunnable):
    """Extrae forma de onda de alta resolución con pares (min, max) para renderizado profesional."""
    def __init__(self, file_path: str, manager: "WaveformCacheManager", num_peaks: int = 4000):
        super().__init__()
        self.file_path = file_path
        self.manager = manager
        self.num_peaks = num_peaks
        self.signals = HiResWaveformWorkerSignals()

    def run(self):
        try:
            peaks = self._extract_minmax_peaks()
            if peaks is not None:
                self.manager._save_hires_peaks_to_cache(self.file_path, peaks)
                self.signals.finished.emit(self.file_path, peaks)
            else:
                self.signals.failed.emit(self.file_path)
        except Exception as e:
            logger.error(f"HiResWaveformRunnable: Error {self.file_path}: {e}")
            self.signals.failed.emit(self.file_path)
        finally:
            self.manager._hires_task_finished(self.file_path)

    def _extract_minmax_peaks(self) -> list:
        """Extrae pares (min_normalizado, max_normalizado) de alta resolución."""
        if not check_ffmpeg():
            return []

        info = get_platform_info()
        ffmpeg_exe = os.path.join(get_ffmpeg_dir(), info["binary_name"])

        # Alta resolución: 22050 Hz mono para capturar detalle real
        sample_rate = 22050
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
        
        # Encontrar el pico absoluto global para normalizar
        global_max = 1
        for s in samples:
            a = abs(s)
            if a > global_max:
                global_max = a
        
        # Dividir en bloques y extraer min/max real (con signo) por bloque
        minmax_peaks = []
        block_size = max(1, num_samples / self.num_peaks)
        for i in range(self.num_peaks):
            start_idx = int(i * block_size)
            end_idx = max(start_idx + 1, int((i + 1) * block_size))
            block = samples[start_idx:end_idx]
            if block:
                block_min = min(block) / global_max  # Negativo (abajo)
                block_max = max(block) / global_max  # Positivo (arriba)
                minmax_peaks.append((block_min, block_max))
            else:
                minmax_peaks.append((0.0, 0.0))

        return minmax_peaks

class WaveformCacheManager(QObject):
    waveform_loaded = Signal(str, list)  # (file_path, peaks) - low res for icons
    hires_waveform_loaded = Signal(str, list)  # (file_path, minmax_peaks) - high res

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

    def _get_hash_key(self, file_path: str) -> str:
        if file_path in self._hash_cache:
            return self._hash_cache[file_path]
        try:
            stat = os.stat(file_path)
            raw = f"{os.path.abspath(file_path)}_{stat.st_mtime}_{stat.st_size}_wf_v1"
        except Exception:
            raw = f"{os.path.abspath(file_path)}_wf_v1"
        hash_val = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        self._hash_cache[file_path] = hash_val
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

    def get_cached_qicon(self, file_path: str) -> QIcon | None:
        if file_path in self._qicon_cache:
            return self._qicon_cache[file_path]
            
        peaks = self.get_cached_peaks(file_path)
        if peaks is not None:
            icon = render_waveform_icon(peaks)
            self._qicon_cache[file_path] = icon
            return icon
        return None

    def request_waveform(self, file_path: str, num_peaks: int = 80):
        if file_path in self._qicon_cache or file_path in self._peaks_cache:
            return
        if file_path in self._pending_files or file_path in self._failed_files:
            return
            
        cached_peaks = self.get_cached_peaks(file_path)
        if cached_peaks is not None:
            icon = render_waveform_icon(cached_peaks)
            self._qicon_cache[file_path] = icon
            self.waveform_loaded.emit(file_path, cached_peaks)
            return
            
        self._pending_files.add(file_path)
        worker = WaveformRunnable(file_path, self, num_peaks)
        worker.signals.finished.connect(self._on_worker_finished)
        worker.signals.failed.connect(self._on_worker_failed)
        self.thread_pool.start(worker)

    def _save_peaks_to_cache(self, file_path: str, peaks: list):
        hash_key = self._get_hash_key(file_path)
        json_path = os.path.join(CACHE_DIR, f"{hash_key}.json")
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(peaks, f)
        except Exception as e:
            logger.error(f"WaveformCacheManager: Error guardando json {json_path}: {e}")

    def _save_hires_peaks_to_cache(self, file_path: str, peaks: list):
        hash_key = self._get_hash_key(file_path)
        json_path = os.path.join(CACHE_DIR, f"{hash_key}_hires.json")
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(peaks, f)
        except Exception as e:
            logger.error(f"WaveformCacheManager: Error guardando hires json {json_path}: {e}")

    def get_cached_hires_peaks(self, file_path: str) -> list | None:
        cache_key = file_path + "_hires"
        if cache_key in self._peaks_cache:
            return self._peaks_cache[cache_key]
        hash_key = self._get_hash_key(file_path)
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

    def request_hires_waveform(self, file_path: str, num_peaks: int = 4000):
        cache_key = file_path + "_hires"
        if cache_key in self._peaks_cache:
            return
        if cache_key in self._pending_files:
            return
        cached = self.get_cached_hires_peaks(file_path)
        if cached is not None:
            self.hires_waveform_loaded.emit(file_path, cached)
            return
        self._pending_files.add(cache_key)
        worker = HiResWaveformRunnable(file_path, self, num_peaks)
        worker.signals.finished.connect(self._on_hires_worker_finished)
        worker.signals.failed.connect(self._on_hires_worker_failed)
        self.thread_pool.start(worker)

    def _on_hires_worker_finished(self, file_path: str, peaks: list):
        cache_key = file_path + "_hires"
        self._peaks_cache[cache_key] = peaks
        self.hires_waveform_loaded.emit(file_path, peaks)

    def _on_hires_worker_failed(self, file_path: str):
        cache_key = file_path + "_hires"
        self._failed_files.add(cache_key)

    def _hires_task_finished(self, file_path: str):
        cache_key = file_path + "_hires"
        self._pending_files.discard(cache_key)

    def _on_worker_finished(self, file_path: str, peaks: list):
        self._peaks_cache[file_path] = peaks
        icon = render_waveform_icon(peaks)
        self._qicon_cache[file_path] = icon
        self.waveform_loaded.emit(file_path, peaks)

    def _on_worker_failed(self, file_path: str):
        self._failed_files.add(file_path)

    def _task_finished(self, file_path: str):
        self._pending_files.discard(file_path)
        
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
