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

class FreesoundMixin:
    """Mixin que maneja la búsqueda y descarga remota de Freesound, así como la autenticación OAuth2."""

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
                "images": r.get("images", {})
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
                        self.loading_next_page = True
                        self.current_page += 1
                        self._exec_online_search()
                return



    def _on_download_clicked(self):
        item_data = self._get_current_media_data() if hasattr(self, "_get_current_media_data") else None
        if not item_data or not item_data.get("es_remoto"):
            return
            
        url = item_data.get("download_url", item_data["ruta"])
        name = item_data["nombre"]

        
        # Determinar carpeta de destino: Etiqueta seleccionada o carpeta Downloads del sistema
        selected_label_name = item_data.get("selected_label")
        from core.utils.config_manager import get_config
        labels = get_config().get("labels", [])
        matched_label = next((l for l in labels if l.get("name") == selected_label_name), None) if selected_label_name else None

        if matched_label and matched_label.get("path"):
            downloads_dir = matched_label["path"]
        else:
            downloads_dir = os.path.expanduser("~/Downloads")

        
        os.makedirs(downloads_dir, exist_ok=True)
        clean_name = "".join(c for c in name if c.isalnum() or c in (".", "_", " ", "-")).strip()
        dest_path = os.path.join(downloads_dir, clean_name).replace("\\", "/")
        
        token = getattr(self.controller, "freesound_auth", {}).get("access_token", "")
        fallback_url = item_data.get("ruta")

        from PySide6.QtWidgets import QProgressDialog
        progress_dialog = QProgressDialog(self.tr("Descargando sonido de Freesound..."), self.tr("Cancelar"), 0, 100, self)
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setValue(0)
        progress_dialog.show()
        
        class DownloadThread(QThread):
            progress = Signal(int)
            finished = Signal(bool)
            error = Signal(str)
            
            def __init__(self, client, url, path, token=None, fallback_url=None):
                super().__init__()
                self.client = client
                self.url = url
                self.path = path
                self.token = token
                self.fallback_url = fallback_url
                
            def run(self):
                try:
                    success = self.client.download_file(self.url, self.path, token=self.token, progress_callback=self.progress.emit)
                    self.finished.emit(success)
                except Exception as e:
                    if self.fallback_url and self.fallback_url != self.url:
                        try:
                            success = self.client.download_file(self.fallback_url, self.path, token=self.token, progress_callback=self.progress.emit)
                            self.finished.emit(success)
                            return
                        except Exception:
                            pass
                    self.error.emit(str(e))
                    
        self.dl_thread = DownloadThread(self.freesound_client, url, dest_path, token=token, fallback_url=fallback_url)

        self.dl_thread.progress.connect(progress_dialog.setValue)
        
        def on_finished(success):
            progress_dialog.close()
            if success:
                item_data["dest_path"] = dest_path
                idx = self.media_model.find_item_index_by_path(item_data["ruta"])
                if idx.isValid():
                    self.media_model.dataChanged.emit(idx, idx, [])

                # Registrar en la colección 'Descargados'
                self.controller.add_to_downloaded_collection(dest_path)
                
                # Actualizar botones
                self.btn_reveal.setVisible(True)
                self.btn_reveal.setEnabled(True)
                if hasattr(self, "combo_tags"):
                    self.combo_tags.setVisible(False)

                self.btn_download.setVisible(True)
                self.btn_download.setEnabled(False)
                self.btn_download.setText(self.tr("En Disco"))
                self.metadata_labels["ruta"].setText(dest_path)
                
                QMessageBox.information(self, self.tr("Descarga Completada"), self.tr(f"El sonido ha sido guardado exitosamente en:\n{dest_path}"))
                
        def on_error(err):
            progress_dialog.close()
            QMessageBox.warning(self, self.tr("Error de Descarga"), self.tr(f"No se pudo descargar el archivo:\n{err}"))
            
        self.dl_thread.finished.connect(on_finished)
        self.dl_thread.error.connect(on_error)
        
        progress_dialog.canceled.connect(self.dl_thread.terminate)
        self.dl_thread.start()

