import math
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QLinearGradient

class AudioVolumeMeterWidget(QWidget):
    """Medidor de volumen vertical en decibelios (simulado)."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(36)
        self.setMinimumHeight(50)
        self._level = 0.0  # 0.0 a 1.0
        self._peak = 0.0
        self._peak_decay = 0.0

    def set_level(self, level: float):
        """Asigna el nivel de volumen lineal (0.0 a 1.0)."""
        self._level = max(0.0, min(level, 1.0))
        if self._level >= self._peak:
            self._peak = self._level
            self._peak_decay = 0.01
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        w = self.width()
        h = self.height()
        
        # Fondo oscuro
        painter.fillRect(0, 0, w, h, QColor("#141414"))
        
        if h <= 0:
            return
            
        bar_w = 14
        bar_x = w - bar_w - 2 # A la derecha
        
        # Borde
        painter.setPen(QColor("#2d2d2d"))
        painter.drawRect(bar_x, 0, bar_w, h - 1)
            
        # Gradiente (Verde -> Amarillo -> Rojo)
        grad = QLinearGradient(0, h, 0, 0)
        grad.setColorAt(0.0, QColor("#1DC038"))  # Verde abajo
        grad.setColorAt(0.7, QColor("#FFC107"))  # Amarillo al medio/alto
        grad.setColorAt(1.0, QColor("#FF5555"))  # Rojo arriba
        
        # Dibujar nivel actual
        level_h = self._level * h
        y_level = h - level_h
        painter.fillRect(bar_x + 1, int(y_level), bar_w - 1, int(level_h), grad)
        
        # Caída de pico
        if self._peak > 0:
            peak_h = self._peak * h
            y_peak = h - peak_h
            painter.fillRect(bar_x + 1, int(y_peak), bar_w - 1, 2, QColor("#FFFFFF"))
            
            # Decaimiento del pico para animación suave
            if self._peak > self._level:
                self._peak -= 0.025
                if self._peak < self._level:
                    self._peak = self._level

        # Dibujar marcas y texto (dB)
        painter.setPen(QColor("#888888"))
        font = painter.font()
        font.setPointSize(7)
        font.setBold(True)
        painter.setFont(font)
        
        # Marcas lineales relativas al pico (esto es visual para acompañar la forma de onda)
        marks = [(1.0, "0"), (0.7, "-6"), (0.45, "-12"), (0.2, "-24"), (0.05, "-48")]
        for ratio, text in marks:
            y = int(h - (ratio * h))
            if y >= h - 1: y = h - 2
            if y <= 5: y = 7
            painter.drawLine(bar_x - 3, y, bar_x, y)
            # Dibujar el texto alineado a la derecha antes de la barra
            text_rect = painter.boundingRect(0, y - 6, bar_x - 5, 12, Qt.AlignRight | Qt.AlignVCenter, text)
            painter.drawText(text_rect, Qt.AlignRight | Qt.AlignVCenter, text)


class MultiChannelMeterWidget(QWidget):
    """Medidor de volumen con una barra vertical POR CANAL: 1 barra si el audio es mono,
    2 si es estéreo, 6 si es 5.1, 8 si es 7.1, etc. — en vez de una sola barra mezclada.

    La escala en dB se dibuja una sola vez a la izquierda (compartida por todas las barras)
    para no repetir el texto por cada canal y mantener el widget compacto."""

    _LABEL_W = 20
    _BAR_W = 10
    _BAR_GAP = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self._channel_count = 2
        self._levels = [0.0, 0.0]
        self._peaks = [0.0, 0.0]
        self.setMinimumHeight(50)
        self._update_fixed_width()

    def channel_count(self) -> int:
        return self._channel_count

    def set_channel_count(self, count: int):
        count = max(1, int(count))
        if count == self._channel_count:
            return
        self._channel_count = count
        self._levels = [0.0] * count
        self._peaks = [0.0] * count
        self._update_fixed_width()
        self.update()

    def _update_fixed_width(self):
        self.setFixedWidth(self._LABEL_W + self._channel_count * (self._BAR_W + self._BAR_GAP))

    def set_levels(self, levels):
        """Asigna el nivel lineal (0.0 a 1.0) de cada canal. Si `levels` trae menos valores
        que canales tiene el medidor, los canales sobrantes se consideran en silencio."""
        for i in range(self._channel_count):
            lvl = max(0.0, min(levels[i], 1.0)) if i < len(levels) else 0.0
            self._levels[i] = lvl
            if lvl >= self._peaks[i]:
                self._peaks[i] = lvl
        self.update()

    def reset_levels(self):
        """Silencia el medidor (p.ej. al pausar/detener la reproducción)."""
        self._levels = [0.0] * self._channel_count
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        painter.fillRect(0, 0, w, h, QColor("#141414"))

        if h <= 0:
            return

        grad = QLinearGradient(0, h, 0, 0)
        grad.setColorAt(0.0, QColor("#1DC038"))
        grad.setColorAt(0.7, QColor("#FFC107"))
        grad.setColorAt(1.0, QColor("#FF5555"))

        # Escala en dB, compartida a la izquierda de todas las barras
        painter.setPen(QColor("#888888"))
        font = painter.font()
        font.setPointSize(7)
        font.setBold(True)
        painter.setFont(font)

        marks = [(1.0, "0"), (0.7, "-6"), (0.45, "-12"), (0.2, "-24"), (0.05, "-48")]
        for ratio, text in marks:
            y = int(h - (ratio * h))
            if y >= h - 1: y = h - 2
            if y <= 5: y = 7
            text_rect = painter.boundingRect(0, y - 6, self._LABEL_W - 4, 12, Qt.AlignRight | Qt.AlignVCenter, text)
            painter.drawText(text_rect, Qt.AlignRight | Qt.AlignVCenter, text)

        # Una barra por canal
        for i in range(self._channel_count):
            bar_x = self._LABEL_W + i * (self._BAR_W + self._BAR_GAP)

            painter.setPen(QColor("#2d2d2d"))
            painter.drawRect(bar_x, 0, self._BAR_W, h - 1)

            level = self._levels[i]
            level_h = level * h
            y_level = h - level_h
            painter.fillRect(bar_x + 1, int(y_level), self._BAR_W - 1, int(level_h), grad)

            peak = self._peaks[i]
            if peak > 0:
                peak_h = peak * h
                y_peak = h - peak_h
                painter.fillRect(bar_x + 1, int(y_peak), self._BAR_W - 1, 2, QColor("#FFFFFF"))

                if peak > level:
                    self._peaks[i] -= 0.025
                    if self._peaks[i] < level:
                        self._peaks[i] = level
