# src/gui/tabs/video_tools/video_tools_view.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt


class VideoToolsTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        label = QLabel(self.tr("Herramientas Multimedia (Próximamente)"))
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)
