from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                                 QFrame, QScrollArea, QPushButton, QSizePolicy, QCheckBox, QLineEdit, QFileDialog)
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QIcon, QPixmap
from core.services.editor_integration_manager import EditorIntegrationManager
from core.utils.config_manager import get_config, save_config
from core.utils.paths import get_src_dir
from gui.styles import apply_folder_browse_button_style
import os
import platform

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

        # --- SECCIÓN ADOBE (Premiere Pro / After Effects no existen en Linux) ---
        if platform.system() != "Linux":
            self.create_adobe_section()

        # --- SECCIÓN DAVINCI (Windows, Mac y Linux) ---
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
        
        import platform
        is_mac = platform.system() == "Darwin"
        
        pr_detected = self.detect_adobe_path("premiere")
        ae_detected = self.detect_adobe_path("aftereffects")
        
        pr_hint = "/Applications/Adobe Premiere Pro [Versión]/Adobe Premiere Pro [Versión].app" if is_mac else r"C:\Program Files\Adobe\Adobe Premiere Pro [Versión]\Adobe Premiere Pro.exe"
        ae_hint = "/Applications/Adobe After Effects [Versión]/Adobe After Effects [Versión].app" if is_mac else r"C:\Program Files\Adobe\Adobe After Effects [Versión]\Support Files\AfterFX.exe"
        
        # Premiere Pro Settings
        pr_layout = self.create_app_setting(
            app_id="premiere",
            app_name="Adobe Premiere Pro",
            icon_name="premiere pro.svg",
            default_path=pr_detected,
            placeholder_hint=pr_hint,
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
            default_path=ae_detected,
            placeholder_hint=ae_hint,
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
        
        sys_name = platform.system()
        dv_detected = self.detect_davinci_path()
        if sys_name == "Darwin":
            dv_hint = "/Applications/DaVinci Resolve/DaVinci Resolve.app"
        elif sys_name == "Linux":
            dv_hint = "/opt/resolve/bin/resolve"
        else:
            dv_hint = r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe"
        
        dv_layout = self.create_app_setting(
            app_id="davinci",
            app_name="DaVinci Resolve",
            icon_name="davinci resolve.svg",
            default_path=dv_detected or dv_hint,
            placeholder_hint=dv_hint,
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
        """Busca y devuelve la versión instalada más reciente de Premiere Pro o After Effects."""
        import platform
        import re
        sys_name = platform.system()

        def extract_version_score(text, filepath=""):
            # 1. Buscar año de 4 dígitos (ej: 2026, 2025, 2024...)
            year_match = re.search(r'(20\d\d)', text)
            if year_match:
                return int(year_match.group(1)) * 1000
            # 2. Buscar versión numérica (ej: 25.0, 24.1...)
            ver_match = re.search(r'(\d+(?:\.\d+)?)', text)
            if ver_match:
                try:
                    return int(float(ver_match.group(1)) * 10)
                except ValueError:
                    pass
            # 3. Fallback a la fecha de modificación del archivo
            if filepath and os.path.exists(filepath):
                try:
                    return int(os.path.getmtime(filepath) // 86400)
                except Exception:
                    pass
            return 1000

        candidates = []

        if sys_name == 'Windows':
            exe_name = "Adobe Premiere Pro.exe" if app_id == "premiere" else "Support Files\\AfterFX.exe"
            target_keyword = "premiere pro" if app_id == "premiere" else "after effects"

            # Paso 1: Consultar el Registro de Windows (App Paths registra la versión activa principal)
            try:
                import winreg
                reg_exe = "Adobe Premiere Pro.exe" if app_id == "premiere" else "AfterFX.exe"
                for root_key in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    try:
                        with winreg.OpenKey(root_key, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{reg_exe}") as key:
                            val, _ = winreg.QueryValueEx(key, "")
                            if val:
                                val = val.strip('"\'' )
                                if os.path.exists(val):
                                    score = extract_version_score(val, val)
                                    candidates.append((score, val))
                    except Exception:
                        pass
            except Exception:
                pass

            # Paso 2: Escanear Program Files en discos comunes
            possible_roots = [os.environ.get("ProgramFiles", r"C:\Program Files")]
            for drive in ("C", "D", "E"):
                d_path = f"{drive}:\\Program Files"
                if d_path not in possible_roots and os.path.exists(d_path):
                    possible_roots.append(d_path)

            for pf in possible_roots:
                adobe_base = os.path.join(pf, "Adobe")
                if not os.path.exists(adobe_base):
                    continue
                try:
                    for item in os.listdir(adobe_base):
                        if target_keyword in item.lower():
                            full_exe = os.path.join(adobe_base, item, exe_name)
                            if os.path.exists(full_exe):
                                score = extract_version_score(item, full_exe)
                                candidates.append((score, full_exe))
                except Exception:
                    pass

        elif sys_name == 'Darwin':
            target_keyword = "premiere pro" if app_id == "premiere" else "after effects"

            # Paso 1: Spotlight (mdfind) para localizar bundles .app al instante
            try:
                import subprocess
                kw_query = "Adobe Premiere Pro" if app_id == "premiere" else "Adobe After Effects"
                out = subprocess.check_output(['mdfind', f'kMDItemFSName == "{kw_query}*.app"'], text=True, errors='ignore').strip()
                for line in out.splitlines():
                    path = line.strip()
                    if path.endswith(".app") and os.path.exists(path):
                        score = extract_version_score(path, path)
                        candidates.append((score, path))
            except Exception:
                pass

            # Paso 2: Escanear /Applications y ~/Applications
            for base_apps in ("/Applications", os.path.expanduser("~/Applications")):
                if not os.path.exists(base_apps):
                    continue
                try:
                    for item in os.listdir(base_apps):
                        if target_keyword in item.lower():
                            full_item = os.path.join(base_apps, item)
                            if item.endswith(".app") and os.path.exists(full_item):
                                score = extract_version_score(item, full_item)
                                candidates.append((score, full_item))
                            elif os.path.isdir(full_item):
                                for sub in os.listdir(full_item):
                                    if target_keyword in sub.lower() and sub.endswith(".app"):
                                        app_bundle = os.path.join(full_item, sub)
                                        score = extract_version_score(item + " " + sub, app_bundle)
                                        candidates.append((score, app_bundle))
                except Exception:
                    pass

        if candidates:
            # Eliminar duplicados y ordenar por versión/año descendente
            seen = set()
            unique_candidates = []
            for score, path in candidates:
                norm = os.path.normpath(path)
                if norm not in seen:
                    seen.add(norm)
                    unique_candidates.append((score, norm))
            unique_candidates.sort(key=lambda x: x[0], reverse=True)
            return unique_candidates[0][1]

        return ""

    def detect_davinci_path(self):
        sys_name = platform.system()
        if sys_name == 'Windows':
            candidates = [
                r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe",
            ]
            for c in candidates:
                if os.path.exists(c):
                    return c
        elif sys_name == 'Darwin':
            candidates = [
                "/Applications/DaVinci Resolve/DaVinci Resolve.app",
                "/Applications/DaVinci Resolve Studio/DaVinci Resolve Studio.app",
                "/Applications/DaVinci Resolve.app",
            ]
            for c in candidates:
                if os.path.exists(c):
                    return c
        elif sys_name == 'Linux':
            candidates = [
                "/opt/resolve/bin/resolve",
                "/home/resolve/bin/resolve",
            ]
            for c in candidates:
                if os.path.exists(c):
                    return c
        return ""
        
    def create_app_setting(self, app_id, app_name, icon_name, default_path, is_enabled, current_path, placeholder_hint=""):
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
        placeholder = default_path or placeholder_hint or self.tr("Seleccionar ruta...")
        path_input.setPlaceholderText(placeholder)
        path_input.setText(current_path)
        
        # Autodetect if empty and enabled and default_path exists on disk
        if is_enabled and not current_path and default_path and os.path.exists(default_path):
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
        checkbox.toggled.connect(lambda checked: self._on_app_toggled(app_id, checked, icon_lbl, path_input, btn_browse, default_path))
        path_input.setEnabled(is_enabled)
        btn_browse.setEnabled(is_enabled)
        
        # Attach icon_lbl to layout object for later reference
        layout.icon_lbl = icon_lbl
        
        return layout
        
    def _browse_exe(self, app_id, line_edit):
        sys_name = platform.system()
        if sys_name == "Darwin":
            start_dir = "/Applications"
            filter_str = "Aplicaciones (*.app);;Todos los archivos (*)"
        elif sys_name == "Linux":
            start_dir = "/opt/resolve/bin" if os.path.exists("/opt/resolve/bin") else "/opt"
            filter_str = "Todos los archivos (*)"
        else:
            start_dir = "C:\\Program Files"
            filter_str = "Ejecutables (*.exe);;Todos los archivos (*.*)"
        file_path, _ = QFileDialog.getOpenFileName(self, self.tr("Seleccionar Ejecutable"), start_dir, filter_str)
        if file_path:
            file_path = os.path.normpath(file_path)
            line_edit.setText(file_path)
            self._save_integration_setting(app_id, "path", file_path)
            
    def _on_app_toggled(self, app_id, checked, icon_lbl, path_input, btn_browse, default_path):
        self._save_integration_setting(app_id, "enabled", checked)
        self.set_icon(icon_lbl, icon_lbl.property("icon_name") or f"{app_id}.svg", opacity=1.0 if checked else 0.3)
        path_input.setEnabled(checked)
        btn_browse.setEnabled(checked)
        
        # Auto-fill if enabling and empty and path exists
        if checked and not path_input.text() and default_path and os.path.exists(default_path):
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
        icon_path = os.path.join(get_src_dir(), "assets", "icons", "svg", icon_name)
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path).scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            label.setPixmap(pixmap)
            
            from PySide6.QtWidgets import QGraphicsOpacityEffect
            effect = QGraphicsOpacityEffect(label)
            effect.setOpacity(opacity)
            label.setGraphicsEffect(effect)

    def update_adobe_status(self, active_editor):
        if not hasattr(self, 'lbl_icon_pr'):
            # Sección Adobe no creada (Linux: Premiere/After Effects no existen)
            return
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

