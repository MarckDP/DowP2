# src/gui/widgets/compare_viewer.py
"""Vista de comparación "antes/después" del Editor de Imagen -- dos
QGraphicsPixmapItem en la misma escena; el "después" vive recortado dentro de un
QGraphicsRectItem con ItemClipsChildrenToShape cuyo ancho sigue al divisor
arrastrable (en vez de recomponer bitmaps a mano en cada frame). Zoom/pan
compartidos vía QGraphicsView real (AnchorUnderMouse hace el centrado en el cursor
solo). Mismo nivel/estilo que ZoomableImageViewer/_PreviewVideoView
(preview_panel.py) -- widget propio, NO un modo más adentro de ZoomableImageViewer
(esa clase ya carga bastante: herramientas de dibujo, Canvas, capas)."""
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsPixmapItem,
    QGraphicsRectItem, QGraphicsLineItem, QLabel,
)
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen

from gui.styles import get_theme_token

_DIVIDER_GRAB_MARGIN = 8
_HANDLE_RADIUS = 7
_MIN_SCALE = 0.05
_MAX_SCALE = 40.0


class CompareViewer(QGraphicsView):
    """set_images(before, after) -- carga y encuadra; clear() -- vacía la escena."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setRenderHint(QPainter.Antialiasing)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setBackgroundBrush(QColor(get_theme_token('fondo_principal', '#0a0a0a')))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)

        # after_item queda de base (siempre dibujado completo) -- before_item vive
        # DENTRO de un rect invisible que lo recorta según el divisor, y se dibuja
        # ENCIMA de la base en su región visible (0..divisor, el lado izquierdo) --
        # truco estándar de Qt para "recortar" un item sin tocar el pixmap en
        # memoria (evita redibujar un checkerboard/máscara a mano en cada frame,
        # que era lo que hacía DowP1). Importante: el lado que efectivamente se ve
        # (izquierda=Original/before, derecha=Resultado/after) tiene que coincidir
        # con dónde _position_chips() pone cada chip -- si se invierte cuál de los
        # dos queda "recortado", las etiquetas quedan al revés del contenido real.
        self._after_item = QGraphicsPixmapItem()
        self._after_item.setTransformationMode(Qt.SmoothTransformation)
        self._scene.addItem(self._after_item)

        self._clip_rect_item = QGraphicsRectItem()
        self._clip_rect_item.setPen(Qt.NoPen)
        self._clip_rect_item.setBrush(Qt.NoBrush)
        self._clip_rect_item.setFlag(QGraphicsItem.ItemClipsChildrenToShape, True)
        self._scene.addItem(self._clip_rect_item)

        self._before_item = QGraphicsPixmapItem(self._clip_rect_item)
        self._before_item.setTransformationMode(Qt.SmoothTransformation)

        divider_color = QColor(get_theme_token('acento_primario', '#B9E640'))
        divider_pen = QPen(divider_color, 2)
        # Cosmetic: el grosor queda fijo en píxeles de PANTALLA, no en unidades de
        # escena -- sin esto, la línea se agranda/achica con el zoom del view igual
        # que la imagen (el line item vive en coordenadas de escena, que sí se
        # transforman con el zoom; un pen cosmético es la forma estándar de Qt de
        # sacar un trazo de esa transformación).
        divider_pen.setCosmetic(True)
        self._divider_line = QGraphicsLineItem()
        self._divider_line.setPen(divider_pen)
        self._divider_line.setZValue(10)
        self._scene.addItem(self._divider_line)

        # El agarre del divisor es un QWidget aparte (no un item de la escena) a
        # propósito: así se puede mantener siempre centrado verticalmente en lo que
        # se ve del VIEWPORT, sin importar el zoom/paneo -- si fuera un item de
        # escena anclado al centro vertical de la imagen completa (como el resto),
        # se saldría de la vista apenas el usuario hace zoom y se mueve hacia
        # arriba/abajo. Solo su X sigue al divisor (ver _position_handle);
        # transparente al mouse para no interceptar el drag que ya maneja
        # mousePressEvent/mouseMoveEvent de este mismo widget.
        self._handle = QLabel(self)
        self._handle.setFixedSize(_HANDLE_RADIUS * 2, _HANDLE_RADIUS * 2)
        self._handle.setStyleSheet(f"""
            QLabel {{
                background-color: {divider_color.name()};
                border: 2px solid white;
                border-radius: {_HANDLE_RADIUS}px;
            }}
        """)
        self._handle.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._handle.hide()

        self._content_size = None  # (w, h) -- tamaño de referencia (el más grande de los dos lados)
        self._divider_fraction = 0.5
        self._dragging_divider = False
        self._panning = False
        self._pan_start = None

        self._lbl_before = self._make_chip()
        self._lbl_after = self._make_chip()

    def _make_chip(self) -> QLabel:
        lbl = QLabel(self)
        lbl.setStyleSheet(f"""
            QLabel {{
                background-color: rgba(0, 0, 0, 170);
                color: {get_theme_token('texto_principal', '#ffffff')};
                border-radius: 4px;
                padding: 3px 8px;
                font-size: 11px;
                font-weight: bold;
            }}
        """)
        lbl.hide()
        return lbl

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    def set_images(self, before_pixmap: QPixmap, after_pixmap: QPixmap):
        if before_pixmap.isNull() or after_pixmap.isNull():
            return
        bw, bh = before_pixmap.width(), before_pixmap.height()
        aw, ah = after_pixmap.width(), after_pixmap.height()
        if bw <= 0 or bh <= 0 or aw <= 0 or ah <= 0:
            return

        self._before_item.setPixmap(before_pixmap)
        self._after_item.setPixmap(after_pixmap)

        # Si difieren en tamaño (típico tras un resize/upscale), se escala el más
        # chico al tamaño del más grande vía setScale() del item -- no se
        # re-samplea el pixmap en memoria, solo la transformación de dibujo.
        target_w, target_h = max(bw, aw), max(bh, ah)
        self._content_size = (target_w, target_h)

        self._before_item.setPos(0, 0)
        self._before_item.setScale(target_w / bw)
        self._after_item.setPos(0, 0)
        self._after_item.setScale(target_w / aw)

        self._clip_rect_item.setRect(0, 0, target_w, target_h)
        self._scene.setSceneRect(0, 0, target_w, target_h)

        self._lbl_before.setText(self.tr("Original: {0}×{1} px").format(bw, bh))
        self._lbl_after.setText(self.tr("Resultado: {0}×{1} px").format(aw, ah))
        self._lbl_before.adjustSize()
        self._lbl_after.adjustSize()
        self._lbl_before.show()
        self._lbl_after.show()
        self._handle.show()

        self._divider_fraction = 0.5
        self._update_divider()
        self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)
        self._position_chips()
        self._position_handle()

    def before_pixmap(self) -> QPixmap:
        return self._before_item.pixmap()

    def after_pixmap(self) -> QPixmap:
        return self._after_item.pixmap()

    def clear(self):
        self._before_item.setPixmap(QPixmap())
        self._after_item.setPixmap(QPixmap())
        self._content_size = None
        self._scene.setSceneRect(0, 0, 1, 1)
        self._lbl_before.hide()
        self._lbl_after.hide()
        self._handle.hide()

    # ------------------------------------------------------------------
    # Divisor / interacción
    # ------------------------------------------------------------------
    def _update_divider(self):
        if not self._content_size:
            return
        w, h = self._content_size
        x = w * self._divider_fraction
        self._clip_rect_item.setRect(0, 0, x, h)
        self._divider_line.setLine(x, 0, x, h)

    def _divider_screen_x(self) -> float:
        if not self._content_size:
            return -1000.0
        w, _h = self._content_size
        return self.mapFromScene(QPointF(w * self._divider_fraction, 0)).x()

    def _position_handle(self):
        """Mantiene el agarre centrado en el eje Y del VIEWPORT (no de la imagen) --
        se recalcula en cada zoom/paneo/resize/arrastre, ver llamadores."""
        if not self._content_size or not self._handle.isVisible():
            return
        x = self._divider_screen_x() - _HANDLE_RADIUS
        y = self.height() / 2 - _HANDLE_RADIUS
        self._handle.move(int(x), int(y))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._content_size:
            if abs(event.position().x() - self._divider_screen_x()) <= _DIVIDER_GRAB_MARGIN:
                self._dragging_divider = True
                event.accept()
                return
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging_divider and self._content_size:
            scene_pos = self.mapToScene(event.position().toPoint())
            w, _h = self._content_size
            self._divider_fraction = max(0.0, min(1.0, scene_pos.x() / w))
            self._update_divider()
            self._position_handle()
            event.accept()
            return
        if self._panning and self._pan_start is not None:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            self._position_handle()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging_divider:
            self._dragging_divider = False
            event.accept()
            return
        if self._panning:
            self._panning = False
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if not self._content_size:
            return
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        new_scale = self.transform().m11() * factor
        if _MIN_SCALE <= new_scale <= _MAX_SCALE:
            self.scale(factor, factor)
        self._position_handle()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_chips()
        self._position_handle()

    def _position_chips(self):
        margin = 10
        self._lbl_before.move(margin, margin)
        self._lbl_after.move(max(margin, self.width() - self._lbl_after.width() - margin), margin)
