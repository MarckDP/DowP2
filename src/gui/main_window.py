# src/gui/main_window.py
import sys
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QTabWidget, QApplication
from PySide6.QtCore import Qt, QPoint
from core.logger.logger_manager import logger
from gui.styles import load_stylesheet
from gui.widgets.title_bar import CustomTitleBar
from core.utils.config_manager import get_config

# Import Tab Views
from gui.tabs.advanced_process.advanced_process_view import AdvancedProcessTab
from gui.tabs.quick_mode.quick_mode_view import QuickModeTab
from gui.tabs.image_tools.image_tools_view import ImageToolsTab
from gui.tabs.video_tools.video_tools_view import VideoToolsTab
from gui.tabs.editing_media.editing_media_view import EditingMediaTab
from gui.tabs.settings.settings_view import SettingsTab


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
                x_screen = msg.pt.x
                y_screen = msg.pt.y
                
                # Ajustar las coordenadas físicas del mouse por el factor de escala DPI
                dpr = self.devicePixelRatioF()
                x_logical = x_screen / dpr
                y_logical = y_screen / dpr
                
                local_pos = self.mapFromGlobal(QPoint(int(x_logical), int(y_logical)))
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
