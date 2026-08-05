from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea
from PySide6.QtCore import Qt
from core.utils.i18n import logger
from core.utils.config_manager import get_config, save_config
from gui.widgets.toggle_switch import ToggleSwitch


class DownloadsPage(QWidget):
    """Página de ajustes de Descargas."""

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
        self.title_label = QLabel(self.tr("Descargas"))
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

        # --- SECCIÓN: OPCIONES DE DESCARGA ---
        self.dl_section_label = QLabel(self.tr("Opciones de Descarga"))
        self.dl_section_label.setObjectName("settingsSectionTitle")
        self.content_layout.addWidget(self.dl_section_label)

        # 1. Switch: Incrustar Metadatos
        self.metadata_row = QHBoxLayout()
        self.metadata_vbox = QVBoxLayout()
        self.metadata_label = QLabel(self.tr("Incrustar Metadatos"))
        self.metadata_label.setObjectName("settingsLabel")
        self.metadata_desc = QLabel(self.tr("Añade información del video (título, autor, fecha) dentro del archivo multimedia."))
        self.metadata_desc.setStyleSheet("color: #888888; font-size: 11px;")
        self.metadata_vbox.addWidget(self.metadata_label)
        self.metadata_vbox.addWidget(self.metadata_desc)
        self.metadata_switch = ToggleSwitch()
        self.metadata_row.addLayout(self.metadata_vbox)
        self.metadata_row.addStretch()
        self.metadata_row.addWidget(self.metadata_switch)
        self.content_layout.addLayout(self.metadata_row)

        # 2. Switch: Incrustar Carátula
        self.thumb_row = QHBoxLayout()
        self.thumb_vbox = QVBoxLayout()
        self.thumb_label = QLabel(self.tr("Incrustar carátula"))
        self.thumb_label.setObjectName("settingsLabel")
        self.thumb_desc = QLabel(self.tr("Utiliza la miniatura del video como imagen de portada del archivo descargado."))
        self.thumb_desc.setStyleSheet("color: #888888; font-size: 11px;")
        self.thumb_vbox.addWidget(self.thumb_label)
        self.thumb_vbox.addWidget(self.thumb_desc)
        self.thumb_switch = ToggleSwitch()
        self.thumb_row.addLayout(self.thumb_vbox)
        self.thumb_row.addStretch()
        self.thumb_row.addWidget(self.thumb_switch)
        self.content_layout.addLayout(self.thumb_row)

        # 3. Switch: Eliminar Sponsors (SponsorBlock)
        self.sponsors_row = QHBoxLayout()
        self.sponsors_vbox = QVBoxLayout()
        self.sponsors_label = QLabel(self.tr("Eliminar sponsors"))
        self.sponsors_label.setObjectName("settingsLabel")
        self.sponsors_desc = QLabel(self.tr("Utiliza SponsorBlock para identificar y omitir segmentos publicitarios dentro del video."))
        self.sponsors_desc.setStyleSheet("color: #888888; font-size: 11px;")
        self.sponsors_vbox.addWidget(self.sponsors_label)
        self.sponsors_vbox.addWidget(self.sponsors_desc)
        self.sponsors_switch = ToggleSwitch()
        self.sponsors_row.addLayout(self.sponsors_vbox)
        self.sponsors_row.addStretch()
        self.sponsors_row.addWidget(self.sponsors_switch)
        self.content_layout.addLayout(self.sponsors_row)

        # Finalizar setup del scroll area
        self.scroll_area.setWidget(self.scroll_content)
        self.main_layout.addWidget(self.scroll_area)

        # Configuración de colores del switch (basado en tema)
        self.update_switch_colors()

        # Connections
        self.metadata_switch.toggled.connect(self.on_embed_metadata_toggled)
        self.thumb_switch.toggled.connect(self.on_embed_thumbnail_toggled)
        self.sponsors_switch.toggled.connect(self.on_remove_sponsors_toggled)

    def update_switch_colors(self):
        config = get_config()
        accent = "#B9E640" if config.get("theme") == "dark" else "#1DC038"
        self.metadata_switch.setTrackColors("#333333", accent)
        self.thumb_switch.setTrackColors("#333333", accent)
        self.sponsors_switch.setTrackColors("#333333", accent)

    def load_current_settings(self):
        config = get_config()
        self.metadata_switch.setChecked(config.get("embed_metadata", True))
        self.thumb_switch.setChecked(config.get("embed_thumbnail", True))
        self.sponsors_switch.setChecked(config.get("remove_sponsors", False))

    def on_embed_metadata_toggled(self, checked):
        if self._is_loading: return
        config = get_config()
        config["embed_metadata"] = checked
        save_config(config)
        logger.info(f"DownloadsPage: Incrustar metadatos cambiado a: {checked}")

    def on_embed_thumbnail_toggled(self, checked):
        if self._is_loading: return
        config = get_config()
        config["embed_thumbnail"] = checked
        save_config(config)
        logger.info(f"DownloadsPage: Incrustar carátula cambiado a: {checked}")

    def on_remove_sponsors_toggled(self, checked):
        if self._is_loading: return
        config = get_config()
        config["remove_sponsors"] = checked
        save_config(config)
        logger.info(f"DownloadsPage: Eliminar sponsors cambiado a: {checked}")
