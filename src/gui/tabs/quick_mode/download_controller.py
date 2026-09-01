# src/gui/tabs/quick_mode/download_controller.py
import os
import requests
import threading
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import QDialog

from core.logger.logger_manager import logger
from core.utils.cleanup_manager import CleanupManager
from core.utils.config_manager import get_config
from core.utils.queue_manager import get_queue_manager
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

        # Recodificación post-descarga (misma tarjeta "Recodificar" de Proceso
        # Avanzado, ver quick_mode_view.py::recode_options y AdvancedProcessTab
        # DownloadController._start_post_download_recode, del que este bloque es
        # contraparte simplificada para Modo Rápido: solo tareas de UNA fila -
        # descarga directa o con recorte de fragmento - se recodifican; una
        # selección de playlist con más de un ítem se ignora (ver
        # _on_task_finished) porque no hay forma de saber qué archivo final
        # corresponde a cada fila dentro de la misma tarea/worker.
        self.queue_mgr = get_queue_manager()
        self.queue_mgr.job_progress_changed.connect(self._on_recode_job_progress)
        self.queue_mgr.job_status_changed.connect(self._on_recode_job_status)
        self._recode_by_download = {}
        self._recode_state = {}

    def start_download_flow(self, url, mode, quality, output_path, speed_limit_val,
                            chk_thumb_file_checked, chk_thumb_only_checked,
                            btn_cut_checked, chk_playlist_selector_checked, recode_data=None):
        """Inicia el flujo de descargas dependiendo de la configuración actual."""
        if not url:
            self.progress_updated.emit(0, self.tr("Pega una URL primero") if hasattr(self, "tr") else "Pega una URL primero", "error")
            return

        if btn_cut_checked:
            self.start_cut_analysis(url, mode, quality, output_path, speed_limit_val,
                                    chk_thumb_file_checked, chk_thumb_only_checked, recode_data)
        elif chk_playlist_selector_checked:
            self.start_playlist_selection(url, mode, quality, output_path, speed_limit_val,
                                         chk_thumb_file_checked, chk_thumb_only_checked, recode_data)
        else:
            self.start_direct_download(url, mode, quality, output_path, speed_limit_val,
                                       chk_thumb_file_checked, chk_thumb_only_checked, recode_data)

    def start_direct_download(self, url, mode, quality, output_path, speed_limit_val,
                              chk_thumb_file_checked, chk_thumb_only_checked, recode_data=None):
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
        if recode_data:
            req.update(recode_data)
        self.start_worker(req, selected_entries=[{"title": self.tr("Descarga directa") if hasattr(self, "tr") else "Descarga directa"}], selected_indices=[0])

    def start_playlist_selection(self, url, mode, quality, output_path, speed_limit_val,
                                 chk_thumb_file_checked, chk_thumb_only_checked, recode_data=None):
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
                                           chk_thumb_file_checked, chk_thumb_only_checked, recode_data)
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
            if recode_data:
                req.update(recode_data)

            selected_entries = [entries[i] for i in selected if 0 <= i < len(entries)]
            self.start_worker(req, selected_entries=selected_entries, selected_indices=selected)

        self.analysis_worker.finished.connect(on_finished)
        self.analysis_worker.start()

    def start_cut_analysis(self, url, mode, quality, output_path, speed_limit_val,
                           chk_thumb_file_checked, chk_thumb_only_checked, recode_data=None):
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
                                              chk_thumb_file_checked, chk_thumb_only_checked, recode_data)

        self.analysis_worker.finished.connect(on_finished)
        self.analysis_worker.start()

    def open_cut_dialog_and_download(self, url, data, mode, quality, output_path, speed_limit_val,
                                     chk_thumb_file_checked, chk_thumb_only_checked, recode_data=None):
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
            if recode_data:
                req.update(recode_data)

            self.busy_state_changed.emit(False, "")
            self.download_text_changed.emit(self.tr("Descargar") if hasattr(self, "tr") else "Descargar")

            if len(selected_fragments) > 1:
                # Una fila por fragmento (en vez de una sola fila para todo el corte):
                # sin esto, con más de un fragmento seleccionado todas las filas
                # terminaban compartiendo el archivo del ÚLTIMO fragmento en terminar
                # (ver _resolve_target_rows) - "Recodificar" solo llegaba a aplicarse a
                # ese, dejando el resto de los fragmentos sin recodificar (ver
                # conversación). El índice 0-based de cada fragmento (selected_indices)
                # se vuelve su "playlist_idx" 1-based en item_keys (ver
                # ActivityPanel.add_activity_rows), que coincide con el fragment_index
                # 1-based que ya manda fragment_progress.
                base_title = (data.get("title") or "").strip()
                entries = []
                for i, frag in enumerate(selected_fragments):
                    suffix = frag[2] if len(frag) > 2 else f"fragment{i+1:02d}"
                    entry = dict(data)
                    entry.pop("playlist_index", None)
                    entry["title"] = f"{base_title} - {suffix}" if base_title else suffix
                    entries.append(entry)
                self.start_worker(req, selected_entries=entries, selected_indices=list(range(len(selected_fragments))))
            else:
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
            # Recuerda qué fragmento está en curso - los eventos "downloading"/"finished"
            # que vengan justo después (hasta el próximo fragment_progress) pertenecen a
            # ESTE fragmento (ver _resolve_target_rows). Necesario para un corte con más
            # de un fragmento: ahí hay una fila por fragmento (ver
            # open_cut_dialog_and_download) y sin esto todas las filas terminaban
            # compartiendo el archivo del ÚLTIMO fragmento que terminara - "Recodificar"
            # solo terminaba aplicándose a ese, el resto quedaba sin recodificar (ver
            # conversación).
            task_data["_frag_idx"] = idx
            for row in self._resolve_target_rows(data, task_data):
                row.set_fragment_progress(idx, total, phase)
            if self.tab.taskbar_manager:
                self.tab.taskbar_manager.set_state("indeterminate")
            return

        if data.get("status") == "downloading":
            # Mientras el ítem tenga fragmentos, el % numérico crudo de yt-dlp no
            # representa el avance real (se dispara una vez por fragmento) - la barra
            # de la fila queda a cargo de fragment_progress en ese caso. Esto NO debe
            # aplicarse también a "finished" (ver más abajo): antes se descartaba con
            # el mismo guard, y como consecuencia row.downloaded_filepath/
            # last_downloaded_filepath nunca se llenaban para un corte de fragmento -
            # "Recodificar" no tenía ningún archivo real que recodificar y no hacía
            # nada después de descargar (ver conversación).
            if has_fragments:
                return
            from core.ytdlp_logic.analyzer import strip_ansi_codes
            p_str = strip_ansi_codes(data.get("_percent_str", "0%")).replace("%", "").strip()
            try:
                val = float(p_str)
            except Exception:
                val = 0
            speed = strip_ansi_codes(data.get("_speed_str", "")).strip() or "..."
            eta = strip_ansi_codes(data.get("_eta_str", "")).strip() or "..."

            for row in self._resolve_target_rows(data, task_data):
                row.update_progress(
                    val,
                    info=f"{speed} - ETA: {eta}",
                    status=self.tr("Descargando") if hasattr(self, "tr") else "Descargando",
                )
                info = data.get("info_dict")
                if info:
                    row.update_metadata_from_dict(info)

        elif data.get("status") == "finished":
            # A diferencia de "downloading", este evento SÍ hay que procesarlo aunque
            # haya fragmentos - es la única fuente del nombre real del archivo de
            # salida (yt-dlp lo reporta igual con el corte, un evento por fragmento).
            filepath = data.get("filename")
            if filepath:
                self.last_downloaded_filepath = filepath
            for row in self._resolve_target_rows(data, task_data):
                if not has_fragments:
                    row.update_progress(100, status=self.tr("Procesando") if hasattr(self, "tr") else "Procesando")
                if filepath:
                    row.downloaded_filepath = filepath
                info = data.get("info_dict")
                if info:
                    row.update_metadata_from_dict(info)

    def _resolve_target_rows(self, data, task_data):
        """
        Devuelve las filas de item_rows a las que corresponde este evento de progreso.
        Dos casos comparten una misma tarea/worker con más de una fila:

        - Playlist: yt-dlp reporta el 'playlist_index' de CADA entrada en su propio
          info_dict.
        - Corte con más de un fragmento (ver open_cut_dialog_and_download, que crea una
          fila por fragmento): los eventos "downloading"/"finished" de un fragmento no
          traen ningún índice propio en info_dict - se usa el último fragment_index visto
          en fragment_progress (guardado en task_data['_frag_idx'], ver más arriba en
          este método).

        En ambos casos, item_keys guarda ese mismo índice por fila (ver
        ActivityPanel.add_activity_rows) para poder enrutar el evento a la fila correcta,
        en vez de aplicarlo ciegamente a todas, que pisaba el archivo/estado de cada fila
        con los de la última entrada/fragmento visto (y por eso antes no se podía
        recodificar cada ítem de playlist, ni cada fragmento de un corte múltiple, por
        separado - ver conversación). Con una sola fila (descarga directa, corte de UN
        fragmento, o playlist de 1 ítem) no hace falta desambiguar.
        """
        rows = task_data["item_rows"]
        if len(rows) <= 1:
            return rows
        info = data.get("info_dict") or {}
        key = info.get("playlist_index")
        if key is None:
            key = info.get("playlist_autonumber")
        if key is None:
            key = task_data.get("_frag_idx")
        if key is None:
            return rows
        keys = task_data.get("item_keys") or []
        for row, row_key in zip(rows, keys):
            if row_key == key:
                return [row]
        return rows

    def _on_task_finished(self, success, message, task_data):
        self._batch_completed += 1

        if task_data in self.active_workers:
            self.active_workers.remove(task_data)

        if task_data.get("worker"):
            task_data["worker"].deleteLater()

        from core.services.editor_integration_manager import EditorIntegrationManager
        editor_mgr = EditorIntegrationManager.get_instance()

        request_data = task_data["request_data"]
        recode_requested = bool(request_data.get("recode_enabled"))
        is_single_row = len(task_data["item_rows"]) == 1

        for row in task_data["item_rows"]:
            if success:
                actual_path = None
                if hasattr(row, 'downloaded_filepath') and row.downloaded_filepath:
                    actual_path = self._find_actual_downloaded_file(row.downloaded_filepath)
                # self.last_downloaded_filepath es un rastro GLOBAL (última descarga de
                # cualquier tarea/fila) - solo sirve de respaldo cuando la tarea tiene una
                # sola fila. Con una playlist (varias filas por tarea, ver
                # _resolve_target_rows) usarlo acá terminaría recodificando o marcando
                # "Completado" con el archivo de OTRA fila si esta nunca recibió su
                # propio evento "finished" (p. ej. un ítem fallido con
                # ignoreerrors='only_download', ver downloader_master.py).
                if not actual_path and is_single_row and self.last_downloaded_filepath:
                    actual_path = self._find_actual_downloaded_file(self.last_downloaded_filepath)

                if not actual_path and not is_single_row:
                    # Ítem de playlist que nunca recibió su propio evento "finished" (p.
                    # ej. falló individualmente con ignoreerrors='only_download' - la
                    # tarea completa igual reporta éxito, pero ESTA fila no tiene un
                    # archivo real que recodificar ni marcar como completado).
                    row.update_progress(0, status=self.tr("Error") if hasattr(self, "tr") else "Error")
                    row.mark_error()
                    continue

                if recode_requested and self._start_post_download_recode(
                    actual_path, request_data, row, row.original_title or request_data.get("title")
                ):
                    # El estado "Completado"/envío al editor lo resuelve
                    # _on_recode_job_status una vez termine la recodificación.
                    continue

                row.update_progress(100, status=self.tr("Completado") if hasattr(self, "tr") else "Completado")
                row.mark_completed(filepath=actual_path or getattr(row, 'downloaded_filepath', None))

                if editor_mgr and editor_mgr.is_auto_send_enabled and hasattr(row, 'downloaded_filepath') and row.downloaded_filepath:
                    editor_mgr.process_raw_download(actual_path or row.downloaded_filepath, request_data)
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

    def _start_post_download_recode(self, actual_path, request_data, row, title):
        """
        Encola un job RECODE async para el archivo que acaba de bajar esta fila.
        Contraparte de AdvancedProcessTab.DownloadController._start_post_download_recode
        (modo SOLO) pero reflejando el progreso en la fila de activity_panel en vez de
        en output_options. Devuelve True si el job quedó encolado (la fila queda a
        cargo de _on_recode_job_progress/_status), False si no se pudo iniciar - en
        ese caso el llamador debe resolver el estado "Completado" normalmente.
        """
        if not actual_path or not os.path.exists(actual_path) or os.path.isdir(actual_path):
            logger.warning(f"QuickModeTab: No se encontró el archivo descargado para recodificar ({title}).")
            return False

        from core.utils.preset_manager import build_recode_output_path
        from core.utils.file_conflict_manager import quarantine_for_recode

        preset_name = request_data.get("recode_preset_name")
        prefix = request_data.get("recode_filename_prefix") or ""
        suffix = request_data.get("recode_filename_suffix") or ""
        settings, out_file = build_recode_output_path(
            actual_path, "video_tools/avanzado", preset_name, prefix=prefix, suffix=suffix
        )
        if not settings:
            logger.warning(f"QuickModeTab: Preset de recodificación '{preset_name}' no encontrado, se omite ({title}).")
            return False

        try:
            backup_path = quarantine_for_recode(actual_path)
        except Exception as e:
            logger.error(f"QuickModeTab: No se pudo poner en cuarentena '{actual_path}': {e}")
            return False

        recode_job_id = self.queue_mgr.add_job({
            "input_path": backup_path,
            "output_path": out_file,
            "settings": settings,
            "duration_sec": 0.0,
            "title": f"Recode: {title}",
        }, "RECODE")

        self._recode_by_download[recode_job_id] = row
        self._recode_state[recode_job_id] = {
            "backup_path": backup_path,
            "keep_original": request_data.get("recode_keep_original", True),
            "request_data": dict(request_data),
            "title": title,
        }

        row.update_progress(0, info="", status=self.tr("Recodificando..."))
        # La cola global nace pausada y solo se reanuda desde Proceso Avanzado (modo
        # LOTES) o Herramientas Multimedia (ver video_tools_view.py) - sin esto, un job
        # RECODE encolado desde Modo Rápido se queda esperando indefinidamente si el
        # usuario nunca tocó esas otras pestañas.
        self.queue_mgr.start_queue()
        return True

    def _on_recode_job_progress(self, job_id, percent, speed, eta):
        row = self._recode_by_download.get(job_id)
        if row is None:
            return
        info = f"{speed} | {eta}" if speed and eta else (speed or eta or "")
        row.update_progress(percent, info=info, status=self.tr("Recodificando..."))

    def _on_recode_job_status(self, job_id, status):
        if job_id not in self._recode_by_download:
            return
        if status not in ("COMPLETED", "FAILED", "CANCELLED"):
            return  # estado intermedio (RUNNING, etc.) - nada que resolver todavía

        row = self._recode_by_download.pop(job_id)
        state = self._recode_state.pop(job_id, {})
        backup_path = state.get("backup_path")
        keep_original = state.get("keep_original", True)
        request_data = state.get("request_data") or {}
        title = state.get("title", "")
        recode_job = self.queue_mgr.get_job(job_id)

        from core.utils.file_conflict_manager import commit_backup, rollback_backup, BACKUP_SUFFIX

        final_path = None
        if status == "COMPLETED":
            # Éxito: la casilla "Mantener medios originales" decide qué pasa con el
            # archivo bajado antes de recodificar.
            if keep_original:
                rollback_backup(backup_path)
            else:
                commit_backup(backup_path)
            final_path = recode_job.final_filepath if recode_job else None
            row.update_progress(100, status=self.tr("Completado"))
            row.mark_completed(filepath=final_path)
            logger.info(f"QuickModeTab: Recodificación post-descarga completada ({title}).")
        else:
            # Fallo o cancelación: SIEMPRE se restaura, sin importar "mantener
            # originales" (la casilla nunca causa pérdida de datos ante un error).
            rollback_backup(backup_path)
            if backup_path and backup_path.endswith(BACKUP_SUFFIX):
                final_path = backup_path[: -len(BACKUP_SUFFIX)]
            if status == "FAILED":
                err = recode_job.error_message if recode_job else "desconocido"
                logger.error(f"QuickModeTab: Falló la recodificación post-descarga de '{title}': {err}")
                row.update_progress(0, status=self.tr("Error al recodificar"))
                row.mark_error()
            else:
                row.update_progress(0, status=self.tr("Recodificación cancelada"))
            if final_path:
                row.downloaded_filepath = final_path
                row.mark_completed(filepath=final_path)

        if final_path:
            from core.services.editor_integration_manager import EditorIntegrationManager
            editor_mgr = EditorIntegrationManager.get_instance()
            if editor_mgr and editor_mgr.is_auto_send_enabled:
                actual = self._find_actual_downloaded_file(final_path)
                editor_mgr.process_raw_download(actual or final_path, request_data)

        # El job RECODE interno ya cumplió su propósito - no debe quedar visible ni
        # reintentable en la cola compartida con Proceso Avanzado / Herramientas
        # Multimedia (no es algo que el usuario haya encolado directamente).
        self.queue_mgr.remove_job(job_id)
