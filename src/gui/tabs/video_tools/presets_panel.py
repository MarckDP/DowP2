# src/gui/tabs/video_tools/presets_panel.py
from PySide6.QtWidgets import QWidget, QVBoxLayout

from gui.widgets.preset_bar import PresetBar
from gui.tabs.video_tools.advanced_recode_panel import _PRESET_NAMESPACE


class PresetsPanel(QWidget):
    """
    Pestaña 'Preajustes' de Herramientas Multimedia.

    Acá el usuario ELIGE qué preset usar para el próximo trabajo, sin pasar
    por la pestaña que lo creó (ej. guardaste "422 Proxy" en Avanzado una vez;
    de ahí en más solo entrás acá, lo elegís, y mandás "Iniciar
    Recodificación" directo). Por eso expone get_settings()/is_valid() con la
    misma forma que AdvancedRecodePanel - EncodingOptionsWidget los trata
    igual sea cual sea la pestaña activa.

    Namespace: por ahora apunta al mismo que usa AdvancedRecodePanel, porque
    es la única pestaña que hoy guarda ajustes reales. Cuando Comprimir/
    Convertir/Proxies tengan lógica propia, esto va a necesitar mostrar
    varios namespaces a la vez (agrupados o con un filtro), no solo uno.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.preset_bar = PresetBar(
            _PRESET_NAMESPACE, get_settings=None, parent=self,
            show_picker=True, show_save_button=False,
        )
        layout.addWidget(self.preset_bar)
        layout.addStretch(1)

    def get_settings(self) -> dict:
        return self.preset_bar.current_preset_settings() or {}

    def is_valid(self) -> bool:
        return self.preset_bar.active_preset_name() is not None

    def get_status(self) -> tuple[bool, str]:
        if self.preset_bar.active_preset_name() is None:
            return False, self.tr("Selecciona un preajuste")
        return True, self.tr("Iniciar Recodificación")
