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
from PySide6.QtWidgets import QPushButton, QCheckBox, QComboBox, QTabBar, QStyledItemDelegate

class HandCursorInstaller(QObject):
    """Instala cursor pointer en widgets interactivos y garantiza QStyledItemDelegate
    en QComboBoxes para soporte de hover y selección visual vía QSS."""
    _TARGET_TYPES = (QPushButton, QCheckBox, QComboBox, QTabBar)
    
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.ChildAdded:
            child = event.child()
            if isinstance(child, QComboBox):
                # Si no tiene un delegate customizado (ej: RichTextDelegate), asignar QStyledItemDelegate
                # para habilitar feedback visual de hover/selección en el menú desplegable QSS.
                if child.itemDelegate().__class__ == QComboBox().itemDelegate().__class__:
                    child.setItemDelegate(QStyledItemDelegate(child))
                # Transparencia en la ventana del menú desplegable para eliminar filos cuadrados detrás del border-radius QSS
                if child.view() and child.view().window():
                    child.view().window().setAttribute(Qt.WA_TranslucentBackground)
            if isinstance(child, self._TARGET_TYPES):
                child.setCursor(Qt.PointingHandCursor)
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

    app.aboutToQuit.connect(on_app_exit)

    logger.info("Application event loop started")
    sys.exit(app.exec())

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}", exc_info=True)
