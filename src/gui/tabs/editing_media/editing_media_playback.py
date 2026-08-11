# src/gui/tabs/editing_media/editing_media_playback.py
import os
import re
import datetime
import subprocess
import platform
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QImageReader, QImage
from PySide6.QtMultimedia import QMediaPlayer
from core.logger.logger_manager import logger
from gui.tabs.editing_media.editing_media_icons import get_svg_icon, get_colored_svg_icon
from core.tabs.editing_media.editing_media_logic import WaveformExtractorThread

class PlaybackMixin:
    """Mixin que maneja la reproducción de audio, extracción de metadata y waveform."""
    
    def _parse_duration_to_seconds(self, dur_str: str) -> float:
        if not dur_str or dur_str == "-":
            return 0.0
        if isinstance(dur_str, (int, float)):
            return float(dur_str)
        try:
            parts = str(dur_str).split(":")
            if len(parts) == 2:
                return float(parts[0]) * 60 + float(parts[1])
            elif len(parts) == 3:
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        except Exception:
            pass
        return 0.0

    def _on_selection_changed(self, selected, deselected):
        # Usamos media_table.selectionModel() porque es compartido
        indexes = self.media_table.selectionModel().selectedIndexes()
        
        # Filtramos solo columna 0 para evitar conteos duplicados en tabla
        self._selected_indexes = sorted([idx for idx in indexes if idx.column() == 0], key=lambda x: x.row())
        
        if len(self._selected_indexes) > 1:
            self.carousel_nav_widget.setVisible(True)
            
            newly_selected = [idx for idx in selected.indexes() if idx.column() == 0]
            if newly_selected:
                try:
                    self._carousel_index = self._selected_indexes.index(newly_selected[-1])
                except ValueError:
                    if not hasattr(self, "_carousel_index") or self._carousel_index >= len(self._selected_indexes):
                        self._carousel_index = 0
            else:
                if not hasattr(self, "_carousel_index") or self._carousel_index >= len(self._selected_indexes):
                    self._carousel_index = 0
                    
            self._update_carousel_ui()
            self._on_media_clicked(self._selected_indexes[self._carousel_index])
        elif len(self._selected_indexes) == 1:
            self.carousel_nav_widget.setVisible(False)
            self._on_media_clicked(self._selected_indexes[0])
            self._update_send_button_state()
        else:
            self.carousel_nav_widget.setVisible(False)
            # Un reset de modelo (p.ej. "Cargar más", scroll infinito de Freesound, o un
            # refresco tras completar una descarga) vacía la selección de forma transitoria
            # antes de que restore_selection() la recupere; no tratar eso como una deselección
            # real del usuario, o se detendría/reiniciaría la reproducción sin motivo.
            if not getattr(self, "_refreshing_media_list", False):
                self._clear_metadata()
                self._stop_audio_playback()
            self._update_send_button_state()

    def _on_carousel_prev(self):
        if hasattr(self, "_selected_indexes") and len(self._selected_indexes) > 1:
            self._carousel_index = (self._carousel_index - 1) % len(self._selected_indexes)
            self._update_carousel_ui()
            self._on_media_clicked(self._selected_indexes[self._carousel_index])

    def _on_carousel_next(self):
        if hasattr(self, "_selected_indexes") and len(self._selected_indexes) > 1:
            self._carousel_index = (self._carousel_index + 1) % len(self._selected_indexes)
            self._update_carousel_ui()
            self._on_media_clicked(self._selected_indexes[self._carousel_index])

    def _update_carousel_ui(self):
        if hasattr(self, "_selected_indexes") and len(self._selected_indexes) > 1:
            self.lbl_carousel_status.setText(f"{self._carousel_index + 1} de {len(self._selected_indexes)}")
            self._update_send_button_state()

    def _update_send_button_state(self, editor_name=None):
        if not hasattr(self, 'btn_send_editor'):
            return

        if hasattr(self, "_send_editor_state") and self._send_editor_state.is_busy():
            # No pisar el texto animado "Enviando..." mientras hay un envío en curso.
            return

        from core.services.editor_integration_manager import EditorIntegrationManager
        from PySide6.QtGui import QIcon
        from PySide6.QtCore import QSize
        editor_mgr = EditorIntegrationManager.get_instance()
        if not editor_mgr or not editor_mgr.active_editor:
            self.btn_send_editor.setText(self.tr("Ningún editor conectado"))
            self.btn_send_editor.setIcon(QIcon())
            self.btn_send_editor.setEnabled(False)
            return

        active = editor_mgr.active_editor
        if active == "premiere":
            icon = get_svg_icon("premiere pro.svg") 
            name = "Premiere Pro"
        elif active == "aftereffects":
            icon = get_svg_icon("after effects.svg") 
            name = "After Effects"
        elif active == "davinci":
            icon = get_svg_icon("davinci resolve.svg")
            name = "DaVinci Resolve"
        else:
            icon = QIcon()
            name = "Editor"

        count = len(getattr(self, "_selected_indexes", []))
        if count > 1:
            self.btn_send_editor.setText(self.tr(f"Enviar ({count})"))
        else:
            self.btn_send_editor.setText(self.tr(f"Enviar"))
            
        if not icon.isNull():
            self.btn_send_editor.setIcon(icon)
            self.btn_send_editor.setIconSize(QSize(20, 20))
        self.btn_send_editor.setEnabled(True)

    # ── Resolución de alta calidad y construcción de paquetes de envío ──────

    def _resolve_high_quality_path(self, item_data, on_ready, on_error):
        """
        Garantiza que el medio a enviar sea el archivo de alta calidad.
        Si es local (o ya descargado en 'dest_path'), llama on_ready(path) de inmediato.
        Si es remoto y no se ha descargado, fuerza la descarga en alta calidad antes de continuar.
        """
        path = item_data.get("ruta")
        is_remote = bool(path) and (path.startswith("http://") or path.startswith("https://"))

        if not is_remote:
            on_ready(path)
            return

        dest_path = item_data.get("dest_path")
        if dest_path and os.path.exists(dest_path):
            logger.info(f"[EditingMedia] '{item_data.get('nombre', path)}' ya está descargado en alta calidad: {dest_path}")
            on_ready(dest_path)
            return

        logger.info(f"[EditingMedia] '{item_data.get('nombre', path)}' es remoto y no está descargado; forzando descarga en alta calidad antes de enviar.")
        self._start_high_quality_download(item_data, on_success=on_ready, on_error=on_error)

    def _capture_subclip_intent(self, item_data):
        """
        Captura AHORA, de forma síncrona, la selección de subclip para este medio (la selección
        rápida activa en la waveform, o subclips guardados) — ANTES de iniciar cualquier descarga
        en segundo plano. La descarga puede disparar un refresco de la lista que reinicia la
        waveform (y su selección), así que la selección debe quedar fijada antes de esperar nada.
        Devuelve una lista de subclips (posiblemente vacía).
        """
        orig_path = item_data.get("ruta")
        label_base = os.path.splitext(item_data.get("nombre") or os.path.basename(orig_path or "clip"))[0] or "clip"

        lite_subs = []
        if hasattr(self, "waveform_widget") and getattr(self, "current_playing_path", None) == orig_path:
            in_r, out_r = self.waveform_widget.get_lite_selection()
            if in_r is not None and out_r is not None:
                dur_sec = 0
                curr_type = getattr(self, "current_playing_type", "audio")
                if curr_type == "audio" and self.audio_player and self.audio_player.duration() > 0:
                    dur_sec = self.audio_player.duration() / 1000.0
                elif curr_type == "video" and hasattr(self, "preview_box") and self.preview_box.media_player.duration() > 0:
                    dur_sec = self.preview_box.media_player.duration() / 1000.0

                if dur_sec == 0:
                    dur_str = item_data.get("duración", "0")
                    if orig_path in getattr(self, "_metadata_cache", {}):
                        dur_str = self._metadata_cache[orig_path].get("duración", dur_str)
                    dur_sec = self._parse_duration_to_seconds(dur_str)

                if dur_sec > 0:
                    lite_subs = [{
                        "name": f"{label_base}_lite",
                        "in": round(in_r * dur_sec, 3),
                        "out": round(out_r * dur_sec, 3)
                    }]

        if lite_subs:
            return lite_subs
        return list(getattr(self, "_saved_subclips_cache", {}).get(orig_path, []))

    def _build_send_package(self, item_data, local_path, captured_subs=None):
        """Construye el paquete a enviar al editor usando el archivo local ya resuelto en alta calidad."""
        saved_subs = captured_subs if captured_subs is not None else self._capture_subclip_intent(item_data)
        local_path_slash = local_path.replace('\\', '/')

        if saved_subs:
            return {"filePath": local_path_slash, "subclips": saved_subs}

        ext = os.path.splitext(local_path)[1].lower()
        if ext in ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.svg'):
            return {"video": None, "thumbnail": local_path_slash, "subtitle": None}
        elif ext in ('.srt', '.vtt', '.ass', '.sub'):
            return {"video": None, "thumbnail": None, "subtitle": local_path_slash}
        else:
            return {"video": local_path_slash, "thumbnail": None, "subtitle": None}

    def _resolve_items_then_send(self, items, on_done, index=0, resolved=None):
        """Resuelve secuencialmente la ruta en alta calidad de cada medio; al terminar llama on_done(resolved)."""
        if resolved is None:
            resolved = {}
        if index >= len(items):
            on_done(resolved)
            return

        item_data = items[index]
        orig_path = item_data.get("ruta")

        def _continue(local_path):
            resolved[orig_path] = local_path
            self._resolve_items_then_send(items, on_done, index + 1, resolved)

        def _continue_error(err):
            resolved[orig_path] = None
            self._resolve_items_then_send(items, on_done, index + 1, resolved)

        self._resolve_high_quality_path(item_data, on_ready=_continue, on_error=_continue_error)

    def _finalize_batch_send(self, items, resolved, editor_mgr, state, captured_subs=None):
        packages = []
        any_failed = False
        for item_data in items:
            orig_path = item_data.get("ruta")
            local_path = resolved.get(orig_path)
            if not local_path:
                any_failed = True
                continue
            subs = captured_subs.get(orig_path) if captured_subs is not None else None
            packages.append(self._build_send_package(item_data, local_path, captured_subs=subs))

        if not packages:
            logger.error("[EditingMedia] Envío cancelado: no se pudo resolver ningún medio en alta calidad.")
            state.finish(False, "Error")
            return

        ok = False
        try:
            if len(packages) == 1:
                pkg = packages[0]
                if "subclips" in pkg:
                    logger.info(f"[EditingMedia] Enviando 1 medio en alta calidad con {len(pkg['subclips'])} subclips a {editor_mgr.active_editor}")
                    ok = editor_mgr.send_subclips(pkg)
                else:
                    logger.info(f"[EditingMedia] Enviando 1 medio en alta calidad al editor activo: {pkg}")
                    ok = editor_mgr.send_file(pkg)
            else:
                logger.info(f"[EditingMedia] Enviando lote de {len(packages)} medios en alta calidad al editor activo.")
                ok = editor_mgr.send_batch(packages)
        except Exception as e:
            logger.error(f"[EditingMedia] Excepción enviando al editor: {e}")
            ok = False

        if any_failed:
            logger.error("[EditingMedia] Uno o más medios no pudieron descargarse en alta calidad y fueron omitidos del envío.")

        success = bool(ok) and not any_failed
        state.finish(success, "Éxito" if success else "Error")

    def _on_send_editor_clicked(self):
        selected_indexes = getattr(self, "_selected_indexes", [])
        if not selected_indexes:
            return

        from core.services.editor_integration_manager import EditorIntegrationManager
        editor_mgr = EditorIntegrationManager.get_instance()
        if not editor_mgr:
            return

        items = []
        for idx in selected_indexes:
            item_data = self.media_model.get_item(idx)
            if item_data and item_data.get("ruta"):
                items.append(item_data)

        if not items:
            return

        # Capturar la selección de subclip de cada medio ANTES de iniciar ninguna descarga.
        captured_subs = {item_data.get("ruta"): self._capture_subclip_intent(item_data) for item_data in items}

        logger.info(f"[EditingMedia] Solicitud de envío iniciada para {len(items)} medio(s) seleccionado(s).")
        self._send_editor_state.start("Enviando")

        self._resolve_items_then_send(
            items,
            on_done=lambda resolved: self._finalize_batch_send(items, resolved, editor_mgr, self._send_editor_state, captured_subs)
        )

    def _on_send_editor_single_clicked(self):
        path = getattr(self, "last_selected_media_path", None)
        if not path:
            return

        from core.services.editor_integration_manager import EditorIntegrationManager
        editor_mgr = EditorIntegrationManager.get_instance()
        if not editor_mgr:
            return

        item_data = self._get_current_media_data() if hasattr(self, "_get_current_media_data") else None
        if (not item_data or item_data.get("ruta") != path) and hasattr(self, "media_model"):
            idx = self.media_model.find_item_index_by_path(path)
            if idx and idx.isValid():
                item_data = self.media_model.get_item(idx)
        if not item_data:
            item_data = {"ruta": path, "nombre": os.path.basename(path)}

        # Capturar la selección de subclip ANTES de iniciar ninguna descarga.
        captured_subs = {item_data.get("ruta"): self._capture_subclip_intent(item_data)}

        logger.info(f"[EditingMedia] Solicitud de envío individual iniciada para: {path}")
        self._send_editor_state.start("Enviando")

        self._resolve_items_then_send(
            [item_data],
            on_done=lambda resolved: self._finalize_batch_send([item_data], resolved, editor_mgr, self._send_editor_state, captured_subs)
        )

    def _on_open_subclip_dialog(self):
        path = getattr(self, "last_selected_media_path", None)
        if not path:
            return

        item_data = self._get_current_media_data() if hasattr(self, "_get_current_media_data") else None
        if not item_data:
            return

        self._stop_audio_playback()
        if hasattr(self, "preview_box") and self.preview_box:
            self.preview_box.stop_media()

        media_type = getattr(self, "current_playing_type", "video")
        is_remote = path.startswith("http://") or path.startswith("https://")
        dest_path = item_data.get("dest_path")
        already_high_quality = (not is_remote) or bool(dest_path and os.path.exists(dest_path))

        if already_high_quality:
            local_path = dest_path if (is_remote and dest_path) else path
            if is_remote:
                # Medio ya descargado en alta calidad: extraer metadatos reales del archivo local.
                meta = self._extract_rich_metadata(local_path, media_type)
                dur_sec = self._parse_duration_to_seconds(meta.get("duración", "0"))
                fps_str = meta.get("fps", "30")
            else:
                dur_str = self._metadata_cache.get(local_path, {}).get("duración", "0") if hasattr(self, "_metadata_cache") else "0"
                dur_sec = self._parse_duration_to_seconds(dur_str)
                fps_str = self._metadata_cache.get(local_path, {}).get("fps", "30") if hasattr(self, "_metadata_cache") else "30"
        else:
            # Medio remoto sin descargar: la ventana se abre igual, con estimados,
            # y se actualizará con datos reales cuando termine la descarga en segundo plano.
            local_path = ""
            dur_sec = self._parse_duration_to_seconds(item_data.get("duración", "0"))
            fps_str = "30"

        try:
            fps_val = float(str(fps_str).replace("fps", "").strip())
        except (ValueError, AttributeError):
            fps_val = 30.0
        if dur_sec <= 0:
            dur_sec = 1.0

        if not hasattr(self, "_saved_subclips_cache"):
            self._saved_subclips_cache = {}
        if not hasattr(self, "_saved_subclip_range_cache"):
            self._saved_subclip_range_cache = {}

        existing = self._saved_subclips_cache.get(path, [])
        state_range = self._saved_subclip_range_cache.get(path, (0.0, dur_sec))

        from gui.dialogs.subclip_dialog import SubclipEditorDialog

        logger.info(f"[EditingMedia] Abriendo editor de subclips para '{item_data.get('nombre', path)}' (pendiente de descarga en alta calidad: {not already_high_quality}).")
        dlg = SubclipEditorDialog(
            media_path=local_path,
            media_type=media_type,
            duration_sec=dur_sec,
            fps=fps_val,
            existing_subclips=existing,
            initial_in_sec=state_range[0],
            initial_out_sec=state_range[1],
            pending_download=not already_high_quality,
            display_name=item_data.get("nombre") or os.path.basename(local_path or path),
            parent=self
        )

        if not already_high_quality:
            self._start_high_quality_download(
                item_data,
                on_success=lambda local_p: self._on_subclip_dialog_download_success(dlg, item_data, local_p),
                on_error=lambda err: dlg.set_resolve_error(err)
            )

        dlg.exec()

        self._saved_subclips_cache[path] = dlg.get_subclips()
        self._saved_subclip_range_cache[path] = (dlg.in_sec, dlg.out_sec)

    def _on_subclip_dialog_download_success(self, dlg, item_data, local_path):
        logger.info(f"[EditingMedia] Descarga en alta calidad lista para el editor de subclips: {local_path}")
        dlg.set_resolved_media_path(local_path)

    def _on_media_clicked(self, index):
        if not index or not hasattr(index, "isValid") or not index.isValid():
            return
            
        item_data = self.media_model.get_item(index)

        if not item_data or not isinstance(item_data, dict):
            return

        if item_data.get("tipo") == "load_more":
            # Recordar dónde estaba el scroll para no saltar a un lugar random cuando
            # _update_media_list() reconstruya la lista con más elementos.
            scroll_widget = self.media_table if getattr(self, "view_mode", "grid") == "list" and hasattr(self, "media_table") else self.media_list
            if scroll_widget:
                self._pending_scroll_restore = scroll_widget.verticalScrollBar().value()
            self._max_display_count = getattr(self, "_max_display_count", 500) + 500
            self._update_media_list()
            return


        name = item_data.get("nombre", "Desconocido")
        tipo = item_data.get("tipo", "desconocido")
        path = item_data.get("ruta")

        if not path:
            self._clear_metadata()
            return

        is_remote = path.startswith("http://") or path.startswith("https://")

        # Si este ítem ya está activo/reproduciéndose y esta llamada viene de una re-selección
        # forzada por un refresco de la lista (p.ej. al completarse una descarga en segundo
        # plano), no reiniciar la reproducción ni la waveform: solo refrescar metadatos/botones.
        if getattr(self, "_suppress_next_media_click_reset", False) and path == getattr(self, "current_playing_path", None):
            self._suppress_next_media_click_reset = False
            self.last_selected_media_path = path
            self._refresh_metadata_panel(item_data, name, tipo, path, is_remote)
            return
        self._suppress_next_media_click_reset = False

        self.last_selected_media_path = path

        # Asegurar metadatos para archivos locales (necesitamos la duración exacta)
        if not is_remote and path not in self._metadata_cache:
            self._metadata_cache[path] = self._extract_rich_metadata(path, tipo)

        # Detener cualquier audio previo al cambiar de archivo
        self._stop_audio_playback()

        self.current_playing_path = path
        self.current_playing_type = tipo
        # Selección nueva y genuina del usuario: cualquier pausa explícita anterior ya no aplica.
        self._user_explicitly_paused = False

        # 1. Controlar la visualización del espectro de audio y header de carátula
        if tipo in ("audio", "video"):
            self.audio_panel.setVisible(True)
            self.audio_controls_widget.setVisible(tipo == "audio")
            
            # Header de carátula e información solo para audios
            if hasattr(self, "audio_header_widget"):
                self.audio_header_widget.setVisible(tipo == "audio")
                if tipo == "audio":
                    self.lbl_audio_name.setText(name)
                    dur_str = item_data.get("duración", "-")
                    if not is_remote and path in self._metadata_cache:
                        dur_str = self._metadata_cache[path].get("duración", dur_str)
                    self.lbl_audio_sub.setText(f"AUDIO • {dur_str}")

                    # Cargar carátula incrustada si existe o icono por defecto
                    from core.tabs.editing_media.thumbnail_cache_manager import ThumbnailCacheManager
                    from gui.styles import get_theme_token
                    from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
                    from PySide6.QtGui import QPixmap

                    accent_color = get_theme_token("acento_primario", "#B9E640")
                    fallback_icon = get_colored_svg_icon("music_note.svg", accent_color, size=32)

                    thumb_path = ThumbnailCacheManager.get_instance().get_cached_thumbnail_path(path)
                    if thumb_path and os.path.exists(thumb_path):
                        pix = QPixmap(thumb_path).scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        self.lbl_cover_art.setPixmap(pix)
                    else:
                        self.lbl_cover_art.setPixmap(fallback_icon.pixmap(32, 32))
                        if not is_remote:
                            ThumbnailCacheManager.get_instance().request_thumbnail(path, "audio")

            self.waveform_widget.set_video_only(False)
            self.waveform_widget.set_audio_path(path)
            self.waveform_widget.set_playback_ratio(0.0)
            
            # Detener hilo de extracción previo si estuviera corriendo
            if hasattr(self, "waveform_thread") and self.waveform_thread and self.waveform_thread.isRunning():
                self.waveform_thread.stop()
                self.waveform_thread.wait()

            if hasattr(self, "remote_waveform_thread") and self.remote_waveform_thread and self.remote_waveform_thread.isRunning():
                try:
                    self.remote_waveform_thread.finished.disconnect()
                except Exception:
                    pass
                
            # Usar una cantidad constante de picos
            num_peaks = 120
            
            # Activar el estado de carga y animación en el widget
            self.waveform_widget.set_loading(True)

            # Si es remoto y tiene imágenes del waveform, usarlas
            if is_remote and "images" in item_data and item_data["images"].get("waveform_m"):
                waveform_url = item_data["images"]["waveform_m"]
                from core.tabs.editing_media.freesound_preview_cache import FreesoundPreviewCacheManager
                fs_cache = FreesoundPreviewCacheManager.get_instance()
                
                cached_peaks = fs_cache.get_cached_waveform_peaks(waveform_url)
                if cached_peaks:
                    # HIT: Renderizado instantáneo a 0ms de la forma de onda descompuesta
                    self.waveform_widget.set_peaks(cached_peaks)
                else:
                    # MISS: Extraer picos en segundo plano y guardar en caché LRU de 10 elementos
                    from core.tabs.editing_media.editing_media_logic import RemoteWaveformLoaderThread
                    
                    self.remote_waveform_thread = RemoteWaveformLoaderThread(waveform_url, num_peaks, self)
                    
                    def _on_remote_waveform_finished(peaks, target_url=waveform_url, req_path=path):
                        if peaks:
                            fs_cache.cache_waveform_peaks(target_url, peaks)
                        if getattr(self, "active_remote_audio_url", None) == req_path:
                            self.waveform_widget.set_peaks(peaks)

                    self.remote_waveform_thread.finished.connect(_on_remote_waveform_finished)
                    self.remote_waveform_thread.start()

            else:
                # Obtener duración en segundos para el muestreo progresivo (usado solo si se extrae con Thread heredado)
                dur_str = item_data.get("duración", "-")
                if not is_remote:
                    dur_str = self._metadata_cache[path].get("duración", "-")
                if dur_str == "-":
                    dur_str = self.controller.get_media_duration_for_file(path)
                
                # Iniciar extracción y renderizado mediante caché global
                from core.tabs.editing_media.waveform_cache_manager import WaveformCacheManager
                wf_mgr = WaveformCacheManager.get_instance()
                
                if not getattr(self, "_waveform_cache_connected", False):
                    wf_mgr.waveform_loaded.connect(self._on_local_waveform_loaded)
                    self._waveform_cache_connected = True
                
                cached_peaks = wf_mgr.get_cached_peaks(path)
                if cached_peaks is not None:
                    # HIT: Renderizado instantáneo
                    self.waveform_widget.set_peaks(cached_peaks)
                    if tipo == "video":
                        self._on_video_waveform_ready(cached_peaks)
                else:
                    # MISS: Extracción asíncrona optimizada
                    wf_mgr.request_waveform(path, num_peaks)

            # Controles de reproducción de audio solo para archivos de audio puros
            if tipo == "audio" and self.audio_player:
                try:
                    if is_remote:
                        from core.tabs.editing_media.freesound_preview_cache import FreesoundPreviewCacheManager
                        fs_cache = FreesoundPreviewCacheManager.get_instance()

                        if not getattr(self, "_freesound_cache_connected", False):
                            fs_cache.preview_ready.connect(self._on_freesound_preview_ready)
                            self._freesound_cache_connected = True

                        self.active_remote_audio_url = path
                        cached_local_path = fs_cache.get_cached_path(path)

                        if cached_local_path and os.path.exists(cached_local_path):
                            # HIT: Reproducción instantánea directa desde disco local
                            self.audio_player.setSource(QUrl.fromLocalFile(cached_local_path))
                            loops = QMediaPlayer.Infinite if getattr(self, "_audio_loop_active", False) else 1
                            self.audio_player.setLoops(loops)
                            self.audio_player.play()
                            from gui.styles import apply_player_play_button_style
                            apply_player_play_button_style(self.btn_play, is_playing=True, icon_size=14)
                        else:
                            # MISS: Solicitar descarga rápida a la caché LRU (reproducción limpia tras ~100ms sin streaming)
                            self.audio_player.stop()
                            self.audio_player.setSource(QUrl())
                            fs_cache.request_preview(path)
                            from gui.styles import apply_player_play_button_style
                            apply_player_play_button_style(self.btn_play, is_playing=True, icon_size=14)

                        self.lbl_time.setText("00:00:00.000 / 00:00:00.000")
                    else:
                        self.audio_player.setSource(QUrl.fromLocalFile(path))
                        self.lbl_time.setText("00:00:00.000 / 00:00:00.000")
                        loops = QMediaPlayer.Infinite if getattr(self, "_audio_loop_active", False) else 1
                        self.audio_player.setLoops(loops)

                        self.audio_player.play()
                        from gui.styles import apply_player_play_button_style
                        apply_player_play_button_style(self.btn_play, is_playing=True, icon_size=14)

                    if is_remote:
                        self._prefetch_next_freesound_item(index)
                except Exception as e:
                    logger.error(f"EditingMediaTab: Error cargando fuente de audio: {e}")



        else:
            self.audio_panel.setVisible(False)

        # 2. Actualizar Vista Previa (Columna Derecha - Superior)
        if tipo == "imagen":
            self.preview_box.setVisible(True)
            self.preview_box.show_image_preview(path)
        elif tipo == "video":
            self.preview_box.setVisible(True)
            self.preview_box.show_video_preview(path)
        elif tipo == "audio":
            # Para audios ocultamos el cuadro superior inútil de video
            self.preview_box.stop_media()
            self.preview_box.setVisible(False)

        self._refresh_metadata_panel(item_data, name, tipo, path, is_remote)

    def _refresh_metadata_panel(self, item_data, name, tipo, path, is_remote):
        # 3. Actualizar Detalles e Info Técnica (Columna Derecha - Inferior)
        self.metadata_labels["nombre"].setText(name)
        self.metadata_labels["ruta"].setText(path)
        self.metadata_labels["tipo"].setText(tipo.upper())
        self.metadata_labels["tamaño"].setText(item_data.get("tamaño", "-"))

        # Ocultar/mostrar botones según tipo local/online y existencia en disco
        dest_path = item_data.get("dest_path")
        dest_exists = bool(dest_path and os.path.exists(dest_path))

        self.btn_reveal.setVisible(not is_remote or dest_exists)
        self.btn_reveal.setEnabled(not is_remote or dest_exists)
        
        if hasattr(self, "combo_tags"):
            self.combo_tags.setVisible(is_remote and not dest_exists)
            if is_remote and hasattr(self, "load_labels"):
                self.load_labels()
                sel_label = item_data.get("selected_label")
                if not sel_label and getattr(self, "last_selected_web_label", None):
                    sel_label = self.last_selected_web_label
                    item_data["selected_label"] = sel_label

                idx = self.combo_tags.findText(sel_label) if sel_label else 0
                self.combo_tags.blockSignals(True)
                self.combo_tags.setCurrentIndex(idx if idx >= 0 else 0)
                self.combo_tags.blockSignals(False)



        if is_remote and dest_exists:
            self.btn_download.setVisible(True)
            self.btn_download.setEnabled(False)
            self.btn_download.setText(self.tr("En Disco"))
        else:
            self.btn_download.setVisible(is_remote)
            self.btn_download.setEnabled(is_remote)
            self.btn_download.setText(self.tr("Descargar Medio"))


        if is_remote:
            license_url = item_data.get("license", "-")
            url_lower = license_url.lower()
            
            # Construir texto TASL
            title = item_data.get("nombre", "Sonido")
            author = item_data.get("username", "Autor Desconocido")
            item_id = item_data.get("id", "")
            source_url = item_data.get("url") or (f"https://freesound.org/s/{item_id}/" if item_id else "https://freesound.org")
            author_url = f"https://freesound.org/people/{author}/" if author != "Autor Desconocido" else ""
            
            if "zero" in url_lower or "cc0" in url_lower:
                lic_title = self.tr("Dominio Público (CC0)")
                lic_desc = self.tr("Puedes usar este sonido para cualquier propósito (incluso comercial) sin necesidad de dar créditos.")
                lic_color = "#1DC038" # Green
                tasl = ""
                icon_name = "check_circle.svg"
            elif "by-nc" in url_lower:
                lic_title = self.tr("Uso No Comercial (CC-BY-NC)")
                lic_desc = self.tr("No puedes usar este sonido en videos monetizados o proyectos comerciales. Es obligatorio dar crédito al autor.")
                lic_color = "#E67E22" # Orange
                cc_url = "https://creativecommons.org/licenses/by-nc/4.0/"
                tasl = self.tr('"{title}" por {author} ({author_url}) obtenida de {source_url} está licenciada bajo CC-BY-NC ({cc_url})').format(
                    title=title, author=author, author_url=author_url, source_url=source_url, cc_url=cc_url
                )
                icon_name = "warning.svg"
            elif "by" in url_lower:
                lic_title = self.tr("Requiere Atribución (CC-BY)")
                lic_desc = self.tr("Uso comercial permitido, pero es obligatorio dar crédito al autor copiando el texto TASL.")
                lic_color = "#40A9E6" # Blue
                cc_url = "https://creativecommons.org/licenses/by/4.0/"
                tasl = self.tr('"{title}" por {author} ({author_url}) obtenida de {source_url} está licenciada bajo CC-BY ({cc_url})').format(
                    title=title, author=author, author_url=author_url, source_url=source_url, cc_url=cc_url
                )
                icon_name = "attribution.svg"
            else:
                lic_title = self.tr("Licencia Desconocida")
                lic_desc = self.tr("Revisa la licencia original antes de usar este sonido.")
                lic_color = "#A6ADC8" # Gray
                tasl = ""
                icon_name = "error.svg"
                
            self.set_license_info(lic_title, lic_desc, lic_color, tasl, icon_name)
            
            self.metadata_header_labels["video_codec"].setText(self.tr("Usuario:"))
            self.metadata_header_labels["video_profile"].setText(self.tr("Licencia:"))
            self.metadata_header_labels["aspecto"].setText(self.tr("Estadísticas:"))
            
            self.metadata_labels["creado"].setText("-")
            self.metadata_labels["modificado"].setText("-")
            self.metadata_labels["duración"].setText(item_data.get("duración", "-"))
            self.metadata_labels["resolución"].setText("-")
            self.metadata_labels["video_codec"].setText(item_data.get("username", "-"))
            self.metadata_labels["video_profile"].setText(item_data.get("license", "-"))
            self.metadata_labels["fps"].setText("-")
            self.metadata_labels["aspecto"].setText(f"Rating: {item_data.get('avg_rating', '-')} | Descargas: {item_data.get('num_downloads', '-')}")
            self.metadata_labels["bitrate_video"].setText("-")
            self.metadata_labels["color"].setText("-")
            self.metadata_labels["audio_codec"].setText("REMOTO (Freesound)")
            self.metadata_labels["samplerate"].setText("-")
            self.metadata_labels["canales"].setText("-")
            self.metadata_labels["bitrate_audio"].setText("-")
        else:
            self.license_panel.setVisible(False)
            self.metadata_header_labels["video_codec"].setText(self.tr("Códec Video:"))
            self.metadata_header_labels["video_profile"].setText(self.tr("Perfil Video:"))
            self.metadata_header_labels["aspecto"].setText(self.tr("Rel. Aspecto:"))
            
            # Obtener metadatos ricos de la cache o extraerlos
            if path not in self._metadata_cache:
                self._metadata_cache[path] = self._extract_rich_metadata(path, tipo)
                
            rich_meta = self._metadata_cache[path]
            
            # Llenar todos los campos en la UI
            self.metadata_labels["creado"].setText(rich_meta.get("creado", "-"))
            self.metadata_labels["modificado"].setText(rich_meta.get("modificado", "-"))
            self.metadata_labels["duración"].setText(rich_meta.get("duración", "-"))
            self.metadata_labels["resolución"].setText(rich_meta.get("resolución", "-"))
            self.metadata_labels["video_codec"].setText(rich_meta.get("video_codec", "-"))
            self.metadata_labels["video_profile"].setText(rich_meta.get("video_profile", "-"))
            self.metadata_labels["fps"].setText(rich_meta.get("fps", "-"))
            self.metadata_labels["aspecto"].setText(rich_meta.get("aspecto", "-"))
            self.metadata_labels["bitrate_video"].setText(rich_meta.get("bitrate_video", "-"))
            self.metadata_labels["color"].setText(rich_meta.get("color", "-"))
            self.metadata_labels["audio_codec"].setText(rich_meta.get("audio_codec", "-"))
            self.metadata_labels["samplerate"].setText(rich_meta.get("samplerate", "-"))
            self.metadata_labels["canales"].setText(rich_meta.get("canales", "-"))
            self.metadata_labels["bitrate_audio"].setText(rich_meta.get("bitrate_audio", "-"))

    def _on_video_waveform_ready(self, peaks: list):
        """Callback para el waveform de videos: muestra los peaks si hay audio, dibuja la regla si no."""
        if peaks:
            self.waveform_widget.set_video_only(False)
            self.waveform_widget.set_peaks(peaks)
            self.audio_panel.setVisible(True)
        else:
            # El video no tiene pista de audio — dibujar la regla de tiempo en su lugar
            path = getattr(self, "current_playing_path", "")
            dur_sec = 1.0
            fps = 30.0
            if path and hasattr(self, "_metadata_cache") and path in self._metadata_cache:
                meta = self._metadata_cache[path]
                dur_str = meta.get("duración", "0")
                dur_sec = self._parse_duration_to_seconds(dur_str)
                if dur_sec <= 0: dur_sec = 1.0
                fps_str = str(meta.get("fps", "30")).replace(" fps", "")
                try:
                    fps = float(fps_str)
                except:
                    pass
            
            self.waveform_widget.set_video_only(True, duration=dur_sec, fps=fps)
            self.audio_panel.setVisible(True)

    def _extract_rich_metadata(self, path: str, tipo: str) -> dict:
        from core.tabs.editing_media.ffprobe_metadata_manager import FFprobeMetadataManager
        return FFprobeMetadataManager.get_instance().get_metadata_instant(path, tipo)

    def _on_async_metadata_ready(self, path: str, meta: dict):
        """Callback cuando la extracción de ffprobe en segundo plano finaliza."""
        if not hasattr(self, "_metadata_cache"):
            self._metadata_cache = {}
        self._metadata_cache[path] = meta
        
        # Actualizar el item en el modelo
        if hasattr(self, "media_model"):
            idx = self.media_model.find_item_index_by_path(path)
            if idx.isValid():
                item = self.media_model.get_item(idx)
                if item:
                    item["duración"] = meta.get("duración", "-")
                    tipo = item.get("tipo", "")
                    
                    # Guardar resolución (útil para imágenes y videos)
                    if meta.get("resolución") and meta.get("resolución") != "-":
                        item["resolución"] = meta.get("resolución")
                    
                    if tipo == "video":
                        res = meta.get("resolución", "")
                        res = res if res != "-" else ""
                        
                        fps = str(meta.get("fps", "")).replace(" fps", "").replace("fps", "").strip()
                        fps_str = f" | {fps} fps" if fps and fps != "-" else ""
                        
                        codec = meta.get("video_codec", "")
                        codec_str = f" | {codec}" if codec and codec != "-" else ""
                        
                        item["detalles_video"] = f"{res}{fps_str}{codec_str}".strip(" |")
                        
                    elif tipo == "audio":
                        sr = meta.get("samplerate", "")
                        sr = sr if sr != "-" else ""
                        
                        ch = meta.get("canales", "")
                        ch_str = f" | {ch}" if ch and ch != "-" else ""
                        
                        br = meta.get("bitrate_audio", "")
                        br_str = f" | {br}" if br and br != "-" else ""
                        
                        codec_audio = meta.get("audio_codec", "")
                        codec_audio_str = f" | {codec_audio}" if codec_audio and codec_audio != "-" else ""
                        
                        item["detalles_audio"] = f"{sr}{ch_str}{br_str}{codec_audio_str}".strip(" |")
                    
                    self.media_model.dataChanged.emit(
                        self.media_model.index(idx.row(), 0), 
                        self.media_model.index(idx.row(), self.media_model.columnCount() - 1)
                    )


        # Si el archivo procesado es el que se está mostrando actualmente en la UI, actualizar panel
        if getattr(self, "current_playing_path", None) == path:
            if hasattr(self, "metadata_labels"):
                self.metadata_labels["creado"].setText(meta.get("creado", "-"))
                self.metadata_labels["modificado"].setText(meta.get("modificado", "-"))
                self.metadata_labels["duración"].setText(meta.get("duración", "-"))
                self.metadata_labels["resolución"].setText(meta.get("resolución", "-"))
                self.metadata_labels["video_codec"].setText(meta.get("video_codec", "-"))
                self.metadata_labels["video_profile"].setText(meta.get("video_profile", "-"))
                self.metadata_labels["fps"].setText(meta.get("fps", "-"))
                self.metadata_labels["aspecto"].setText(meta.get("aspecto", "-"))
                self.metadata_labels["bitrate_video"].setText(meta.get("bitrate_video", "-"))
                self.metadata_labels["color"].setText(meta.get("color", "-"))
                self.metadata_labels["audio_codec"].setText(meta.get("audio_codec", "-"))
                self.metadata_labels["samplerate"].setText(meta.get("samplerate", "-"))
                self.metadata_labels["canales"].setText(meta.get("canales", "-"))
                self.metadata_labels["bitrate_audio"].setText(meta.get("bitrate_audio", "-"))

            if getattr(self, "current_playing_type", None) == "audio" and hasattr(self, "lbl_audio_sub"):
                dur_str = meta.get("duración", "-")
                self.lbl_audio_sub.setText(f"AUDIO • {dur_str}")


    # ── Métodos de Control para el Reproductor de Audio Central ─────────────
    def _on_play_clicked(self):
        from gui.styles import apply_player_play_button_style
        if not self.audio_player:
            return
        
        state = self.audio_player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.audio_player.pause()
            # Recordar que el usuario pausó explícitamente, para que una descarga en curso
            # (p.ej. la previa de Freesound aún cargando en la caché LRU) no la reanude sola
            # al terminar.
            self._user_explicitly_paused = True
            apply_player_play_button_style(self.btn_play, is_playing=False, icon_size=14)
        else:
            self.audio_player.play()
            self._user_explicitly_paused = False
            apply_player_play_button_style(self.btn_play, is_playing=True, icon_size=14)

    def _on_volume_changed(self, value):
        float_val = value if isinstance(value, float) else value / 100.0
        if self.audio_output:
            self.audio_output.setVolume(float_val)

    def _on_waveform_seek_requested(self, ratio):
        item_data = self._get_current_media_data() if hasattr(self, "_get_current_media_data") else None
        tipo = item_data.get("tipo") if item_data else None

        if tipo == "video":
            if self.preview_box and self.preview_box.media_player and self.preview_box.media_player.duration() > 0:
                pos = int(self.preview_box.media_player.duration() * ratio)
                self.preview_box.media_player.setPosition(pos)
        else:
            if self.audio_player and self.audio_player.duration() > 0:
                pos = int(self.audio_player.duration() * ratio)
                self.audio_player.setPosition(pos)

    def _on_video_position_changed(self, position):
        if not self.preview_box or not self.preview_box.media_player:
            return
        item_data = self._get_current_media_data() if hasattr(self, "_get_current_media_data") else None
        if item_data and item_data.get("tipo") == "video":
            duration = self.preview_box.media_player.duration()
            if duration > 0:
                ratio = position / duration
                self.waveform_widget.set_playback_ratio(ratio)

    def _format_time_ms(self, ms: int) -> str:
        """Formatea milisegundos a HH:MM:SS.mmm (estándar de edición de video)."""
        if not ms or ms < 0:
            ms = 0
        ms = int(ms)
        s, ms_r = divmod(ms, 1000)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}.{ms_r:03d}"

    def _on_audio_position_changed(self, position):
        if not self.audio_player:
            return
        duration = self.audio_player.duration()
        if duration > 0:
            ratio = position / duration
            self.waveform_widget.set_playback_ratio(ratio)
            self.lbl_time.setText(f"{self._format_time_ms(position)} / {self._format_time_ms(duration)}")

    def _on_audio_duration_changed(self, duration):
        if self.audio_player:
            pos = self.audio_player.position()
            self.lbl_time.setText(f"{self._format_time_ms(pos)} / {self._format_time_ms(duration)}")

    def _on_freesound_preview_ready(self, url: str, local_path: str):
        """Maneja la finalización de la descarga rápida en caché LRU."""
        if getattr(self, "active_remote_audio_url", None) == url:
            if local_path and os.path.exists(local_path):
                self.audio_player.setSource(QUrl.fromLocalFile(local_path))
                loops = QMediaPlayer.Infinite if getattr(self, "_audio_loop_active", False) else 1
                self.audio_player.setLoops(loops)
                from gui.styles import apply_player_play_button_style
                # Si el usuario pausó explícitamente mientras esta previa terminaba de
                # descargarse en segundo plano, respetar esa pausa en vez de arrancar solo.
                if getattr(self, "_user_explicitly_paused", False):
                    apply_player_play_button_style(self.btn_play, is_playing=False, icon_size=14)
                else:
                    self.audio_player.play()
                    apply_player_play_button_style(self.btn_play, is_playing=True, icon_size=14)
            else:
                logger.error(f"PlaybackMixin: Error al descargar previa de Freesound para {url}")
                
    def _on_local_waveform_loaded(self, file_path: str, peaks: list):
        """Maneja la recepción de picos de audio de la caché para archivos locales."""
        if self.waveform_widget.audio_path == file_path:
            item_data = self._get_current_media_data()
            tipo = item_data.get("tipo") if item_data else None
            
            if tipo == "video":
                self._on_video_waveform_ready(peaks)
            else:
                self.waveform_widget.set_peaks(peaks)
                
    def _prefetch_next_freesound_item(self, current_index):
        """Pre-carga de forma transparente únicamente el archivo de audio N+1 (siguiente fila) y su forma de onda."""
        if not current_index or not current_index.isValid():
            return
            
        next_row = current_index.row() + 1
        if next_row < self.media_model.rowCount():
            next_data = self.media_model.get_item_by_row(next_row)
            if next_data and next_data.get("tipo") == "audio":
                next_path = next_data.get("ruta", "")
                if next_path.startswith("http://") or next_path.startswith("https://"):
                    from core.tabs.editing_media.freesound_preview_cache import FreesoundPreviewCacheManager
                    fs_cache = FreesoundPreviewCacheManager.get_instance()
                    # Pre-cargar audio N+1 en la caché LRU de 10 elementos
                    fs_cache.request_preview(next_path)

                    # Pre-cargar forma de onda N+1 si está disponible
                    if "images" in next_data and next_data["images"].get("waveform_m"):
                        wf_url = next_data["images"]["waveform_m"]
                        if not fs_cache.get_cached_waveform_peaks(wf_url):
                            from core.tabs.editing_media.editing_media_logic import RemoteWaveformLoaderThread
                            w_width = self.waveform_widget.width()
                            num_peaks = max(50, min((w_width - 24) // 5, 180)) if w_width > 50 else 80
                            self._prefetch_wf_thread = RemoteWaveformLoaderThread(wf_url, num_peaks, self)
                            self._prefetch_wf_thread.finished.connect(
                                lambda peaks, u=wf_url: fs_cache.cache_waveform_peaks(u, peaks) if peaks else None
                            )
                            self._prefetch_wf_thread.start()



    def _stop_audio_playback(self):

        from gui.styles import apply_player_play_button_style
        if self.audio_player:
            try:
                self.audio_player.stop()
                apply_player_play_button_style(self.btn_play, is_playing=False, icon_size=14)
            except Exception:
                pass

    def _clear_metadata(self):
        for lbl in self.metadata_labels.values():
            lbl.setText("-")
        self.btn_reveal.setEnabled(False)
        if hasattr(self, "license_panel"):
            self.license_panel.setVisible(False)

    def _on_reveal_clicked(self):
        item_data = self._get_current_media_data() if hasattr(self, "_get_current_media_data") else None
        if item_data:
            path = item_data.get("dest_path") or item_data.get("ruta")
            if path and os.path.exists(path):

                norm_path = os.path.normpath(path)
                sys_os = platform.system().lower()
                try:
                    if sys_os == "windows":
                        subprocess.Popen(['explorer', '/select,', norm_path])
                    elif sys_os == "darwin":
                        subprocess.Popen(['open', '-R', norm_path])
                    else:
                        # Linux: intenta nautilus --select o abre carpeta contenedora
                        try:
                            subprocess.Popen(['nautilus', '--select', norm_path])
                        except Exception:
                            from PySide6.QtGui import QDesktopServices
                            from PySide6.QtCore import QUrl
                            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(norm_path)))
                except Exception as e:
                    logger.error(f"Error al revelar archivo en explorador: {e}")

    def _on_toggle_audio_loop(self):
        """Alterna el modo de repetición del reproductor de audio."""
        from gui.styles import apply_player_loop_button_style

        self._audio_loop_active = not self._audio_loop_active
        if self.audio_player:
            if self._audio_loop_active:
                self.audio_player.setLoops(QMediaPlayer.Infinite)
            else:
                self.audio_player.setLoops(1)
        apply_player_loop_button_style(self.btn_loop_audio, is_active=self._audio_loop_active, icon_size=14)
