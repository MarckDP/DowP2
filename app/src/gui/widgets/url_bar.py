# src/gui/widgets/url_bar.py
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QSizePolicy
from PySide6.QtCore import Signal
from core.logger.logger_manager import logger
from gui.widgets.animated_button import AnimatedButton

class URLBar(QWidget):
    analyze_requested = Signal(str)
    solo_toggled = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.init_ui()
        
        # Registrar el campo de URL en el monitor de portapapeles
        from core.utils.clipboard_monitor import ClipboardURLMonitor
        monitor = ClipboardURLMonitor.instance()
        monitor.register(self.url_input)
        monitor.url_detected.connect(self._on_clipboard_url_detected)

    def _on_clipboard_url_detected(self, url):
        """Llamado cuando el monitor de portapapeles pega una URL."""
        # Solo auto-analizar si la URL fue pegada en NUESTRO campo
        if self.url_input.text().strip() != url:
            return
        # Verificar si auto-análisis está activado
        from core.utils.config_manager import get_config
        if get_config().get("auto_analyze", False):
            self.analyze_requested.emit(url)

    def _on_text_edited(self, text):
        """Llamado cuando el usuario edita el texto manualmente (incluyendo pegar)."""
        url = text.strip()
        if not url:
            return
            
        # Verificar si auto-análisis está activado
        from core.utils.config_manager import get_config
        if not get_config().get("auto_analyze", False):
            return
            
        # Comprobar si parece una URL válida
        if not url.startswith(("http://", "https://")):
            return
            
        # Comprobar si el texto coincide con el portapapeles (indica que fue pegado)
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        if clipboard:
            clip_text = clipboard.text().strip()
            if url == clip_text:
                logger.info("URLBar: Detección de pegado manual. Analizando...")
                self.analyze_requested.emit(url)

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.solo_btn = AnimatedButton(self.tr("SOLO"))
        self.solo_btn.setCheckable(True)
        from core.utils.config_manager import get_config
        self.solo_btn.setChecked(get_config().get("solo_mode", True))
        self.solo_btn.setObjectName("soloButton")
        self.solo_btn.setFixedWidth(65)
        self.solo_btn.toggled.connect(self.solo_toggled.emit)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(self.tr("Pega la URL aquí (YouTube, Twitch, etc...)"))
        self.url_input.returnPressed.connect(self.on_analyze_clicked)
        self.url_input.textEdited.connect(self._on_text_edited)
        
        self.analyze_btn = AnimatedButton(self.tr("Analizar URL"))
        self.analyze_btn.setFixedWidth(120)
        self.analyze_btn.setObjectName("analyzeButton")
        self.analyze_btn.clicked.connect(self.on_analyze_clicked)

        layout.addWidget(self.solo_btn)
        layout.addWidget(self.url_input)
        layout.addWidget(self.analyze_btn)

    def on_analyze_clicked(self):
        url = self.url_input.text().strip()
        if url:
            self.analyze_requested.emit(url)

    def set_loading(self, loading: bool):
        self.analyze_btn.setEnabled(not loading)
        self.analyze_btn.setText(self.tr("Analizando...") if loading else self.tr("Analizar URL"))

    def text(self):
        return self.url_input.text().strip()
