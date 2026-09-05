# src/gui/tabs/batch_process/tab_view.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

class BatchProcessTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        label = QLabel(self.tr("Proceso por Lotes (Próximamente)"))
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)
