# src/gui/widgets/volume_control.py
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QSlider, QStyle, QStyleOptionSlider
from PySide6.QtCore import Qt, Signal, QSize
from gui.styles import apply_volume_control_style
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon


class ClickJumpSlider(QSlider):
    """
    QSlider personalizado que salta inmediatamente a la posición donde se hace clic o arrastra,
    en lugar de avanzar por bloques (pageStep).
    """
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            val = self._calc_value_from_pos(event.position().x() if hasattr(event, 'position') else event.x())
            self.setValue(val)
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            val = self._calc_value_from_pos(event.position().x() if hasattr(event, 'position') else event.x())
            self.setValue(val)
            event.accept()
        super().mouseMoveEvent(event)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        step = 5 if delta > 0 else -5
        self.setValue(self.value() + step)
        event.accept()

    def _calc_value_from_pos(self, x_pos):
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        sr = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self)
        
        handle_width = sr.width() if sr.isValid() and sr.width() > 0 else 10
        half_handle = handle_width / 2.0
        total_width = self.width()
        
        if total_width <= handle_width:
            return self.minimum()
            
        usable_width = total_width - handle_width
        clamped_x = max(half_handle, min(float(x_pos), total_width - half_handle))
        ratio = (clamped_x - half_handle) / usable_width
        
        if self.invertedAppearance():
            ratio = 1.0 - ratio
            
        val = round(self.minimum() + ratio * (self.maximum() - self.minimum()))
        return max(self.minimum(), min(self.maximum(), val))


class VolumeControlWidget(QWidget):
    """
    Widget unificado para el control de volumen en reproductores.
    Incluye un botón de Mute con íconos dinámicos y un QSlider horizontal.
    """
    volume_changed = Signal(float)       # Emite valor flotante (0.0 a 1.0)
    volume_value_changed = Signal(int)   # Emite valor entero (0 a 100)

    def __init__(self, parent=None, initial_volume=70, slider_width=75):
        super().__init__(parent)
        self._last_non_zero_volume = initial_volume if initial_volume > 0 else 70
        self._is_muted = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 1. Botón Mute / Alternador de Volumen
        self.btn_mute = QPushButton(self)
        self.btn_mute.setFixedSize(24, 24)
        self.btn_mute.setToolTip("Silenciar / Activar sonido")
        self.btn_mute.clicked.connect(self.toggle_mute)
        layout.addWidget(self.btn_mute)

        # 2. Slider de Volumen
        self.slider = ClickJumpSlider(Qt.Horizontal, self)
        self.slider.setRange(0, 100)
        self.slider.setFixedWidth(slider_width)
        self.slider.setValue(initial_volume)
        self.slider.valueChanged.connect(self._on_slider_value_changed)
        layout.addWidget(self.slider)

        # Aplicar estilo inicial de temas
        self._update_ui()

    def set_volume(self, value: int):
        """Establece el nivel de volumen (0 a 100) programáticamente."""
        self.slider.setValue(max(0, min(100, value)))

    def get_volume(self) -> int:
        """Devuelve el nivel actual del slider (0 a 100)."""
        return self.slider.value()

    def set_slider_visible(self, visible: bool):
        """Muestra u oculta el slider horizontal (útil para vistas muy compactas)."""
        self.slider.setVisible(visible)

    def is_muted(self) -> bool:
        """Devuelve si el audio está actualmente silenciado."""
        return self._is_muted

    def toggle_mute(self):
        """Alterna el estado de silencio (Mute ON / OFF) con 1 clic."""
        if self._is_muted:
            # Desilenciar: restaurar volumen anterior
            self._is_muted = False
            restore_vol = self._last_non_zero_volume if self._last_non_zero_volume > 0 else 70
            self.slider.setValue(restore_vol)
        else:
            # Silenciar: guardar volumen actual y poner en 0
            curr_vol = self.slider.value()
            if curr_vol > 0:
                self._last_non_zero_volume = curr_vol
            self._is_muted = True
            self.slider.setValue(0)

    def _on_slider_value_changed(self, value: int):
        if value > 0:
            self._last_non_zero_volume = value
            self._is_muted = False
        else:
            self._is_muted = True

        self._update_ui()
        self.volume_changed.emit(value / 100.0)
        self.volume_value_changed.emit(value)

    def _update_ui(self):
        """Actualiza el ícono del botón y aplica los estilos del tema."""
        val = self.slider.value()

        if self._is_muted or val == 0:
            icon_name = "volume_off.svg" if self._is_muted else "volume_mute.svg"
            icon_color = "#6c7086"
        elif val < 50:
            icon_name = "volume_down.svg"
            icon_color = "#cdd6f4"
        else:
            icon_name = "volume_up.svg"
            icon_color = "#cdd6f4"

        self.btn_mute.setIcon(get_colored_svg_icon(icon_name, icon_color, size=16))
        self.btn_mute.setIconSize(QSize(16, 16))

        # Aplicar estilos unificados de tema desde styles.py
        apply_volume_control_style(self.btn_mute, self.slider)
