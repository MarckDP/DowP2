# src/gui/tabs/video_tools/encoding_options_widget.py
from PySide6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QTabWidget,
    QWidget,
)
from PySide6.QtCore import Signal

from gui.styles import get_theme_token

class EncodingOptionsWidget(QFrame):
    """
    Panel derecho de opciones con pestañas (Preajustes, Avanzados, Herramientas).
    Se ubica en el panel derecho de la interfaz. El contenido de cada pestaña está
    pendiente de diseño; por ahora solo se deja el cascarón de pestañas.
    """
    options_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("encodingOptionsWidget")
        self._init_ui()

    def _init_ui(self):
        bg_color = get_theme_token('fondo_secundario', '#1e1e1e')
        border_color = get_theme_token('borde_normal', '#2d2d2d')
        self.setStyleSheet(f"""
            QFrame#encodingOptionsWidget {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Tab Widget Principal de Opciones
        self.tabs = QTabWidget()

        self.tab_presets = QWidget()
        self.tabs.addTab(self.tab_presets, self.tr("Preajustes"))

        self.tab_advanced = QWidget()
        self.tabs.addTab(self.tab_advanced, self.tr("Avanzados"))

        self.tab_tools = QWidget()
        self.tabs.addTab(self.tab_tools, self.tr("Herramientas"))

        layout.addWidget(self.tabs)

    def get_encoding_settings(self) -> dict:
        return {}
