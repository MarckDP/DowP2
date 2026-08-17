# src/gui/tabs/video_tools/encoding_options_widget.py
from PySide6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QTabWidget,
    QWidget,
)
from PySide6.QtCore import Signal

from gui.styles import get_theme_token
from gui.tabs.video_tools.presets_panel import PresetsPanel
from gui.tabs.video_tools.advanced_recode_panel import AdvancedRecodePanel

class EncodingOptionsWidget(QFrame):
    """
    Panel derecho de opciones con pestañas (Preajustes, Comprimir, Convertir, Proxies, Avanzado).
    Caja principal contenedora con fondo transparente y borde acorde al tema.
    """
    options_changed = Signal(dict)
    # Emitida cuando cambia el estado del botón "Iniciar" (válido/inválido + texto contextual)
    start_status_changed = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("encodingOptionsWidget")
        self._init_ui()

    def _init_ui(self):
        bg_color = get_theme_token('fondo_secundario', '#121212')
        border_color = get_theme_token('borde_normal', '#222222')
        accent_color = get_theme_token('acento_primario', '#B9E640')
        self.setStyleSheet(f"""
            QFrame#encodingOptionsWidget {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
            QTabWidget#encodingTabs::pane {{
                background: transparent;
                border-top: 1px solid {border_color};
            }}
            QTabWidget#encodingTabs > QTabBar::tab {{
                background: transparent;
                padding: 8px 18px;
            }}
            QTabWidget#encodingTabs > QTabBar::tab:selected {{
                background: transparent;
                color: #ffffff;
                border-bottom: 3px solid {accent_color};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(0)

        # Tab Widget Principal de Opciones
        self.tabs = QTabWidget()
        self.tabs.setObjectName("encodingTabs")

        self.tab_presets = PresetsPanel(self)
        self.tabs.addTab(self.tab_presets, self.tr("Preajustes"))

        self.tab_compress = QWidget()
        self.tabs.addTab(self.tab_compress, self.tr("Comprimir"))

        self.tab_convert = QWidget()
        self.tabs.addTab(self.tab_convert, self.tr("Convertir"))

        self.tab_proxies = QWidget()
        self.tabs.addTab(self.tab_proxies, self.tr("Proxies"))

        self.tab_advanced = AdvancedRecodePanel(self)
        self.tabs.addTab(self.tab_advanced, self.tr("Avanzado"))
        self.tab_advanced.validity_changed.connect(self._on_advanced_validity_changed)

        # Preajustes cambia de válido/inválido cuando el usuario elige o deselecciona un preset
        self.tab_presets.preset_bar.preset_applied.connect(self._on_presets_validity_changed)

        layout.addWidget(self.tabs)

        self.tabs.currentChanged.connect(self._on_tab_changed)

    def get_current_status(self) -> tuple[bool, str]:
        current = self.tabs.currentWidget()
        if current is self.tab_advanced:
            return self.tab_advanced.get_status()
        if current is self.tab_presets:
            return self.tab_presets.get_status()
        return True, self.tr("Iniciar Recodificación")

    def _emit_current_status(self):
        is_valid, text = self.get_current_status()
        self.start_status_changed.emit(is_valid, text)

    def _on_tab_changed(self, index: int):
        self._emit_current_status()

    def _on_advanced_validity_changed(self, _is_valid: bool):
        if self.tabs.currentWidget() is self.tab_advanced:
            self._emit_current_status()

    def _on_presets_validity_changed(self, *_args):
        if self.tabs.currentWidget() is self.tab_presets:
            self._emit_current_status()

    def get_encoding_settings(self) -> dict:
        current = self.tabs.currentWidget()
        if current is self.tab_advanced:
            return self.tab_advanced.get_settings()
        if current is self.tab_presets:
            return self.tab_presets.get_settings()
        return {}
