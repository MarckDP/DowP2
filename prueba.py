import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QComboBox

app = QApplication(sys.argv)
app.setStyle("Fusion")  # <- clave
win = QMainWindow()
combo = QComboBox()
combo.addItems(["Opción 1", "Opción 2", "Opción 3", "Opción 4"])
win.setCentralWidget(combo)
win.show()
sys.exit(app.exec())