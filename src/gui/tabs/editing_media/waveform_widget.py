# src/gui/tabs/editing_media/waveform_widget.py
import math
from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QColor, QPen

from gui.styles import get_theme_token

class AudioWaveformWidget(QWidget):
    """Widget que dibuja una forma de onda de audio real e interactiva con barra de reproducción."""
    
    # Señal emitida cuando el usuario hace clic para cambiar la posición del audio (seek)
    seek_requested = Signal(float)  # Retorna el porcentaje (0.0 a 1.0)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(70)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        # Posición de reproducción (0.0 a 1.0)
        self._playback_ratio = 0.0
        self.audio_path = ""
        self.peaks = []  # Almacena las amplitudes reales

    def set_audio_path(self, path: str):
        """Asocia la ruta del archivo de audio."""
        self.audio_path = path or ""
        self.peaks = []  # Reiniciar picos para forzar recálculo asíncrono
        self.update()

    def set_peaks(self, peaks: list):
        """Asigna los picos reales extraídos del audio y repinta."""
        self.peaks = peaks or []
        self.update()

    def set_playback_ratio(self, ratio: float):
        """Actualiza la posición del cabezal y repinta el widget."""
        self._playback_ratio = max(0.0, min(ratio, 1.0))
        self.update()

    def get_playback_ratio(self) -> float:
        return self._playback_ratio

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        width = self.width()
        height = self.height()
        acento = get_theme_token('acento_primario', '#B9E640')
        fondo_normal = get_theme_token('fondo_principal', '#0a0a0a')

        # Fondo del espectro
        painter.fillRect(0, 0, width, height, QColor(fondo_normal))

        mid_y = height / 2

        # 1. Determinar el set de picos a renderizar (reales o simulados por defecto)
        if not self.peaks:
            # Si no hay picos reales cargados aún, dibujar una onda senoidal elegante y simple
            peaks_to_draw = []
            num_sim_bars = 80
            for i in range(num_sim_bars):
                val = (math.sin(i * 0.25) * 0.4 + math.cos(i * 0.1) * 0.2 + 0.35)
                peaks_to_draw.append(max(0.05, min(val, 0.95)))
        else:
            peaks_to_draw = self.peaks

        num_bars = len(peaks_to_draw)
        if num_bars == 0:
            return

        # Rango horizontal para dibujar las barras (de 10 a width - 10)
        start_x = 10
        end_x = width - 10
        span = max(1, end_x - start_x)

        # Calcular ancho de barra y espaciado dinámicamente
        step = span / (num_bars - 1) if num_bars > 1 else span
        bar_width = max(1, int(step * 0.6))

        # Configurar pincel para las barras
        pen = QPen()
        pen.setWidth(bar_width)
        pen.setCapStyle(Qt.RoundCap)

        # Cabezal de reproducción
        playhead_x = start_x + self._playback_ratio * span

        # 2. Dibujar las barras de amplitudes
        for i, peak in enumerate(peaks_to_draw):
            x = start_x + i * step
            if x >= width:
                break

            wave_h = peak * (height - 14)
            wave_h = max(2, wave_h)

            # Color según si ya fue reproducido o no
            col = QColor(acento)
            if x <= playhead_x:
                # Ya reproducido: color acento brillante
                pen.setColor(col)
            else:
                # No reproducido: semi-transparente
                col.setAlpha(60)
                pen.setColor(col)

            painter.setPen(pen)
            painter.drawLine(int(x), int(mid_y - wave_h / 2), int(x), int(mid_y + wave_h / 2))

        # 3. Dibujar cabezal de reproducción (línea vertical roja)
        if self.audio_path or self.peaks:
            pen_head = QPen(QColor("#ff6c6b"), 2)
            painter.setPen(pen_head)
            painter.drawLine(int(playhead_x), 4, int(playhead_x), height - 4)

    def mousePressEvent(self, event):
        """Permite hacer click en la onda para buscar posiciones (seeking)."""
        if event.button() == Qt.LeftButton:
            x = event.position().x()
            start_x = 10
            end_x = self.width() - 10
            span = end_x - start_x
            if span > 0:
                ratio = (x - start_x) / span
                ratio = max(0.0, min(ratio, 1.0))
                self.seek_requested.emit(ratio)
                self.set_playback_ratio(ratio)
            super().mousePressEvent(event)
