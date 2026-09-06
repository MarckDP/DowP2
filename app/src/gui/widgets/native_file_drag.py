# src/gui/widgets/native_file_drag.py
from PySide6.QtCore import Qt, QMimeData, QUrl, QEvent, QRectF
from PySide6.QtGui import QDrag, QPixmap, QPainter, QColor, QFont, QFontMetrics
from PySide6.QtWidgets import QApplication


def _build_badge_pixmap(text: str) -> QPixmap:
    """Pastilla oscura con `text` que acompaña al cursor durante el arrastre, para que
    se vea cuántos archivos van cuando son varios (el cursor nativo no lo indica)."""
    font = QFont()
    font.setPointSize(9)
    font.setBold(True)
    width = QFontMetrics(font).horizontalAdvance(text) + 22
    height = 24
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(0, 0, 0, 205))
    painter.setPen(QColor(255, 255, 255, 60))
    painter.drawRoundedRect(QRectF(0.5, 0.5, width - 1, height - 1), 6, 6)
    painter.setPen(QColor("#ffffff"))
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, text)
    painter.end()
    return pixmap


def start_native_file_drag(source_widget, file_paths: list, badge_text: str = ""):
    """Inicia un QDrag nativo del SO ofreciendo file_paths como URLs locales, con source_widget
    como origen del gesto (p.ej. para arrastrar uno o varios subclips ya cortados hacia el
    Explorador u otra aplicación). badge_text, si se pasa, dibuja una pastilla junto al cursor
    (p.ej. "12 archivos"). Al finalizar, limpia manualmente el estado ':hover' de
    source_widget, ya que Qt no dispara un evento Leave tras un QDrag.exec nativo."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in file_paths])
    drag = QDrag(source_widget)
    drag.setMimeData(mime)
    if badge_text:
        try:
            drag.setPixmap(_build_badge_pixmap(badge_text))
        except Exception:
            pass
    drag.exec(Qt.CopyAction)
    QApplication.sendEvent(source_widget, QEvent(QEvent.Leave))
    source_widget.update()
