from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea
from PySide6.QtCore import Qt
from core.utils.i18n import logger
from core.utils.config_manager import get_config, save_config
from gui.widgets.toggle_switch import ToggleSwitch


class NetworkPage(QWidget):
    """Página de ajustes de Conexión y Red."""

    def __init__(self):
        super().__init__()
        self._is_loading = True
        self.init_ui()
        self.load_current_settings()
        self._is_loading = False

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(12)

        # Title
        self.title_label = QLabel(self.tr("Conexión y Red"))
        self.title_label.setObjectName("settingsTitle")
        self.main_layout.addWidget(self.title_label)

        # Divider
        line = QFrame()
        line.setObjectName("settingsDivider")
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        self.main_layout.addWidget(line)

        # Crear el QScrollArea
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("background-color: transparent;")

        # Widget contenedor para el contenido del scroll
        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("settingsScrollContent")
        self.scroll_content.setStyleSheet("QWidget#settingsScrollContent { background-color: transparent; }")

        # Layout para el contenido del scroll
        self.content_layout = QVBoxLayout(self.scroll_content)
        self.content_layout.setContentsMargins(0, 10, 10, 0)
        self.content_layout.setSpacing(12)
        self.content_layout.setAlignment(Qt.AlignTop)

        # --- SECCIÓN: RED ---
        self.net_label = QLabel(self.tr("Red"))
        self.net_label.setObjectName("settingsSectionTitle")
        self.content_layout.addWidget(self.net_label)

        # Switch: Impersonate
        self.imp_row = QHBoxLayout()
        self.imp_vbox = QVBoxLayout()

        self.imp_label = QLabel(self.tr("Usar Impersonate (Disfraz de Navegador)"))
        self.imp_label.setObjectName("settingsLabel")

        self.imp_desc = QLabel(self.tr("Evita bloqueos de YouTube simulando ser Chrome. (Puede ser más lento)"))
        self.imp_desc.setStyleSheet("color: #888888; font-size: 11px;")

        self.imp_vbox.addWidget(self.imp_label)
        self.imp_vbox.addWidget(self.imp_desc)

        self.imp_switch = ToggleSwitch()

        self.imp_row.addLayout(self.imp_vbox)
        self.imp_row.addStretch()
        self.imp_row.addWidget(self.imp_switch)
        self.content_layout.addLayout(self.imp_row)

        # Finalizar setup del scroll area
        self.scroll_area.setWidget(self.scroll_content)
        self.main_layout.addWidget(self.scroll_area)

        # Configuración de colores del switch (basado en tema)
        self.update_switch_colors()

        # Connections
        self.imp_switch.toggled.connect(self.on_impersonate_toggled)

    def update_switch_colors(self):
        config = get_config()
        accent = "#B9E640" if config.get("theme") == "dark" else "#1DC038"
        self.imp_switch.setTrackColors("#333333", accent)

    def load_current_settings(self):
        config = get_config()
        self.imp_switch.setChecked(config.get("use_impersonate", False))

    def on_impersonate_toggled(self, checked):
        if self._is_loading: return
        config = get_config()
        config["use_impersonate"] = checked
        save_config(config)
        logger.info(f"NetworkPage: Uso de Impersonate cambiado a: {checked}")
