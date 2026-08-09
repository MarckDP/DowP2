# src/gui/main_window.py
import sys
import os
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QTabWidget, QApplication, QHBoxLayout, QPushButton
from PySide6.QtCore import Qt, QPoint, QSize
from PySide6.QtGui import QIcon
from core.logger.logger_manager import logger
from gui.styles import load_stylesheet
from gui.widgets.title_bar import CustomTitleBar
from core.utils.i18n import load_language
from core.utils.config_manager import get_config

# Import Tab Views
from gui.tabs.advanced_process.advanced_process_view import AdvancedProcessTab
from gui.tabs.quick_mode.quick_mode_view import QuickModeTab
from gui.tabs.image_tools.image_tools_view import ImageToolsTab
from gui.tabs.video_tools.video_tools_view import VideoToolsTab
from gui.tabs.editing_media.editing_media_view import EditingMediaTab
from gui.tabs.settings.settings_view import SettingsTab

class EditorStatusCornerWidget(QWidget):
    """Widget de la esquina superior derecha para el control global de NLEs."""
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        from PySide6.QtWidgets import QHBoxLayout, QPushButton, QLabel, QGraphicsOpacityEffect
        from PySide6.QtGui import QIcon, QPixmap
        from PySide6.QtCore import Qt, QSize
        import os
        import subprocess
        from PySide6.QtWidgets import QHBoxLayout, QPushButton
        from PySide6.QtGui import QIcon
        from PySide6.QtCore import Qt, QSize
        import os
        
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(5, 2, 10, 2)
        self.layout.setSpacing(5)
        
        self.btn_toggle = QPushButton()
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.setChecked(True)
        self.btn_toggle.setFixedSize(QSize(28, 28))
        self.btn_toggle.setCursor(Qt.PointingHandCursor)
        
        self.btn_settings = QPushButton()
        self.btn_settings.setFixedSize(QSize(28, 28))
        self.btn_settings.setCursor(Qt.PointingHandCursor)
        self.btn_settings.setToolTip("Ajustes de Integraciones")
        
        base_dir = os.path.dirname(os.path.abspath(__file__))
        icons_dir = os.path.join(os.path.dirname(base_dir), "assets", "icons", "svg")
        self.btn_settings.setIcon(QIcon(os.path.join(icons_dir, "settings.svg")))
        
        self._icon_green = QIcon(os.path.join(icons_dir, "check_circle_green.svg"))
        self._icon_yellow = QIcon(os.path.join(icons_dir, "warning.svg")) # or some other icon
        self._icon_red = QIcon(os.path.join(icons_dir, "error_red.svg"))
        self._icon_off = QIcon(os.path.join(icons_dir, "pause.svg"))
        
        self.btn_toggle.toggled.connect(self.on_toggle)
        self.btn_settings.clicked.connect(self.on_settings_clicked)
        
        # Diccionario para almacenar los iconos de apps
        self.app_icons = {}
        
        # Cargar configuración para ver qué apps están habilitadas
        config = get_config()
        integrations = config.get('integrations', {})
        
        apps = [
            ("premiere", "premiere pro.svg", "Adobe Premiere Pro"),
            ("aftereffects", "after effects.svg", "Adobe After Effects"),
            ("davinci", "davinci resolve.svg", "DaVinci Resolve")
        ]
        
        for app_id, svg_name, app_name in apps:
            is_enabled = integrations.get(f"{app_id}_enabled", False)
            if is_enabled:
                lbl = QLabel()
                lbl.setFixedSize(28, 28)
                lbl.setAlignment(Qt.AlignCenter)
                lbl.setCursor(Qt.PointingHandCursor)
                lbl.setToolTip(f"{app_name} (Cerrado)")
                
                # Cargar pixmap
                icon_path = os.path.join(icons_dir, svg_name)
                # Escalar a 24x24 para dejar espacio al borde de 2px (24 + 2 + 2 = 28)
                pixmap = QPixmap(icon_path).scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                lbl.setPixmap(pixmap)
                
                # Efecto de opacidad/color
                effect = QGraphicsOpacityEffect(lbl)
                effect.setOpacity(0.3) # Estado 1: Cerrado = opaco
                lbl.setGraphicsEffect(effect)
                
                # Guardar info en el label para click handling
                lbl.setProperty("app_id", app_id)
                lbl.setProperty("app_name", app_name)
                lbl.setProperty("exe_path", integrations.get(f"{app_id}_path", ""))
                lbl.setProperty("state", 1) # 1=Closed, 2=Open, 3=Connected
                lbl.mousePressEvent = lambda e, l=lbl: self.on_app_icon_clicked(l)
                
                self.layout.addWidget(lbl)
                self.app_icons[app_id] = lbl
        
        self.layout.addWidget(self.btn_toggle)
        self.layout.addWidget(self.btn_settings)
        
        self._active_editor = None
        self._process_status = {}
        self.update_ui_state()
        
    def late_init(self):
        """Llamado después de que EditorIntegrationManager se inicializa en main.py"""
        from core.services.editor_integration_manager import EditorIntegrationManager
        self.editor_manager = EditorIntegrationManager.get_instance()
        if self.editor_manager:
            self.editor_manager.active_editor_changed.connect(self.on_editor_changed)
            self.editor_manager.process_status_changed.connect(self.on_process_changed)
            
            self._active_editor = self.editor_manager.active_editor
            self._process_status = self.editor_manager.process_status
            self.btn_toggle.setChecked(self.editor_manager.is_auto_send_enabled)
        self.update_ui_state()
            
    def on_editor_changed(self, editor_name):
        self._active_editor = editor_name
        self.update_ui_state()
        
    def on_process_changed(self, status_dict):
        self._process_status = status_dict
        self.update_ui_state()
        
    def on_toggle(self, checked):
        if hasattr(self, 'editor_manager') and self.editor_manager:
            self.editor_manager.is_auto_send_enabled = checked
        self.update_ui_state()
        
    def update_ui_state(self):
        # 1. Update toggle button
        is_on = self.btn_toggle.isChecked()
        if not is_on:
            self.btn_toggle.setIcon(self._icon_off)
            self.btn_toggle.setToolTip("Auto-enviar: PAUSADO")
        else:
            if self._active_editor:
                self.btn_toggle.setIcon(self._icon_green)
                self.btn_toggle.setToolTip(f"Auto-enviar a {self._active_editor}: ACTIVO")
            else:
                self.btn_toggle.setIcon(self._icon_yellow)
                self.btn_toggle.setToolTip("Auto-enviar: ESPERANDO CONEXIÓN")
                
        # 2. Update App Icons
        for app_id, lbl in self.app_icons.items():
            is_running = self._process_status.get(app_id, False)
            is_active = (self._active_editor == app_id)
            
            effect = lbl.graphicsEffect()
            if is_active:
                lbl.setProperty("state", 3)
                effect.setOpacity(1.0)
                lbl.setStyleSheet("border: 2px solid #55ff55; border-radius: 6px; background-color: rgba(85, 255, 85, 0.1);") # Brillante / Marco
                lbl.setToolTip(f"{lbl.property('app_name')} (Conectado)")
            elif is_running:
                lbl.setProperty("state", 2)
                effect.setOpacity(0.8) # Abierto pero sin conexión (opaco pero a color)
                lbl.setStyleSheet("border: 2px solid transparent; border-radius: 6px;")
                lbl.setToolTip(f"{lbl.property('app_name')} (Abierto - Sin vincular)")
            else:
                lbl.setProperty("state", 1)
                effect.setOpacity(0.3) # Cerrado (grisáceo / opaco)
                lbl.setStyleSheet("border: 2px solid transparent; border-radius: 6px;")
                lbl.setToolTip(f"{lbl.property('app_name')} (Cerrado - Clic para abrir)")
                
    def on_app_icon_clicked(self, lbl):
        import subprocess
        import os
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QPixmap
        
        state = lbl.property("state")
        app_id = lbl.property("app_id")
        exe_path = lbl.property("exe_path")
        
        # Animación de "Click" (Pop effect)
        svg_name = ""
        if app_id == "premiere": svg_name = "premiere pro.svg"
        elif app_id == "aftereffects": svg_name = "after effects.svg"
        elif app_id == "davinci": svg_name = "davinci resolve.svg"
        
        if svg_name:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            icons_dir = os.path.join(os.path.dirname(base_dir), "assets", "icons", "svg")
            icon_path = os.path.join(icons_dir, svg_name)
            
            # Achicar
            pixmap_small = QPixmap(icon_path).scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            lbl.setPixmap(pixmap_small)
            
            # Restaurar
            def restore_size():
                pixmap_normal = QPixmap(icon_path).scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                lbl.setPixmap(pixmap_normal)
            QTimer.singleShot(120, restore_size)
        
        if state == 1:
            # Launch app
            if exe_path and os.path.exists(exe_path):
                from core.logger.logger_manager import logger
                logger.info(f"Lanzando: {exe_path}")
                try:
                    subprocess.Popen(exe_path)
                except Exception as e:
                    logger.error(f"Error lanzando {app_id}: {e}")
            else:
                from gui.dialogs.dialogs import show_warning
                show_warning(self.main_window, "Ruta no encontrada", f"No se encontró el ejecutable en:\n{exe_path}\nConfigura la ruta en Ajustes -> Integraciones.")
        elif state == 2:
            # Force active (if supported)
            if hasattr(self, 'editor_manager') and self.editor_manager:
                success = self.editor_manager.force_adobe_target(app_id)
                if not success:
                    from gui.dialogs.dialogs import show_info
                    show_info(self.main_window, "DowP Importer", "La extensión no está respondiendo. Abre el panel de DowP en tu editor para conectar.")
                
    def on_settings_clicked(self):
        # Ir a la pestaña principal de Ajustes (índice 5 en main_window.tabs)
        self.main_window.tabs.setCurrentIndex(5)
        # Ir a la sub-pestaña de Integraciones
        settings_tab = self.main_window.tab_settings
        settings_tab.btn_integrations.click()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        logger.debug("MainWindow: Inicializando sistema de pestañas")

        # ── Barra de título personalizada ─────────────────────────────────────
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        # Permite redimensionar desde los bordes incluso sin decoración nativa
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        # Cargar tema inicial
        config = get_config()
        initial_theme = config.get("theme", "dark")

        version = QApplication.instance().applicationVersion()
        self.setWindowTitle(self.tr(f"DowP {version}"))
        self.setMinimumSize(1200, 860)
        self.resize(1200, 860)
        self.setStyleSheet(load_stylesheet(initial_theme))

        # ── Layout principal ──────────────────────────────────────────────────
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.main_layout = QVBoxLayout(central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Barra de título arriba del todo
        self.title_bar = CustomTitleBar(self, title=self.windowTitle())
        self.main_layout.addWidget(self.title_bar)

        # ── Pestañas ──────────────────────────────────────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setObjectName("mainTabs")

        # 1. Modo Rápido
        self.tab_quick = QuickModeTab()
        self.tabs.addTab(self.tab_quick, self.tr("Modo Rápido"))

        # 2. Proceso Avanzado
        self.tab_single = AdvancedProcessTab()
        self.tabs.addTab(self.tab_single, self.tr("Proceso Avanzado"))

        # 3. Herramientas de Imagen
        self.tab_image = ImageToolsTab()
        self.tabs.addTab(self.tab_image, self.tr("Herramientas de Imagen"))

        # 4. Herramientas de Video
        self.tab_video = VideoToolsTab()
        self.tabs.addTab(self.tab_video, self.tr("Herramientas de Video"))

        # 5. Medios de Edición
        self.tab_editing = EditingMediaTab()
        self.tabs.addTab(self.tab_editing, self.tr("Medios de Edición"))

        # 6. Ajustes
        self.tab_settings = SettingsTab()
        self.tabs.addTab(self.tab_settings, self.tr("Ajustes"))
        
        # Corner Widget (Editor Status)
        self.editor_status_widget = EditorStatusCornerWidget(self)
        self.tabs.setCornerWidget(self.editor_status_widget, Qt.TopRightCorner)

        self.main_layout.addWidget(self.tabs)

        # ── Conexiones ────────────────────────────────────────────────────────
        self.tab_settings.theme_changed.connect(self.update_theme)
        self.tabs.currentChanged.connect(self.on_tab_changed)

        logger.info("MainWindow: Sistema de pestañas inicializado")

    def on_tab_changed(self, index):
        """Se ejecuta al cambiar de pestaña."""
        if self.tabs.widget(index) == self.tab_single:
            logger.info("MainWindow: Recargando etiquetas en Proceso Avanzado")
            self.tab_single.video_details.load_labels()

        from core.utils.clipboard_monitor import ClipboardURLMonitor
        ClipboardURLMonitor.instance().check_clipboard(force=True)

    def showEvent(self, event):
        super().showEvent(event)
        from core.utils.clipboard_monitor import ClipboardURLMonitor
        ClipboardURLMonitor.instance().check_clipboard(force=True)
        # Conectar el corner widget al EditorManager (que ya fue inicializado en main.py)
        if hasattr(self, 'editor_status_widget') and not getattr(self, '_editor_status_initialized', False):
            self.editor_status_widget.late_init()
            self._editor_status_initialized = True

    def update_theme(self, theme_name):
        logger.info(f"MainWindow: Cambiando tema a {theme_name}")
        self.setStyleSheet(load_stylesheet(theme_name))

    def nativeEvent(self, eventType, message):
        """Maneja eventos nativos de Windows para permitir redimensionar la ventana sin bordes."""
        try:
            import ctypes
            import ctypes.wintypes
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == 0x0084: # WM_NCHITTEST
                # Usa QCursor.pos() porque Qt ya se encarga de normalizar las coordenadas 
                # a nivel lógico para todos los monitores independientemente de su DPI.
                from PySide6.QtGui import QCursor
                local_pos = self.mapFromGlobal(QCursor.pos())
                x = local_pos.x()
                y = local_pos.y()
                
                w, h = self.width(), self.height()
                border = 6 # Grosor del borde para redimensionar
                
                left = x < border
                right = x > w - border
                top = y < border
                bottom = y > h - border
                
                if left and top: return True, 13 # HTTOPLEFT
                if right and top: return True, 14 # HTTOPRIGHT
                if left and bottom: return True, 16 # HTBOTTOMLEFT
                if right and bottom: return True, 17 # HTBOTTOMRIGHT
                if left: return True, 10 # HTLEFT
                if right: return True, 11 # HTRIGHT
                if top: return True, 12 # HTTOP
                if bottom: return True, 15 # HTBOTTOM
        except Exception:
            pass

        return super().nativeEvent(eventType, message)


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
