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
        
        # Atributos de seguimiento independientes para la descarga actual
        self.current_item_rows = []
        self.current_item_keys = []
        self.current_item_pos = 0
        self.completed_items = 0

    def start_download_flow(self, url, mode, quality, output_path, speed_limit_val,
                            chk_thumb_file_checked, chk_thumb_only_checked,
                            btn_cut_checked, chk_playlist_selector_checked):
        """Inicia el flujo de descargas dependiendo de la configuración actual."""
        if self.is_downloading:
            self.cancel_download()
            return

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
            is_playlist=False
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
            )
            
            # Sobrescribir opciones con las del diálogo de selección de playlist
            req["mode"] = dialog.result_data.get("playlist_mode") or req["mode"]
            # Re-evaluar formato si cambió el modo/calidad de la playlist
            from core.ytdlp_logic.format_selectors import quick_format_selector
            req["format_selector"] = quick_format_selector(req["mode"], dialog.result_data.get("playlist_quality") or quality)

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
        # 1. Buscar la miniatura del video
        thumb_url = None
        thumbs = data.get("thumbnails") or []
        valid_thumbs = [t for t in thumbs if t.get("url")]
        if valid_thumbs:
            valid_thumbs.sort(key=lambda t: (t.get("width") or 0) * (t.get("height") or 0), reverse=True)
            thumb_url = valid_thumbs[0]["url"]
        else:
            thumb_url = data.get("thumbnail")

        # Descargar miniatura de manera síncrona
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

        # 2. Encontrar stream_url para la vista previa del reproductor
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

        # 3. Lanzar FragmentDialog con un overlay semitransparente sobre la ventana principal
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

        # 4. Si el usuario guarda el fragmento
        if result:
            frag_data = dialog.get_fragments_data()
            selected_fragments = frag_data["fragments"]
            fragment_mode = frag_data["mode"]
            
            # Construimos la petición de descarga
            req = build_quick_request_data(
                url=url,
                title=data.get("title", ""),
                mode=mode,
                quality=quality,
                output_path=output_path,
                speed_limit_val=speed_limit_val,
                chk_thumb_file_checked=chk_thumb_file_checked,
                chk_thumb_only_checked=chk_thumb_only_checked,
                is_playlist=False
            )
            req["selected_fragments"] = selected_fragments
            req["fragment_mode"] = fragment_mode
            
            self.is_downloading = True
            self.busy_state_changed.emit(False, "")
            self.download_text_changed.emit(self.tr("Cancelar") if hasattr(self, "tr") else "Cancelar")
            
            self.start_worker(req, selected_entries=[data], selected_indices=[0])
        else:
            self.busy_state_changed.emit(False, "")
            self.progress_updated.emit(0, self.tr("Recorte cancelado") if hasattr(self, "tr") else "Recorte cancelado", "wait")

    def start_worker(self, request_data, selected_entries=None, selected_indices=None):
        """Inicia el DownloadWorker."""
        self.cancellation_event.clear()
        self.last_request_data = request_data.copy()
        self.last_downloaded_filepath = None
        
        # Agregamos las nuevas filas acumulativamente
        self.current_item_rows, self.current_item_keys = self.tab.activity_panel.add_activity_rows(
            selected_entries or [], selected_indices or []
        )
        self.current_item_pos = 1 if self.current_item_rows else 0
        self.completed_items = 0
        
        self.download_worker = DownloadWorker(request_data, self.cancellation_event)
        self.download_worker.progress.connect(self._on_download_progress)
        self.download_worker.finished.connect(self._on_download_finished)
        
        self.is_downloading = True
        self.controls_state_changed.emit(False)
        self.download_text_changed.emit(self.tr("Cancelar") if hasattr(self, "tr") else "Cancelar")
        self.progress_updated.emit(0, self.tr("Iniciando descarga...") if hasattr(self, "tr") else "Iniciando descarga...", "running")
        
        self.download_worker.start()

    def cancel_download(self):
        """Cancela la descarga activa en curso."""
        if self.download_worker:
            self.cancellation_event.set()
        self.is_downloading = False
        self.controls_state_changed.emit(True)
        self.download_text_changed.emit(self.tr("Descargar") if hasattr(self, "tr") else "Descargar")
        self.progress_updated.emit(0, self.tr("Cancelando descarga...") if hasattr(self, "tr") else "Cancelando descarga...", "wait")

    def _on_download_progress(self, data):
        if data.get("status") == "downloading":
            from core.ytdlp_logic.analyzer import strip_ansi_codes
            p_str = strip_ansi_codes(data.get("_percent_str", "0%")).replace("%", "").strip()
            try:
                val = float(p_str)
            except Exception:
                val = 0
            speed = strip_ansi_codes(data.get("_speed_str", "")).strip() or "..."
            eta = strip_ansi_codes(data.get("_eta_str", "")).strip() or "..."
            
            row_idx = self._resolve_progress_row(data)
            if row_idx is not None and 0 <= row_idx < len(self.current_item_rows):
                self.current_item_pos = row_idx + 1
                row = self.current_item_rows[row_idx]
                row.update_progress(
                    val,
                    info=f"{speed} - ETA: {eta}",
                    status=self.tr("Descargando") if hasattr(self, "tr") else "Descargando",
                )
                info = data.get("info_dict")
                if info:
                    row.update_metadata_from_dict(info)
                    
            total = max(1, len(self.current_item_rows))
            global_percent = ((max(0, self.current_item_pos - 1) + (val / 100.0)) / total) * 100.0
            
            msg = (self.tr("{} de {}").format(max(1, self.current_item_pos), total)
                   if hasattr(self, "tr") else f"{max(1, self.current_item_pos)} de {total}")
            self.progress_updated.emit(int(global_percent), msg, "downloading")
            
        elif data.get("status") == "finished":
            filepath = data.get("filename")
            if filepath:
                self.last_downloaded_filepath = filepath
            row_idx = self._resolve_progress_row(data)
            if row_idx is not None and 0 <= row_idx < len(self.current_item_rows):
                row = self.current_item_rows[row_idx]
                row.update_progress(100, status=self.tr("Procesando") if hasattr(self, "tr") else "Procesando")
                if filepath:
                    row.downloaded_filepath = filepath
                info = data.get("info_dict")
                if info:
                    row.update_metadata_from_dict(info)
                self.completed_items = max(self.completed_items, row_idx + 1)
                self.current_item_pos = min(len(self.current_item_rows), row_idx + 2)
                
            total = max(1, len(self.current_item_rows))
            msg = (self.tr("{} de {}").format(min(total, self.completed_items + 1), total)
                   if hasattr(self, "tr") else f"{min(total, self.completed_items + 1)} de {total}")
            self.progress_updated.emit(
                int((self.completed_items / total) * 100),
                msg,
                "downloading"
            )

    def _resolve_progress_row(self, data):
        if len(self.current_item_rows) <= 1:
            return 0 if self.current_item_rows else None
        info = data.get("info_dict") or {}
        playlist_index = info.get("playlist_index")
        if playlist_index in self.current_item_keys:
            return self.current_item_keys.index(playlist_index)
        return max(0, min(len(self.current_item_rows) - 1, self.current_item_pos - 1))

    def _on_download_finished(self, success, message):
        self.is_downloading = False
        self.controls_state_changed.emit(True)
        self.download_text_changed.emit(self.tr("Descargar") if hasattr(self, "tr") else "Descargar")
        
        if success:
            for row in self.current_item_rows:
                row.update_progress(100, status=self.tr("Completado") if hasattr(self, "tr") else "Completado")
                row.mark_completed()
            title = self.last_request_data.get("title", "").strip()
            output_dir = self.last_request_data.get("output_path", "")
            if title and output_dir:
                keep_thumb = self.last_request_data.get("download_thumbnail_file", False)
                CleanupManager.cleanup_ytdlp_temp_files(output_dir, title, keep_thumbnail=keep_thumb)
                CleanupManager.deferred_cleanup(output_dir, title, keep_thumbnail=keep_thumb)
            self.progress_updated.emit(100, self.tr("Descarga completada con éxito") if hasattr(self, "tr") else "Descarga completada con éxito", "done")
            logger.info("QuickDownloadController: Descarga finalizada con éxito.")
        else:
            if self.current_item_rows:
                idx = max(0, min(len(self.current_item_rows) - 1, self.current_item_pos - 1))
                self.current_item_rows[idx].update_progress(0, status=self.tr("Error") if hasattr(self, "tr") else "Error")
                self.current_item_rows[idx].mark_error()
            self.progress_updated.emit(0, self.tr(f"Error: {message}") if hasattr(self, "tr") else f"Error: {message}", "error")
            logger.error(f"QuickDownloadController: Error en descarga: {message}")
            
        if self.download_worker:
            self.download_worker.deleteLater()
        self.download_worker = None
        self.download_finished_signal.emit(success, message)
