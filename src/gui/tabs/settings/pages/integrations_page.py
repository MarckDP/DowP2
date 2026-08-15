from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                                 QFrame, QScrollArea, QPushButton, QSizePolicy, QCheckBox, QLineEdit, QFileDialog)
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QIcon, QPixmap
from core.services.editor_integration_manager import EditorIntegrationManager
from core.utils.config_manager import get_config, save_config
from gui.styles import apply_folder_browse_button_style
import os

class IntegrationsPage(QWidget):
    """Página de ajustes de Integraciones para NLEs."""

    integration_toggled = Signal(str, bool)  # (app_id, enabled)

    def __init__(self):
        super().__init__()
        self.init_ui()
        
        # Conectar al EditorIntegrationManager
        self.editor_mgr = EditorIntegrationManager.get_instance()
        if self.editor_mgr:
            self.editor_mgr.active_editor_changed.connect(self.update_adobe_status)
            self.update_adobe_status(self.editor_mgr.active_editor)

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(12)

        # Title
        self.title_label = QLabel(self.tr("Integraciones"))
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
        self.content_layout.setSpacing(20)
        self.content_layout.setAlignment(Qt.AlignTop)

        # --- SECCIÓN ADOBE ---
        self.create_adobe_section()
        
        # --- SECCIÓN DAVINCI (Placeholder) ---
        self.create_davinci_section()

        self.content_layout.addStretch(1)

        # Finalizar setup del scroll area
        self.scroll_area.setWidget(self.scroll_content)
        self.main_layout.addWidget(self.scroll_area)
        
    def create_card_frame(self):
        card = QFrame()
        card.setObjectName("settingsCard")
        return card

    def create_adobe_section(self):
        self.adobe_card = self.create_card_frame()
        card_layout = QVBoxLayout(self.adobe_card)
        card_layout.setContentsMargins(15, 15, 15, 15)
        card_layout.setSpacing(15)
        
        # Header (Title + Status)
        header_layout = QHBoxLayout()
        title = QLabel(self.tr("Adobe Premiere Pro & After Effects"))
        title.setObjectName("settingsSectionTitle")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        
        self.adobe_status_lbl = QLabel(self.tr("Desconectado"))
        self.adobe_status_lbl.setStyleSheet("color: #ff5555; font-weight: bold;")
        
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.adobe_status_lbl)
        card_layout.addLayout(header_layout)
        
        # Cargar configuración
        config = get_config()
        integrations = config.get('integrations', {})
        
        pr_default = self.detect_adobe_path("premiere") or "C:\\Program Files\\Adobe\\Adobe Premiere Pro 2024\\Adobe Premiere Pro.exe"
        ae_default = self.detect_adobe_path("aftereffects") or "C:\\Program Files\\Adobe\\Adobe After Effects 2024\\Support Files\\AfterFX.exe"
        
        # Premiere Pro Settings
        pr_layout = self.create_app_setting(
            app_id="premiere",
            app_name="Adobe Premiere Pro",
            icon_name="premiere pro.svg",
            default_path=pr_default,
            is_enabled=integrations.get('premiere_enabled', False),
            current_path=integrations.get('premiere_path', '')
        )
        card_layout.addLayout(pr_layout)
        
        card_layout.addSpacing(10)
        
        # After Effects Settings
        ae_layout = self.create_app_setting(
            app_id="aftereffects",
            app_name="Adobe After Effects",
            icon_name="after effects.svg",
            default_path=ae_default,
            is_enabled=integrations.get('aftereffects_enabled', False),
            current_path=integrations.get('aftereffects_path', '')
        )
        card_layout.addLayout(ae_layout)
        
        # Description
        desc = QLabel(self.tr("Instala la extensión DowP Importer en Premiere o After Effects. Activa los interruptores arriba y configura la ruta para lanzar las aplicaciones desde DowP."))
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #aaaaaa; margin-top: 10px;")
        card_layout.addWidget(desc)
        
        # Mantener referencias para estado visual (compatibilidad anterior por ahora)
        self.lbl_icon_pr = pr_layout.icon_lbl
        self.lbl_icon_ae = ae_layout.icon_lbl
        
        self.content_layout.addWidget(self.adobe_card)

    def create_davinci_section(self):
        self.davinci_card = self.create_card_frame()
        card_layout = QVBoxLayout(self.davinci_card)
        card_layout.setContentsMargins(15, 15, 15, 15)
        card_layout.setSpacing(15)
        
        # Header
        header_layout = QHBoxLayout()
        title = QLabel(self.tr("DaVinci Resolve"))
        title.setObjectName("settingsSectionTitle")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        
        self.davinci_status_lbl = QLabel(self.tr("Desconectado"))
        self.davinci_status_lbl.setStyleSheet("color: #ff5555; font-weight: bold;")
        
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.davinci_status_lbl)
        card_layout.addLayout(header_layout)
        
        # Cargar configuración
        config = get_config()
        integrations = config.get('integrations', {})
        
        dv_layout = self.create_app_setting(
            app_id="davinci",
            app_name="DaVinci Resolve",
            icon_name="davinci resolve.svg",
            default_path="C:\\Program Files\\Blackmagic Design\\DaVinci Resolve\\Resolve.exe",
            is_enabled=integrations.get('davinci_enabled', False),
            current_path=integrations.get('davinci_path', '')
        )
        card_layout.addLayout(dv_layout)
        
        # Configuración adicional de DaVinci (Timeline, Carpetas, etc)
        settings_layout = QVBoxLayout()
        settings_layout.setContentsMargins(40, 10, 0, 0)
        settings_layout.setSpacing(10)
        
        self.cb_dv_timeline = QCheckBox(self.tr("Importar automáticamente a la línea de tiempo (Playhead)"))
        self.cb_dv_timeline.setChecked(integrations.get('davinci_import_timeline', True))
        self.cb_dv_timeline.toggled.connect(lambda checked: self._save_integration_setting("davinci", "import_timeline", checked))
        settings_layout.addWidget(self.cb_dv_timeline)
        
        self.cb_dv_images_timeline = QCheckBox(self.tr("Importar también imágenes a la línea de tiempo"))
        self.cb_dv_images_timeline.setChecked(integrations.get('davinci_import_images_timeline', False))
        self.cb_dv_images_timeline.toggled.connect(lambda checked: self._save_integration_setting("davinci", "import_images_timeline", checked))
        settings_layout.addWidget(self.cb_dv_images_timeline)
        
        self.cb_dv_folders = QCheckBox(self.tr("Crear estructura de carpetas (DowP Imports / Audio / Video)"))
        self.cb_dv_folders.setChecked(integrations.get('davinci_create_folders', True))
        self.cb_dv_folders.toggled.connect(lambda checked: self._save_integration_setting("davinci", "create_folders", checked))
        settings_layout.addWidget(self.cb_dv_folders)
        
        card_layout.addLayout(settings_layout)
        
        desc = QLabel(self.tr("La integración de DaVinci usa la API nativa de scripting. Asegúrate de tener DaVinci abierto y permitir scripts (Preferencias -> Sistema -> General -> External scripting = Local)."))
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #aaaaaa; margin-top: 10px;")
        card_layout.addWidget(desc)
        
        self.content_layout.addWidget(self.davinci_card)
        self.lbl_icon_dv = dv_layout.icon_lbl
        
    def detect_adobe_path(self, app_id):
        import platform
        if platform.system() != 'Windows':
            return ""
            
        base_path = "C:\\Program Files\\Adobe"
        if not os.path.exists(base_path):
            return ""
            
        candidates = []
        target_folder_keyword = "Premiere Pro" if app_id == "premiere" else "After Effects"
        exe_name = "Adobe Premiere Pro.exe" if app_id == "premiere" else "Support Files\\AfterFX.exe"
        
        try:
            for item in os.listdir(base_path):
                if target_folder_keyword in item:
                    full_exe_path = os.path.join(base_path, item, exe_name)
                    if os.path.exists(full_exe_path):
                        import re
                        match = re.search(r'\d{4}', item)
                        year = int(match.group()) if match else 2000
                        candidates.append((year, full_exe_path))
        except Exception:
            pass
            
        if candidates:
            # Sort by year descending and return the highest
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]
            
        return ""
        
    def create_app_setting(self, app_id, app_name, icon_name, default_path, is_enabled, current_path):
        layout = QVBoxLayout()
        layout.setSpacing(8)
        
        # Top row: Checkbox + Icon
        top_row = QHBoxLayout()
        
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(32, 32)
        self.set_icon(icon_lbl, icon_name, opacity=1.0 if is_enabled else 0.3)
        
        checkbox = QCheckBox(f"Activar acceso directo a {app_name}")
        checkbox.setChecked(is_enabled)
        checkbox.setStyleSheet("font-weight: bold; font-size: 14px;")
        
        top_row.addWidget(icon_lbl)
        top_row.addWidget(checkbox)
        top_row.addStretch()
        layout.addLayout(top_row)
        
        # Bottom row: Path input
        path_row = QHBoxLayout()
        path_row.setContentsMargins(40, 0, 0, 0) # Indent
        
        path_input = QLineEdit()
        path_input.setPlaceholderText(default_path)
        path_input.setText(current_path)
        
        # Autodetect if empty and enabled
        if is_enabled and not current_path and os.path.exists(default_path):
            path_input.setText(default_path)
            self._save_integration_setting(app_id, "path", default_path)
            
        path_input.textChanged.connect(lambda text: self._save_integration_setting(app_id, "path", text))
        
        btn_browse = QPushButton()
        btn_browse.setFixedSize(32, 32)
        btn_browse.setCursor(Qt.PointingHandCursor)
        apply_folder_browse_button_style(btn_browse, self.tr("Seleccionar ejecutable"))
        btn_browse.clicked.connect(lambda: self._browse_exe(app_id, path_input))
        
        path_row.addWidget(QLabel("Ruta:"))
        path_row.addWidget(path_input, 1)
        path_row.addWidget(btn_browse)
        layout.addLayout(path_row)
        
        # Connect checkbox
        checkbox.toggled.connect(lambda checked: self._on_app_toggled(app_id, checked, icon_lbl, path_input, default_path))
        path_input.setEnabled(is_enabled)
        btn_browse.setEnabled(is_enabled)
        
        # Attach icon_lbl to layout object for later reference
        layout.icon_lbl = icon_lbl
        
        return layout
        
    def _browse_exe(self, app_id, line_edit):
        file_path, _ = QFileDialog.getOpenFileName(self, self.tr("Seleccionar Ejecutable"), "C:\\Program Files", "Ejecutables (*.exe *.app)")
        if file_path:
            file_path = os.path.normpath(file_path)
            line_edit.setText(file_path)
            self._save_integration_setting(app_id, "path", file_path)
            
    def _on_app_toggled(self, app_id, checked, icon_lbl, path_input, default_path):
        self._save_integration_setting(app_id, "enabled", checked)
        self.set_icon(icon_lbl, icon_lbl.property("icon_name") or f"{app_id}.svg", opacity=1.0 if checked else 0.3)
        path_input.setEnabled(checked)
        
        # Auto-fill if enabling and empty
        if checked and not path_input.text() and os.path.exists(default_path):
            path_input.setText(default_path)

        # Notificar a la ventana principal para que el ícono en la esquina superior
        # derecha aparezca/desaparezca de inmediato, sin requerir reiniciar la app.
        self.integration_toggled.emit(app_id, checked)

    def _save_integration_setting(self, app_id, key, value):
        config = get_config()
        if 'integrations' not in config:
            config['integrations'] = {}
            
        config_key = f"{app_id}_{key}"
        config['integrations'][config_key] = value
        save_config(config)
        
    def set_icon(self, label, icon_name, opacity=1.0, size=32):
        # Asegurar que el icono existe
        label.setProperty("icon_name", icon_name) # Guardar nombre para restaurar luego
        icon_path = os.path.join("src", "assets", "icons", "svg", icon_name)
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path).scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            label.setPixmap(pixmap)
            
            from PySide6.QtWidgets import QGraphicsOpacityEffect
            effect = QGraphicsOpacityEffect(label)
            effect.setOpacity(opacity)
            label.setGraphicsEffect(effect)

    def update_adobe_status(self, active_editor):
        if active_editor == 'premiere':
            self.adobe_status_lbl.setText(self.tr("Conectado (Premiere Pro)"))
            self.adobe_status_lbl.setStyleSheet("color: #55ff55; font-weight: bold;")
            self.set_icon(self.lbl_icon_pr, "premiere pro.svg", opacity=1.0)
            self.set_icon(self.lbl_icon_ae, "after effects.svg", opacity=0.3)
        elif active_editor == 'aftereffects':
            self.adobe_status_lbl.setText(self.tr("Conectado (After Effects)"))
            self.adobe_status_lbl.setStyleSheet("color: #55ff55; font-weight: bold;")
            self.set_icon(self.lbl_icon_pr, "premiere pro.svg", opacity=0.3)
            self.set_icon(self.lbl_icon_ae, "after effects.svg", opacity=1.0)
        else:
            self.adobe_status_lbl.setText(self.tr("Desconectado"))
            self.adobe_status_lbl.setStyleSheet("color: #ff5555; font-weight: bold;")
            self.set_icon(self.lbl_icon_pr, "premiere pro.svg", opacity=0.3)
            self.set_icon(self.lbl_icon_ae, "after effects.svg", opacity=0.3)

    def force_target(self, target_app):
        from gui.dialogs.dialogs import show_info
        if self.editor_mgr:
            success = self.editor_mgr.force_adobe_target(target_app)
            if not success:
                show_info(self, self.tr("DowP Importer"), self.tr(f"No se detecta conexión con {target_app}. Asegúrate de tener la extensión abierta."))

