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
