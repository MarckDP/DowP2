# src/gui/tabs/image_tools/canvas_flatten.py
"""Aplanado de formas/pincel/Canvas manual a un único QImage para exportar --
standalone (no vive adentro de ZoomableImageViewer, mismo criterio ya aplicado
con CompareViewer) para no seguir engordando esa clase.

Clona los QGraphicsItem en vez de reusar los reales: así una exportación nunca
corre riesgo de mover/perder algo de la sesión de edición en vivo del usuario --
la escena temporal que arma esta función es 100% descartable."""
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import (
    QGraphicsScene, QGraphicsRectItem, QGraphicsEllipseItem,
    QGraphicsLineItem, QGraphicsPixmapItem,
)

from gui.tabs.image_tools.layers.layer_model import Layer


def _clone_item(item):
    """Copia geometría+pen+brush (formas/línea) o pixmap+pos (pincel) -- None si
    el tipo no es ninguno de los que puede producir el editor (ver
    zoomable_image_viewer.py::_make_shape_item/_press_layers_draw/_create_raster_layer)."""
    if isinstance(item, QGraphicsRectItem):
        clone = QGraphicsRectItem(item.rect())
        clone.setPen(item.pen())
        clone.setBrush(item.brush())
    elif isinstance(item, QGraphicsEllipseItem):
        clone = QGraphicsEllipseItem(item.rect())
        clone.setPen(item.pen())
        clone.setBrush(item.brush())
    elif isinstance(item, QGraphicsLineItem):
        clone = QGraphicsLineItem(item.line())
        clone.setPen(item.pen())
    elif isinstance(item, QGraphicsPixmapItem):
        clone = QGraphicsPixmapItem(item.pixmap())
        clone.setPos(item.pos())
    else:
        return None
    clone.setTransform(item.transform())
    return clone


def build_flattened_image(base_pixmap: QPixmap, canvas_state: dict | None, layers: list[Layer]) -> QImage:
    """Compone `base_pixmap` (posicionada/escalada según `canvas_state`, o a
    tamaño nativo si no hay override) más las `layers` visibles no-"image" (formas/
    pincel del usuario) sobre el área de `canvas_state["canvas_rect"]` (o el propio
    tamaño de `base_pixmap` si no hay canvas_state), devolviendo un QImage RGBA listo
    para guardarse como el archivo de origen "real" a convertir."""
    scene = QGraphicsScene()

    base_item = scene.addPixmap(base_pixmap)
    if canvas_state is not None:
        sx, sy = canvas_state.get("image_scale", (1.0, 1.0))
        base_item.setTransform(QTransform().scale(sx, sy))
        base_item.setPos(canvas_state["image_pos"])
        canvas_rect = QRectF(canvas_state["canvas_rect"])
    else:
        canvas_rect = QRectF(0, 0, base_pixmap.width(), base_pixmap.height())

    for layer in layers:
        if layer.kind == "image" or not layer.visible or layer.graphics_item is None:
            continue
        clone = _clone_item(layer.graphics_item)
        if clone is None:
            continue
        clone.setOpacity(layer.opacity)
        clone.setZValue(layer.graphics_item.zValue())
        scene.addItem(clone)

    w = max(1, round(canvas_rect.width()))
    h = max(1, round(canvas_rect.height()))
    image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    scene.render(painter, QRectF(0, 0, w, h), canvas_rect)
    painter.end()
    return image
