# main.py
import sys
import os

# Add 'src' to path to import modules
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

# ═══ Escalado ANTES de QApplication (obligatorio) ═══
from core.utils.scaling import apply_ui_scaling, flush_scaling_logs
ui_scale_factor = apply_ui_scaling()

from core.logger.logger_manager import logger

# Enviar los logs de escalado al logger real 
flush_scaling_logs()


from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase, QIcon
from gui.main_window import MainWindow
from core.utils.i18n import load_language
from core.utils.config_manager import get_config

__version__ = "2.0.0"

from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtWidgets import QPushButton, QCheckBox, QRadioButton, QComboBox, QTabBar, QStyledItemDelegate


class _ComboPopupMaskFilter(QObject):
    """Mantiene la máscara del contenedor del popup (QComboBoxPrivateContainer) sincronizada
    con su tamaño en cada resize o show.

    Qt solo pinta el panel nativo opaco de menú (QStyle::PE_PanelMenu, reservado para los
    indicadores de scroll arriba/abajo) cuando `mask().isEmpty()` es verdadero.
    Asignarle cualquier máscara no vacía (su propio rect) hace que Qt se salte ese dibujado por completo."""

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            obj.setMask(obj.rect())
        return False


_DEFAULT_COMBO_DELEGATE_TYPE = None

class HandCursorInstaller(QObject):
    """Instala cursor pointer en widgets interactivos y garantiza QStyledItemDelegate
    y máscara de recorte sin bordes nativos en QComboBoxes para soporte de hover y selección visual vía QSS."""
    _TARGET_TYPES = (QPushButton, QCheckBox, QRadioButton, QComboBox, QTabBar)

    def __init__(self, parent=None):
        super().__init__(parent)
        global _DEFAULT_COMBO_DELEGATE_TYPE
        if _DEFAULT_COMBO_DELEGATE_TYPE is None:
            _DEFAULT_COMBO_DELEGATE_TYPE = type(QComboBox().itemDelegate())
        self._mask_filter = _ComboPopupMaskFilter(self)

    def _setup_combo(self, combo: QComboBox):
        if type(combo.itemDelegate()) is _DEFAULT_COMBO_DELEGATE_TYPE:
            combo.setItemDelegate(QStyledItemDelegate(combo))
        if combo.view() and combo.view().window():
            container = combo.view().window()
            container.setAttribute(Qt.WA_TranslucentBackground, True)
            container.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
            container.installEventFilter(self._mask_filter)

    def eventFilter(self, obj, event):
        ev_type = event.type()
        if ev_type == QEvent.Type.ChildAdded:
            child = event.child()
            if isinstance(child, QComboBox):
                self._setup_combo(child)
            if isinstance(child, self._TARGET_TYPES):
                child.setCursor(Qt.PointingHandCursor)
        elif ev_type in (QEvent.Type.Show, QEvent.Type.Polish):
            if isinstance(obj, QComboBox):
                self._setup_combo(obj)
        return False

def main():
    # 0. Setup App and Language
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # Estilo base multiplataforma que previene bugs de QComboBox en Windows

    # Instalar cursor pointer en widgets interactivos (ChildAdded, no Enter — más eficiente)
    app.installEventFilter(HandCursorInstaller(app))
    
    # Calculate absolute base directory
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Load Fonts
    font_path = os.path.join(base_dir, "src", "assets", "fonts", "Raleway.ttf")
    if os.path.exists(font_path):
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id != -1:
            family = QFontDatabase.applicationFontFamilies(font_id)[0]
            logger.info(f"Fuente cargada: {family}")
        else:
            logger.warning("No se pudo cargar la fuente Raleway (formato no soportado o archivo corrupto).")
    
    app.setApplicationName("DowP")
    app.setApplicationVersion(__version__)
    
    # Cargar Ícono Global de la Aplicación
    icon_path = os.path.join(base_dir, "src", "assets", "icons", "app", "DowP_Logo.svg")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    else:
        logger.warning(f"No se encontró el ícono de la app en: {icon_path}")
    
    logger.info(f"Starting DowP {__version__} application")
    
    config = get_config()
    load_language(app, config.get("language", "en"))
    
    # ── Splash Screen con verificación de dependencias integrada ──
    from gui.splash_screen import SplashScreen
    
    splash = SplashScreen()
    window_holder = [None]  # Usar lista para evitar GC
    
    # Iniciar Master Manager de Editores (Adobe, DaVinci, Vegas)
    from core.services.editor_integration_manager import EditorIntegrationManager
    from core.utils.queue_manager import get_queue_manager
    editor_manager = EditorIntegrationManager()
    editor_manager.start_all_services()
    editor_manager.connect_to_queue(get_queue_manager())
    
    def on_splash_ready(main_window):
        """Recibe la MainWindow ya construida desde el splash."""
        window_holder[0] = main_window
        main_window.show()
        splash.cleanup()
        logger.info("Application main window shown")
    
    def on_splash_failed():
        logger.error("Dependency installation failed. Exiting.")
        splash.cleanup()
        sys.exit(1)
    
    splash.ready.connect(on_splash_ready)
    splash.failed.connect(on_splash_failed)
    splash.start()

    def on_app_exit():
        logger.info("Cerrando servicios en segundo plano...")
        try:
            from core.utils.queue_manager import get_queue_manager
            get_queue_manager().stop_worker()
        except Exception as e:
            logger.debug(f"Error deteniendo QueueManager en salida: {e}")
        try:
            editor_manager.stop_all_services()
        except BaseException as e:
            logger.debug(f"Error deteniendo Editor Manager en salida: {e}")

    app.aboutToQuit.connect(on_app_exit)

    logger.info("Application event loop started")
    sys.exit(app.exec())

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}", exc_info=True)
