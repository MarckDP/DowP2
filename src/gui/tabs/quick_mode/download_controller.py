# src/gui/tabs/quick_mode/download_controller.py
import os
import requests
import threading
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import QDialog

from core.logger.logger_manager import logger
from core.utils.cleanup_manager import CleanupManager
from core.utils.config_manager import get_config
from core.tabs.quick_mode.quick_mode_logic import build_quick_request_data, reveal_in_file_manager
from gui.tabs.advanced_process.workers import AnalysisWorker, DownloadWorker
from gui.dialogs.playlist_selection_dialog import PlaylistSelectionDialog


class QuickDownloadController(QObject):
    """Controlador de descargas y análisis para la pestaña QuickMode."""
    
    # Señales para notificar cambios a la vista
    busy_state_changed = Signal(bool, str)       # (busy, message)
    controls_state_changed = Signal(bool)       # (enabled)
    download_text_changed = Signal(str)         # (text)
    download_finished_signal = Signal(bool, str) # (success, message)
    progress_updated = Signal(int, str, str)    # (value, message, status_type)

    def __init__(self, parent_tab):
        super().__init__(parent_tab)
        self.tab = parent_tab
        self.download_worker = None
        self.analysis_worker = None
        self.cancellation_event = threading.Event()
        self.is_downloading = False
        self.last_request_data = None
        self.last_downloaded_filepath = None
        
        # Atributos de seguimiento para las descargas
        self.active_workers = []
        self.pending_tasks = []
        self.current_item_rows = []
        self.current_item_keys = []
        self.current_item_pos = 0
        self.completed_items = 0

        # Contadores de la tanda actual, para la barra general ("X de Y
        # completados"). Se reinician cuando arranca una tanda nueva desde
        # estado idle (ver start_worker).
        self._batch_total = 0
        self._batch_completed = 0

    def start_download_flow(self, url, mode, quality, output_path, speed_limit_val,
                            chk_thumb_file_checked, chk_thumb_only_checked,
                            btn_cut_checked, chk_playlist_selector_checked):
        """Inicia el flujo de descargas dependiendo de la configuración actual."""
        if not url:
            self.progress_updated.emit(0, self.tr("Pega una URL primero") if hasattr(self, "tr") else "Pega una URL primero", "error")
            return

        if btn_cut_checked:
            self.start_cut_analysis(url, mode, quality, output_path, speed_limit_val,
                                    chk_thumb_file_checked, chk_thumb_only_checked)
        elif chk_playlist_selector_checked:
            self.start_playlist_selection(url, mode, quality, output_path, speed_limit_val,
                                         chk_thumb_file_checked, chk_thumb_only_checked)
        else:
            self.start_direct_download(url, mode, quality, output_path, speed_limit_val,
                                       chk_thumb_file_checked, chk_thumb_only_checked)

    def start_direct_download(self, url, mode, quality, output_path, speed_limit_val,
                              chk_thumb_file_checked, chk_thumb_only_checked):
        """Descarga directa sin análisis previo."""
        req = build_quick_request_data(
            url=url,
            title="",
            mode=mode,
            quality=quality,
            output_path=output_path,
            speed_limit_val=speed_limit_val,
            chk_thumb_file_checked=chk_thumb_file_checked,
            chk_thumb_only_checked=chk_thumb_only_checked,
            is_playlist=False,
            conflict_policy=self.tab.output_options.conflict_policy_combo.currentData(),
        )
        self.start_worker(req, selected_entries=[{"title": self.tr("Descarga directa") if hasattr(self, "tr") else "Descarga directa"}], selected_indices=[0])

    def start_playlist_selection(self, url, mode, quality, output_path, speed_limit_val,
                                 chk_thumb_file_checked, chk_thumb_only_checked):
        """Inicia el análisis de la lista de reproducción para posterior selección."""
        self.busy_state_changed.emit(True, self.tr("Analizando playlist...") if hasattr(self, "tr") else "Analizando playlist...")
        self.analysis_worker = AnalysisWorker(url, analyze_playlist=True, fast_mode=True)

        def on_finished(data, error):
            if self.analysis_worker:
                self.analysis_worker.deleteLater()
            self.analysis_worker = None
            
            if error:
                self.busy_state_changed.emit(False, "")
                self.progress_updated.emit(0, self.tr(f"Error: {error}") if hasattr(self, "tr") else f"Error: {error}", "error")
                return

            entries = data.get("entries") or []
            if len(entries) <= 1:
                self.busy_state_changed.emit(False, "")
                self.start_direct_download(url, mode, quality, output_path, speed_limit_val,
                                           chk_thumb_file_checked, chk_thumb_only_checked)
                return

            dialog = PlaylistSelectionDialog(data, self.tab)
            if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.result_data:
                self.busy_state_changed.emit(False, "")
                self.progress_updated.emit(0, self.tr("Selección cancelada") if hasattr(self, "tr") else "Selección cancelada", "wait")
                return

            selected = dialog.result_data.get("selected_indices", [])
            if not selected:
                self.busy_state_changed.emit(False, "")
                self.progress_updated.emit(0, self.tr("No se seleccionaron medios") if hasattr(self, "tr") else "No se seleccionaron medios", "error")
                return

            req = build_quick_request_data(
                url=data.get("original_url", data.get("webpage_url", url)),
                title=data.get("title") or (self.tr("Playlist") if hasattr(self, "tr") else "Playlist"),
                mode=mode,
                quality=quality,
                output_path=output_path,
                speed_limit_val=speed_limit_val,
                chk_thumb_file_checked=chk_thumb_file_checked,
                chk_thumb_only_checked=chk_thumb_only_checked,
                is_playlist=True,
                playlist_items=",".join(str(i + 1) for i in selected),
                conflict_policy=self.tab.output_options.conflict_policy_combo.currentData(),
            )
            
            req["mode"] = dialog.result_data.get("playlist_mode") or req["mode"]
            from core.ytdlp_logic.format_selectors import quick_format_selector
            req["format_selector"] = quick_format_selector(req["mode"], dialog.result_data.get("playlist_quality") or quality, url=req.get("url", ""))

            selected_entries = [entries[i] for i in selected if 0 <= i < len(entries)]
            self.start_worker(req, selected_entries=selected_entries, selected_indices=selected)

        self.analysis_worker.finished.connect(on_finished)
        self.analysis_worker.start()

    def start_cut_analysis(self, url, mode, quality, output_path, speed_limit_val,
                           chk_thumb_file_checked, chk_thumb_only_checked):
        """Inicia el análisis para corte de fragmento."""
        self.busy_state_changed.emit(True, self.tr("Analizando video para recorte...") if hasattr(self, "tr") else "Analizando video para recorte...")
        self.analysis_worker = AnalysisWorker(url, analyze_playlist=False, fast_mode=True)
        
        def on_finished(data, error):
            if self.analysis_worker:
                self.analysis_worker.deleteLater()
            self.analysis_worker = None
            
            if error:
                self.busy_state_changed.emit(False, "")
                self.progress_updated.emit(0, self.tr(f"Error al analizar: {error}") if hasattr(self, "tr") else f"Error al analizar: {error}", "error")
                return
                
            self.open_cut_dialog_and_download(url, data, mode, quality, output_path, speed_limit_val,
                                              chk_thumb_file_checked, chk_thumb_only_checked)
            
        self.analysis_worker.finished.connect(on_finished)
        self.analysis_worker.start()

    def open_cut_dialog_and_download(self, url, data, mode, quality, output_path, speed_limit_val,
                                     chk_thumb_file_checked, chk_thumb_only_checked):
        """Abre el diálogo de fragmento de corte."""
        thumb_url = None
        thumbs = data.get("thumbnails") or []
        valid_thumbs = [t for t in thumbs if t.get("url")]
        if valid_thumbs:
            valid_thumbs.sort(key=lambda t: (t.get("width") or 0) * (t.get("height") or 0), reverse=True)
            thumb_url = valid_thumbs[0]["url"]
        else:
            thumb_url = data.get("thumbnail")

        pixmap = None
        if thumb_url:
            try:
                from PySide6.QtGui import QImage, QPixmap
                resp = requests.get(thumb_url, timeout=3)
                resp.raise_for_status()
                img = QImage.fromData(resp.content)
                if not img.isNull():
                    pixmap = QPixmap.fromImage(img)
            except Exception as e:
                logger.warning(f"QuickDownloadController: No se pudo descargar miniatura para FragmentDialog: {e}")

        formats = data.get("formats") or []
        preview_format = None
        for f in formats:
            if f.get("url") and not f.get("url", "").startswith("rtmp") and f.get("acodec") != "none" and f.get("vcodec") != "none":
                h = f.get("height") or 0
                if 360 <= h <= 720:
                    preview_format = f
                    break
        if not preview_format:
            for f in formats:
                if f.get("url") and f.get("vcodec") != "none":
                    preview_format = f
                    break
        stream_url = preview_format.get("url", "") if preview_format else ""

        from gui.dialogs.fragment_dialog import FragmentDialog
        
        dialog = FragmentDialog(
            self.tab,
            stream_url=stream_url,
            thumbnail_pixmap=pixmap,
            duration=data.get("duration", 0),
            fps=data.get("fps", 30) or 30,
            source_url=data.get("webpage_url", url),
        )

        main_win = self.tab.window()
        overlay = None
        try:
            from PySide6.QtWidgets import QWidget as _QWidget
            overlay = _QWidget(main_win)
            overlay.setStyleSheet("background-color: rgba(0, 0, 0, 160);")
            overlay.setGeometry(main_win.rect())
            overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            overlay.show()
            overlay.raise_()
        except Exception:
            overlay = None

        result = dialog.exec()

        if overlay is not None:
            try:
                overlay.hide()
                overlay.deleteLater()
            except Exception:
                pass

        if result:
            frag_data = dialog.get_fragments_data()
            selected_fragments = frag_data["fragments"]
            fragment_mode = frag_data["mode"]
            
            req = build_quick_request_data(
                url=url,
                title=data.get("title", ""),
                mode=mode,
                quality=quality,
                output_path=output_path,
                speed_limit_val=speed_limit_val,
                chk_thumb_file_checked=chk_thumb_file_checked,
                chk_thumb_only_checked=chk_thumb_only_checked,
                is_playlist=False,
                conflict_policy=self.tab.output_options.conflict_policy_combo.currentData(),
            )
            req["selected_fragments"] = selected_fragments
            req["fragment_mode"] = fragment_mode
            
            self.busy_state_changed.emit(False, "")
            self.download_text_changed.emit(self.tr("Descargar") if hasattr(self, "tr") else "Descargar")
            
            self.start_worker(req, selected_entries=[data], selected_indices=[0])
        else:
            self.busy_state_changed.emit(False, "")
            self.progress_updated.emit(0, self.tr("Recorte cancelado") if hasattr(self, "tr") else "Recorte cancelado", "wait")

    def start_worker(self, request_data, selected_entries=None, selected_indices=None):
        """Inicia un DownloadWorker respectando la concurrencia global."""
        from core.utils.config_manager import get_config
        max_concurrent = get_config().get("max_concurrent_downloads", 3)

        # Si no hay nada activo ni encolado, esta es una tanda nueva: reiniciar
        # los contadores para la barra general ("X de Y completados").
        if not self.active_workers and not self.pending_tasks:
            self._batch_total = 0
            self._batch_completed = 0
        self._batch_total += 1

        self.last_request_data = request_data.copy()
        self.last_downloaded_filepath = None

        item_rows, item_keys = self.tab.activity_panel.add_activity_rows(
            selected_entries or [], selected_indices or []
        )
        self.current_item_rows.extend(item_rows)
        self.current_item_keys.extend(item_keys)

        canc_event = threading.Event()
        task_data = {
            "request_data": request_data.copy(),
            "item_rows": item_rows,
            "item_keys": item_keys,
            "cancellation_event": canc_event,
        }

        if len(self.active_workers) < max_concurrent:
            self._start_task_worker(task_data)
        else:
            for row in item_rows:
                row.update_progress(0, status=self.tr("En cola") if hasattr(self, "tr") else "En cola")
            self.pending_tasks.append(task_data)
            self.is_downloading = True
            self._emit_batch_progress()

    def _emit_batch_progress(self):
        """
        Actualiza la barra general (la de 'Opciones de salida') para que solo
        muestre cuántos ítems de la tanda actual ya terminaron — nunca el
        progreso en vivo de un ítem individual (eso lo maneja cada fila).
        """
        total = self._batch_total
        completed = self._batch_completed
        if total <= 0:
            return
        percent = int(completed / total * 100)
        msg = (
            self.tr("{0} de {1} completados").format(completed, total)
            if hasattr(self, "tr") else f"{completed} de {total} completados"
        )
        self.progress_updated.emit(percent, msg, "downloading")
        if self.tab.taskbar_manager:
            self.tab.taskbar_manager.set_state("normal")
            self.tab.taskbar_manager.set_value(percent)

    def _start_task_worker(self, task_data):
        worker = DownloadWorker(task_data["request_data"], task_data["cancellation_event"])
        task_data["worker"] = worker
        self.download_worker = worker

        worker.progress.connect(lambda d, task=task_data: self._on_task_progress(d, task))
        worker.finished.connect(lambda success, msg, task=task_data: self._on_task_finished(success, msg, task))

        self.active_workers.append(task_data)
        self.is_downloading = True
        self.controls_state_changed.emit(False)
        self.download_text_changed.emit(self.tr("Descargar") if hasattr(self, "tr") else "Descargar")
        self._emit_batch_progress()
        worker.start()

    def cancel_download(self):
        """Cancela todas las descargas activas y limpia las pendientes."""
        self.pending_tasks.clear()
        for task in list(self.active_workers):
            task["cancellation_event"].set()
        self.active_workers.clear()
        self.is_downloading = False
        self.controls_state_changed.emit(True)
        self.download_text_changed.emit(self.tr("Descargar") if hasattr(self, "tr") else "Descargar")
        self.progress_updated.emit(0, self.tr("Descargas canceladas") if hasattr(self, "tr") else "Descargas canceladas", "wait")
        if self.tab.taskbar_manager:
            self.tab.taskbar_manager.stop()

    def _find_actual_downloaded_file(self, filepath):
        """Busca el archivo real descargado ignorando extensiones temporales."""
        if not filepath:
            return None
            
        import os
        if os.path.exists(filepath):
            return filepath
            
        parent_dir = os.path.dirname(filepath)
        if not os.path.exists(parent_dir):
            return None
            
        base_name = os.path.splitext(os.path.basename(filepath))[0]
        
        for temp_ext in ['.temp', '.ytdl', '.part']:
            if base_name.endswith(temp_ext):
                base_name = base_name[:-len(temp_ext)]
                
        import re
        base_name = re.sub(r'\.f[a-zA-Z0-9-]+$', '', base_name)
                
        best_match = None
        try:
            for entry in os.scandir(parent_dir):
                if entry.is_file():
                    entry_base = os.path.splitext(entry.name)[0]
                    if entry_base == base_name:
                        return entry.path
                    if entry_base.startswith(base_name):
                        best_match = entry.path
        except Exception:
            pass
            
        return best_match

    def _on_task_progress(self, data, task_data):
        has_fragments = bool(task_data["request_data"].get("selected_fragments"))

        if data.get("status") == "fragment_progress":
            idx = data.get("fragment_index")
            total = data.get("fragment_count")
            phase = data.get("phase", "downloading")
            for row in task_data["item_rows"]:
                row.set_fragment_progress(idx, total, phase)
            if self.tab.taskbar_manager:
                self.tab.taskbar_manager.set_state("indeterminate")
            return

        # Mientras el ítem tenga fragmentos, el progreso numérico crudo de
        # yt-dlp no representa el avance real (se dispara una vez por
        # fragmento) — la barra de la fila queda a cargo de fragment_progress.
        if has_fragments:
            return

        if data.get("status") == "downloading":
            from core.ytdlp_logic.analyzer import strip_ansi_codes
            p_str = strip_ansi_codes(data.get("_percent_str", "0%")).replace("%", "").strip()
            try:
                val = float(p_str)
            except Exception:
                val = 0
            speed = strip_ansi_codes(data.get("_speed_str", "")).strip() or "..."
            eta = strip_ansi_codes(data.get("_eta_str", "")).strip() or "..."

            for row in task_data["item_rows"]:
                row.update_progress(
                    val,
                    info=f"{speed} - ETA: {eta}",
                    status=self.tr("Descargando") if hasattr(self, "tr") else "Descargando",
                )
                info = data.get("info_dict")
                if info:
                    row.update_metadata_from_dict(info)

        elif data.get("status") == "finished":
            filepath = data.get("filename")
            if filepath:
                self.last_downloaded_filepath = filepath
            for row in task_data["item_rows"]:
                row.update_progress(100, status=self.tr("Procesando") if hasattr(self, "tr") else "Procesando")
                if filepath:
                    row.downloaded_filepath = filepath
                info = data.get("info_dict")
                if info:
                    row.update_metadata_from_dict(info)

    def _on_task_finished(self, success, message, task_data):
        self._batch_completed += 1

        if task_data in self.active_workers:
            self.active_workers.remove(task_data)

        if task_data.get("worker"):
            task_data["worker"].deleteLater()

        from core.services.editor_integration_manager import EditorIntegrationManager
        editor_mgr = EditorIntegrationManager.get_instance()

        for row in task_data["item_rows"]:
            if success:
                row.update_progress(100, status=self.tr("Completado") if hasattr(self, "tr") else "Completado")
                actual_path = None
                if hasattr(row, 'downloaded_filepath') and row.downloaded_filepath:
                    actual_path = self._find_actual_downloaded_file(row.downloaded_filepath)
                if not actual_path and self.last_downloaded_filepath:
                    actual_path = self._find_actual_downloaded_file(self.last_downloaded_filepath)
                    
                row.mark_completed(filepath=actual_path or getattr(row, 'downloaded_filepath', None))
                
                if editor_mgr and editor_mgr.is_auto_send_enabled and hasattr(row, 'downloaded_filepath') and row.downloaded_filepath:
                    editor_mgr.process_raw_download(actual_path or row.downloaded_filepath, task_data["request_data"])
            elif message == "SKIPPED_CONFLICT":
                # No es un error: la política de conflicto elegida fue "Omitir"
                # y el archivo ya existía.
                row.update_progress(0, status=self.tr("Omitido") if hasattr(self, "tr") else "Omitido")
            else:
                row.update_progress(0, status=self.tr("Error") if hasattr(self, "tr") else "Error")
                row.mark_error()

        if success:
            title = task_data["request_data"].get("title", "").strip()
            output_dir = task_data["request_data"].get("output_path", "")
            if title and output_dir:
                keep_thumb = task_data["request_data"].get("download_thumbnail_file", False)
                CleanupManager.cleanup_ytdlp_temp_files(output_dir, title, keep_thumbnail=keep_thumb)
                CleanupManager.deferred_cleanup(output_dir, title, keep_thumbnail=keep_thumb)

        # Despachar siguiente tarea si existe
        from core.utils.config_manager import get_config
        max_concurrent = get_config().get("max_concurrent_downloads", 3)
        if self.pending_tasks and len(self.active_workers) < max_concurrent:
            next_task = self.pending_tasks.pop(0)
            self._start_task_worker(next_task)

        if not self.active_workers and not self.pending_tasks:
            self.is_downloading = False
            self.controls_state_changed.emit(True)
            self.download_text_changed.emit(self.tr("Descargar") if hasattr(self, "tr") else "Descargar")
            self.progress_updated.emit(100, self.tr("Descargas completadas") if hasattr(self, "tr") else "Descargas completadas", "done")
            if self.tab.taskbar_manager:
                self.tab.taskbar_manager.stop()
        else:
            self._emit_batch_progress()

        self.download_finished_signal.emit(success, message)
