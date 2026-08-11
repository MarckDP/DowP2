# src/gui/tabs/editing_media/editing_media_freesound.py
import os
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QMessageBox
from core.logger.logger_manager import logger
from gui.tabs.editing_media.editing_media_icons import get_svg_icon

class FreesoundSearchThread(QThread):
    """Hilo secundario para realizar búsquedas en Freesound sin congelar la interfaz."""
    finished_search = Signal(dict)
    error_search = Signal(str)

    def __init__(self, client, query, token, page=1, sort_order=None, duration_min=None, duration_max=None, license_type=None, parent=None):
        super().__init__(parent)
        self.client = client
        self.query = query
        self.token = token
        self.page = page
        self.sort_order = sort_order
        self.duration_min = duration_min
        self.duration_max = duration_max
        self.license_type = license_type

    def run(self):
        try:
            results = self.client.search(
                self.query,
                self.token,
                duration_min=self.duration_min,
                duration_max=self.duration_max,
                license_type=self.license_type,
                sort_order=self.sort_order,
                page=self.page
            )
            self.finished_search.emit(results)
        except Exception as e:
            self.error_search.emit(str(e))

class FreesoundOriginalDownloadThread(QThread):
    """Hilo secundario para descargar el archivo ORIGINAL (no la preview comprimida) de un sonido de Freesound. Requiere OAuth2."""
    progress = Signal(int)
    finished = Signal(bool, str)  # (success, ruta_final_resuelta)
    error = Signal(str)

    def __init__(self, client, sound_id, dest_dir, fallback_name, token, parent=None):
        super().__init__(parent)
        self.client = client
        self.sound_id = sound_id
        self.dest_dir = dest_dir
        self.fallback_name = fallback_name
        self.token = token

    def run(self):
        try:
            resolved_path = self.client.download_original(
                self.sound_id, self.dest_dir, self.fallback_name, self.token,
                progress_callback=self.progress.emit
            )
            self.finished.emit(True, resolved_path)
        except Exception as e:
            self.error.emit(str(e))


class FreesoundMixin:
    """Mixin que maneja la búsqueda y descarga remota de Freesound, así como la autenticación OAuth2."""

    def _resolve_freesound_dest_path(self, item_data: dict) -> str:
        """Calcula la ruta local destino (carpeta de etiqueta seleccionada, o la carpeta de
        descargas por defecto configurada en Ajustes, o ~/Downloads) para un sonido de Freesound."""
        name = item_data["nombre"]
        selected_label_name = item_data.get("selected_label")
        from core.utils.config_manager import get_config
        config = get_config()
        labels = config.get("labels", [])
        matched_label = next((l for l in labels if l.get("name") == selected_label_name), None) if selected_label_name else None

        if matched_label and matched_label.get("path"):
            downloads_dir = matched_label["path"]
        else:
            custom_dir = config.get("default_web_download_dir")
            downloads_dir = custom_dir if custom_dir and os.path.isdir(custom_dir) else os.path.expanduser("~/Downloads")

        os.makedirs(downloads_dir, exist_ok=True)
        clean_name = "".join(c for c in name if c.isalnum() or c in (".", "_", " ", "-")).strip()
        return os.path.join(downloads_dir, clean_name).replace("\\", "/")

    def _start_high_quality_download(self, item_data: dict, on_success, on_error):
        """
        Descarga silenciosamente (sin diálogo modal) el archivo ORIGINAL en alta calidad de un
        sonido remoto de Freesound (vía OAuth2, no la preview comprimida). Llama
        on_success(dest_path) o on_error(mensaje).
        """
        token = getattr(self.controller, "freesound_auth", {}).get("access_token", "")
        if not token:
            msg = "Debes iniciar sesión con Freesound para descargar el archivo original en alta calidad."
            logger.error(f"[EditingMedia] {msg} ('{item_data.get('nombre')}')")
            on_error(msg)
            return

        sound_id = item_data.get("id")
        if not sound_id:
            msg = "No se pudo determinar el ID del sonido de Freesound."
            logger.error(f"[EditingMedia] {msg} ('{item_data.get('nombre')}')")
            on_error(msg)
            return

        fallback_path = self._resolve_freesound_dest_path(item_data)
        dest_dir = os.path.dirname(fallback_path)
        fallback_name = os.path.basename(fallback_path)

        logger.info(f"[EditingMedia] Descargando archivo original en alta calidad de Freesound (id={sound_id}) '{item_data.get('nombre')}' -> {dest_dir}")

        thread = FreesoundOriginalDownloadThread(self.freesound_client, sound_id, dest_dir, fallback_name, token, parent=self)
        if not hasattr(self, "_hq_download_threads"):
            self._hq_download_threads = []
        self._hq_download_threads.append(thread)

        def _cleanup():
            if thread in self._hq_download_threads:
                self._hq_download_threads.remove(thread)

        def _on_finished(success, resolved_path):
            _cleanup()
            if not success or not resolved_path:
                logger.error(f"[EditingMedia] La descarga en alta calidad de '{item_data.get('nombre')}' no tuvo éxito.")
                on_error("La descarga no tuvo éxito.")
                return

            item_data["dest_path"] = resolved_path
            if hasattr(self, "media_model"):
                idx = self.media_model.find_item_index_by_path(item_data.get("ruta"))
                if idx.isValid():
                    self.media_model.dataChanged.emit(idx, idx, [])
            if hasattr(self, "controller"):
                self.controller.add_to_downloaded_collection(resolved_path)

            logger.info(f"[EditingMedia] Descarga en alta calidad completada: {resolved_path}")
            on_success(resolved_path)

        def _on_error(err):
            _cleanup()
            logger.error(f"[EditingMedia] Error descargando '{item_data.get('nombre')}' en alta calidad: {err}")
            on_error(err)

        thread.finished.connect(_on_finished)
        thread.error.connect(_on_error)
        thread.start()

    def _update_media_input_changed(self, text):
        if hasattr(self, "search_spinner"):
            self.search_spinner.start()

        selected = self.tree_folders.currentItem()
        is_online = False
        if selected:
            data = selected.data(0, Qt.UserRole)
            if data and data.get("tipo") == "root_online":
                is_online = True
        
        if is_online:
            self.current_page = 1
            self.online_results = []
            self.search_timer.start(600)
        else:
            if hasattr(self, "local_search_timer"):
                self.local_search_timer.start(250)
            else:
                self._apply_active_filters_fast()
                if hasattr(self, "search_spinner"):
                    self.search_spinner.stop()

    def _update_freesound_login_button(self):
        """Actualiza el icono y tooltip del botón de login de Freesound según el estado de autenticación."""
        if not hasattr(self, "btn_freesound_login"):
            return
        if self.controller.is_freesound_authenticated:
            username = self.controller.freesound_username or "usuario"
            self.btn_freesound_login.setIcon(get_svg_icon("person.svg"))
            self.btn_freesound_login.setToolTip(self.tr(f"Conectado como: {username} (clic para cerrar sesión)"))
        else:
            self.btn_freesound_login.setIcon(get_svg_icon("login.svg"))
            self.btn_freesound_login.setToolTip(self.tr("Iniciar sesión con Freesound"))

    def _on_freesound_login_clicked(self):
        """Maneja el clic en el botón de login/logout de Freesound."""
        if self.controller.is_freesound_authenticated:
            # Ya autenticado → preguntar si desea cerrar sesión
            reply = QMessageBox.question(
                self,
                self.tr("Cerrar Sesión"),
                self.tr(f"¿Desea cerrar la sesión de Freesound ({self.controller.freesound_username})?"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.controller.clear_freesound_auth()
                self._update_freesound_login_button()
                self.online_results = []
                self.current_page = 1
                self._update_media_list()
        else:
            # No autenticado → iniciar flujo OAuth2
            self._start_freesound_oauth()

    def _start_freesound_oauth(self):
        """Inicia el flujo OAuth2 con Freesound."""
        from core.tabs.editing_media.freesound_auth import FreesoundAuth
        
        self._oauth_handler = FreesoundAuth()
        self._oauth_handler.signals.auth_success.connect(self._on_oauth_success)
        self._oauth_handler.signals.auth_error.connect(self._on_oauth_error)
        self._oauth_handler.start_oauth_flow()
        
        # Mostrar feedback visual al usuario
        QMessageBox.information(
            self,
            self.tr("Iniciar Sesión en Freesound"),
            self.tr("Se ha abierto tu navegador para iniciar sesión en Freesound.\n\n"
                    "Inicia sesión y autoriza la aplicación. "
                    "Esta ventana se actualizará automáticamente cuando completes el proceso.")
        )

    def _on_oauth_success(self, auth_data: dict):
        """Callback cuando la autenticación OAuth2 es exitosa."""
        self.controller.freesound_auth.update(auth_data)
        self.controller.save_data()
        self._update_freesound_login_button()
        self.current_page = 1
        self.online_results = []
        self._exec_online_search()
        logger.info(f"EditingMediaTab: Autenticación OAuth2 exitosa para '{auth_data.get('username', '')}'")

    def _on_oauth_error(self, error_msg: str):
        """Callback cuando la autenticación OAuth2 falla."""
        logger.error(f"EditingMediaTab: Error OAuth2: {error_msg}")
        QMessageBox.warning(
            self,
            self.tr("Error de Autenticación"),
            self.tr(f"No se pudo completar la autenticación con Freesound:\n{error_msg}")
        )

    def _exec_online_search(self):
        token = self.controller.freesound_token
        query = self.search_input.text().strip()
        
        sort_order = None
        duration_max = None
        license_type = None

        if hasattr(self, "freesound_license_combo"):
            license_type = self.freesound_license_combo.currentData()

        if not query:
            # Si el cuadro de búsqueda está vacío, cargar automáticamente sonidos recientes ("Más nuevos")
            # y limitar a audios menores a 5 minutos (300 segundos) para mostrar solo efectos/audios cortos
            sort_order = "Más nuevos"
            duration_max = 300
            
        if not hasattr(self, "_active_freesound_threads"):
            self._active_freesound_threads = set()

        if hasattr(self, "online_search_thread") and self.online_search_thread and self.online_search_thread.isRunning():
            old_thread = self.online_search_thread
            try:
                old_thread.finished_search.disconnect()
            except Exception:
                pass
            try:
                old_thread.error_search.disconnect()
            except Exception:
                pass
            self._active_freesound_threads.add(old_thread)
            old_thread.finished.connect(lambda t=old_thread: self._active_freesound_threads.discard(t))
            
        if hasattr(self, "search_spinner"):
            self.search_spinner.start()

        self.online_search_thread = FreesoundSearchThread(
            self.freesound_client,
            query,
            token,
            page=self.current_page,
            sort_order=sort_order,
            duration_max=duration_max,
            license_type=license_type,
            parent=self
        )
        self.online_search_thread.finished_search.connect(self._on_online_search_success)
        self.online_search_thread.error_search.connect(self._on_online_search_error)
        
        new_thread = self.online_search_thread
        self._active_freesound_threads.add(new_thread)
        new_thread.finished.connect(lambda t=new_thread: self._active_freesound_threads.discard(t))
        new_thread.start()

    def _on_search_timer_timeout(self):
        """Callback del temporizador de búsqueda diferida en Freesound."""
        self._exec_online_search()

    def _on_online_search_success(self, data):
        self.loading_next_page = False
        if hasattr(self, "search_spinner"):
            self.search_spinner.stop()
        results = data.get("results", [])
        
        if self.current_page == 1:
            self.online_results = []
            
        new_items = []
        for r in results:
            previews = r.get("previews", {})
            preview_lq_url = previews.get("preview-lq-mp3", previews.get("preview-hq-mp3", previews.get("preview-lq-ogg", "")))
            download_hq_url = previews.get("preview-hq-mp3", previews.get("preview-hq-ogg", preview_lq_url))
            if not preview_lq_url:
                continue

            dur = r.get("duration", 0)
            dur_m = int(dur // 60)
            dur_s = int(dur % 60)
            dur_str = f"{dur_m:02d}:{dur_s:02d}"

            size_val = r.get("filesize", 0)
            size_kb = size_val / 1024.0
            if size_kb > 1024:
                size_str = f"{size_kb / 1024.0:.1f} MB"
            else:
                size_str = f"{size_kb:.1f} KB"

            sound_name = r.get("name", "Sonido sin nombre").strip()
            sound_type = r.get("type", "").strip().lower()
            if sound_type and not any(sound_name.lower().endswith(f".{ext}") for ext in ["wav", "mp3", "flac", "ogg", "aiff", "m4a", "aac"]):
                sound_name = f"{sound_name}.{sound_type}"

            raw_license = str(r.get("license", "")).lower()
            if "zero" in raw_license or "cc0" in raw_license or "publicdomain" in raw_license:
                license_clean = "CC0"
            elif "by-nc" in raw_license or "noncommercial" in raw_license:
                license_clean = "CC BY-NC"
            elif "by" in raw_license or "attribution" in raw_license:
                license_clean = "CC BY"
            elif raw_license:
                license_clean = r.get("license", "Freesound")
            else:
                license_clean = "CC0"

            sr_val = r.get("samplerate")
            if sr_val:
                try:
                    sr_num = int(sr_val)
                    sample_rate_str = f"{sr_num / 1000.0:.1f} kHz" if sr_num >= 1000 else f"{sr_num} Hz"
                except Exception:
                    sample_rate_str = str(sr_val)
            else:
                sample_rate_str = "-"

            new_items.append({
                "nombre": sound_name,
                "ruta": preview_lq_url,
                "download_url": download_hq_url,
                "tipo": "audio",
                "file_type": sound_type.upper() if sound_type else "AUDIO",
                "tamaño": size_str,
                "duración": dur_str,
                "duration": dur,
                "es_remoto": True,
                "username": r.get("username", "-"),
                "license": license_clean,
                "library": "Freesound",
                "sample_rate": sample_rate_str,
                "avg_rating": f"{r.get('avg_rating', 0):.1f}",
                "num_downloads": str(r.get("num_downloads", 0)),
                "description": r.get("description", "-"),
                "images": r.get("images", {}),
                "id": str(r.get("id", "")),
                "url": r.get("url", "")
            })


        
        self.online_results.extend(new_items)
        self._update_media_list()

    def _on_online_search_error(self, error_msg):
        self.loading_next_page = False
        if hasattr(self, "search_spinner"):
            self.search_spinner.stop()
        logger.error(f"EditingMediaTab: Error en búsqueda online: {error_msg}")
        if self.current_page == 1:
            self.online_results = []
        self._update_media_list()
        QMessageBox.warning(self, self.tr("Error de Búsqueda"), self.tr(f"No se pudo completar la búsqueda en Freesound:\n{error_msg}"))

    def _on_list_scroll(self, value):
        selected = self.tree_folders.currentItem()
        if selected:
            data = selected.data(0, Qt.UserRole)
            if data and data.get("tipo") == "root_online":
                scroll_widget = self.media_table if getattr(self, "view_mode", "grid") == "list" and hasattr(self, "media_table") else self.media_list
                max_scroll = scroll_widget.verticalScrollBar().maximum()
                # Si llega casi al final y no hay búsqueda activa, cargar la siguiente página
                if value >= max_scroll - 15 and max_scroll > 0:
                    if not self.loading_next_page:
                        if hasattr(self, "online_search_thread") and self.online_search_thread and self.online_search_thread.isRunning():
                            return
                        # Recordar la posición de scroll actual para restaurarla tras cargar la
                        # siguiente página, en vez de dejar que el reset del modelo salte al tope.
                        self._pending_scroll_restore = value
                        self.loading_next_page = True
                        self.current_page += 1
                        self._exec_online_search()
                return



    def _on_download_clicked(self):
        item_data = self._get_current_media_data() if hasattr(self, "_get_current_media_data") else None
        if not item_data or not item_data.get("es_remoto"):
            return

        token = getattr(self.controller, "freesound_auth", {}).get("access_token", "")
        if not token:
            QMessageBox.warning(
                self,
                self.tr("Inicia sesión requerida"),
                self.tr("Debes iniciar sesión con Freesound para descargar el archivo original en alta calidad.")
            )
            return

        sound_id = item_data.get("id")
        if not sound_id:
            QMessageBox.warning(self, self.tr("Error"), self.tr("No se pudo determinar el ID del sonido de Freesound."))
            return

        fallback_path = self._resolve_freesound_dest_path(item_data)
        dest_dir = os.path.dirname(fallback_path)
        fallback_name = os.path.basename(fallback_path)

        from PySide6.QtWidgets import QProgressDialog
        progress_dialog = QProgressDialog(self.tr("Descargando sonido original de Freesound..."), self.tr("Cancelar"), 0, 100, self)
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setValue(0)
        progress_dialog.show()

        self.dl_thread = FreesoundOriginalDownloadThread(self.freesound_client, sound_id, dest_dir, fallback_name, token, parent=self)
        self.dl_thread.progress.connect(progress_dialog.setValue)

        def on_finished(success, resolved_path):
            progress_dialog.close()
            if success and resolved_path:
                item_data["dest_path"] = resolved_path
                idx = self.media_model.find_item_index_by_path(item_data["ruta"])
                if idx.isValid():
                    self.media_model.dataChanged.emit(idx, idx, [])

                # Registrar en la colección 'Descargados'
                self.controller.add_to_downloaded_collection(resolved_path)

                # Actualizar botones
                self.btn_reveal.setVisible(True)
                self.btn_reveal.setEnabled(True)
                if hasattr(self, "combo_tags"):
                    self.combo_tags.setVisible(False)

                self.btn_download.setVisible(True)
                self.btn_download.setEnabled(False)
                self.btn_download.setText(self.tr("En Disco"))
                self.metadata_labels["ruta"].setText(resolved_path)

                logger.info(f"[EditingMedia] Descarga manual del original en alta calidad completada: {resolved_path}")
                QMessageBox.information(self, self.tr("Descarga Completada"), self.tr(f"El sonido original ha sido guardado exitosamente en:\n{resolved_path}"))
            else:
                logger.error(f"[EditingMedia] La descarga manual del original de '{item_data.get('nombre')}' no tuvo éxito.")

        def on_error(err):
            progress_dialog.close()
            logger.error(f"[EditingMedia] Error en descarga manual del original de '{item_data.get('nombre')}': {err}")
            QMessageBox.warning(self, self.tr("Error de Descarga"), self.tr(f"No se pudo descargar el archivo original:\n{err}"))

        self.dl_thread.finished.connect(on_finished)
        self.dl_thread.error.connect(on_error)

        progress_dialog.canceled.connect(self.dl_thread.terminate)
        self.dl_thread.start()

