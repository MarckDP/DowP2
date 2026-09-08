# src/core/utils/clipboard_monitor.py
"""
Monitor de portapapeles para auto-pegar URLs.

Cuando la ventana de la aplicación recibe foco, comprueba si el portapapeles
contiene una URL válida (que no sea la misma que ya está en el campo).
Si la encuentra, la pega automáticamente en el campo de URL activo.

Funciona en Windows, macOS y Linux (X11/Wayland).
"""
import re
from PySide6.QtWidgets import QApplication, QLineEdit
from PySide6.QtCore import QObject, Signal
from core.logger.logger_manager import logger

# Patrón amplio para detectar URLs compatibles con yt-dlp
_URL_PATTERN = re.compile(
    r'^https?://'           # http:// o https://
    r'[^\s/$.?#]'           # al menos un carácter válido
    r'[^\s]*$',             # resto de la URL
    re.IGNORECASE
)


class ClipboardURLMonitor(QObject):
    """
    Monitorea el portapapeles y auto-pega URLs en campos QLineEdit registrados.

    Uso:
        monitor = ClipboardURLMonitor.instance()
        monitor.register(my_url_input)   # QLineEdit
        monitor.unregister(my_url_input) # al destruir el widget
    """
    url_detected = Signal(str)  # Emitida cuando se detecta una URL nueva

    _instance = None

    @classmethod
    def instance(cls):
        """Devuelve la instancia singleton del monitor."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        self._registered_inputs: list[QLineEdit] = []
        self._last_clipboard_text = ""
        
        # Leer configuración
        from core.utils.config_manager import get_config
        self._enabled = get_config().get("auto_paste_url", True)

        # Conectar al cambio de ventana activa (funciona cross-platform)
        app = QApplication.instance()
        if app:
            app.applicationStateChanged.connect(self._on_app_state_changed)

    def register(self, line_edit: QLineEdit):
        """Registra un QLineEdit para recibir auto-paste de URLs."""
        if line_edit not in self._registered_inputs:
            self._registered_inputs.append(line_edit)
            logger.debug(f"ClipboardMonitor: Campo registrado ({len(self._registered_inputs)} total)")

    def unregister(self, line_edit: QLineEdit):
        """Desregistra un QLineEdit."""
        if line_edit in self._registered_inputs:
            self._registered_inputs.remove(line_edit)
            logger.debug(f"ClipboardMonitor: Campo desregistrado ({len(self._registered_inputs)} total)")

    def set_enabled(self, enabled: bool):
        """Activa/desactiva el monitor."""
        self._enabled = enabled

    def is_enabled(self) -> bool:
        return self._enabled

    def _on_app_state_changed(self, state):
        """Llamado cuando cambia el estado de la aplicación (foco, minimizado, etc.)."""
        from PySide6.QtCore import Qt
        if state == Qt.ApplicationActive and self._enabled:
            self.check_clipboard()

    def check_clipboard(self, force: bool = False):
        """Comprueba si hay una URL nueva en el portapapeles y la pega en el campo activo."""
        if not self._enabled:
            return

        clipboard = QApplication.clipboard()
        if not clipboard:
            return

        text = clipboard.text().strip()
        if not text:
            return

        # Ignorar si es el mismo texto que ya procesamos (salvo que se fuerce)
        if not force and text == self._last_clipboard_text:
            return

        # Verificar si es una URL válida
        if not _URL_PATTERN.match(text):
            return

        # Buscar el campo de URL visible y activo para pegar
        target = self._find_target_input(text)
        if target:
            self._last_clipboard_text = text
            target.setText(text)
            target.setCursorPosition(0)
            logger.info(f"ClipboardMonitor: URL auto-pegada en campo activo")
            self.url_detected.emit(text)

    def _check_clipboard(self):
        self.check_clipboard(force=False)

    def _find_target_input(self, url: str) -> QLineEdit | None:
        """
        Busca el mejor campo de URL donde pegar.
        Prioridad:
          1. El campo que tiene el foco
          2. El campo de la pestaña activa visible
          3. El primer campo vacío
        """
        # Limpiar referencias muertas
        self._registered_inputs = [inp for inp in self._registered_inputs
                                   if inp is not None and not self._is_deleted(inp)]

        if not self._registered_inputs:
            return None

        # 1. ¿Algún campo tiene el foco?
        for inp in self._registered_inputs:
            if inp.hasFocus():
                if inp.text().strip() != url:
                    return inp
                return None  # Ya tiene la misma URL

        # 2. ¿Algún campo es visible y está vacío o tiene una URL diferente?
        for inp in self._registered_inputs:
            if inp.isVisible() and not inp.text().strip():
                return inp

        # 3. El primer campo visible (reemplazar contenido si es diferente)
        for inp in self._registered_inputs:
            if inp.isVisible() and inp.text().strip() != url:
                return inp

        return None

    @staticmethod
    def _is_deleted(widget) -> bool:
        """Comprueba si un widget Qt ha sido destruido."""
        try:
            widget.objectName()
            return False
        except RuntimeError:
            return True
