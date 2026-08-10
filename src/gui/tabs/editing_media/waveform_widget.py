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
        self.is_loading = False
        self.loading_phase = 0.0

        # Selección rápida (lite subclip)
        self._lite_start_ratio = None
        self._lite_end_ratio = None

        # Timer para animación de carga
        from PySide6.QtCore import QTimer
        self.loading_timer = QTimer(self)
        self.loading_timer.setInterval(30)  # ~33 FPS
        self.loading_timer.timeout.connect(self._animate_loading)

    def set_loading(self, loading: bool):
        """Activa o desactiva la animación de carga."""
        self.is_loading = loading
        if loading:
            self.peaks = []
            if not self.loading_timer.isActive():
                self.loading_timer.start()
        else:
            self.loading_timer.stop()
        self.update()

    def _animate_loading(self):
        self.loading_phase += 0.15
        if self.loading_phase > 2 * math.pi:
            self.loading_phase -= 2 * math.pi
        self.update()

    def set_audio_path(self, path: str):
        """Asocia la ruta del archivo de audio."""
        self.audio_path = path or ""
        self.peaks = []  # Reiniciar picos para forzar recálculo asíncrono
        if not path:
            self.set_loading(False)
        self.update()

    def set_peaks(self, peaks: list):
        """Asigna los picos reales extraídos del audio y repinta."""
        self._raw_peaks = list(peaks) if peaks else []
        self.peaks = self._raw_peaks
        self.set_loading(False)  # Detener animación cuando se asignan picos
        self.clear_lite_selection()
        self.update()

    def get_lite_selection(self):
        """Devuelve una tupla (in_ratio, out_ratio) si existe una selección, o (None, None)."""
        if self._lite_start_ratio is not None and self._lite_end_ratio is not None:
            if self._lite_start_ratio == self._lite_end_ratio:
                return None, None
            return min(self._lite_start_ratio, self._lite_end_ratio), max(self._lite_start_ratio, self._lite_end_ratio)
        return None, None

    def clear_lite_selection(self):
        """Limpia la selección rápida."""
        self._lite_start_ratio = None
        self._lite_end_ratio = None
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_raw_peaks") and self._raw_peaks and not self.is_loading:
            self.peaks = self._raw_peaks
            self.update()

    def _resample_peaks(self, peaks: list, target_count: int) -> list:
        if not peaks or target_count <= 0 or len(peaks) == target_count:
            return peaks
        n = len(peaks)
        resampled = []
        for i in range(target_count):
            pos = i * (n - 1) / max(1, target_count - 1)
            idx = int(pos)
            frac = pos - idx
            if idx >= n - 1:
                resampled.append(peaks[-1])
            else:
                val = peaks[idx] * (1.0 - frac) + peaks[idx + 1] * frac
                resampled.append(val)
        return resampled

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

        # Highlight de selección rápida (lite subclip)
        in_ratio, out_ratio = self.get_lite_selection()
        if in_ratio is not None and out_ratio is not None:
            sel_start_x = 10
            sel_span = max(1, (width - 10) - sel_start_x)
            sel_x = sel_start_x + in_ratio * sel_span
            sel_w = (out_ratio - in_ratio) * sel_span
            
            # Fondo de la selección
            sel_color = QColor(acento)
            sel_color.setAlpha(30)
            painter.fillRect(int(sel_x), 0, int(sel_w), height, sel_color)
            
            # Bordes de la selección
            pen_border = QPen(QColor(acento), 1)
            painter.setPen(pen_border)
            painter.drawLine(int(sel_x), 0, int(sel_x), height)
            painter.drawLine(int(sel_x + sel_w), 0, int(sel_x + sel_w), height)

        mid_y = height / 2

        # Usamos una cantidad constante de barras
        target_num_bars = 120

        # 1. Determinar el set de picos a renderizar (reales o animados de carga)
        if self.is_loading:
            peaks_to_draw = []
            num_sim_bars = target_num_bars
            for i in range(num_sim_bars):
                # Onda oscilante dinámica
                val = math.sin(i * 0.15 + self.loading_phase) * 0.25 + 0.35
                pulse = math.sin(self.loading_phase * 0.5) * 0.1 + 0.9
                peaks_to_draw.append(max(0.05, min(val * pulse, 0.95)))
        elif not self.peaks:
            # Si no hay picos y no está cargando, dejar vacío (evita confusión)
            return
        else:
            peaks_to_draw = self.peaks

        num_bars = len(peaks_to_draw)
        if num_bars == 0:
            return

        # Rango horizontal para dibujar las barras (de 10 a width - 10)
        start_x = 10
        end_x = width - 10
        span = max(1, end_x - start_x)

        # Calcular ancho de barra y espaciado basándose STRICTAMENTE en la cantidad real de picos a dibujar
        step = span / (num_bars - 1) if num_bars > 1 else span
        bar_width = max(1, min(int(step * 0.6), 8))

        # Configurar pincel para las barras
        pen = QPen()
        pen.setWidth(bar_width)
        pen.setCapStyle(Qt.RoundCap)

        # Para que QPainter con Antialiasing no difumine las líneas, debemos alinearlas
        # a los centros de los píxeles (offset=0.5) si el grosor es impar.
        offset = 0.5 if bar_width % 2 != 0 else 0.0

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
            if self.is_loading:
                # Efecto shimmer/glimmer en la transparencia durante la carga
                alpha = int(100 + 50 * math.sin(self.loading_phase + i * 0.15))
                col.setAlpha(max(20, min(alpha, 255)))
                pen.setColor(col)
            elif x <= playhead_x:
                # Ya reproducido: color acento brillante
                pen.setColor(col)
            else:
                # No reproducido: semi-transparente
                col.setAlpha(60)
                pen.setColor(col)

            painter.setPen(pen)
            x_coord = int(x) + offset
            from PySide6.QtCore import QPointF
            painter.drawLine(QPointF(x_coord, mid_y - wave_h / 2), QPointF(x_coord, mid_y + wave_h / 2))

        # 3. Dibujar cabezal de reproducción (línea vertical roja)
        if (self.audio_path or self.peaks) and not self.is_loading:
            pen_head = QPen(QColor("#ff6c6b"), 2)
            painter.setPen(pen_head)
            painter.drawLine(int(playhead_x), 4, int(playhead_x), height - 4)

    def mousePressEvent(self, event):
        """Permite hacer click en la onda para buscar posiciones (seeking) o iniciar selección (clic derecho)."""
        x = event.position().x()
        start_x = 10
        end_x = self.width() - 10
        span = end_x - start_x
        if span > 0:
            ratio = (x - start_x) / span
            ratio = max(0.0, min(ratio, 1.0))
            
            if event.button() == Qt.LeftButton:
                self.seek_requested.emit(ratio)
                self.set_playback_ratio(ratio)
            elif event.button() == Qt.RightButton:
                self._lite_start_ratio = ratio
                self._lite_end_ratio = ratio
                self.update()

    def mouseMoveEvent(self, event):
        """Permite arrastrar el cabezal de reproducción (scrubbing) o la selección (clic derecho) a través de la onda."""
        x = event.position().x()
        start_x = 10
        end_x = self.width() - 10
        span = end_x - start_x
        if span > 0:
            ratio = (x - start_x) / span
            ratio = max(0.0, min(ratio, 1.0))
            
            if event.buttons() & Qt.LeftButton:
                self.seek_requested.emit(ratio)
                self.set_playback_ratio(ratio)
            elif event.buttons() & Qt.RightButton:
                self._lite_end_ratio = ratio
                self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Finaliza la selección o la limpia si fue solo un clic."""
        if event.button() == Qt.RightButton:
            if self._lite_start_ratio is not None and self._lite_end_ratio is not None:
                if abs(self._lite_start_ratio - self._lite_end_ratio) < 0.005:
                    self.clear_lite_selection()
        super().mouseReleaseEvent(event)
