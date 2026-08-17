# prueba.py
import sys
import os

# Añadir src al path para importar módulos del proyecto
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QComboBox, QGroupBox, QSlider, QScrollArea, QFrame
)
from PySide6.QtCore import Qt
from gui.styles import load_stylesheet
from gui.widgets.combo_box import AutoPopupComboBox

app = QApplication(sys.argv)
app.setStyle("Fusion")

win = QMainWindow()
win.setWindowTitle("Comparador de ComboBox: Variantes de Ancho (Con Estilo DowP vs Nativo Fusion)")
win.resize(1100, 750)

central_widget = QWidget()
root_layout = QVBoxLayout(central_widget)
root_layout.setContentsMargins(15, 15, 15, 15)
root_layout.setSpacing(10)

# Barra superior con control de ancho interactivo
ctrl_bar = QHBoxLayout()
lbl_slider = QLabel("<b>Ajustar Ancho de Prueba en Vivo (Slider):</b>")
slider_w = QSlider(Qt.Horizontal)
slider_w.setRange(100, 450)
slider_w.setValue(200)
slider_w.setFixedWidth(250)
lbl_val = QLabel("200 px")
lbl_val.setStyleSheet("font-weight: bold; min-width: 50px;")

ctrl_bar.addWidget(lbl_slider)
ctrl_bar.addWidget(slider_w)
ctrl_bar.addWidget(lbl_val)
ctrl_bar.addStretch()
root_layout.addLayout(ctrl_bar)

# Contenedor de paneles lado a lado
panels_layout = QHBoxLayout()
panels_layout.setSpacing(15)

items_prueba = [
    "★ Mejor Compatible (1080p60 H.264 / AAC 320kbps)",
    "Solo Video - 4K 2160p60 HDR",
    "Audio AAC 320kbps",
    "Opción de Texto Muy Largo para Probar Truncado en Espacios Reducidos",
    "Normal"
]

# -------------------------------------------------------------
# Panel Izquierdo: CON ESTILO DOWP
# -------------------------------------------------------------
group_dowp = QGroupBox("CON Estilo DowP 2.0 (QSS)")
layout_dowp = QVBoxLayout(group_dowp)
layout_dowp.setSpacing(8)

layout_dowp.addWidget(QLabel("<b>1. Ancho Compacto (150 px) — como en Modo Rápido:</b>"))
cb_dowp_150 = QComboBox()
cb_dowp_150.setFixedWidth(150)
cb_dowp_150.addItems(items_prueba)
layout_dowp.addWidget(cb_dowp_150)

layout_dowp.addWidget(QLabel("<b>2. Ancho Medio (220 px) — como en Proceso Avanzado:</b>"))
cb_dowp_220 = QComboBox()
cb_dowp_220.setFixedWidth(220)
cb_dowp_220.addItems(items_prueba)
layout_dowp.addWidget(cb_dowp_220)

layout_dowp.addWidget(QLabel("<b>3. AutoPopupComboBox (Ancho dinámico con Slider):</b>"))
cb_dowp_dyn_auto = AutoPopupComboBox()
cb_dowp_dyn_auto.setFixedWidth(200)
cb_dowp_dyn_auto.addItems(items_prueba)
layout_dowp.addWidget(cb_dowp_dyn_auto)

layout_dowp.addWidget(QLabel("<b>4. QComboBox Estándar (Ancho dinámico con Slider):</b>"))
cb_dowp_dyn_std = QComboBox()
cb_dowp_dyn_std.setFixedWidth(200)
cb_dowp_dyn_std.addItems(items_prueba)
layout_dowp.addWidget(cb_dowp_dyn_std)

layout_dowp.addWidget(QLabel("<b>5. Selector de Etiquetas (Con Íconos Circulares y Color):</b>"))
from gui.styles import create_colored_circle_icon, update_label_combobox_style
cb_dowp_tags = AutoPopupComboBox()
cb_dowp_tags.setFixedWidth(200)
cb_dowp_tags.addItem("Etiqueta", "")
cb_dowp_tags.addItem(create_colored_circle_icon("#3388ff", 12), "Pruebas", "")
cb_dowp_tags.setItemData(1, "#3388ff", Qt.UserRole + 1)
cb_dowp_tags.addItem(create_colored_circle_icon("#ff5555", 12), "Importante", "")
cb_dowp_tags.setItemData(2, "#ff5555", Qt.UserRole + 1)
cb_dowp_tags.addItem(create_colored_circle_icon("#B9E640", 12), "Finalizado", "")
cb_dowp_tags.setItemData(3, "#B9E640", Qt.UserRole + 1)
cb_dowp_tags.setCurrentIndex(1)
cb_dowp_tags.currentIndexChanged.connect(lambda idx: update_label_combobox_style(cb_dowp_tags))
layout_dowp.addWidget(cb_dowp_tags)

layout_dowp.addStretch()

# Aplicar el stylesheet al panel de DowP
qss = load_stylesheet("dark")
group_dowp.setStyleSheet(qss)
panels_layout.addWidget(group_dowp)

# -------------------------------------------------------------
# Panel Derecho: SIN ESTILO (Fusion Puro / Nativo)
# -------------------------------------------------------------
group_native = QGroupBox("SIN Estilo (Nativo Fusion sin QSS)")
layout_native = QVBoxLayout(group_native)
layout_native.setSpacing(8)

layout_native.addWidget(QLabel("<b>1. Ancho Compacto (150 px):</b>"))
cb_native_150 = QComboBox()
cb_native_150.setFixedWidth(150)
cb_native_150.addItems(items_prueba)
layout_native.addWidget(cb_native_150)

layout_native.addWidget(QLabel("<b>2. Ancho Medio (220 px):</b>"))
cb_native_220 = QComboBox()
cb_native_220.setFixedWidth(220)
cb_native_220.addItems(items_prueba)
layout_native.addWidget(cb_native_220)

layout_native.addWidget(QLabel("<b>3. AutoPopupComboBox (Ancho dinámico con Slider):</b>"))
cb_native_dyn_auto = AutoPopupComboBox()
cb_native_dyn_auto.setFixedWidth(200)
cb_native_dyn_auto.addItems(items_prueba)
layout_native.addWidget(cb_native_dyn_auto)

layout_native.addWidget(QLabel("<b>4. QComboBox Estándar (Ancho dinámico con Slider):</b>"))
cb_native_dyn_std = QComboBox()
cb_native_dyn_std.setFixedWidth(200)
cb_native_dyn_std.addItems(items_prueba)
layout_native.addWidget(cb_native_dyn_std)

layout_native.addWidget(QLabel("<b>5. Selector de Etiquetas (Con Íconos Circulares y Color):</b>"))
cb_native_tags = AutoPopupComboBox()
cb_native_tags.setFixedWidth(200)
cb_native_tags.addItem("Etiqueta", "")
cb_native_tags.addItem(create_colored_circle_icon("#3388ff", 12), "Pruebas", "")
cb_native_tags.setItemData(1, "#3388ff", Qt.UserRole + 1)
cb_native_tags.addItem(create_colored_circle_icon("#ff5555", 12), "Importante", "")
cb_native_tags.setItemData(2, "#ff5555", Qt.UserRole + 1)
cb_native_tags.addItem(create_colored_circle_icon("#B9E640", 12), "Finalizado", "")
cb_native_tags.setItemData(3, "#B9E640", Qt.UserRole + 1)
layout_native.addWidget(cb_native_tags)

layout_native.addStretch()
panels_layout.addWidget(group_native)

root_layout.addLayout(panels_layout)

# Conectar el slider para redimensionar los combos dinámicos en vivo
def on_slider_changed(val):
    lbl_val.setText(f"{val} px")
    cb_dowp_dyn_auto.setFixedWidth(val)
    cb_dowp_dyn_std.setFixedWidth(val)
    cb_native_dyn_auto.setFixedWidth(val)
    cb_native_dyn_std.setFixedWidth(val)

slider_w.valueChanged.connect(on_slider_changed)

win.setCentralWidget(central_widget)
win.show()

sys.exit(app.exec())