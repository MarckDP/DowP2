# src/gui/widgets/tab_drag_hover.py
from PySide6.QtCore import QObject, QEvent, QTimer


class TabBarDragHoverSwitcher(QObject):
    """Al arrastrar archivos sobre la cabecera de un QTabWidget (ej. arrastrando ítems
    desde Gestor de Medios), cambia automáticamente a la pestaña sobrevolada tras un
    breve hover, permitiendo que el drag -- que sigue activo -- continúe y termine
    sobre el widget de cola visible debajo (Editor de Imagen / Herramientas
    Multimedia), donde el dropEvent normal de ese widget toma el control.

    No modifica nada del lado origen del drag (ver _DragCleanupMixin en
    editing_media_tree.py): solo observa eventos de drag sobre la tab bar."""

    def __init__(self, tab_widget, hoverable_indices=None, hover_delay_ms=600, parent=None):
        super().__init__(parent or tab_widget)
        self.tab_widget = tab_widget
        self.tab_bar = tab_widget.tabBar()
        self.hoverable_indices = hoverable_indices  # None = cualquier pestaña
        self.hover_delay_ms = hover_delay_ms
        self._pending_index = -1

        # QTabBar no acepta drops por defecto; lo habilitamos únicamente para poder
        # recibir DragEnter/DragMove y detectar el hover -- nunca procesamos un Drop
        # real acá.
        self.tab_bar.setAcceptDrops(True)
        self.tab_bar.installEventFilter(self)

        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._switch_now)

    def eventFilter(self, obj, event):
        if obj is not self.tab_bar:
            return False

        etype = event.type()
        if etype in (QEvent.DragEnter, QEvent.DragMove):
            if not event.mimeData().hasUrls():
                return False
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            idx = self.tab_bar.tabAt(pos)
            if idx == -1 or (self.hoverable_indices is not None and idx not in self.hoverable_indices):
                self._hover_timer.stop()
                self._pending_index = -1
            elif idx != self._pending_index:
                self._pending_index = idx
                self._hover_timer.start(self.hover_delay_ms)
            event.acceptProposedAction()
            return True

        if etype == QEvent.DragLeave:
            self._hover_timer.stop()
            self._pending_index = -1
            return False

        if etype == QEvent.Drop:
            event.ignore()  # la tab bar nunca es un destino de drop real
            return True

        return False

    def _switch_now(self):
        if 0 <= self._pending_index < self.tab_widget.count():
            self.tab_widget.setCurrentIndex(self._pending_index)
        self._pending_index = -1
