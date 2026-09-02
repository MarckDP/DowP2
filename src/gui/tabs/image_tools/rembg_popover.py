# src/gui/tabs/image_tools/rembg_popover.py
"""Contenido del popover "Eliminar Fondo (IA)" del Editor de Imagen -- misma cascada y
mismos controles que usaba DowP 1 (image_tools_tab.pyc, rembg_master_frame/
rembg_options_frame, líneas 784-847): Aceleración GPU (checkbox, encendida por
defecto -- este SÍ tiene toggle GPU/CPU, a diferencia del reescalado que es siempre
GPU), Motor (así lo llamaba DowP 1, aunque en realidad es la FAMILIA del modelo:
Rembg Standard/BiRefNet/RMBG 2.0/InSPyReNet), Modelo, Suavizado (difumina el borde,
0-20px) y Exp/Contr (contrae/expande el recorte, -10..+10px).

Sin checkbox propio de "activar/desactivar" -- mismo criterio que upscale_popover.py:
mientras Motor y/o Modelo sigan en su placeholder, la función no se aplica (botón
gris); al elegir ambos, se aplica (botón verde). Sin botones Abrir/Borrar inline --
esos ya viven en Ajustes > Modelos (ver models_page.py); acá solo se avisa si el
modelo elegido no está instalado o requiere descarga manual.

Solo selección: no dispara ningún procesamiento todavía, eso se conecta en un paso
aparte."""
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QCheckBox, QSlider,
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFontMetrics

from gui.styles import get_theme_token
from core.constants import REMBG_MODEL_FAMILIES, AI_ENGINE_HOLDER, AI_MODEL_HOLDER
from core.setup.models_setup import is_rembg_model_installed, is_rembg_model_gated

_GPU_TOOLTIP = (
    "Si está activo, usa la tarjeta gráfica (GPU).\n"
    "Si se desactiva, usará el procesador (CPU) a máxima potencia.\n"
    "Desactívalo si tienes problemas de drivers o cuelgues."
)
_SMOOTH_TOOLTIP = (
    "Difumina el borde del recorte para una transición más suave.\n"
    "0 = sin suavizado, 20 = máximo difuminado."
)
_EXPAND_TOOLTIP = (
    "Valores negativos contraen el recorte (elimina halos).\n"
    "Valores positivos expanden el recorte (recupera bordes cortados)."
)


class RembgPopoverContent(QFrame):
    """selection_changed(family_key, model_key, is_valid) -- model_key es el nombre
    amigable del modelo dentro de la familia elegida. is_valid es False mientras
    Motor y/o Modelo sigan en su placeholder."""
    selection_changed = Signal(str, str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("rembgPopover")
        bg = get_theme_token('fondo_secundario', '#1e1e1e')
        border = get_theme_token('borde_normal', '#2d2d2d')
        self.setStyleSheet(f"""
            QFrame#rembgPopover {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        self._label_widgets = []

        title = QLabel(self.tr("Eliminar Fondo con IA"))
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(title)

        # Aceleración por hardware -- a diferencia del reescalado (siempre GPU), rembg
        # sí corre por CPU si se desactiva (mismo default que DowP 1: encendida).
        self.check_gpu = QCheckBox(self.tr("Aceleración de Hardware (GPU)"))
        self.check_gpu.setChecked(True)
        self.check_gpu.setToolTip(_GPU_TOOLTIP)
        layout.addWidget(self.check_gpu)

        # Motor (familia del modelo)
        family_row = QHBoxLayout()
        family_row.addWidget(self._label("Motor:"))
        self.combo_family = QComboBox()
        self.combo_family.addItem(AI_ENGINE_HOLDER, None)
        for family_name in REMBG_MODEL_FAMILIES.keys():
            self.combo_family.addItem(family_name, family_name)
        self.combo_family.currentIndexChanged.connect(self._on_family_changed)
        family_row.addWidget(self.combo_family, 1)
        layout.addLayout(family_row)

        # Modelo
        model_row = QHBoxLayout()
        model_row.addWidget(self._label("Modelo:"))
        self.combo_model = QComboBox()
        self.combo_model.addItem(AI_MODEL_HOLDER, None)
        self.combo_model.currentIndexChanged.connect(self._on_model_changed)
        model_row.addWidget(self.combo_model, 1)
        layout.addLayout(model_row)

        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("font-size: 11px;")
        self.lbl_status.setVisible(False)
        layout.addWidget(self.lbl_status)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background-color: {border}; max-height: 1px; border: none;")
        layout.addWidget(sep)

        # Suavizado (feather del borde)
        smooth_row = QHBoxLayout()
        smooth_row.addWidget(self._label("Suavizado:"))
        self.slider_smooth = QSlider(Qt.Horizontal)
        self.slider_smooth.setRange(0, 20)
        self.slider_smooth.setValue(0)
        self.slider_smooth.setToolTip(_SMOOTH_TOOLTIP)
        self.lbl_smooth_value = QLabel("0 px")
        self.lbl_smooth_value.setFixedWidth(40)
        self.lbl_smooth_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.slider_smooth.valueChanged.connect(
            lambda v: self.lbl_smooth_value.setText(f"{v} px")
        )
        smooth_row.addWidget(self.slider_smooth, 1)
        smooth_row.addWidget(self.lbl_smooth_value)
        layout.addLayout(smooth_row)

        # Exp/Contr (contrae o expande el recorte)
        expand_row = QHBoxLayout()
        expand_row.addWidget(self._label("Exp/Contr:"))
        self.slider_expand = QSlider(Qt.Horizontal)
        self.slider_expand.setRange(-10, 10)
        self.slider_expand.setValue(0)
        self.slider_expand.setToolTip(_EXPAND_TOOLTIP)
        self.lbl_expand_value = QLabel("0 px")
        self.lbl_expand_value.setFixedWidth(40)
        self.lbl_expand_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.slider_expand.valueChanged.connect(self._on_expand_changed)
        expand_row.addWidget(self.slider_expand, 1)
        expand_row.addWidget(self.lbl_expand_value)
        layout.addLayout(expand_row)

        self._resize_label_column()

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(self.tr(text))
        self._label_widgets.append(lbl)
        return lbl

    def _resize_label_column(self):
        fm = QFontMetrics(self.font())
        candidates = [w.text() for w in self._label_widgets]
        width = max(fm.horizontalAdvance(t) for t in candidates) + 6
        for w in self._label_widgets:
            w.setFixedWidth(width)

    def _on_expand_changed(self, v: int):
        sign = "+" if v > 0 else ""
        self.lbl_expand_value.setText(f"{sign}{v} px")

    def _current_family_key(self):
        return self.combo_family.currentData()

    def _on_family_changed(self, _index: int):
        family_key = self._current_family_key()
        self.combo_model.blockSignals(True)
        self.combo_model.clear()
        self.combo_model.addItem(AI_MODEL_HOLDER, None)
        models = REMBG_MODEL_FAMILIES.get(family_key, {})
        for model_name, model_info in models.items():
            label = model_name
            if is_rembg_model_gated(model_info):
                label = f"{model_name} 🔒"
            self.combo_model.addItem(label, model_name)
        self.combo_model.blockSignals(False)
        self._update_status()
        self._emit_selection()

    def _on_model_changed(self, _index: int):
        self._update_status()
        self._emit_selection()

    def _update_status(self):
        family_key = self._current_family_key()
        model_key = self.combo_model.currentData()
        models = REMBG_MODEL_FAMILIES.get(family_key, {})
        model_info = models.get(model_key)
        if not model_info:
            self.lbl_status.setVisible(False)
            return
        if is_rembg_model_installed(model_info):
            self.lbl_status.setText(self.tr("✅ Modelo listo"))
            self.lbl_status.setStyleSheet(
                f"font-size: 11px; color: {get_theme_token('estado_exito', '#4caf50')};"
            )
        elif is_rembg_model_gated(model_info):
            self.lbl_status.setText(
                self.tr("🔒 Requiere descarga manual — andá a Ajustes > Modelos.")
            )
            self.lbl_status.setStyleSheet(
                f"font-size: 11px; color: {get_theme_token('estado_aviso', '#e6a23c')};"
            )
        else:
            self.lbl_status.setText(
                self.tr("⚠️ No instalado — andá a Ajustes > Modelos para descargarlo.")
            )
            self.lbl_status.setStyleSheet(
                f"font-size: 11px; color: {get_theme_token('estado_aviso', '#e6a23c')};"
            )
        self.lbl_status.setVisible(True)

    def is_valid_selection(self) -> bool:
        return self.combo_family.currentData() is not None and self.combo_model.currentData() is not None

    def _emit_selection(self):
        family_key = self.combo_family.currentData()
        model_key = self.combo_model.currentData()
        self.selection_changed.emit(family_key or "", model_key or "", self.is_valid_selection())

    def current_selection(self) -> tuple[str, str]:
        return self.combo_family.currentData(), self.combo_model.currentData()

    def gpu_enabled(self) -> bool:
        return self.check_gpu.isChecked()

    def smooth_value(self) -> int:
        return self.slider_smooth.value()

    def expand_value(self) -> int:
        return self.slider_expand.value()
