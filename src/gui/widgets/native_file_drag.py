# src/gui/widgets/native_file_drag.py
from PySide6.QtCore import Qt, QMimeData, QUrl, QEvent
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QApplication


def start_native_file_drag(source_widget, file_paths: list):
    """Inicia un QDrag nativo del SO ofreciendo file_paths como URLs locales, con source_widget
    como origen del gesto (p.ej. para arrastrar uno o varios subclips ya cortados hacia el
    Explorador u otra aplicación). Al finalizar, limpia manualmente el estado ':hover' de
    source_widget, ya que Qt no dispara un evento Leave tras un QDrag.exec nativo."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in file_paths])
    drag = QDrag(source_widget)
    drag.setMimeData(mime)
    drag.exec(Qt.CopyAction)
    QApplication.sendEvent(source_widget, QEvent(QEvent.Leave))
    source_widget.update()
