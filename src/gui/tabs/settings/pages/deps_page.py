from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                                 QPushButton, QFrame, QScrollArea, QProgressBar, QMessageBox)
from PySide6.QtCore import Qt, Signal, QThread
from core.utils.i18n import logger
import platform

from core.setup.ffmpeg_setup import check_ffmpeg, download_ffmpeg, get_local_version as ffmpeg_local, get_latest_remote_version as ffmpeg_remote
from core.setup.deno_setup import check_deno, download_deno, get_local_version as deno_local, get_latest_remote_version as deno_remote
from core.setup.ytdlp_setup import check_ytdlp, download_ytdlp, get_local_version as ytdlp_local, get_latest_remote_version as ytdlp_remote

class UpdateCheckWorker(QThread):
    finished_signal = Signal(dict) # {dep_id: {"local": str, "remote": str}}
    
    def __init__(self, configs, parent=None):
        super().__init__(parent)
        self.configs = configs

    def run(self):
        results = {}
        for config in self.configs:
            dep_id = config["id"]
            try:
                remote_ver = config["remote_func"]()
            except Exception as e:
                logger.error(f"Error fetching remote version for {dep_id}: {e}")
                remote_ver = None
            
            try:
                local_ver = config["local_func"]()
            except Exception:
                local_ver = None
                
            results[dep_id] = {"local": local_ver, "remote": remote_ver}
        self.finished_signal.emit(results)

class DependencyDownloadWorker(QThread):
    finished_signal = Signal(bool, str, str)  # success, message, dep_id
    progress_signal = Signal(str, str) # current phase message, dep_id
    numeric_progress_signal = Signal(int, str) # percentage, dep_id

    def __init__(self, dep_id, download_func, version=None, parent=None):
        super().__init__(parent)
        self.dep_id = dep_id
        self.download_func = download_func
        self.version = version

    def run(self):
        try:
            self.progress_signal.emit(f"Descargando {self.dep_id}...", self.dep_id)
            
            def progress_cb(percent):
                self.numeric_progress_signal.emit(percent, self.dep_id)
            
            if self.dep_id == "ffmpeg":
                success, msg = self.download_func(version=self.version, progress_callback=progress_cb)
            else:
                success, msg = self.download_func(progress_callback=progress_cb)
                
            self.finished_signal.emit(success, msg, self.dep_id)
        except Exception as e:
            logger.error(f"Error in DependencyDownloadWorker for {self.dep_id}: {e}")
            self.finished_signal.emit(False, str(e), self.dep_id)

class DependencyRowWidget(QFrame):
    """A modular row representing a single dependency."""
    download_requested = Signal(str, object) # Emits dep_id, version (str or None)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.dep_id = config["id"]
        self.is_installed = False
        self.local_ver = None

        self.setObjectName("dependencyRow")
        self.setStyleSheet("QFrame#dependencyRow { background-color: transparent; }")

        self.init_ui()
        self.check_status()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(4)

        top_layout = QHBoxLayout()
        
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        
        # Name and Status in the same horizontal line
        name_status_layout = QHBoxLayout()
        name_status_layout.setSpacing(10)
        name_status_layout.setAlignment(Qt.AlignVCenter)
        
        self.name_label = QLabel(self.config["name"])
        self.name_label.setObjectName("settingsSectionTitle")
        
        self.status_label = QLabel("Chequeando...")
        self.status_label.setStyleSheet("font-weight: bold; font-size: 12px; padding-top: 4px;")
        
        name_status_layout.addWidget(self.name_label)
        name_status_layout.addWidget(self.status_label)
        name_status_layout.addStretch()
        
        self.version_label = QLabel("Versión: Calculando...")
        self.version_label.setStyleSheet("color: #AAAAAA; font-size: 13px;")
        
        self.desc_label = QLabel(self.config["description"])
        self.desc_label.setStyleSheet("color: #888888; font-size: 11px;")
        self.desc_label.setWordWrap(True)

        info_layout.addLayout(name_status_layout)
        info_layout.addWidget(self.version_label)
        info_layout.addWidget(self.desc_label)
        
        top_layout.addLayout(info_layout)
        top_layout.addStretch() # Empuja los botones hacia la derecha

        action_layout = QVBoxLayout()
        action_layout.setSpacing(6)
        action_layout.setAlignment(Qt.AlignVCenter | Qt.AlignRight)

        self.action_btn = QPushButton("Descargar")
        self.action_btn.setCursor(Qt.PointingHandCursor)
        self.action_btn.setFixedWidth(120)
        self.action_btn.clicked.connect(self.on_download_clicked)
        
        action_layout.addWidget(self.action_btn)

        # Restaurar button only for FFmpeg on Windows
        if self.dep_id == "ffmpeg" and platform.system().lower() == "windows":
            self.restore_btn = QPushButton("Restaurar (8.0.1)")
            self.restore_btn.setCursor(Qt.PointingHandCursor)
            self.restore_btn.setFixedWidth(120)
            self.restore_btn.setStyleSheet("background-color: #28A745; color: white; border: none; padding: 5px; border-radius: 4px;")
            self.restore_btn.clicked.connect(self.on_download_clicked)
            action_layout.addWidget(self.restore_btn)
        else:
            self.restore_btn = None

        top_layout.addLayout(action_layout)
        layout.addLayout(top_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.hide()
        
        self.progress_msg = QLabel("")
        self.progress_msg.setStyleSheet("color: #888888; font-size: 11px;")
        self.progress_msg.hide()

        layout.addWidget(self.progress_bar)
        layout.addWidget(self.progress_msg)
        
        # Straight line divider at the bottom
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setFrameShadow(QFrame.Plain)
        divider.setStyleSheet("color: #333333; background-color: #333333;")
        layout.addWidget(divider)

    def check_status(self):
        self.is_installed = self.config["check_func"]()
        if self.is_installed:
            try:
                self.local_ver = self.config["local_func"]()
            except Exception:
                self.local_ver = None
        else:
            self.local_ver = None
        self.update_ui_state()

    def update_ui_state(self):
        if self.is_installed:
            self.status_label.setText("Instalado")
            self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 12px; margin-top: 4px;")
            v_text = f"Versión: {self.local_ver}" if self.local_ver else "Versión: Desconocida"
            self.version_label.setText(v_text)
            self.version_label.setStyleSheet("color: #AAAAAA; font-size: 13px;")
            
            # Default state when installed but not checked for updates
            self.action_btn.setText("Actualizado")
            self.action_btn.setDisabled(True)
        else:
            self.status_label.setText("Falta")
            self.status_label.setStyleSheet("color: #F44336; font-weight: bold; font-size: 12px; margin-top: 4px;")
            self.version_label.setText("No instalado")
            self.version_label.setStyleSheet("color: #F44336; font-size: 13px;")
            self.action_btn.setText("Descargar")
            self.action_btn.setDisabled(False)
            
        if self.restore_btn:
            if self.local_ver and "8.0.1" in self.local_ver:
                self.restore_btn.setDisabled(True)
                self.restore_btn.setStyleSheet("background-color: #555555; color: #888888; border: none; padding: 5px; border-radius: 4px;")
            else:
                self.restore_btn.setDisabled(False)
                self.restore_btn.setStyleSheet("background-color: #28A745; color: white; border: none; padding: 5px; border-radius: 4px;")

    def set_update_available(self, remote_ver):
        if not self.is_installed:
            return
            
        if not remote_ver:
            self.version_label.setText(f"Versión: {self.local_ver}")
            self.version_label.setStyleSheet("color: #AAAAAA; font-size: 13px;")
            return
            
        r_ver = str(remote_ver).strip().lstrip('v')
        l_ver = str(self.local_ver).strip().lstrip('v')
        
        # Consider updated if versions are different AND remote version is not a substring of local
        # (e.g. remote "8.1.1" vs local "8.1.1-tessus")
        if r_ver != l_ver and r_ver not in l_ver:
            self.version_label.setText(f"Versión: {self.local_ver} (Nueva: {remote_ver})")
            self.version_label.setStyleSheet("color: #FFC107; font-weight: bold; font-size: 13px;")
            self.action_btn.setText("Actualizar")
            self.action_btn.setDisabled(False)
            self.action_btn.setStyleSheet("background-color: #007BFF; color: white; border: none; padding: 5px; border-radius: 4px;")
        else:
            self.version_label.setText(f"Versión: {self.local_ver}")
            self.version_label.setStyleSheet("color: #AAAAAA; font-size: 13px;")
            self.action_btn.setText("Actualizado")
            self.action_btn.setDisabled(True)
            self.action_btn.setStyleSheet("")

    def on_download_clicked(self):
        version = None
        sender = self.sender()
        
        if sender == self.restore_btn:
            version = "8.0.1"
        elif self.action_btn.text() == "Actualizar":
            version = "latest"
            
        self.set_downloading_state(True)
        self.download_requested.emit(self.dep_id, version)

    def set_downloading_state(self, is_downloading, message=""):
        self.action_btn.setDisabled(is_downloading)
        if self.restore_btn:
            self.restore_btn.setDisabled(is_downloading)
            
        if is_downloading:
            self.progress_bar.setRange(0, 0) # Indeterminate until first progress update
            self.progress_bar.setValue(0)
            self.progress_bar.show()
            self.progress_msg.setText(message if message else "Iniciando...")
            self.progress_msg.show()
            self.status_label.setText("Procesando")
            self.status_label.setStyleSheet("color: #FFC107; font-weight: bold; font-size: 12px; margin-top: 4px;")
        else:
            self.progress_bar.hide()
            self.progress_msg.hide()
            self.action_btn.setStyleSheet("")
            self.check_status() # Re-check status when done

    def update_progress_msg(self, msg):
        self.progress_msg.setText(msg)

    def update_numeric_progress(self, value):
        if self.progress_bar.minimum() == 0 and self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(value)

class DependenciesPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.workers = {} 
        self.update_worker = None
        
        self.dependencies_config = [
            {
                "id": "ffmpeg",
                "name": "FFmpeg",
                "description": "Motor de procesamiento multimedia, necesario para combinar audio y video de alta calidad o recortar fragmentos.",
                "check_func": check_ffmpeg,
                "download_func": download_ffmpeg,
                "local_func": ffmpeg_local,
                "remote_func": ffmpeg_remote
            },
            {
                "id": "ytdlp",
                "name": "yt-dlp",
                "description": "El núcleo de descargas, maneja la extracción de datos de YouTube y otras plataformas.",
                "check_func": check_ytdlp,
                "download_func": download_ytdlp,
                "local_func": ytdlp_local,
                "remote_func": ytdlp_remote
            },
            {
                "id": "deno",
                "name": "Deno",
                "description": "Entorno de ejecución de JavaScript. Necesario por yt-dlp para extraer las firmas de ciertos sitios web.",
                "check_func": check_deno,
                "download_func": download_deno,
                "local_func": deno_local,
                "remote_func": deno_remote
            }
        ]

        self.rows = {} 
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        
        # Title matching GeneralPage
        self.title_label = QLabel(self.tr("Gestor de Dependencias"))
        self.title_label.setObjectName("settingsTitle")
        layout.addWidget(self.title_label)
        
        # Divider matching GeneralPage
        line = QFrame()
        line.setObjectName("settingsDivider")
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        # Description
        self.desc_label = QLabel(self.tr("Estas herramientas son necesarias para que DowP 2.0 funcione correctamente."))
        self.desc_label.setObjectName("settingsLabel")
        layout.addWidget(self.desc_label)

        # Scroll area for the list
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setStyleSheet("background-color: transparent;")

        scroll_content = QWidget()
        self.list_layout = QVBoxLayout(scroll_content)
        self.list_layout.setContentsMargins(0, 0, 10, 0)
        self.list_layout.setSpacing(0)
        self.list_layout.setAlignment(Qt.AlignTop)

        for dep in self.dependencies_config:
            row = DependencyRowWidget(dep)
            row.download_requested.connect(self.start_download)
            self.list_layout.addWidget(row)
            self.rows[dep["id"]] = row

        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area)
        
        # Bottom Check Updates Button
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()
        
        self.btn_check_updates = QPushButton("Buscar Actualizaciones")
        self.btn_check_updates.setCursor(Qt.PointingHandCursor)
        self.btn_check_updates.setStyleSheet("""
            QPushButton {
                background-color: #FF8C00; 
                color: white; 
                padding: 8px 20px; 
                font-weight: bold;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #E67E22;
            }
            QPushButton:disabled {
                background-color: #555555;
                color: #888888;
            }
        """)
        self.btn_check_updates.clicked.connect(self.check_all_updates)
        bottom_layout.addWidget(self.btn_check_updates)
        
        layout.addLayout(bottom_layout)

    def check_all_updates(self):
        self.btn_check_updates.setDisabled(True)
        self.btn_check_updates.setText("Buscando...")
        
        for row in self.rows.values():
            if row.is_installed:
                row.version_label.setText(f"Versión: {row.local_ver} (Buscando...)")
        
        self.update_worker = UpdateCheckWorker(self.dependencies_config)
        self.update_worker.finished_signal.connect(self.on_update_check_finished)
        self.update_worker.start()

    def on_update_check_finished(self, results):
        self.btn_check_updates.setDisabled(False)
        self.btn_check_updates.setText("Buscar Actualizaciones")
        
        for dep_id, vers in results.items():
            if dep_id in self.rows:
                # Update the local version string just in case
                if vers["local"]:
                    self.rows[dep_id].local_ver = vers["local"]
                if self.rows[dep_id].is_installed:
                    self.rows[dep_id].set_update_available(vers["remote"])

    def start_download(self, dep_id, version=None):
        config = next((item for item in self.dependencies_config if item["id"] == dep_id), None)
        if not config:
            return

        worker = DependencyDownloadWorker(dep_id, config["download_func"], version=version)
        worker.progress_signal.connect(self.on_worker_progress)
        worker.numeric_progress_signal.connect(self.on_worker_numeric_progress)
        worker.finished_signal.connect(self.on_worker_finished)
        
        self.workers[dep_id] = worker
        worker.start()

    def on_worker_numeric_progress(self, val, dep_id):
        if dep_id in self.rows:
            self.rows[dep_id].update_numeric_progress(val)

    def on_worker_progress(self, msg, dep_id):
        if dep_id in self.rows:
            self.rows[dep_id].update_progress_msg(msg)

    def on_worker_finished(self, success, msg, dep_id):
        if dep_id in self.workers:
            del self.workers[dep_id] 
            
        if dep_id in self.rows:
            if success:
                try:
                    # Forzamos a que lea la versión real en vez de la caché después de una descarga exitosa
                    self.rows[dep_id].config["local_func"](force_check=True)
                except Exception as e:
                    logger.error(f"Error forzando actualización de versión local para {dep_id}: {e}")
            self.rows[dep_id].set_downloading_state(False)
            
        if not success:
            QMessageBox.warning(self, "Error de Descarga", f"Fallo al descargar {dep_id}:\n{msg}")
        else:
            logger.info(f"Dependency {dep_id} downloaded successfully.")
