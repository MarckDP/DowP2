import os
import platform
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QScrollArea, QProgressBar, QMessageBox,
    QRadioButton, QButtonGroup, QFileDialog, QLineEdit, QToolButton,
    QSizePolicy, QGroupBox
)
from PySide6.QtCore import Qt, Signal, QThread, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from core.utils.i18n import logger
from gui.styles import get_theme_token

from core.setup.ffmpeg_setup import check_ffmpeg, download_ffmpeg, get_local_version as ffmpeg_local, get_latest_remote_version as ffmpeg_remote, get_ffmpeg_dir
from core.setup.deno_setup import check_deno, download_deno, get_local_version as deno_local, get_latest_remote_version as deno_remote
from core.setup.ytdlp_setup import check_ytdlp, download_ytdlp, get_local_version as ytdlp_local, get_latest_remote_version as ytdlp_remote
from core.setup.potprovider_setup import (
    check_all as check_potprovider, download_potprovider,
    get_local_version as potprovider_local, get_latest_remote_version as potprovider_remote
)
from core.setup.wpc_setup import (
    check_wpc, install_wpc,
    get_local_version as wpc_local, get_latest_remote_version as wpc_remote,
    get_browser_display_name, detect_system_browser
)

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

class WPCUpdateCheckWorker(QThread):
    """Consulta en segundo plano la última versión remota de WPC (pip/PyPI)."""
    finished_signal = Signal(object)  # remote_version (str) o None

    def run(self):
        try:
            remote_ver = wpc_remote()
        except Exception as e:
            logger.error(f"Error obteniendo la versión remota de WPC: {e}")
            remote_ver = None
        self.finished_signal.emit(remote_ver)


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

class WPCInstallWorker(QThread):
    """Hilo para instalar/actualizar yt-dlp-getpot-wpc via pip sin bloquear la UI."""
    finished_signal = Signal(bool, str)
    numeric_progress_signal = Signal(int)

    def run(self):
        def cb(pct):
            self.numeric_progress_signal.emit(pct)
        success, msg = install_wpc(progress_callback=cb)
        self.finished_signal.emit(success, msg)


class POTProviderPanel(QFrame):
    """
    Panel de selección del PO Token Provider activo.
    Muestra bgutil-pot y WPC como opciones, con estado, versión y acciones para cada uno.
    """
    provider_changed = Signal(str)  # emite el nuevo provider id

    _TOOLTIP_WPC_BROWSER = (
        "WPC (WebPoClient) usa un navegador real basado en Chromium para generar\n"
        "los PO Tokens que YouTube requiere. Cualquier navegador Chromium funciona:\n\n"
        "  \u2022  Google Chrome\n"
        "  \u2022  Brave Browser\n"
        "  \u2022  Microsoft Edge\n"
        "  \u2022  Chromium\n\n"
        "Si dejas el campo vacío, WPC intentará detectar tu navegador automáticamente.\n"
        "Haz clic en '...' para seleccionar el ejecutable manualmente."
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("potProviderPanel")
        self._wpc_worker = None
        self.setStyleSheet("""
            QFrame#potProviderPanel {
                background-color: rgba(255,255,255,0.03);
                border: 1px solid #333;
                border-radius: 8px;
                padding: 4px;
            }
        """)
        self._build_ui()
        self._load_state()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # ── Título ──────────────────────────────────────────────────────────
        title_row = QHBoxLayout()
        title_lbl = QLabel("PO Token Provider")
        title_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #EEEEEE;")
        title_row.addWidget(title_lbl)

        info_btn = QToolButton()
        info_btn.setText("?")
        info_btn.setFixedSize(20, 20)
        info_btn.setStyleSheet(
            "QToolButton { border: 1px solid #555; border-radius: 10px;"
            " color: #AAA; font-size: 11px; background: #2a2a2a; }"
            " QToolButton:hover { background: #3a3a3a; color: #FFF; }"
        )
        info_btn.setToolTip(
            "El PO Token es requerido por YouTube para autenticar descargas sin cookies.\n"
            "DowP puede usar dos engines distintos — elige el que mejor funcione para ti.\n\n"
            "  bgutil-pot: Binario Rust, sin dependencias extra. Automático.\n"
            "  WPC:        Usa tu navegador Chrome/Brave/Edge para generar tokens más fiables.\n"
            "  Ninguno:    Sin token — puede fallar con error 429 o bot-check."
        )
        info_btn.clicked.connect(lambda: info_btn.setToolTip(info_btn.toolTip()))
        title_row.addWidget(info_btn)
        title_row.addStretch()
        root.addLayout(title_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #333;")
        root.addWidget(sep)

        # ── Grupo de radio buttons ───────────────────────────────────────────
        self._btn_group = QButtonGroup(self)

        self._radio_bgutil = self._make_radio("bgutil-pot  (recomendado)", "bgutil")
        self._radio_wpc    = self._make_radio("WPC – WebPoClient", "wpc")
        self._radio_none   = self._make_radio("Ninguno", "none")

        self._btn_group.addButton(self._radio_bgutil, 0)
        self._btn_group.addButton(self._radio_wpc,    1)
        self._btn_group.addButton(self._radio_none,   2)
        self._btn_group.idClicked.connect(self._on_radio_changed)

        # ── Fila bgutil ──────────────────────────────────────────────────────
        row_bgutil = QHBoxLayout()
        row_bgutil.addWidget(self._radio_bgutil)
        self._bgutil_status = QLabel("Chequeando...")
        self._bgutil_status.setStyleSheet("color: #888; font-size: 11px;")
        row_bgutil.addWidget(self._bgutil_status)
        row_bgutil.addStretch()
        self._bgutil_btn = QPushButton("Actualizar")
        self._bgutil_btn.setFixedWidth(100)
        self._bgutil_btn.setCursor(Qt.PointingHandCursor)
        self._bgutil_btn.setVisible(False)
        self._bgutil_btn.clicked.connect(self._on_bgutil_action)
        row_bgutil.addWidget(self._bgutil_btn)
        root.addLayout(row_bgutil)

        # ── Fila WPC ─────────────────────────────────────────────────────────
        row_wpc = QHBoxLayout()
        row_wpc.addWidget(self._radio_wpc)
        self._wpc_status = QLabel("Chequeando...")
        self._wpc_status.setStyleSheet("color: #888; font-size: 11px;")
        row_wpc.addWidget(self._wpc_status)
        row_wpc.addStretch()
        self._wpc_btn = QPushButton("Instalar")
        self._wpc_btn.setFixedWidth(100)
        self._wpc_btn.setCursor(Qt.PointingHandCursor)
        self._wpc_btn.clicked.connect(self._on_wpc_action)
        row_wpc.addWidget(self._wpc_btn)
        root.addLayout(row_wpc)

        # WPC progress bar (oculta por defecto)
        self._wpc_progress = QProgressBar()
        self._wpc_progress.setTextVisible(False)
        self._wpc_progress.setFixedHeight(4)
        self._wpc_progress.setRange(0, 100)
        self._wpc_progress.hide()
        root.addWidget(self._wpc_progress)

        # ── Fila Ninguno ─────────────────────────────────────────────────────
        root.addWidget(self._radio_none)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("color: #333;")
        root.addWidget(sep2)

        # ── Campo de ruta de navegador (WPC) ─────────────────────────────────
        browser_label_row = QHBoxLayout()
        browser_lbl = QLabel("Navegador para WPC:")
        browser_lbl.setStyleSheet("color: #CCC; font-size: 12px;")
        browser_label_row.addWidget(browser_lbl)

        # Botón de ayuda con tooltip detallado
        browser_help = QToolButton()
        browser_help.setText("?")
        browser_help.setFixedSize(18, 18)
        browser_help.setToolTip(self._TOOLTIP_WPC_BROWSER)
        browser_help.setStyleSheet(
            "QToolButton { border: 1px solid #555; border-radius: 9px;"
            " color: #AAA; font-size: 10px; background: #2a2a2a; }"
            " QToolButton:hover { background: #3a3a3a; color: #FFF; }"
        )
        browser_label_row.addWidget(browser_help)
        browser_label_row.addStretch()
        root.addLayout(browser_label_row)

        browser_path_row = QHBoxLayout()
        self._browser_field = QLineEdit()
        self._browser_field.setPlaceholderText("Auto-detectado: deja vacío o elige un ejecutable")
        self._browser_field.setStyleSheet(
            "background: #1e1e1e; color: #DDD; border: 1px solid #444;"
            " border-radius: 4px; padding: 4px 8px; font-size: 12px;"
        )
        self._browser_field.textChanged.connect(self._on_browser_path_changed)

        self._browser_detected_lbl = QLabel()
        self._browser_detected_lbl.setStyleSheet("color: #4CAF50; font-size: 11px;")

        browse_btn = QToolButton()
        browse_btn.setText("...")
        browse_btn.setFixedSize(28, 28)
        browse_btn.setCursor(Qt.PointingHandCursor)
        browse_btn.setToolTip("Seleccionar ejecutable del navegador (chrome.exe, brave.exe, msedge.exe...)")
        browse_btn.setStyleSheet(
            "QToolButton { background: #2e2e2e; border: 1px solid #555;"
            " border-radius: 4px; color: #DDD; }"
            " QToolButton:hover { background: #3e3e3e; }"
        )
        browse_btn.clicked.connect(self._pick_browser)

        browser_path_row.addWidget(self._browser_field)
        browser_path_row.addWidget(browse_btn)
        root.addLayout(browser_path_row)
        root.addWidget(self._browser_detected_lbl)

    def _make_radio(self, text, provider_id):
        rb = QRadioButton(text)
        rb.setProperty("provider_id", provider_id)
        rb.setStyleSheet("color: #DDD; font-size: 13px;")
        return rb

    # ── Estado ──────────────────────────────────────────────────────────────

    def _load_state(self):
        from core.utils.config_manager import get_config
        cfg = get_config()
        provider = cfg.get("pot_provider", "bgutil")
        browser_path = cfg.get("pot_wpc_browser_path", "")

        if provider == "bgutil":
            self._radio_bgutil.setChecked(True)
        elif provider == "wpc":
            self._radio_wpc.setChecked(True)
        else:
            self._radio_none.setChecked(True)

        self._browser_field.blockSignals(True)
        self._browser_field.setText(browser_path)
        self._browser_field.blockSignals(False)
        self._update_detected_label()
        self._refresh_status()

    def _refresh_status(self):
        # bgutil
        if check_potprovider():
            ver = potprovider_local() or "?"
            self._bgutil_status.setText(f"✓ Instalado  v{ver}")
            self._bgutil_status.setStyleSheet("color: #4CAF50; font-size: 11px;")
            self._bgutil_btn.setVisible(False)
        else:
            self._bgutil_status.setText("✗ No instalado")
            self._bgutil_status.setStyleSheet("color: #F44336; font-size: 11px;")
            self._bgutil_btn.setVisible(True)
            self._bgutil_btn.setText("Descargar")

        # WPC
        wpc_local(force_check=True)
        if check_wpc():
            ver = wpc_local() or "?"
            self._wpc_status.setText(f"✓ Instalado  v{ver}")
            self._wpc_status.setStyleSheet("color: #4CAF50; font-size: 11px;")
            # Igual que el resto de dependencias: recién instalado se muestra "Actualizado"
            # y deshabilitado; solo se habilita como "Actualizar" si "Buscar Actualizaciones"
            # detecta una versión remota más nueva (ver set_wpc_update_available).
            self._wpc_btn.setText("Actualizado")
            self._wpc_btn.setDisabled(True)
            self._wpc_btn.setStyleSheet("")
        else:
            self._wpc_status.setText("✗ No instalado")
            self._wpc_status.setStyleSheet("color: #F44336; font-size: 11px;")
            self._wpc_btn.setText("Instalar")
            self._wpc_btn.setDisabled(False)
            self._wpc_btn.setStyleSheet("")

    def _update_detected_label(self):
        configured = self._browser_field.text().strip()
        if configured and os.path.isfile(configured):
            self._browser_detected_lbl.setText(f"✓ Ruta configurada: {os.path.basename(configured)}")
        else:
            name = get_browser_display_name()
            if name and name != "No detectado":
                self._browser_detected_lbl.setText(f"Auto-detectado: {name}")
                self._browser_detected_lbl.setStyleSheet("color: #4CAF50; font-size: 11px;")
            else:
                self._browser_detected_lbl.setText(
                    "⚠ No se detectó ningún navegador Chromium (Chrome, Brave, Edge...)"
                )
                self._browser_detected_lbl.setStyleSheet("color: #FFC107; font-size: 11px;")

    # ── Handlers ─────────────────────────────────────────────────────────────

    def _on_radio_changed(self, btn_id):
        mapping = {0: "bgutil", 1: "wpc", 2: "none"}
        provider = mapping.get(btn_id, "bgutil")
        from core.utils.config_manager import get_config, save_config
        cfg = get_config()
        cfg["pot_provider"] = provider
        save_config(cfg)
        logger.info(f"POT Provider cambiado a: {provider}")
        self.provider_changed.emit(provider)

    def _on_browser_path_changed(self, text):
        from core.utils.config_manager import get_config, save_config
        cfg = get_config()
        cfg["pot_wpc_browser_path"] = text.strip()
        save_config(cfg)
        self._update_detected_label()

    def _pick_browser(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar ejecutable del navegador",
            "",
            "Ejecutables (*.exe);;Todos los archivos (*)" if platform.system() == "Windows"
            else "Todos los archivos (*)"
        )
        if path:
            self._browser_field.setText(path)

    def _on_bgutil_action(self):
        from core.setup.potprovider_setup import download_potprovider
        self._bgutil_btn.setDisabled(True)
        self._bgutil_btn.setText("Descargando...")

        class _BGWorker(QThread):
            done = Signal(bool, str)
            def run(self):
                ok, msg = download_potprovider()
                self.done.emit(ok, msg)

        self._bgutil_worker = _BGWorker()
        self._bgutil_worker.done.connect(self._on_bgutil_done)
        self._bgutil_worker.start()

    def _on_bgutil_done(self, ok, msg):
        self._refresh_status()
        if not ok:
            QMessageBox.warning(self, "Error", f"No se pudo descargar bgutil-pot:\n{msg}")

    def set_wpc_update_available(self, remote_ver):
        """Llamado tras 'Buscar Actualizaciones': habilita el botón de WPC como 'Actualizar'
        (con el mismo estilo que el resto de dependencias) solo si hay una versión remota
        más nueva que la instalada; si no, lo deja como 'Actualizado' y deshabilitado."""
        if not check_wpc():
            return

        local_ver = wpc_local() or ""
        if not remote_ver:
            return

        r_ver = str(remote_ver).strip().lstrip('v')
        l_ver = str(local_ver).strip().lstrip('v')

        if r_ver != l_ver and r_ver not in l_ver:
            self._wpc_status.setText(f"✓ Instalado  v{local_ver} (Nueva: {remote_ver})")
            self._wpc_status.setStyleSheet("color: #FFC107; font-weight: bold; font-size: 11px;")
            self._wpc_btn.setText("Actualizar")
            self._wpc_btn.setDisabled(False)
            self._wpc_btn.setStyleSheet("background-color: #007BFF; color: white; border: none; padding: 5px; border-radius: 4px;")
        else:
            self._wpc_status.setText(f"✓ Instalado  v{local_ver}")
            self._wpc_status.setStyleSheet("color: #4CAF50; font-size: 11px;")
            self._wpc_btn.setText("Actualizado")
            self._wpc_btn.setDisabled(True)
            self._wpc_btn.setStyleSheet("")

    def _on_wpc_action(self):
        self._wpc_btn.setDisabled(True)
        self._wpc_btn.setText("Instalando...")
        self._wpc_progress.setValue(0)
        self._wpc_progress.show()

        self._wpc_worker = WPCInstallWorker()
        self._wpc_worker.numeric_progress_signal.connect(self._wpc_progress.setValue)
        self._wpc_worker.finished_signal.connect(self._on_wpc_done)
        self._wpc_worker.start()

    def _on_wpc_done(self, ok, msg):
        self._wpc_progress.hide()
        self._wpc_btn.setDisabled(False)
        self._refresh_status()
        if not ok:
            QMessageBox.warning(self, "Error instalando WPC", msg)
        else:
            QMessageBox.information(self, "WPC instalado", msg)


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
            },
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

        # ── Panel selector de PO Token Provider ──
        self.pot_panel = POTProviderPanel()
        layout.addWidget(self.pot_panel)

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
        
        # Bottom Action Buttons Layout
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(10)
        bottom_layout.addStretch()
        
        # Botón para abrir la carpeta contenedora de dependencias
        self.btn_open_folder = QPushButton(self.tr("Abrir Carpeta"))
        self.btn_open_folder.setCursor(Qt.PointingHandCursor)
        self.btn_open_folder.setToolTip(self.tr("Abrir la carpeta donde se almacenan los binarios de las dependencias"))
        self.btn_open_folder.setStyleSheet(f"""
            QPushButton {{
                background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                color: {get_theme_token('texto_principal', '#ffffff')};
                border: 1px solid {get_theme_token('borde_normal', '#444444')};
                padding: 8px 18px;
                font-weight: bold;
                font-size: 12px;
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')};
                border-color: {get_theme_token('acento_primario', '#B9E640')};
            }}
        """)
        self.btn_open_folder.clicked.connect(self.open_dependencies_folder)
        bottom_layout.addWidget(self.btn_open_folder)

        # Botón para buscar actualizaciones (con contraste de texto mejorado)
        self.btn_check_updates = QPushButton(self.tr("Buscar Actualizaciones"))
        self.btn_check_updates.setCursor(Qt.PointingHandCursor)
        self.btn_check_updates.setStyleSheet("""
            QPushButton {
                background-color: #FF8C00; 
                color: #000000; 
                padding: 8px 20px; 
                font-weight: bold;
                font-size: 12px;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #FFA500;
                color: #000000;
            }
            QPushButton:disabled {
                background-color: #333333;
                color: #777777;
            }
        """)
        self.btn_check_updates.clicked.connect(self.check_all_updates)
        bottom_layout.addWidget(self.btn_check_updates)
        
        layout.addLayout(bottom_layout)

    def open_dependencies_folder(self):
        """Abre la carpeta de dependencias en el explorador de archivos."""
        try:
            deps_dir = os.path.dirname(get_ffmpeg_dir())
            if not os.path.exists(deps_dir):
                os.makedirs(deps_dir, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(deps_dir))
        except Exception as e:
            logger.error(f"Error abriendo la carpeta de dependencias: {e}")

    def check_all_updates(self):
        self.btn_check_updates.setDisabled(True)
        self.btn_check_updates.setText("Buscando...")
        
        for row in self.rows.values():
            if row.is_installed:
                row.version_label.setText(f"Versión: {row.local_ver} (Buscando...)")
        
        self.update_worker = UpdateCheckWorker(self.dependencies_config)
        self.update_worker.finished_signal.connect(self.on_update_check_finished)
        self.update_worker.start()

        # También comprobar si hay una actualización disponible para WPC (PO Token Provider)
        if check_wpc():
            self._wpc_update_worker = WPCUpdateCheckWorker()
            self._wpc_update_worker.finished_signal.connect(self.pot_panel.set_wpc_update_available)
            self._wpc_update_worker.start()

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
