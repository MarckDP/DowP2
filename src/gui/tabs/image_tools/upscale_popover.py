# src/gui/tabs/image_tools/upscale_popover.py
"""Contenido del popover "Reescalar IA" del Editor de Imagen: elegir motor (Waifu2x/
SRMD/Upscayl) y sus parámetros -- misma cascada y mismos controles que usaba DowP 1
(image_tools_tab.pyc, upscale_options_frame, líneas 854-900 y 1298-1410): Motor,
Modelo, Escala, Tile Size, Potencia (concurrencia), Reducir Ruido (oculto para
Upscayl, relabeled "Nivel Ruido/Blur" para SRMD) y TTA.

DowP 1 no tiene ningún toggle de GPU/CPU para reescalado -- los 3 motores son
binarios NCNN-Vulkan, siempre por GPU (sin modo CPU). "Potencia" es lo más parecido
(concurrencia de hilos/carga GPU, no un on/off de hardware).

Solo selección: no dispara ningún reescalado todavía, eso se conecta en un paso
aparte."""
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit, QCheckBox,
)
from PySide6.QtCore import Signal
from PySide6.QtGui import QFontMetrics

from gui.styles import get_theme_token
from core.constants import (
    UPSCALING_TOOLS, WAIFU2X_MODELS, SRMD_MODELS, UPSCAYL_MODELS_MAP,
    AI_ENGINE_HOLDER, AI_MODEL_HOLDER,
)
from core.setup.models_setup import is_upscaling_engine_installed

_TILE_TOOLTIP = (
    "Tamaño del bloque de procesamiento (VRAM).\n"
    "0 = Automático (Recomendado).\n"
    "Prueba 128 o 256 si tienes errores de GPU."
)
_POWER_TOOLTIP = (
    "Control de hilos (concurrencia).\n"
    "'Seguro' evita crashes en GPUs modestas.\n"
    "'Máximo' usa toda la potencia pero puede colgar el PC."
)


class UpscalePopoverContent(QFrame):
    """selection_changed(engine_key, model_key, is_valid) -- model_key es la clave
    amigable dentro del motor elegido (nombre de familia Waifu2x/SRMD, o nombre de
    archivo crudo de Upscayl tomado de UPSCAYL_MODELS_MAP). is_valid es False
    mientras Motor y/o Modelo sigan en su placeholder."""
    selection_changed = Signal(str, str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("upscalePopover")
        bg = get_theme_token('fondo_secundario', '#1e1e1e')
        border = get_theme_token('borde_normal', '#2d2d2d')
        self.setStyleSheet(f"""
            QFrame#upscalePopover {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        self._label_widgets = []

        title = QLabel(self.tr("Reescalar con IA"))
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(title)

        # Motor
        engine_row = QHBoxLayout()
        engine_row.addWidget(self._label("Motor:"))
        self.combo_engine = QComboBox()
        self.combo_engine.addItem(AI_ENGINE_HOLDER, None)
        for key, info in UPSCALING_TOOLS.items():
            installed = is_upscaling_engine_installed(info)
            label = f"{info['name']} {'✓' if installed else '✗ (no descargado)'}"
            self.combo_engine.addItem(label, key)
        self.combo_engine.currentIndexChanged.connect(self._on_engine_changed)
        engine_row.addWidget(self.combo_engine, 1)
        layout.addLayout(engine_row)

        # Modelo
        model_row = QHBoxLayout()
        model_row.addWidget(self._label("Modelo:"))
        self.combo_model = QComboBox()
        self.combo_model.addItem(AI_MODEL_HOLDER, None)
        self.combo_model.currentIndexChanged.connect(self._on_model_changed)
        model_row.addWidget(self.combo_model, 1)
        layout.addLayout(model_row)

        # Escala (estático 2x/3x/4x, igual que DowP 1 -- no depende del modelo elegido)
        scale_row = QHBoxLayout()
        scale_row.addWidget(self._label("Escala:"))
        self.combo_scale = QComboBox()
        self.combo_scale.addItems(["2x", "3x", "4x"])
        scale_row.addWidget(self.combo_scale)
        scale_row.addStretch()
        scale_row.addWidget(QLabel(self.tr("Tile Size:")))
        self.entry_tile = QLineEdit("0")
        self.entry_tile.setFixedWidth(60)
        self.entry_tile.setToolTip(_TILE_TOOLTIP)
        scale_row.addWidget(self.entry_tile)
        layout.addLayout(scale_row)

        # Potencia (concurrencia)
        power_row = QHBoxLayout()
        power_row.addWidget(self._label("Potencia:"))
        self.combo_power = QComboBox()
        self.combo_power.addItems(["Automático", "Seguro (Estabilidad)", "Equilibrado", "Máximo (Potente)"])
        self.combo_power.setToolTip(_POWER_TOOLTIP)
        power_row.addWidget(self.combo_power, 1)
        layout.addLayout(power_row)

        # Reducir Ruido -- visibilidad/label cambia según el motor (ver _on_engine_changed)
        self.lbl_denoise = self._label("Reducir Ruido:")
        self.combo_denoise = QComboBox()
        self.combo_denoise.addItems(["-1 (Ninguna)", "0 (Baja)", "1 (Media)", "2 (Alta)", "3 (Máxima)"])
        self.combo_denoise.setCurrentText("2 (Alta)")
        denoise_row_layout = QHBoxLayout()
        denoise_row_layout.addWidget(self.lbl_denoise)
        denoise_row_layout.addWidget(self.combo_denoise, 1)
        layout.addLayout(denoise_row_layout)
        self._denoise_widgets = (self.lbl_denoise, self.combo_denoise)

        # TTA
        self.check_tta = QCheckBox(self.tr("TTA (Mejor calidad, muy lento)"))
        layout.addWidget(self.check_tta)

        self.lbl_warning = QLabel()
        self.lbl_warning.setWordWrap(True)
        self.lbl_warning.setStyleSheet(f"color: {get_theme_token('estado_aviso', '#e6a23c')}; font-size: 11px;")
        self.lbl_warning.setVisible(False)
        layout.addWidget(self.lbl_warning)

        self._set_denoise_visible(False)
        self._resize_label_column()

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(self.tr(text))
        self._label_widgets.append(lbl)
        return lbl

    def _resize_label_column(self):
        """Ancho de columna calculado según la etiqueta más larga (incluye
        "Nivel Ruido/Blur:", que solo se ve con SRMD) en vez de un fijo arbitrario --
        antes 60px recortaba ese texto contra el combo de al lado, dando la sensación
        de que todo estaba "pegado". Con esto el cuadro directamente se agranda lo
        necesario (reposition() ya recalcula sizeHint() en cada apertura/resize)."""
        fm = QFontMetrics(self.font())
        candidates = [w.text() for w in self._label_widgets] + [self.tr("Nivel Ruido/Blur:")]
        width = max(fm.horizontalAdvance(t) for t in candidates) + 6
        for w in self._label_widgets:
            w.setFixedWidth(width)

    def _current_engine_key(self):
        return self.combo_engine.currentData()

    def _set_denoise_visible(self, visible: bool):
        for w in self._denoise_widgets:
            w.setVisible(visible)

    def _on_engine_changed(self, _index: int):
        engine_key = self._current_engine_key()

        self.combo_model.blockSignals(True)
        self.combo_model.clear()
        self.combo_model.addItem(AI_MODEL_HOLDER, None)
        if engine_key == "Waifu2x":
            for name, info in WAIFU2X_MODELS.items():
                scales = "/".join(info["scales"])
                self.combo_model.addItem(f"{name} ({scales})", name)
            self.lbl_denoise.setText(self.tr("Reducir Ruido:"))
            self._set_denoise_visible(True)
        elif engine_key == "SRMD":
            for name, info in SRMD_MODELS.items():
                scales = "/".join(info["scales"])
                self.combo_model.addItem(f"{name} ({scales})", name)
            self.lbl_denoise.setText(self.tr("Nivel Ruido/Blur:"))
            self._set_denoise_visible(True)
        elif engine_key == "Upscayl":
            for raw_name, friendly_name in UPSCAYL_MODELS_MAP.items():
                self.combo_model.addItem(friendly_name, raw_name)
            self._set_denoise_visible(False)
        else:
            self._set_denoise_visible(False)
        self.combo_model.blockSignals(False)

        self._update_warning()
        self._emit_selection()

    def _on_model_changed(self, _index: int):
        self._emit_selection()

    def _update_warning(self):
        engine_key = self._current_engine_key()
        info = UPSCALING_TOOLS.get(engine_key)
        if info and not is_upscaling_engine_installed(info):
            self.lbl_warning.setText(
                self.tr("Este motor no está descargado — andá a Ajustes > Modelos para instalarlo.")
            )
            self.lbl_warning.setVisible(True)
        else:
            self.lbl_warning.setVisible(False)

    def is_valid_selection(self) -> bool:
        return self.combo_engine.currentData() is not None and self.combo_model.currentData() is not None

    def _emit_selection(self):
        engine_key = self.combo_engine.currentData()
        model_key = self.combo_model.currentData()
        self.selection_changed.emit(engine_key or "", model_key or "", self.is_valid_selection())

    def current_selection(self) -> tuple[str, str]:
        return self.combo_engine.currentData(), self.combo_model.currentData()
