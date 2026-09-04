# src/gui/widgets/popover_button.py
"""Botón que despliega un panel de contenido flotante debajo suyo, sin empujar ni
redimensionar nada más -- mismo patrón que ya usa quick_mode_view.py para su barra
"Recodificar" (_build_recode_bar/_reposition_recode_popover/RecodeOptionsWidget),
generalizado para reusar en los botones de la franja superior del Editor de Imagen
(Reescalar IA, Eliminar Fondo IA, Canvas, etc.).

Quien use este botón es responsable de dos cosas que varían demasiado entre pantallas
como para meterlas aquí:
  1. Llamar a `reposition()` en el resizeEvent del host, si el popover puede estar abierto.
  2. Cerrar el popover en clicks afuera -- instalar un eventFilter en QApplication como
     ya hace quick_mode_view.py, chequeando `not btn.geometry_contains_global(pos)`.
"""
from typing import Callable, Optional

from PySide6.QtWidgets import QPushButton, QWidget
from PySide6.QtCore import Signal, QRect, QEvent


class PopoverTriggerButton(QPushButton):
    opened = Signal()
    closed = Signal()

    def __init__(self, host: QWidget, content: QWidget, parent=None, left_click_opens: bool = True,
                 on_right_click: Optional[Callable[[], bool]] = None):
        """`left_click_opens=False` deja el clic izquierdo completamente libre para
        que quien use el botón lo cablee a otra cosa (ej. Canvas: clic izquierdo
        activa/desactiva edición directa, sin abrir este popover) -- el popover sigue
        disponible igual vía clic derecho (ver contextMenuEvent) o llamando
        toggle_popover()/set_open() a mano.

        `on_right_click`, si se pasa, se llama primero en cada clic derecho (ver
        contextMenuEvent) y decide si lo consume: devolver True significa "ya me
        encargué de este clic, no toques el popover" (ej. Reescalar/Eliminar Fondo/
        Redimensionar: el clic derecho desactiva la configuración en el acto, sin
        menú intermedio, y no hace nada si no hay nada activo). Devolver False cae
        al comportamiento de siempre (abrir/cerrar el popover), que es lo que usa
        Canvas para ofrecer sus opciones por clic derecho."""
        super().__init__(parent)
        self._host = host
        self.content = content
        self.content.setParent(host)
        self.content.hide()
        self._is_open = False
        self._repositioning = False
        self._on_right_click = on_right_click

        # Escuchar cambios de layout/visibilidad del contenido para reajustar tamaño en vivo
        self.content.installEventFilter(self)

        if left_click_opens:
            self.clicked.connect(self.toggle_popover)

    def eventFilter(self, obj, event):
        """Si el contenido cambia de tamaño o visibilidad de widgets (ej. se eligen
        opciones que muestran más campos o avisos), reajustar posición y tamaño
        automáticamente."""
        if obj == self.content and event.type() == QEvent.LayoutRequest and self._is_open and not self._repositioning:
            self.reposition()
        return super().eventFilter(obj, event)

    def contextMenuEvent(self, event):
        """Clic derecho: si hay on_right_click y devuelve True, el clic ya quedó
        atendido por quien usa el botón y aquí no se hace nada más. Si no hay
        handler, o devuelve False, abre/cierra el popover -- igual que siempre, sin
        importar qué haga el clic izquierdo en este botón en particular."""
        if self._on_right_click is not None and self._on_right_click():
            event.accept()
            return
        self.toggle_popover()
        event.accept()

    def is_open(self) -> bool:
        return self._is_open

    def toggle_popover(self):
        self.set_open(not self._is_open)

    def set_open(self, open_: bool):
        if open_ == self._is_open:
            return
        self._is_open = open_
        if open_:
            self.reposition()
            self.content.show()
            self.content.raise_()
            self.opened.emit()
        else:
            self.content.hide()
            self.closed.emit()

    def reposition(self):
        """Ancla `content` justo debajo del botón, en coordenadas del host. Si no
        entra alineado a la izquierda, corrige para que su borde derecho no se salga
        de la ventana (mismo criterio que _reposition_recode_popover).
        Ajusta dinámicamente ancho y alto según el contenido visible (sizeHint)."""
        if not self._is_open or self._repositioning:
            return
        self._repositioning = True
        try:
            # Despejar restricciones previas para que el layout calcule su tamaño real
            self.content.setMinimumSize(0, 0)
            self.content.setMaximumSize(16777215, 16777215)
            if self.content.layout():
                self.content.layout().activate()

            top_left = self.mapTo(self._host, self.rect().bottomLeft())
            hint = self.content.sizeHint()
            width = max(hint.width(), 220)
            max_w = max(200, self._host.width() - 20)
            width = min(width, max_w)

            x = top_left.x()
            if x + width > self._host.width() - 10:
                x = max(10, self._host.width() - 10 - width)
            y = top_left.y() + 3

            self.content.setFixedWidth(width)
            layout = self.content.layout()
            if layout:
                layout.activate()
            height = self.content.sizeHint().height()
            # sizeHint() no tiene en cuenta el texto que se parte en varias líneas:
            # devuelve el alto "natural", no el que hace falta a ESTE ancho. Con un
            # aviso largo (ej. la línea de estado de los popovers de IA) eso deja el
            # popover corto y se corta la última fila. heightForWidth() sí lo sabe --
            # cuando el layout lo soporta, manda el mayor de los dos.
            if layout and layout.hasHeightForWidth():
                height = max(height, layout.heightForWidth(width))

            # Evitar desbordes verticales
            max_h = max(100, self._host.height() - 20)
            height = min(height, max_h)
            if y + height > self._host.height() - 10:
                y = max(10, self._host.height() - 10 - height)

            self.content.setFixedHeight(height)
            self.content.move(x, y)
            if self.content.isVisible():
                self.content.raise_()
        finally:
            self._repositioning = False

    def global_rects(self) -> tuple[QRect, QRect]:
        """Rects globales del botón y de su contenido -- para que el host arme su
        propio eventFilter de "cerrar al clickear afuera" sin duplicar este cálculo."""
        btn_rect = QRect(self.mapToGlobal(self.rect().topLeft()), self.size())
        content_rect = QRect(self.content.mapToGlobal(self.content.rect().topLeft()), self.content.size())
        return btn_rect, content_rect

