# src/gui/tabs/video_tools/presets_panel.py
from PySide6.QtWidgets import QWidget, QVBoxLayout

from gui.widgets.preset_bar import PresetBar

PRESET_NAMESPACE = "video_tools/preajustes"


class PresetsPanel(QWidget):
    """
    Pestaña 'Preajustes' de Herramientas Multimedia.

    Por ahora es solo la barra de gestión de presets (guardar/cargar/exportar/
    importar/eliminar). No contiene opciones propias: los ajustes que guarda
    cada preset vendrán de las demás pestañas (Comprimir, Convertir, etc.)
    cuando se implementen — de ahí que get_settings/set_settings sean
    provisionales y operen sobre un dict vacío.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.preset_bar = PresetBar(PRESET_NAMESPACE, self.get_settings, self.set_settings, self)
        layout.addWidget(self.preset_bar)
        layout.addStretch(1)

    def get_settings(self) -> dict:
        # Provisional: cuando existan las lógicas de las otras pestañas,
        # aquí se recolectarán sus ajustes para guardarlos como preset.
        return {}

    def set_settings(self, settings: dict):
        # Provisional: aquí se distribuirán los ajustes del preset a las otras pestañas.
        pass
