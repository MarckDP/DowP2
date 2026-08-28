from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, 
                                 QSpacerItem, QSizePolicy, QStyledItemDelegate, QScrollArea, 
                                 QPushButton, QMessageBox, QToolButton)
from PySide6.QtCore import Signal, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from core.logger.logger_manager import logger
from core.utils.config_manager import get_config, save_config
from core.utils.paths import get_user_themes_dir, get_user_fonts_dir
from core.utils.font_manager import get_available_fonts, init_fonts
from gui.styles import get_available_themes, apply_folder_open_button_style
from gui.widgets.toggle_switch import ToggleSwitch
from gui.widgets.combo_box import AutoPopupComboBox

class GeneralPage(QWidget):
    language_changed = Signal(str)
    theme_changed = Signal(str)
    font_changed = Signal(str)

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
        self.title_label = QLabel(self.tr("Ajustes Generales"))
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
        self.scroll_area.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")
        
        # Widget contenedor para el contenido del scroll
        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("settingsScrollContent")
        self.scroll_content.setStyleSheet("QWidget#settingsScrollContent { background-color: transparent; }")
        
        # Layout para el contenido del scroll
        self.content_layout = QVBoxLayout(self.scroll_content)
        self.content_layout.setContentsMargins(0, 10, 10, 0)
        self.content_layout.setSpacing(12)
        self.content_layout.setAlignment(Qt.AlignTop)

        # --- SECCIÓN: ASPECTO ---
        self.aspecto_label = QLabel(self.tr("Aspecto"))
        self.aspecto_label.setObjectName("settingsSectionTitle")
        self.content_layout.addWidget(self.aspecto_label)

        # 1. Idioma
        self.lang_row = QHBoxLayout()
        self.lang_label = QLabel(self.tr("Idioma de la aplicación"))
        self.lang_label.setObjectName("settingsLabel")
        
        self.lang_combo = AutoPopupComboBox()
        self.lang_combo.setFixedWidth(180)
        self.lang_combo.addItem("Español", "es")
        self.lang_combo.addItem("English", "en")
        
        self.lang_row.addWidget(self.lang_label)
        self.lang_row.addStretch()
        self.lang_row.addWidget(self.lang_combo)
        self.content_layout.addLayout(self.lang_row)

        # 2. Tema
        self.theme_row = QHBoxLayout()
        self.theme_label = QLabel(self.tr("Tema visual"))
        self.theme_label.setObjectName("settingsLabel")
        
        self.theme_combo = AutoPopupComboBox()
        self.theme_combo.setFixedWidth(180)
        
        self.btn_open_themes = QPushButton()
        self.btn_open_themes.setFixedSize(30, 30)
        apply_folder_open_button_style(self.btn_open_themes, tooltip=self.tr("Abrir carpeta de temas personalizados (%APPDATA%/DowP2/themes)"), icon_size=15)
        self.btn_open_themes.clicked.connect(self._open_user_themes_dir)

        self.theme_row.addWidget(self.theme_label)
        self.theme_row.addStretch()
        self.theme_row.addWidget(self.theme_combo)
        self.theme_row.addWidget(self.btn_open_themes)
        self.content_layout.addLayout(self.theme_row)

        # 3. Tipografía / Fuente
        self.font_row = QHBoxLayout()
        self.font_label = QLabel(self.tr("Tipografía / Fuente"))
        self.font_label.setObjectName("settingsLabel")
        
        self.font_combo = AutoPopupComboBox()
        self.font_combo.setFixedWidth(180)

        self.btn_open_fonts = QPushButton()
        self.btn_open_fonts.setFixedSize(30, 30)
        apply_folder_open_button_style(self.btn_open_fonts, tooltip=self.tr("Abrir carpeta de fuentes personalizadas (%APPDATA%/DowP2/fonts)"), icon_size=15)
        self.btn_open_fonts.clicked.connect(self._open_user_fonts_dir)

        self.font_row.addWidget(self.font_label)
        self.font_row.addStretch()
        self.font_row.addWidget(self.font_combo)
        self.font_row.addWidget(self.btn_open_fonts)
        self.content_layout.addLayout(self.font_row)

        # --- SECCIÓN: COMPORTAMIENTO ---
        self.comp_label = QLabel(self.tr("Comportamiento"))
        self.comp_label.setObjectName("settingsSectionTitle")
        self.content_layout.addWidget(self.comp_label)

        # 3. Switch: Análisis automático
        self.auto_row = QHBoxLayout()
        self.auto_label = QLabel(self.tr("Analizar automáticamente al pegar URL"))
        self.auto_label.setObjectName("settingsLabel")
        
        self.auto_switch = ToggleSwitch()
        self.auto_row.addWidget(self.auto_label)
        self.auto_row.addStretch()
        self.auto_row.addWidget(self.auto_switch)
        self.content_layout.addLayout(self.auto_row)

        # 4. Switch: Auto-pegar URL del portapapeles
        self.paste_row = QHBoxLayout()
        self.paste_vbox = QVBoxLayout()
        
        self.paste_label = QLabel(self.tr("Auto-pegar URL del portapapeles"))
        self.paste_label.setObjectName("settingsLabel")
        
        self.paste_desc = QLabel(self.tr("Al volver a la ventana, pega automáticamente la URL copiada en el campo de análisis."))
        self.paste_desc.setStyleSheet("color: #888888; font-size: 11px;")
        
        self.paste_vbox.addWidget(self.paste_label)
        self.paste_vbox.addWidget(self.paste_desc)
        
        self.paste_switch = ToggleSwitch()
        
        self.paste_row.addLayout(self.paste_vbox)
        self.paste_row.addStretch()
        self.paste_row.addWidget(self.paste_switch)
        self.content_layout.addLayout(self.paste_row)

        # 5. Switch: Compatibilidad Adobe (Selección predeterminada)
        self.adobe_row = QHBoxLayout()
        self.adobe_vbox = QVBoxLayout()
        
        self.adobe_label = QLabel(self.tr("Selección predeterminada para Adobe"))
        self.adobe_label.setObjectName("settingsLabel")
        
        self.adobe_desc = QLabel(self.tr("Si está activo, preseleccionará el formato más compatible (✨). Si no, la mejor calidad absoluta."))
        self.adobe_desc.setStyleSheet("color: #888888; font-size: 11px;") # Compact description
        
        self.adobe_vbox.addWidget(self.adobe_label)
        self.adobe_vbox.addWidget(self.adobe_desc)
        
        self.adobe_switch = ToggleSwitch()
        
        self.adobe_row.addLayout(self.adobe_vbox)
        self.adobe_row.addStretch()
        self.adobe_row.addWidget(self.adobe_switch)
        self.content_layout.addLayout(self.adobe_row)

        # Finalizar setup del scroll area
        self.scroll_area.setWidget(self.scroll_content)
        self.main_layout.addWidget(self.scroll_area)

        # Configuración de colores del switch (basado en tema)
        self.update_switch_colors()

        # Connections
        self.lang_combo.currentIndexChanged.connect(self.on_language_selection)
        self.theme_combo.currentIndexChanged.connect(self.on_theme_selection)
        self.font_combo.currentIndexChanged.connect(self.on_font_selection)
        self.auto_switch.toggled.connect(self.on_auto_analyze_toggled)
        self.paste_switch.toggled.connect(self.on_auto_paste_toggled)
        self.adobe_switch.toggled.connect(self.on_adobe_compat_toggled)


    def _open_user_themes_dir(self):
        """Abre la carpeta de temas personalizados del usuario en el explorador de archivos."""
        themes_dir = get_user_themes_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(themes_dir))
        logger.info(f"GeneralPage: Abierta carpeta de temas: {themes_dir}")

    def _open_user_fonts_dir(self):
        """Abre la carpeta de fuentes personalizadas del usuario en el explorador de archivos."""
        fonts_dir = get_user_fonts_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(fonts_dir))
        logger.info(f"GeneralPage: Abierta carpeta de fuentes: {fonts_dir}")

    def _populate_themes(self):
        """Carga los temas disponibles dinámicamente."""
        self.theme_combo.blockSignals(True)
        self.theme_combo.clear()
        themes = get_available_themes()
        for t in themes:
            self.theme_combo.addItem(t["name"], t["id"])
        self.theme_combo.blockSignals(False)

    def _populate_fonts(self):
        """Carga las fuentes disponibles dinámicamente."""
        self.font_combo.blockSignals(True)
        self.font_combo.clear()
        self.font_combo.addItem(self.tr("Por defecto del tema"), "theme_default")
        
        fonts = get_available_fonts()
        for f in fonts:
            self.font_combo.addItem(f, f)
        self.font_combo.blockSignals(False)

    def update_switch_colors(self):
        config = get_config()
        accent = "#B9E640" if config.get("theme") == "dark" else "#1DC038"
        self.auto_switch.setTrackColors("#333333", accent)
        self.paste_switch.setTrackColors("#333333", accent)
        self.adobe_switch.setTrackColors("#333333", accent)

    def load_current_settings(self):
        config = get_config()
        
        # Load Language
        lang = config.get("language", "es")
        index = self.lang_combo.findData(lang)
        if index >= 0:
            self.lang_combo.setCurrentIndex(index)
            
        # Load Themes
        self._populate_themes()
        theme = config.get("theme", "dark")
        index = self.theme_combo.findData(theme)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)
            
        # Load Fonts
        self._populate_fonts()
        font_family = config.get("font_family", "theme_default")
        index = self.font_combo.findData(font_family)
        if index >= 0:
            self.font_combo.setCurrentIndex(index)
        else:
            self.font_combo.setCurrentIndex(0) # fallback a por defecto
            
        # Load Switches
        self.auto_switch.setChecked(config.get("auto_analyze", True))
        self.paste_switch.setChecked(config.get("auto_paste_url", True))
        self.adobe_switch.setChecked(config.get("adobe_compat_default", True))

    def on_language_selection(self, index):
        if self._is_loading: return
        lang_code = self.lang_combo.itemData(index)
        config = get_config()
        if config.get("language") != lang_code:
            config["language"] = lang_code
            save_config(config)
            logger.info(f"GeneralPage: Idioma guardado: {lang_code}. Reinicio requerido.")
            self.language_changed.emit(lang_code)

    def on_theme_selection(self, index):
        if self._is_loading: return
        theme_code = self.theme_combo.itemData(index)
        if not theme_code: return
        config = get_config()
        if config.get("theme") != theme_code:
            config["theme"] = theme_code
            save_config(config)
            self.update_switch_colors()
            logger.info(f"GeneralPage: Tema cambiado a {theme_code}")
            self.theme_changed.emit(theme_code)

    def on_font_selection(self, index):
        if self._is_loading: return
        font_code = self.font_combo.itemData(index)
        if font_code is None: return
        config = get_config()
        if config.get("font_family") != font_code:
            config["font_family"] = font_code
            save_config(config)
            logger.info(f"GeneralPage: Tipografía cambiada a {font_code}")
            self.font_changed.emit(font_code)

    def on_auto_analyze_toggled(self, checked):
        if self._is_loading: return
        config = get_config()
        config["auto_analyze"] = checked
        save_config(config)
        logger.info(f"GeneralPage: Auto-análisis cambiado a: {checked}")

    def on_auto_paste_toggled(self, checked):
        if self._is_loading: return
        config = get_config()
        config["auto_paste_url"] = checked
        save_config(config)
        # Actualizar el monitor en tiempo real
        from core.utils.clipboard_monitor import ClipboardURLMonitor
        ClipboardURLMonitor.instance().set_enabled(checked)
        logger.info(f"GeneralPage: Auto-pegar URL cambiado a: {checked}")

    def on_adobe_compat_toggled(self, checked):
        if self._is_loading: return
        config = get_config()
        config["adobe_compat_default"] = checked
        save_config(config)
        logger.info(f"GeneralPage: Selección Adobe por defecto cambiada a: {checked}")
