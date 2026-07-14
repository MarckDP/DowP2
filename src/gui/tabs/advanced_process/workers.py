# src/gui/tabs/single_process/workers.py
from PySide6.QtCore import QThread, Signal
from core.tabs.advanced_process.video_details_logic import analyze_media_for_queue
from core.ytdlp_logic.downloader_master import DownloaderMaster
import time

class AnalysisWorker(QThread):
    """Worker thread for running yt-dlp analysis in background."""
    finished = Signal(dict, str)
    progress = Signal(int, int)

    def __init__(self, url, analyze_playlist=True, fast_mode=True):
        super().__init__()
        self.url = url
        self.analyze_playlist = analyze_playlist
        self.fast_mode = fast_mode

    def run(self):
        def on_progress(current, total):
            self.progress.emit(current, total)

        data, error = analyze_media_for_queue(
            self.url,
            analyze_playlist=self.analyze_playlist,
            fast_mode=self.fast_mode,
            progress_callback=on_progress
        )
        self.finished.emit(data if data else {}, error if error else "")

class DownloadWorker(QThread):
    """Hilo encargado de la descarga y reporte de progreso."""
    finished = Signal(bool, str)
    progress = Signal(dict)

    def __init__(self, request_data, cancellation_event=None):
        super().__init__()
        self.request_data = request_data
        self.cancellation_event = cancellation_event
        self.master = DownloaderMaster()
        self._last_emit_time = 0

    def run(self):
        success, message = self.master.download(
            self.request_data, 
            self._on_progress, 
            self.cancellation_event
        )
        self.finished.emit(success, message)

    def _on_progress(self, d):
        # Limitamos la emisión de señales para no saturar el hilo principal
        current_time = time.time()
        # Emitimos si han pasado > 100ms o si es el mensaje final
        if current_time - self._last_emit_time < 0.1 and d.get('status') != 'finished':
            return
            
        self._last_emit_time = current_time
        self.progress.emit(d)
