# src/gui/tabs/advanced_process/download_controller.py
import os
import time
import threading
import platform
import subprocess
from PySide6.QtCore import QObject
from core.logger.logger_manager import logger
from core.utils.cleanup_manager import CleanupManager
from core.utils.config_manager import get_config
from gui.tabs.advanced_process.workers import DownloadWorker

class DownloadController(QObject):
    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab
        self.queue_mgr = tab.queue_mgr
        
        self.is_downloading = False
        self.solo_worker = None
        self.solo_request_data = None
        self.cancellation_event = threading.Event()
        self.paused_job_ids = set()
        self.last_downloaded_filepath = None
        self.last_progress_update = 0
        
        # Connect signals
        self.queue_mgr.job_progress_changed.connect(self._on_queue_job_progress)
        self.queue_mgr.job_status_changed.connect(self._on_queue_job_status)
        self.queue_mgr._worker.finished_all.connect(self._on_queue_finished_all)

    def on_download_button_clicked(self):
        """Maneja el clic en el botón de descarga, alternando entre iniciar/reanudar y pausar."""
        if self.tab.url_bar.solo_btn.isChecked():
            if self.is_downloading:
                self.pause_solo_download()
            else:
                self.start_solo_download()
        else:
            if self.is_downloading:
                self.pause_download()
            else:
                self.start_download()

    def start_download(self):
        """Inicia o reanuda la cola de trabajos."""
        self.tab._save_current_job_options()
        
        for job in self.queue_mgr.get_all_jobs():
            if job.status == "PENDING":
                if job.job_type == "PLAYLIST":
                    continue
                if not job.request_data and job.video_data:
                    job.request_data = self.tab._build_default_request_data(job.video_data, job.title)
                    
        self.queue_mgr.start_queue()
        
        self.tab.output_options.btn_start_download.setEnabled(True)
        self.tab.output_options.set_download_state("pause_queue", self.tab.tr("Pausar cola"))
        self.is_downloading = True
        self.tab.url_bar.solo_btn.setEnabled(False)
        self.update_queue_main_progress()

    def start_solo_download(self):
        """Inicia una descarga directa en modo SOLO sin usar el gestor de colas."""
        req_data = self.tab._collect_request_data()
        if not req_data:
            return

        self.cancellation_event.clear()
        self.solo_worker = DownloadWorker(req_data, self.cancellation_event)
        self.solo_request_data = req_data.copy()

        has_fragments = bool(req_data.get("selected_fragments"))

        self.is_downloading = True
        self.tab.url_bar.solo_btn.setEnabled(False)
        self.tab.output_options.set_download_state("cancelling", self.tab.tr("Cancelar"))
        self.tab.output_options.set_progress(0, self.tab.tr("Iniciando descarga..."), "running")
        if self.tab.taskbar_manager:
            self.tab.taskbar_manager.set_state("indeterminate")

        def on_solo_progress(d):
            from core.ytdlp_logic.analyzer import strip_ansi_codes

            if d.get("status") == "fragment_progress":
                idx = d.get("fragment_index")
                total = d.get("fragment_count")
                verb = self.tab.tr("Cortando") if d.get("phase") == "cutting" else self.tab.tr("Descargando")
                msg = f"{verb} {self.tab.tr('fragmento')} {idx} {self.tab.tr('de')} {total}"
                self.tab.output_options.set_progress(-1, msg, "running")
                if self.tab.taskbar_manager:
                    self.tab.taskbar_manager.set_state("indeterminate")
                return

            # Mientras el job tenga fragmentos, el progreso numérico crudo de
            # yt-dlp (downloading/finished) no representa el avance real del
            # job completo (se dispara una vez por fragmento) — se ignora acá
            # y la barra queda a cargo únicamente de fragment_progress.
            if has_fragments:
                return

            if d.get("status") == "downloading":
                p_str = strip_ansi_codes(d.get('_percent_str', '0%')).replace('%','').strip()
                try:
                    val = float(p_str)
                    speed = strip_ansi_codes(d.get('_speed_str', '')).strip() or '...'
                    eta = strip_ansi_codes(d.get('_eta_str', '')).strip() or '...'
                    msg = f"{int(val)}% — {speed} — ETA: {eta}"
                    self.tab.output_options.set_progress(int(val), msg, "downloading")
                    if self.tab.taskbar_manager:
                        self.tab.taskbar_manager.set_state("normal")
                        self.tab.taskbar_manager.set_value(int(val))
                except Exception:
                    pass
            elif d.get("status") == "finished":
                if d.get("filename"):
                    self.last_downloaded_filepath = d.get("filename")
                self.tab.output_options.set_progress(100, self.tab.tr("Procesando descarga..."), "downloading")

        def on_solo_finished(success, message):
            self.is_downloading = False
            self.tab.output_options.set_download_state("idle")
            self.tab.url_bar.solo_btn.setEnabled(True)
            if self.tab.taskbar_manager:
                self.tab.taskbar_manager.stop()
                
            if success:
                title = self.solo_request_data.get("title", "").strip()
                output_dir = self.solo_request_data.get("output_path", "")
                if title and output_dir:
                    keep_thumb = self.solo_request_data.get("download_thumbnail_file", False)
                    CleanupManager.cleanup_ytdlp_temp_files(output_dir, title, keep_thumbnail=keep_thumb)
                    CleanupManager.deferred_cleanup(output_dir, title, keep_thumbnail=keep_thumb)
                self.tab.output_options.set_progress(100, self.tab.tr("Descarga completada con éxito"), "done")
                logger.info("AdvancedProcessTab: Descarga directa SOLO finalizada con éxito.")
                from core.services.editor_integration_manager import EditorIntegrationManager
                editor_mgr = EditorIntegrationManager.get_instance()
                if editor_mgr and editor_mgr.is_auto_send_enabled:
                    actual_path = self._find_actual_downloaded_file(self.last_downloaded_filepath)
                    editor_mgr.process_raw_download(actual_path or self.last_downloaded_filepath, self.solo_request_data)
            else:
                self.tab.output_options.set_progress(0, self.tab.tr(f"Error: {message}"), "wait")
                logger.error(f"AdvancedProcessTab: Error en descarga directa SOLO: {message}")
                
            self.solo_worker = None

        self.solo_worker.progress.connect(on_solo_progress)
        self.solo_worker.finished.connect(on_solo_finished)
        self.solo_worker.start()

    def pause_solo_download(self):
        """Pausa (cancela) la descarga directa en modo SOLO."""
        if self.is_downloading and self.solo_worker:
            logger.info("AdvancedProcessTab: Cancelando descarga directa SOLO...")
            self.cancellation_event.set()
            self.is_downloading = False
            self.tab.output_options.set_download_state("idle")
            self.tab.output_options.set_progress(0, self.tab.tr("Descarga cancelada"), "wait")
            self.tab.url_bar.solo_btn.setEnabled(True)

    def pause_download(self):
        """Pausa la cola sin cancelar los trabajos pendientes."""
        if self.is_downloading:
            logger.info("AdvancedProcessTab: Pausando cola de descargas...")
            self.queue_mgr.pause_queue()
            
            jobs = self.queue_mgr.get_all_jobs()
            running_jobs = [j for j in jobs if j.status == "RUNNING"]
            if running_jobs:
                for job in running_jobs:
                    self.paused_job_ids.add(job.job_id)
                    self.queue_mgr.cancel_job(job.job_id)
                
                self.tab.output_options.set_download_state("paused", self.tab.tr("Pausando..."))
                self.tab.output_options.btn_start_download.setEnabled(False)
            else:
                self.is_downloading = False
                self.tab.output_options.set_download_state("paused", self.tab.tr("Reanudar cola"))
                self.tab.output_options.btn_start_download.setEnabled(True)

    def update_queue_main_progress(self):
        """
        Actualiza la barra de progreso principal evaluando toda la cola de forma
        global. La cola soporta varios jobs corriendo en simultáneo
        (max_concurrent_downloads, ver QueueWorker.run() en queue_manager.py),
        así que "el progreso de un job en particular" deja de tener sentido en
        cuanto hay más de uno activo — en ese caso se muestra cuántos de
        cuántos ya terminaron ("X de Y completados"), igual que en Modo
        Rápido. Solo se muestra el % real de un job cuando es el único
        corriendo y no tiene fragmentos (ahí sí hay un solo número que
        representa fielmente lo que está pasando).
        """
        jobs = self.queue_mgr.get_all_jobs()
        if not jobs:
            if self.tab.taskbar_manager:
                self.tab.taskbar_manager.stop()
            return

        total = len(jobs)
        completed = 0
        other_done = 0
        running_jobs = []
        analyzing_count = 0

        for j in jobs:
            if j.status == "COMPLETED":
                completed += 1
            elif j.status in ("FAILED", "CANCELLED", "SKIPPED"):
                other_done += 1
            elif j.status == "RUNNING":
                running_jobs.append(j)
            elif j.status == "ANALYZING":
                analyzing_count += 1

        processed = completed + other_done
        taskbar_state = "stop"
        taskbar_value = None

        single_job = running_jobs[0] if len(running_jobs) == 1 else None
        single_has_fragments = bool(
            single_job and single_job.request_data and single_job.request_data.get("selected_fragments")
        )

        if single_job and not single_has_fragments:
            msg = (
                f"({processed + 1}/{total}) {int(single_job.progress)}% — {single_job.speed} — ETA: {single_job.eta}"
                if total > 1 else
                f"{int(single_job.progress)}% — {single_job.speed} — ETA: {single_job.eta}"
            )
            percent = single_job.progress
            state = "downloading"
            taskbar_state = "normal"
            taskbar_value = int(percent)

        elif running_jobs:
            # Más de un job corriendo (o el único que corre tiene fragmentos):
            # no hay un % único representativo del conjunto.
            msg = f"{processed} de {total} completados"
            percent = int(processed / total * 100) if total else 0
            state = "downloading"
            taskbar_state = "indeterminate"

        elif analyzing_count:
            msg = self.tab.tr("Analizando...")
            percent = 0
            state = "running"
            taskbar_state = "indeterminate"

        else:
            if processed == total and total > 0:
                msg = f"Proceso completado ({completed}/{total})"
                percent = 100
                state = "done"
            else:
                msg = f"En espera ({processed}/{total})..."
                percent = 0
                state = "wait"

        self.tab.output_options.set_progress(int(percent), msg, state)

        if self.tab.taskbar_manager:
            if taskbar_state == "stop":
                self.tab.taskbar_manager.stop()
            else:
                self.tab.taskbar_manager.set_state(taskbar_state)
                if taskbar_value is not None:
                    self.tab.taskbar_manager.set_value(taskbar_value)

    def _on_queue_job_progress(self, job_id, percent, speed, eta):
        current_time = time.time()
        if current_time - self.last_progress_update < 0.33 and percent < 100:
            return
        self.last_progress_update = current_time
        self.update_queue_main_progress()

    def _on_queue_finished_all(self):
        self.queue_mgr.pause_queue()
        self.is_downloading = False
        jobs = self.queue_mgr.get_all_jobs()
        has_pending = any(j.status == "PENDING" for j in jobs)
        if has_pending:
            self.tab.output_options.set_download_state("paused", self.tab.tr("Reanudar cola"))
        else:
            self.tab.output_options.set_download_state("idle")
        self.tab.output_options.btn_start_download.setEnabled(True)
        self.tab.subtitle_controller.on_subtitle_selection_changed()
        self.tab.subtitle_options.btn_download_subtitles.setEnabled(True)
        self.tab.url_bar.solo_btn.setEnabled(True)
        self.update_queue_main_progress()
        logger.info("AdvancedProcessTab: Descargas finalizadas.")

    def on_queue_panel_action(self, action):
        jobs = self.queue_mgr.get_all_jobs()
        
        if not jobs:
            self.is_downloading = False
            self.tab.output_options.set_download_state("idle")
            self.tab.output_options.btn_start_download.setEnabled(False)
            self.tab._selected_job_id = None
            self.tab._current_video_data = None
            self.tab.video_details.reset_ui()
            self.tab.subtitle_controller.clear_subtitles()
            self.tab.output_options.set_progress(0, self.tab.tr("En espera"), "wait")
        else:
            if action == "reset":
                self.is_downloading = False
                has_pending = any(j.status == "PENDING" for j in jobs)
                if has_pending:
                    self.tab.output_options.set_download_state("paused", self.tab.tr("Reanudar cola"))
                    self.tab.output_options.btn_start_download.setEnabled(True)
                else:
                    self.tab.output_options.set_download_state("idle")
                    self.tab.output_options.btn_start_download.setEnabled(True)
        
        self.update_queue_main_progress()

    def _on_queue_job_status(self, job_id, status):
        self.update_queue_main_progress()
        
        if status == "COMPLETED":
            job = self.queue_mgr.get_job(job_id)
            if job and job.request_data:
                title = job.request_data.get("title", "").strip()
                output_dir = job.request_data.get("output_path", "")
                if title and output_dir:
                    logger.info(f"AdvancedProcessTab: Iniciando limpieza de residuos para '{title}'")
                    from core.utils.config_manager import get_config
                    batch_thumb_mode = get_config().get("batch_thumbnail_mode", "manual")
                    if batch_thumb_mode in ("with_media", "thumbnail_only"):
                        keep_thumb = True
                    else:
                        keep_thumb = job.request_data.get("download_thumbnail_file", False)
                        
                    CleanupManager.cleanup_ytdlp_temp_files(output_dir, title, keep_thumbnail=keep_thumb)
                    CleanupManager.deferred_cleanup(output_dir, title, keep_thumbnail=keep_thumb)
        elif status in ("FAILED", "CANCELLED"):
            job = self.queue_mgr.get_job(job_id)
            err_msg = job.error_message if job else ""
            if status == "FAILED":
                logger.error(f"AdvancedProcessTab: Fallo en descarga de {job_id}: {err_msg}")
            
            if status == "CANCELLED" and job_id in self.paused_job_ids:
                self.paused_job_ids.discard(job_id)
                self.queue_mgr.reset_job(job_id)
        
        if self.is_downloading and self.queue_mgr.is_paused():
            jobs = self.queue_mgr.get_all_jobs()
            if not any(j.status == "RUNNING" for j in jobs):
                self.is_downloading = False
                self.tab.output_options.set_download_state("paused", self.tab.tr("Reanudar cola"))
                self.tab.output_options.btn_start_download.setEnabled(True)
                self.tab.subtitle_options.btn_download_subtitles.setEnabled(True)
                self.tab.url_bar.solo_btn.setEnabled(True)

    def on_open_output_path_clicked(self):
        path = self.tab.output_options.output_path_input.text().strip()
        if not path:
            return

        if self.tab.url_bar.solo_btn.isChecked():
            if self.last_downloaded_filepath:
                actual_path = self._find_actual_downloaded_file(self.last_downloaded_filepath)
                if actual_path:
                    self._open_and_select(actual_path)
                    return
        else:
            if self.tab._selected_job_id:
                job = self.queue_mgr.get_job(self.tab._selected_job_id)
                if job and job.status == "COMPLETED" and job.final_filepath:
                    actual_path = self._find_actual_downloaded_file(job.final_filepath)
                    if actual_path:
                        self._open_and_select(actual_path)
                        return

        # Fallback estándar
        if os.path.exists(path):
            path = os.path.abspath(path)
            if os.name == 'nt':
                os.startfile(path)
            else:
                from PySide6.QtGui import QDesktopServices
                from PySide6.QtCore import QUrl
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _find_actual_downloaded_file(self, filepath):
        if not filepath:
            return None
        if os.path.exists(filepath):
            return filepath
            
        if os.path.isdir(filepath):
            return filepath
            
        parent_dir = os.path.dirname(filepath)
        if not os.path.exists(parent_dir):
            return None
            
        base_name = os.path.splitext(os.path.basename(filepath))[0]
        
        for temp_ext in ['.temp', '.ytdl', '.part']:
            if base_name.endswith(temp_ext):
                base_name = base_name[:-len(temp_ext)]
                
        best_match = None
        try:
            for entry in os.scandir(parent_dir):
                if entry.is_file():
                    entry_base = os.path.splitext(entry.name)[0]
                    if entry_base == base_name:
                        return entry.path
                    if entry_base.startswith(base_name):
                        best_match = entry.path
        except Exception as e:
            logger.error(f"Error escaneando directorio para encontrar archivo: {e}")
            
        if best_match:
            return best_match
            
        return parent_dir

    def _open_and_select(self, path):
        path = os.path.abspath(path)
        if not os.path.exists(path):
            return
            
        try:
            if os.name == 'nt':
                if os.path.isdir(path):
                    os.startfile(path)
                else:
                    subprocess.run(['explorer', '/select,', path])
            elif platform.system() == 'Darwin':
                if os.path.isdir(path):
                    subprocess.run(['open', path])
                else:
                    subprocess.run(['open', '-R', path])
            else:
                if os.path.isdir(path):
                    subprocess.run(['xdg-open', path])
                else:
                    subprocess.run(['xdg-open', os.path.dirname(path)])
        except Exception as e:
            logger.error(f"Error abriendo explorador en la ruta {path}: {e}")
