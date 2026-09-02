# src/gui/widgets/popover_button.py
"""Botón que despliega un panel de contenido flotante debajo suyo, sin empujar ni
redimensionar nada más -- mismo patrón que ya usa quick_mode_view.py para su barra
"Recodificar" (_build_recode_bar/_reposition_recode_popover/RecodeOptionsWidget),
generalizado para reusar en los botones de la franja superior del Editor de Imagen
(Reescalar IA, Eliminar Fondo IA, Canvas, etc.).

Quien use este botón es responsable de dos cosas que varían demasiado entre pantallas
como para meterlas acá:
  1. Llamar a `reposition()` en el resizeEvent del host, si el popover puede estar abierto.
  2. Cerrar el popover en clicks afuera -- instalar un eventFilter en QApplication como
     ya hace quick_mode_view.py, chequeando `not btn.geometry_contains_global(pos)`.
"""
from PySide6.QtWidgets import QPushButton, QWidget
from PySide6.QtCore import Signal, QRect


class PopoverTriggerButton(QPushButton):
    opened = Signal()
    closed = Signal()

    def __init__(self, host: QWidget, content: QWidget, parent=None, left_click_opens: bool = True):
        """`left_click_opens=False` deja el clic izquierdo completamente libre para
        que quien use el botón lo cablee a otra cosa (ej. Canvas: clic izquierdo
        activa/desactiva edición directa, sin abrir este popover) -- el popover sigue
        disponible igual vía clic derecho (ver contextMenuEvent) o llamando
        toggle_popover()/set_open() a mano."""
        super().__init__(parent)
        self._host = host
        self.content = content
        self.content.setParent(host)
        self.content.hide()
        self._is_open = False
        if left_click_opens:
            self.clicked.connect(self.toggle_popover)

    def contextMenuEvent(self, event):
        """Clic derecho: siempre abre/cierra el popover, sin importar qué haga el
        clic izquierdo en este botón en particular."""
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
        de la ventana (mismo criterio que _reposition_recode_popover)."""
        if not self._is_open:
            return
        top_left = self.mapTo(self._host, self.rect().bottomLeft())
        width = max(self.content.sizeHint().width(), 220)
        max_w = max(200, self._host.width() - 20)
        width = min(width, max_w)
        x = top_left.x()
        if x + width > self._host.width() - 10:
            x = max(10, self._host.width() - 10 - width)
        y = top_left.y() + 3
        self.content.setFixedWidth(width)
        # El alto hay que fijarlo DESPUÉS del ancho: con setWordWrap en el contenido
        # (ej. el aviso de "motor no instalado"), el sizeHint().height() depende del
        # ancho ya aplicado. Sin esto, Qt deja el widget en su tamaño por defecto
        # (~640x480) porque nunca fue gestionado por un layout ni redimensionado.
        self.content.setFixedHeight(self.content.sizeHint().height())
        self.content.move(x, y)
        if self.content.isVisible():
            self.content.raise_()

    def global_rects(self) -> tuple[QRect, QRect]:
        """Rects globales del botón y de su contenido -- para que el host arme su
        propio eventFilter de "cerrar al clickear afuera" sin duplicar este cálculo."""
        btn_rect = QRect(self.mapToGlobal(self.rect().topLeft()), self.size())
        content_rect = QRect(self.content.mapToGlobal(self.content.rect().topLeft()), self.content.size())
        return btn_rect, content_rect
