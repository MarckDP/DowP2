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

from core.setup.setup_manager import verify_all_dependencies
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase, QIcon
from gui.main_window import MainWindow
from core.utils.i18n import load_language
from core.utils.config_manager import get_config

__version__ = "2.0.0"

from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtWidgets import QPushButton, QCheckBox, QComboBox, QTabBar

class HandCursorInstaller(QObject):
    """Instala cursor pointer en widgets interactivos cuando se crean.
    Usa ChildAdded en vez de Enter para procesar una sola vez por widget."""
    _TARGET_TYPES = (QPushButton, QCheckBox, QComboBox, QTabBar)
    
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.ChildAdded:
            child = event.child()
            if isinstance(child, self._TARGET_TYPES):
                child.setCursor(Qt.PointingHandCursor)
        return False

def main():
    # 0. Setup App and Language
    app = QApplication(sys.argv)
    
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
    
    logger.info("Checking dependencies...")
    status = verify_all_dependencies()
    if not all(status.values()):
        logger.info("Some dependencies are missing. Showing installer dialog...")
        from gui.dialogs.dependency_dialog import DependencyDialog
        dialog = DependencyDialog()
        if not dialog.exec():
            logger.info("Dependency installation cancelled or failed. Exiting.")
            sys.exit(0)
        logger.info("Dependencies ready.")
    else:
        logger.info("All dependencies found.")
    
    logger.debug("Initializing MainWindow")
    window = MainWindow()
    window.show()
    
    logger.info("Application event loop started")
    sys.exit(app.exec())

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}", exc_info=True)
