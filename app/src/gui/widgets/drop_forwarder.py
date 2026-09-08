# src/gui/widgets/drop_forwarder.py
from PySide6.QtCore import QObject, QEvent
from PySide6.QtWidgets import QWidget


class WholeAreaDropForwarder(QObject):
    """Activa el arrastre-y-suelta de archivos (desde el SO o desde otra parte de
    DowP) en TODA el área de root_widget, sin importar cuán anidado esté el widget
    concreto que quede bajo el cursor (vista previa, waveform, controles, etc.).

    Qt solo entrega los eventos de drag al widget EXACTO bajo el cursor que tenga
    Qt.WA_AcceptDrops activo -- no los sube solo a los widgets ancestros -- así que
    activar setAcceptDrops(True) únicamente en root_widget no alcanza si adentro
    hay widgets hijos (QGraphicsView, QLabel, reproductores, etc.) que no lo
    activan por su cuenta. Esta clase resuelve eso activándolo explícitamente y
    de forma recursiva en root_widget y en todos sus descendientes (findChildren),
    interceptando el evento antes de que llegue a cada uno vía installEventFilter.

    on_drop_paths(paths: list[str]) se llama con las rutas locales del drop -- el
    llamador decide qué hacer (ej. delegar a la cola existente para que también
    procese carpetas en un hilo de fondo, ver _start_scan en
    image_queue_widget.py/media_queue_widget.py).

    exclude: widgets a excluir de la instalación recursiva (y sus propios
    descendientes) -- útil para no pisar un widget que ya maneja sus propios drops
    correctamente por su cuenta (ej. la cola de archivos)."""

    def __init__(self, root_widget, on_drop_paths, exclude=None, parent=None):
        super().__init__(parent or root_widget)
        self._on_drop_paths = on_drop_paths
        self._exclude = exclude or []
        self._install(root_widget)

    def _is_excluded(self, widget):
        for ex in self._exclude:
            if widget is ex or ex.isAncestorOf(widget):
                return True
        return False

    def _install(self, root_widget):
        candidates = [root_widget] + root_widget.findChildren(QWidget)
        for w in candidates:
            if self._is_excluded(w):
                continue
            w.setAcceptDrops(True)
            w.installEventFilter(self)

    def eventFilter(self, obj, event):
        etype = event.type()
        if etype in (QEvent.DragEnter, QEvent.DragMove):
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
                return True
            return False

        if etype == QEvent.Drop:
            urls = event.mimeData().urls()
            paths = [url.toLocalFile() for url in urls if url.isLocalFile()]
            if paths:
                event.acceptProposedAction()
                self._on_drop_paths(paths)
                return True
            return False

        return False
