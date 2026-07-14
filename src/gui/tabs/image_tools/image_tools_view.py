# src/gui/tabs/image_tools/tab_view.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

class ImageToolsTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        label = QLabel(self.tr("Herramientas de Imagen (Próximamente)"))
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)
