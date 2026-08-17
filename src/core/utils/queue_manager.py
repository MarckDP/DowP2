# src/core/utils/queue_manager.py
import os
import re
import threading
import time
from uuid import uuid4
from PySide6.QtCore import QObject, Signal, QThread, QMutex, QRecursiveMutex, QMutexLocker
from core.logger.logger_manager import logger

class JobStatus:
    PENDING = "PENDING"
    ANALYZING = "ANALYZING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"
    NO_AUDIO = "NO_AUDIO"

class Job:
    """
    Representa una tarea de descarga o procesamiento en la cola.
    """
    def __init__(self, config: dict, job_type: str = "DOWNLOAD"):
        self.job_id = str(uuid4())
        self.job_type = job_type
        self.config = config  # Contiene url, output_path, speed_limit, etc. (Opciones iniciales por defecto)
        self.video_data = None    # Datos en crudo de la extracción de yt-dlp (formatos disponibles, miniatura, etc.)
        self.request_data = None  # Opciones específicas seleccionadas por el usuario para esta descarga
        self.analysis_data = None
        self.status = JobStatus.PENDING
        self.progress = 0.0
        self.speed = ""
        self.eta = ""
        self.title = config.get("title", "Tarea de descarga")
        self.error_message = ""
        self.final_filepath = None
        self.created_at = time.time()

class SingleJobWorker(QThread):
    """Hilo individual de descarga para un trabajo en la cola."""
    finished_job = Signal(str, str) # job_id, status

    def __init__(self, job, queue_worker):
        super().__init__()
        self.job = job
        self.queue_worker = queue_worker
        self.cancellation_event = threading.Event()
        self.downloader = None

    def cancel(self):
        self.cancellation_event.set()
        if self.downloader:
            self.downloader.cancel_download()

    def run(self):
        try:
            if self.job.job_type == "DOWNLOAD":
                self.queue_worker._execute_download(self.job, self.cancellation_event, self)
            elif self.job.job_type == "PLAYLIST":
                self.queue_worker._execute_playlist(self.job, self.cancellation_event, self)
            elif self.job.job_type == "RECODE":
                self.queue_worker._execute_recode(self.job, self.cancellation_event, self)
        except Exception as e:
            import traceback
            logger.error(f"SingleJobWorker: Error inesperado en job {self.job.job_id}: {traceback.format_exc()}")
            self.job.status = JobStatus.FAILED
            self.job.error_message = str(e)
            self.queue_worker.job_status_changed.emit(self.job.job_id, JobStatus.FAILED)
        finally:
            self.finished_job.emit(self.job.job_id, self.job.status)


class QueueWorker(QThread):
    """
    Hilo despachador de la cola encargado de gestionar trabajos concurrentes.
    """
    job_status_changed = Signal(str, str)             # job_id, status
    job_progress_changed = Signal(str, float, str, str) # job_id, progress%, speed, eta
    finished_all = Signal()

    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self._is_running = True
        self._cancellation_event = threading.Event()
        self._active_workers = {}
        self._workers_mutex = QRecursiveMutex()

    def stop(self):
        """Detiene el despachador y sus hilos de descarga activos."""
        self._is_running = False
        self._cancellation_event.set()
        with QMutexLocker(self._workers_mutex):
            for worker in list(self._active_workers.values()):
                worker.cancel()
        self.wait(1000)

    def run(self):
        logger.info("QueueWorker: Hilo despachador de cola iniciado.")
        from core.utils.config_manager import get_config
        while self._is_running:
            if self.manager.is_paused():
                time.sleep(0.3)
                continue

            max_concurrent = get_config().get("max_concurrent_downloads", 3)
            
            with QMutexLocker(self._workers_mutex):
                active_count = len(self._active_workers)
                active_recodes = sum(1 for w in self._active_workers.values() if w.job.job_type == "RECODE")

            if active_count < max_concurrent:
                job = self.manager._get_next_runnable_job(active_recodes)
                if job:
                    job.status = JobStatus.RUNNING
                    self.job_status_changed.emit(job.job_id, JobStatus.RUNNING)
                    
                    worker = SingleJobWorker(job, self)
                    worker.finished_job.connect(self._on_single_job_finished)
                    with QMutexLocker(self._workers_mutex):
                        self._active_workers[job.job_id] = worker
                    worker.start()
                    continue
                else:
                    with QMutexLocker(self._workers_mutex):
                        if len(self._active_workers) == 0:
                            self.manager.pause_queue()
                            self.finished_all.emit()
            time.sleep(0.3)

    def _on_single_job_finished(self, job_id, status):
        with QMutexLocker(self._workers_mutex):
            if job_id in self._active_workers:
                worker = self._active_workers.pop(job_id)
                worker.deleteLater()

    def cancel_current_job(self):
        with QMutexLocker(self._workers_mutex):
            for worker in list(self._active_workers.values()):
                worker.cancel()

    def _download_best_thumb(self, entry, output_dir, title, force_png=False):
        """
        Descarga la mejor miniatura disponible (Forzando MaxRes) y la guarda sin usar PIL.
        """
        try:
            # 1. Buscar la URL base
            thumb_url = None
            thumbs = entry.get('thumbnails')
            
            if thumbs:
                sorted_thumbs = sorted(thumbs, key=lambda x: x.get('width', 0) or 0, reverse=True)
                thumb_url = sorted_thumbs[0].get('url')
            
            if not thumb_url:
                thumb_url = entry.get('thumbnail')
            
            if not thumb_url:
                return None

            # 2. INTENTO INTELIGENTE: Forzar MaxResDefault
            final_url = thumb_url
            if "i.ytimg.com" in thumb_url:
                max_res_url = re.sub(r'/(hq|mq|sd|default)default', '/maxresdefault', thumb_url)
                
                try:
                    import requests
                    check_resp = requests.get(max_res_url, timeout=5, stream=True)
                    if check_resp.status_code == 200:
                        final_url = max_res_url
                        check_resp.close()
                except:
                    pass

            # 3. Descargar datos reales
            import requests
            response = requests.get(final_url, timeout=30)
            response.raise_for_status()
            image_data = response.content
            
            # 4. Procesar y guardar sin usar PIL
            content_type = response.headers.get("Content-Type", "").lower()
            if "png" in content_type or image_data.startswith(b'\x89PNG\r\n\x1a\n'):
                smart_ext = ".png"
            elif "webp" in content_type or (image_data.startswith(b'RIFF') and image_data[8:12] == b'WEBP'):
                smart_ext = ".webp"
            elif "gif" in content_type or image_data.startswith(b'GIF8'):
                smart_ext = ".gif"
            else:
                smart_ext = ".jpg"
            
            sanitized_title = self._sanitize_filename(title)
            output_path = os.path.join(output_dir, f"{sanitized_title}{smart_ext}")
            
            with open(output_path, "wb") as f:
                f.write(image_data)
                
            logger.info(f"QueueWorker: Miniatura guardada ({'MAXRES' if final_url != thumb_url else 'ORIG'}): {output_path}")
            return output_path
            
        except Exception as e:
            logger.warning(f"QueueWorker: Falló descarga de miniatura para '{title}': {e}")
            return None

    def _execute_download(self, job, cancellation_event=None, worker_ref=None):
        """Ejecuta una descarga usando DownloaderMaster de forma sincrónica dentro de este hilo."""
        if cancellation_event is None:
            cancellation_event = self._cancellation_event

        job.status = JobStatus.RUNNING
        self.job_status_changed.emit(job.job_id, JobStatus.RUNNING)

        from core.ytdlp_logic.downloader_master import DownloaderMaster
        downloader = DownloaderMaster()
        if worker_ref:
            worker_ref.downloader = downloader

        # Generar un progress callback que emita la señal Qt de progreso
        def progress_callback(d):
            if d.get("status") == "downloading":
                from core.ytdlp_logic.analyzer import strip_ansi_codes
                p_str = strip_ansi_codes(d.get('_percent_str', '0%')).replace('%','').strip()
                try:
                    val = float(p_str)
                    speed = strip_ansi_codes(d.get('_speed_str', '')).strip() or '...'
                    eta = strip_ansi_codes(d.get('_eta_str', '')).strip() or '...'
                    job.progress = val
                    job.speed = speed
                    job.eta = eta
                    self.job_progress_changed.emit(job.job_id, val, speed, eta)
                except Exception:
                    pass
            elif d.get("status") == "finished":
                job.progress = 100.0
                if d.get("filename"):
                    job.final_filepath = d.get("filename")
                self.job_progress_changed.emit(job.job_id, 100.0, "", "Procesando final...")

        # Iniciar la descarga
        config_to_use = job.request_data if job.request_data else job.config
        
        # Sobreescribir opciones según el modo de miniatura en lote
        from core.utils.config_manager import get_config
        batch_thumb_mode = get_config().get("batch_thumbnail_mode", "manual")
        
        # Modo especial: solo descargar miniatura
        if batch_thumb_mode == "thumbnail_only":
            self.job_progress_changed.emit(job.job_id, 10.0, "Descargando miniatura...", "...")
            output_dir = config_to_use.get("output_path") or self._default_output_path()
            title = config_to_use.get("title") or job.title or "thumbnail"
            
            data_source = job.video_data if job.video_data else job.analysis_data
            if not data_source:
                try:
                    from core.ytdlp_logic.analyzer import get_video_info
                    data_source = get_video_info(config_to_use.get("url"), extra_opts={'noplaylist': True})
                except Exception as e:
                    logger.error(f"QueueWorker: Error analizando para miniatura sola: {e}")
            
            if data_source:
                thumb_path = self._download_best_thumb(data_source, output_dir, title)
                if thumb_path:
                    job.status = JobStatus.COMPLETED
                    job.progress = 100.0
                    job.final_filepath = thumb_path
                    self.job_status_changed.emit(job.job_id, JobStatus.COMPLETED)
                    return
            
            job.status = JobStatus.FAILED
            job.error_message = "No se pudo obtener la miniatura para este video."
            self.job_status_changed.emit(job.job_id, JobStatus.FAILED)
            return

        # Para otros modos (manual o con video/audio)
        should_download_thumb_file = False
        if batch_thumb_mode == "with_media":
            should_download_thumb_file = True
        elif batch_thumb_mode == "manual":
            should_download_thumb_file = config_to_use.get("download_thumbnail_file", False)
            
        # Nos aseguramos de que yt-dlp NO intente descargar el archivo físico por su cuenta
        # (pero permitimos embed_thumbnail para incrustación)
        config_to_use = config_to_use.copy()
        config_to_use["download_thumbnail_file"] = False

        # GUARDIA DE MEMORIA: Proteger miniatura existente para evitar que yt-dlp la borre (al incrustar)
        output_dir_guard = config_to_use.get("output_path") or self._default_output_path()
        title_guard = config_to_use.get("title") or job.title or "download"
        sanitized_title_guard = self._sanitize_filename(title_guard)
        
        guarded_thumbnails = {}
        for ext in ['.jpg', '.jpeg', '.png', '.webp']:
            thumb_path_guard = os.path.join(output_dir_guard, f"{sanitized_title_guard}{ext}")
            if os.path.exists(thumb_path_guard):
                try:
                    with open(thumb_path_guard, "rb") as f:
                        guarded_thumbnails[thumb_path_guard] = f.read()
                except Exception:
                    pass

        success, message = downloader.download(
            config_to_use,
            progress_callback=progress_callback,
            cancellation_event=cancellation_event
        )

        # RESTAURAR GUARDIA DE MEMORIA
        for thumb_path_guard, thumb_data in guarded_thumbnails.items():
            if not os.path.exists(thumb_path_guard):
                try:
                    with open(thumb_path_guard, "wb") as f:
                        f.write(thumb_data)
                    logger.info(f"QueueWorker: Miniatura restaurada desde memoria: {thumb_path_guard}")
                except Exception as e:
                    logger.warning(f"QueueWorker: Fallo al restaurar miniatura: {e}")

        if success:
            job.status = JobStatus.COMPLETED
            job.progress = 100.0
            
            if should_download_thumb_file:
                try:
                    output_dir = config_to_use.get("output_path") or self._default_output_path()
                    title = config_to_use.get("title") or job.title or "download"
                    data_source = job.video_data if job.video_data else job.analysis_data
                    if data_source:
                        self._download_best_thumb(data_source, output_dir, title, force_png=True)
                except Exception as e:
                    logger.warning(f"QueueWorker: Falló la descarga de miniatura: {e}")
                    
            self.job_status_changed.emit(job.job_id, JobStatus.COMPLETED)
        else:
            if self._cancellation_event.is_set():
                job.status = JobStatus.CANCELLED
                self.job_status_changed.emit(job.job_id, JobStatus.CANCELLED)
            else:
                job.status = JobStatus.FAILED
                from core.ytdlp_logic.analyzer import strip_ansi_codes
                job.error_message = strip_ansi_codes(message) if message else message
                self.job_status_changed.emit(job.job_id, JobStatus.FAILED)

    def _execute_playlist(self, job, cancellation_event=None, worker_ref=None):
        if cancellation_event is None:
            cancellation_event = self._cancellation_event

        job.status = JobStatus.RUNNING
        job.progress = 0.0
        self.job_status_changed.emit(job.job_id, JobStatus.RUNNING)

        entries = job.analysis_data.get("entries", []) if job.analysis_data else []
        selected_indices = job.config.get("selected_indices", [])
        selected_entries = [
            (idx, entries[idx]) for idx in selected_indices
            if isinstance(idx, int) and 0 <= idx < len(entries) and entries[idx]
        ]
        if not selected_entries:
            job.status = JobStatus.FAILED
            job.error_message = "La playlist no tiene medios seleccionados."
            self.job_status_changed.emit(job.job_id, JobStatus.FAILED)
            return

        from core.ytdlp_logic.downloader_master import DownloaderMaster
        master = DownloaderMaster()
        if worker_ref:
            worker_ref.downloader = master

        playlist_title = self._sanitize_filename(job.config.get("title") or "Playlist")
        base_output = job.config.get("output_path") or self._default_output_path()
        playlist_output = os.path.join(base_output, playlist_title)
        os.makedirs(playlist_output, exist_ok=True)

        total = len(selected_entries)
        mode = job.config.get("playlist_mode", "video+audio")
        quality = job.config.get("playlist_quality", "best_compatible")

        from core.utils.config_manager import get_config
        batch_thumb_mode = get_config().get("batch_thumbnail_mode", "manual")

        for pos, (entry_index, entry) in enumerate(selected_entries, start=1):
            if self._cancellation_event.is_set():
                job.status = JobStatus.CANCELLED
                self.job_status_changed.emit(job.job_id, JobStatus.CANCELLED)
                return

            item_title = self._sanitize_filename(
                entry.get("title") or entry.get("id") or entry.get("url") or f"Item {pos:03d}"
            )
            item_url = self._entry_url(entry)
            if not item_url:
                logger.warning(f"QueueWorker: Item de playlist sin URL: {item_title}")
                continue

            prefix = f"{pos:03d} - "
            
            # Si el modo de lote es "Solo miniaturas"
            if batch_thumb_mode == "thumbnail_only":
                total_percent = pos / total * 100.0
                job.progress = total_percent
                self.job_progress_changed.emit(
                    job.job_id, total_percent, f"[{pos}/{total}] Descargando miniatura", ""
                )
                try:
                    self._download_best_thumb(entry, playlist_output, f"{prefix}{item_title}")
                except Exception as e:
                    logger.warning(f"QueueWorker: Falló miniatura de playlist {item_title}: {e}")
                continue

            # Para otros modos (manual o con video/audio)
            should_download_thumb_file = False
            if batch_thumb_mode == "with_media":
                should_download_thumb_file = True
            elif batch_thumb_mode == "manual":
                should_download_thumb_file = job.config.get("download_thumbnail_file", False)

            child_data = {
                "url": item_url,
                "title": f"{prefix}{item_title}",
                "mode": mode,
                "output_path": playlist_output,
                "format_selector": self._playlist_format_selector(mode, quality),
                "speed_limit": job.config.get("speed_limit"),
                "embed_metadata": job.config.get("embed_metadata", True),
                "embed_thumbnail": job.config.get("embed_thumbnail", True),
                "remove_sponsors": job.config.get("remove_sponsors", False),
                "is_playlist": True,
                "force_audio_extract": (mode == "audio_only"),
                "audio_ext": "mp3" if mode == "audio_only" and quality in ["320", "192", "128"] else None,
                "video_ext": "mp4" if mode != "audio_only" else None,
                "download_thumbnail_file": False # Hacemos la descarga directa nosotros
            }

            def progress_callback(d, item_pos=pos, item_name=item_title):
                if d.get("status") == "downloading":
                    from core.ytdlp_logic.analyzer import strip_ansi_codes
                    p_str = strip_ansi_codes(d.get('_percent_str', '0%')).replace('%', '').strip()
                    try:
                        item_percent = float(p_str)
                    except Exception:
                        item_percent = 0.0
                    total_percent = ((item_pos - 1) + (item_percent / 100.0)) / total * 100.0
                    job.progress = total_percent
                    job.speed = f"[{item_pos}/{total}] {item_name[:32]}"
                    job.eta = strip_ansi_codes(d.get('_eta_str', '')).strip() or "..."
                    self.job_progress_changed.emit(job.job_id, total_percent, job.speed, job.eta)
                elif d.get("status") == "finished":
                    total_percent = item_pos / total * 100.0
                    job.progress = total_percent
                    self.job_progress_changed.emit(job.job_id, total_percent, f"[{item_pos}/{total}] Procesando", "")

            success, message = master.download(
                child_data,
                progress_callback=progress_callback,
                cancellation_event=cancellation_event
            )
            
            if success:
                if should_download_thumb_file:
                    try:
                        self._download_best_thumb(entry, playlist_output, f"{prefix}{item_title}", force_png=True)
                    except Exception as e:
                        logger.warning(f"QueueWorker: Falló miniatura de playlist {item_title}: {e}")
            else:
                if self._cancellation_event.is_set():
                    job.status = JobStatus.CANCELLED
                    self.job_status_changed.emit(job.job_id, JobStatus.CANCELLED)
                else:
                    job.status = JobStatus.FAILED
                    from core.ytdlp_logic.analyzer import strip_ansi_codes
                    job.error_message = strip_ansi_codes(message) if message else message
                    self.job_status_changed.emit(job.job_id, JobStatus.FAILED)
                return

        job.status = JobStatus.COMPLETED
        job.progress = 100.0
        job.final_filepath = playlist_output
        self.job_status_changed.emit(job.job_id, JobStatus.COMPLETED)

    @staticmethod
    def _sanitize_filename(filename):
        cleaned = re.sub(r'[<>:"/\\|?*#]', '', str(filename or "")).strip()
        return cleaned or "Playlist"

    @staticmethod
    def _entry_url(entry):
        url = entry.get("webpage_url") or entry.get("url") or entry.get("id")
        if not url:
            return None
        url = str(url)
        if url.startswith(("http://", "https://")):
            return url
        ie_key = (entry.get("ie_key") or entry.get("extractor_key") or "").lower()
        if "youtube" in ie_key:
            return f"https://www.youtube.com/watch?v={entry.get('id') or url}"
        return url

    @staticmethod
    def _playlist_format_selector(mode, quality):
        from core.ytdlp_logic.format_selectors import playlist_format_selector
        return playlist_format_selector(mode, quality)

    def _execute_recode(self, job, cancellation_event=None, worker_ref=None):
        import subprocess
        from core.setup.ffmpeg_setup import get_ffmpeg_dir
        
        if cancellation_event is None:
            cancellation_event = self._cancellation_event

        job.status = JobStatus.RUNNING
        job.progress = 0.0
        self.job_status_changed.emit(job.job_id, JobStatus.RUNNING)
        self.job_progress_changed.emit(job.job_id, 0.0, "Iniciando FFmpeg...", "")

        config = job.config
        input_file = config.get("input_path")
        output_file = config.get("output_path")
        settings = config.get("settings", {})
        duration_sec = config.get("duration_sec", 0.0)
        
        ffmpeg_exe = os.path.join(get_ffmpeg_dir(), "ffmpeg.exe" if os.name == 'nt' else "ffmpeg")
        if not os.path.exists(ffmpeg_exe):
            job.status = JobStatus.FAILED
            job.error_message = "No se encontró ffmpeg."
            self.job_status_changed.emit(job.job_id, JobStatus.FAILED)
            return

        # Construir comando FFmpeg
        cmd = [ffmpeg_exe, "-y"]
        trim_in = settings.get("trim_in_sec")
        trim_out = settings.get("trim_out_sec")
        if trim_in is not None and trim_in > 0:
            cmd.extend(["-ss", f"{trim_in:.3f}"])
        if trim_out is not None and trim_out > 0:
            cmd.extend(["-to", f"{trim_out:.3f}"])
        cmd.extend(["-i", input_file])

        stream_mode = settings.get("stream_mode", "video+audio")

        # Selección explícita de pistas de audio a conservar (ver advanced_recode_panel.py):
        # None = comportamiento de siempre, ffmpeg elige automáticamente 1 pista (la
        #        mayoría de los archivos fuente solo tienen una, así que este sigue siendo
        #        el camino más común, sin cambios de comportamiento).
        # "all" = todas las pistas de audio del archivo fuente.
        # int   = índice RELATIVO de audio (0 = primera pista, 1 = segunda, etc.).
        # OJO: agregar CUALQUIER -map desactiva la auto-selección de ffmpeg para TODOS
        # los tipos de stream a la vez, no solo audio — por eso, apenas se activa esto,
        # hay que mapear el video a mano también (si corresponde) para no perderlo.
        audio_track_selection = settings.get("audio_track_selection")
        explicit_mapping = audio_track_selection is not None

        # Opciones de Video
        if stream_mode == "audio_only":
            cmd.append("-vn")
        else:
            if explicit_mapping:
                cmd.extend(["-map", "0:v:0?"])
            video_mode = settings.get("video_mode", "recode")
            if video_mode == "copy":
                cmd.extend(["-c:v", "copy"])
            else:
                v_args = settings.get("video_args", [])
                if v_args:
                    cmd.extend(v_args)
                else:
                    cmd.extend(["-c:v", "libx264", "-crf", "23"])

        # Opciones de Audio
        if stream_mode == "video_only":
            cmd.append("-an")
        else:
            if audio_track_selection == "all":
                cmd.extend(["-map", "0:a"])
            elif isinstance(audio_track_selection, int):
                cmd.extend(["-map", f"0:a:{audio_track_selection}"])

            audio_mode = settings.get("audio_mode", "recode")
            if audio_mode == "copy":
                cmd.extend(["-c:a", "copy"])
            else:
                a_args = settings.get("audio_args", [])
                if a_args:
                    cmd.extend(a_args)
                else:
                    cmd.extend(["-c:a", "aac", "-b:a", "192k"])

        cmd.append(output_file)
        
        logger.info(f"QueueWorker: Iniciando RECODE con comando: {' '.join(cmd)}")
        
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                startupinfo=startupinfo,
                encoding="utf-8",
                errors="replace"
            )
            
            # Guardamos la referencia para poder cancelarlo
            if worker_ref:
                worker_ref.downloader = proc # Usamos downloader para guardar el Popen, sobrecargando su uso temporalmente
                # Override cancel
                def _cancel_proc():
                    proc.terminate()
                worker_ref.cancel = _cancel_proc

            time_regex = re.compile(r"time=\s*(\d+):(\d+):(\d+\.\d+|\d+)")
            speed_regex = re.compile(r"speed=\s*([\d\.]+)x")
            
            for line in proc.stderr:
                if cancellation_event.is_set():
                    proc.terminate()
                    break
                    
                time_match = time_regex.search(line)
                speed_match = speed_regex.search(line)
                
                if time_match and duration_sec > 0:
                    h, m, s = float(time_match.group(1)), float(time_match.group(2)), float(time_match.group(3))
                    current_sec = h * 3600 + m * 60 + s
                    percent = min((current_sec / duration_sec) * 100.0, 100.0)
                    
                    speed_str = f"{speed_match.group(1)}x" if speed_match else "..."
                    
                    eta_str = "..."
                    if speed_match:
                        sp = float(speed_match.group(1))
                        if sp > 0:
                            rem = (duration_sec - current_sec) / sp
                            eta_str = f"{int(rem)}s"
                    
                    job.progress = percent
                    job.speed = speed_str
                    job.eta = eta_str
                    self.job_progress_changed.emit(job.job_id, percent, f"Velocidad: {speed_str}", f"ETA: {eta_str}")

            proc.wait()
            
            if cancellation_event.is_set():
                job.status = JobStatus.CANCELLED
                self.job_status_changed.emit(job.job_id, JobStatus.CANCELLED)
                if os.path.exists(output_file):
                    try:
                        os.remove(output_file)
                    except Exception:
                        pass
                return
                
            if proc.returncode == 0:
                job.status = JobStatus.COMPLETED
                job.progress = 100.0
                job.final_filepath = output_file
                self.job_progress_changed.emit(job.job_id, 100.0, "Completado", "")
                self.job_status_changed.emit(job.job_id, JobStatus.COMPLETED)
            else:
                job.status = JobStatus.FAILED
                job.error_message = f"FFmpeg terminó con código {proc.returncode}"
                self.job_status_changed.emit(job.job_id, JobStatus.FAILED)
                
        except Exception as e:
            logger.error(f"QueueWorker: Error en RECODE: {e}")
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            self.job_status_changed.emit(job.job_id, JobStatus.FAILED)

    @staticmethod
    def _default_output_path():
        try:
            from core.utils.config_manager import get_config
            return get_config().get("last_output_path") or os.getcwd()
        except Exception:
            return os.getcwd()

    def cancel_current_job(self):
        """Activa la bandera de cancelación para detener yt-dlp."""
        self._cancellation_event.set()

    def stop(self):
        """Detiene el bucle principal del hilo de trabajo."""
        self._is_running = False
        self.cancel_current_job()
        self.quit()
        self.wait()


class QueueManager(QObject):
    """
    Gestor de la cola de trabajos. Centraliza la lista de trabajos y sincroniza
    los estados con la UI de forma thread-safe utilizando señales de Qt.
    """
    job_added = Signal(str)                          # job_id
    job_removed = Signal(str)                        # job_id
    job_status_changed = Signal(str, str)            # job_id, status
    job_progress_changed = Signal(str, float, str, str) # job_id, percent, speed, eta
    queue_reordered = Signal()                       # Emitido cuando la cola cambia de orden
    queue_finished = Signal()

    def __init__(self):
        super().__init__()
        self._jobs = []
        self._mutex = QRecursiveMutex()
        self._is_paused = True # Por defecto nace pausado hasta que el usuario inicie la cola

        # Inicializar y arrancar el hilo de trabajo
        self._worker = QueueWorker(self)
        self._worker.job_status_changed.connect(self._on_worker_status_changed)
        self._worker.job_progress_changed.connect(self._on_worker_progress_changed)
        self._worker.finished_all.connect(self.queue_finished)
        self._worker.start()

    def __del__(self):
        self.stop_worker()

    def stop_worker(self):
        """Detiene el hilo secundario de la cola limpiamente."""
        with QMutexLocker(self._mutex):
            if hasattr(self, '_worker') and self._worker and self._worker.isRunning():
                self._worker.stop()

    def is_paused(self) -> bool:
        with QMutexLocker(self._mutex):
            return self._is_paused

    def start_queue(self):
        """Inicia o reanuda el procesamiento de la cola."""
        with QMutexLocker(self._mutex):
            self._is_paused = False
        logger.info("QueueManager: Cola iniciada/reanudada.")

    def pause_queue(self):
        """Pausa el procesamiento de la cola (las descargas activas continúan, pero no empezará ninguna nueva)."""
        with QMutexLocker(self._mutex):
            self._is_paused = True
        logger.info("QueueManager: Cola pausada.")

    def add_job(self, config: dict, job_type: str = "DOWNLOAD") -> str:
        """Añade un nuevo trabajo a la cola."""
        job = Job(config, job_type)
        with QMutexLocker(self._mutex):
            self._jobs.append(job)
        logger.info(f"QueueManager: Trabajo añadido ({job.job_id}): {job.title}")
        self.job_added.emit(job.job_id)
        return job.job_id

    def remove_job(self, job_id: str):
        """Remueve un trabajo de la cola. Si está activo, lo cancela primero."""
        self.cancel_job(job_id)
        with QMutexLocker(self._mutex):
            self._jobs = [j for j in self._jobs if j.job_id != job_id]
        logger.info(f"QueueManager: Trabajo eliminado ({job_id})")
        self.job_removed.emit(job_id)

    def cancel_job(self, job_id: str):
        """Cancela un trabajo específico si está corriendo o pendiente."""
        with QMutexLocker(self._mutex):
            job = next((j for j in self._jobs if j.job_id == job_id), None)
            if not job:
                return

            if job.status == JobStatus.RUNNING:
                self._worker.cancel_current_job()
            elif job.status == JobStatus.PENDING:
                job.status = JobStatus.CANCELLED
                self.job_status_changed.emit(job_id, JobStatus.CANCELLED)

    def clear_queue(self):
        """Limpia todos los trabajos. Cancela el actual si está corriendo."""
        self.pause_queue()
        jobs_to_remove = []
        with QMutexLocker(self._mutex):
            jobs_to_remove = list(self._jobs)
            running_job = next((j for j in self._jobs if j.status == JobStatus.RUNNING), None)
            if running_job:
                self._worker.cancel_current_job()
            self._jobs = []
        logger.info("QueueManager: Cola vaciada.")
        for j in jobs_to_remove:
            self.job_removed.emit(j.job_id)
        self.queue_reordered.emit()

    def clear_inactive_jobs(self):
        """Limpia absolutamente todos los trabajos de la cola, cancelando el actual si está corriendo o analizando."""
        self.pause_queue()
        jobs_to_remove = []
        with QMutexLocker(self._mutex):
            all_statuses = [f"{j.title} ({j.job_id}): {j.status}" for j in self._jobs]
            logger.info(f"QueueManager: clear_inactive_jobs llamada. Trabajos actuales en cola: {all_statuses}")
            
            jobs_to_remove = list(self._jobs)
            
            # Cancelar el trabajo activo si está corriendo
            running_job = next((j for j in self._jobs if j.status == JobStatus.RUNNING), None)
            if running_job:
                logger.info(f"QueueManager: Cancelando trabajo activo {running_job.job_id} al limpiar toda la lista.")
                self._worker.cancel_current_job()
                
            self._jobs = []
            
        logger.info(f"QueueManager: Eliminando {len(jobs_to_remove)} trabajos de la cola.")
        for j in jobs_to_remove:
            logger.info(f"QueueManager: Removiendo trabajo {j.job_id} ({j.title}) con estado {j.status}")
            self.job_removed.emit(j.job_id)
            
        logger.info("QueueManager: Todos los trabajos de la cola han sido limpiados.")
        self.queue_reordered.emit()

    def reset_job(self, job_id: str):
        """Restaura el estado de un trabajo terminal a PENDING."""
        terminal_statuses = (JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.FAILED, JobStatus.SKIPPED, JobStatus.NO_AUDIO)
        with QMutexLocker(self._mutex):
            job = next((j for j in self._jobs if j.job_id == job_id), None)
            if not job or job.status not in terminal_statuses:
                return
            
            job.status = JobStatus.PENDING
            job.error_message = None
            
        self.job_progress_changed.emit(job_id, 0.0, "", "")
        self.job_status_changed.emit(job_id, JobStatus.PENDING)
        logger.info(f"QueueManager: Trabajo {job_id} reseteado a PENDING.")

    def reset_all_terminal_jobs(self):
        """Restaura todos los trabajos terminados a PENDING."""
        self.pause_queue()
        inactive_statuses = (JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.FAILED, JobStatus.SKIPPED, JobStatus.NO_AUDIO)
        with QMutexLocker(self._mutex):
            jobs_to_reset = [j.job_id for j in self._jobs if j.status in inactive_statuses]
            
        for j_id in jobs_to_reset:
            self.reset_job(j_id)
            
        if jobs_to_reset:
            logger.info(f"QueueManager: {len(jobs_to_reset)} trabajos reseteados.")

    def update_job_data(self, job_id: str, video_data=None, request_data=None):
        """Actualiza los datos internos (video_data o request_data) de un trabajo sin alterar su estado visual."""
        with QMutexLocker(self._mutex):
            job = next((j for j in self._jobs if j.job_id == job_id), None)
            if not job:
                return
            if video_data is not None:
                job.video_data = video_data
            if request_data is not None:
                job.request_data = request_data

    def update_job_status(self, job_id: str, status: str):
        """Actualiza el estado de un trabajo y emite la señal correspondiente."""
        with QMutexLocker(self._mutex):
            job = next((j for j in self._jobs if j.job_id == job_id), None)
            if not job:
                return
            job.status = status
        self.job_status_changed.emit(job_id, status)

    def move_job_up(self, job_id: str):
        """Mueve un trabajo una posición arriba en la cola."""
        with QMutexLocker(self._mutex):
            idx = next((i for i, j in enumerate(self._jobs) if j.job_id == job_id), -1)
            if idx > 0:
                self._jobs[idx - 1], self._jobs[idx] = self._jobs[idx], self._jobs[idx - 1]
        self.queue_reordered.emit()

    def move_job_down(self, job_id: str):
        """Mueve un trabajo una posición abajo en la cola."""
        with QMutexLocker(self._mutex):
            idx = next((i for i, j in enumerate(self._jobs) if j.job_id == job_id), -1)
            if idx != -1 and idx < len(self._jobs) - 1:
                self._jobs[idx], self._jobs[idx + 1] = self._jobs[idx + 1], self._jobs[idx]
        self.queue_reordered.emit()

    def get_job(self, job_id: str) -> Job | None:
        """Retorna una copia de los datos de un trabajo (o la referencia de manera segura)."""
        with QMutexLocker(self._mutex):
            return next((j for j in self._jobs if j.job_id == job_id), None)

    def get_all_jobs(self) -> list:
        """Retorna una lista con todos los trabajos actuales."""
        with QMutexLocker(self._mutex):
            return list(self._jobs)

    def _get_next_runnable_job(self, active_recodes: int) -> Job | None:
        """Obtiene la siguiente tarea PENDING saltando los RECODE si ya hay uno corriendo."""
        with QMutexLocker(self._mutex):
            for j in self._jobs:
                if j.status == JobStatus.PENDING:
                    if j.job_type == "RECODE" and active_recodes > 0:
                        continue
                    return j
            return None

    def _on_worker_status_changed(self, job_id: str, status: str):
        self.job_status_changed.emit(job_id, status)

    def _on_worker_progress_changed(self, job_id: str, percent: float, speed: str, eta: str):
        self.job_progress_changed.emit(job_id, percent, speed, eta)

    def update_max_concurrent_downloads(self, value: int):
        logger.info(f"QueueManager: Límite de descargas simultáneas actualizado a: {value}")

    @classmethod
    def get_instance(cls):
        return get_queue_manager()

    def shutdown(self):
        """Apaga el hilo de forma segura al cerrar la app."""
        self._worker.stop()

# Instancia global compartida para todo el ciclo de vida de la aplicación
_global_queue_manager = None

def get_queue_manager() -> QueueManager:
    global _global_queue_manager
    if _global_queue_manager is None:
        _global_queue_manager = QueueManager()
    return _global_queue_manager
