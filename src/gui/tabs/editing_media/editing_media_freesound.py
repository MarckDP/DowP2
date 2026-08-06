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

    def __init__(self, client, query, token, page=1, sort_order=None, parent=None):
        super().__init__(parent)
        self.client = client
        self.query = query
        self.token = token
        self.page = page
        self.sort_order = sort_order

    def run(self):
        try:
            results = self.client.search(self.query, self.token, sort_order=self.sort_order, page=self.page)
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
        if not query:
            # Si el cuadro de búsqueda está vacío, cargar automáticamente sonidos recientes ("Más nuevos")
            sort_order = "Más nuevos"
            
        if self.online_search_thread and self.online_search_thread.isRunning():
            if self.online_search_thread.page == self.current_page:
                return
            self.online_search_thread.terminate()
            self.online_search_thread.wait()
            
        if hasattr(self, "search_spinner"):
            self.search_spinner.start()

        self.online_search_thread = FreesoundSearchThread(self.freesound_client, query, token, self.current_page, sort_order, self)
        self.online_search_thread.finished_search.connect(self._on_online_search_success)
        self.online_search_thread.error_search.connect(self._on_online_search_error)
        self.online_search_thread.start()

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
            preview_url = previews.get("preview-hq-mp3", previews.get("preview-lq-mp3", ""))
            if not preview_url:
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
                
            new_items.append({
                "nombre": r.get("name", "Sonido sin nombre") + ".mp3",
                "ruta": preview_url,
                "tipo": "audio",
                "tamaño": size_str,
                "duración": dur_str,
                "es_remoto": True,
                "username": r.get("username", "-"),
                "license": r.get("license", "-"),
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
        if not selected:
            return
        data = selected.data(0, Qt.UserRole)
        if not data or data.get("tipo") != "root_online":
            return
            
        max_scroll = self.media_list.verticalScrollBar().maximum()
        # Si llega casi al final y no hay búsqueda activa, cargar la siguiente página
        if value >= max_scroll - 5 and max_scroll > 0:
            if not self.loading_next_page:
                self.loading_next_page = True
                self.current_page += 1
                self._exec_online_search()

    def _on_download_clicked(self):
        selected_item = self.media_list.currentItem()
        if not selected_item:
            return
        item_data = selected_item.data(Qt.UserRole)
        if not item_data or not item_data.get("es_remoto"):
            return
            
        url = item_data["ruta"]
        name = item_data["nombre"]
        
        workspace_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        downloads_dir = os.path.join(workspace_dir, "downloads", "freesound")
        os.makedirs(downloads_dir, exist_ok=True)
        
        clean_name = "".join(c for c in name if c.isalnum() or c in (".", "_", " ", "-")).strip()
        dest_path = os.path.join(downloads_dir, clean_name).replace("\\", "/")
        
        from PySide6.QtWidgets import QProgressDialog
        progress_dialog = QProgressDialog(self.tr("Descargando sonido de Freesound..."), self.tr("Cancelar"), 0, 100, self)
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setValue(0)
        progress_dialog.show()
        
        class DownloadThread(QThread):
            progress = Signal(int)
            finished = Signal(bool)
            error = Signal(str)
            
            def __init__(self, client, url, path):
                super().__init__()
                self.client = client
                self.url = url
                self.path = path
                
            def run(self):
                try:
                    success = self.client.download_file(self.url, self.path, self.progress.emit)
                    self.finished.emit(success)
                except Exception as e:
                    self.error.emit(str(e))
                    
        self.dl_thread = DownloadThread(self.freesound_client, url, dest_path)
        self.dl_thread.progress.connect(progress_dialog.setValue)
        
        def on_finished(success):
            progress_dialog.close()
            if success:
                item_data["ruta"] = dest_path
                item_data["es_remoto"] = False
                
                selected_item.setData(Qt.UserRole, item_data)
                
                self.btn_reveal.setVisible(True)
                self.btn_reveal.setEnabled(True)
                self.btn_download.setVisible(False)
                self.btn_download.setEnabled(False)
                self.metadata_labels["ruta"].setText(dest_path)
                
                for col_name in self.controller.collections.keys():
                    if url in self.controller.collections[col_name]:
                        idx = self.controller.collections[col_name].index(url)
                        self.controller.collections[col_name][idx] = dest_path
                self.controller.save_data()
                
                QMessageBox.information(self, self.tr("Descarga Completada"), self.tr(f"El sonido ha sido guardado exitosamente en:\n{dest_path}"))
                self._update_media_list()
                
        def on_error(err):
            progress_dialog.close()
            QMessageBox.warning(self, self.tr("Error de Descarga"), self.tr(f"No se pudo descargar el archivo:\n{err}"))
            
        self.dl_thread.finished.connect(on_finished)
        self.dl_thread.error.connect(on_error)
        
        progress_dialog.canceled.connect(self.dl_thread.terminate)
        self.dl_thread.start()
