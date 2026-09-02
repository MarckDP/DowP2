# src/gui/widgets/floating_panel.py
"""Ventana flotante arrastrable genérica -- a diferencia de CollapsiblePanel (que solo
desliza pegada a un borde), esta se puede mover libremente por encima de otro widget
(su `host`), agarrando la barra de título con el mouse. Pensada para el panel de Capas
del Editor de Imagen (estilo paneles flotantes de Photoshop), pero sin nada específico
de capas -- reusable para cualquier otro panel flotante futuro."""
from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget

from gui.styles import get_theme_token
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon


class _TitleBar(QWidget):
    close_clicked = Signal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.SizeAllCursor)
        self.setFixedHeight(28)
        self._drag_start = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 4, 0)
        layout.setSpacing(4)

        lbl = QLabel(title)
        lbl.setStyleSheet(f"color: {get_theme_token('texto_principal', '#ffffff')}; font-weight: bold; font-size: 12px;")
        layout.addWidget(lbl)
        layout.addStretch()

        self.btn_close = QPushButton()
        self.btn_close.setIcon(get_colored_svg_icon("close.svg", "#888888", size=12))
        self.btn_close.setFixedSize(18, 18)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setStyleSheet("border: none; background: transparent; padding: 0px;")
        self.btn_close.clicked.connect(self.close_clicked.emit)
        layout.addWidget(self.btn_close)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start is not None and (event.buttons() & Qt.LeftButton):
            panel = self.parent()
            global_pos = event.globalPosition().toPoint()
            delta = global_pos - self._drag_start
            self._drag_start = global_pos
            panel.move(panel.pos() + delta)
            panel.clamp_to_host()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        super().mouseReleaseEvent(event)


class FloatingPanel(QFrame):
    """`host` es el widget sobre el que flota (define los límites para no perderse
    fuera de la ventana -- ver clamp_to_host). `content` se agrega debajo de la barra
    de título tal cual, sin envolver en scroll: quien arma `content` es responsable de
    que su propio contenido no necesite scroll horizontal."""
    closed = Signal()

    def __init__(self, title: str, content: QWidget, host: QWidget, width: int = 260, parent=None):
        super().__init__(parent if parent is not None else host)
        self._host = host
        self.setObjectName("floatingPanel")
        self.setFixedWidth(width)
        bg = get_theme_token('fondo_secundario', '#1e1e1e')
        border = get_theme_token('borde_normal', '#2d2d2d')
        self.setStyleSheet(f"""
            QFrame#floatingPanel {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.title_bar = _TitleBar(title, self)
        self.title_bar.close_clicked.connect(self.closed.emit)
        layout.addWidget(self.title_bar)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {border};")
        layout.addWidget(sep)

        layout.addWidget(content)
        self.hide()
        self._positioned = False

    def show_panel(self):
        if not self._positioned:
            self._default_position()
            self._positioned = True
        self.adjustSize()
        self.clamp_to_host()
        self.show()
        self.raise_()

    def hide_panel(self):
        self.hide()

    def _default_position(self):
        host_rect = self._host.rect()
        x = max(10, host_rect.width() - self.width() - 20)
        y = 10
        self.move(x, y)

    def clamp_to_host(self):
        host_rect = self._host.rect()
        x = min(max(0, self.x()), max(0, host_rect.width() - self.width()))
        y = min(max(0, self.y()), max(0, host_rect.height() - self.height()))
        self.move(x, y)
