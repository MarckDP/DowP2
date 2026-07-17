# src/gui/tabs/editing_media/editing_media_icons.py
import os
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor

_SVG_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "assets", "icons", "svg"
))

def get_colored_svg_icon(name: str, color_hex: str, size=16) -> QIcon:
    """Carga y tintura un icono SVG con el color especificado."""
    path = os.path.join(_SVG_DIR, name)
    if not os.path.exists(path):
        return QIcon()
    pix = QPixmap(path)
    if pix.isNull():
        return QIcon()
    pix = pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    painter = QPainter(pix)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(pix.rect(), QColor(color_hex))
    painter.end()
    return QIcon(pix)

def get_colored_folder_icon(color_hex: str) -> QIcon:
    """Genera un icono de carpeta abierta/cerrada coloreado."""
    icon = QIcon()
    path_closed = os.path.join(_SVG_DIR, "folder.svg")
    path_open = os.path.join(_SVG_DIR, "folder_open.svg")
    
    if os.path.exists(path_closed):
        pix_closed = QPixmap(path_closed)
        if not pix_closed.isNull():
            pix_closed = pix_closed.scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter = QPainter(pix_closed)
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(pix_closed.rect(), QColor(color_hex))
            painter.end()
            icon.addPixmap(pix_closed, QIcon.Mode.Normal, QIcon.State.Off)
            
    if os.path.exists(path_open):
        pix_open = QPixmap(path_open)
        if not pix_open.isNull():
            pix_open = pix_open.scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter = QPainter(pix_open)
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(pix_open.rect(), QColor(color_hex))
            painter.end()
            icon.addPixmap(pix_open, QIcon.Mode.Normal, QIcon.State.On)
            
    return icon
