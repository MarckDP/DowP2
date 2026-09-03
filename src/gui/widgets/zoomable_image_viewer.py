# src/gui/widgets/zoomable_image_viewer.py
"""Visor de imagen con zoom (rueda del mouse, centrado en el cursor) y paneo (clic
izquierdo + arrastrar), fondo de cuadrícula de transparencia con el mismo estándar
visual que el resto de la app (gui/styles.py::create_checkerboard_pixmap).

Pensado para el Editor de Imagen, donde hace falta inspeccionar detalles a resolución
real -- a diferencia del preview del Gestor de Medios (solo ajustar a la ventana).

El canvas (espacio de trabajo editable, ver apply_canvas_state) se muestra SIEMPRE que
hay una imagen cargada -- se inicializa automáticamente al tamaño nativo de la imagen
en set_pixmap() y queda arrastrable/redimensionable de entrada, sin tener que abrir
ningún popover primero. `_interaction_mode` decide qué hace un click/arrastre:
"canvas_edit" (default: arrastrar handles/imagen del canvas) o "layers_draw"
(herramienta Capas: crear/mover/redimensionar formas y pintar con el pincel, ver
set_active_tool) -- mutuamente excluyentes, nunca "ninguno" mientras haya imagen. Los
handles de redimensionar de Canvas y de una figura seleccionada comparten la misma
matemática genérica (_resize_target_rect/_resize_apply_fn) -- mismo truco de
drawForeground() (resetear el transform y dibujar en coordenadas de VIEWPORT) para que
los handles (y el indicador de tamaño en px) tengan tamaño constante en pantalla sin
importar el zoom."""
import math
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsEllipseItem, QGraphicsLineItem, QApplication,
)
from PySide6.QtCore import Qt, QRectF, QPointF, QRect, QPoint, QLineF, Signal
from PySide6.QtGui import QPixmap, QPainter, QBrush, QPen, QColor, QPainterPath, QTransform, QImage, QFont

from gui.styles import create_checkerboard_pixmap, get_theme_token

_MIN_SCALE = 0.05
_MAX_SCALE = 40.0
_ZOOM_STEP = 1.15

_HANDLE_DRAW = 9   # tamaño del cuadradito del handle en pantalla (px, constante)
_HANDLE_HIT = 14   # área de detección de click (más grande que el dibujo, más fácil de agarrar)
_MIN_SIZE = 8  # tamaño mínimo al redimensionar por arrastre (canvas o figura), en px de escena
_SNAP_PX = 12  # distancia en píxeles de PANTALLA (no de escena) para pegar el canvas al borde de la imagen con Ctrl

# handle_id -> (h_align, v_align): qué borde(s) del rect mueve cada handle
_HANDLE_ANCHORS = {
    "nw": ("left", "top"), "n": ("center", "top"), "ne": ("right", "top"),
    "w": ("left", "center"), "e": ("right", "center"),
    "sw": ("left", "bottom"), "s": ("center", "bottom"), "se": ("right", "bottom"),
}

_SHAPE_ITEM_TYPES = (QGraphicsRectItem, QGraphicsEllipseItem)


class ZoomableImageViewer(QGraphicsView):
    # -- Señales del modo Canvas (sin cambios de comportamiento) --
    margin_dragged = Signal(int)
    size_dragged = Signal(int, int)
    # Sin payload -- "el usuario tocó el canvas a mano" (resize por handle o
    # arrastre de la imagen), a diferencia de elegir un preset del popover (eso
    # sigue siendo 100% configuración de lote, ver canvas_popover.py). Quien
    # escuche esto usa get_canvas_state() para capturar el estado completo y
    # guardarlo por archivo (ver ImageToolsTab._on_canvas_edited).
    canvas_edited = Signal()

    # -- Señales del modo Capas --
    shape_created = Signal(object, str)       # QGraphicsItem, "rect"|"ellipse"|"line"
    raster_layer_created = Signal(object)      # QGraphicsPixmapItem (nueva capa de pincel)
    shape_selected = Signal(object)            # QGraphicsItem o None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._native_size = None  # QSize de la imagen tal cual se cargó, sin escalar
        self._user_zoomed = False
        self._checker_tile = self._build_checker_tile()
        self._dark_bg_color = QColor(get_theme_token('fondo_principal', '#0a0a0a'))

        self._interaction_mode = "canvas_edit"  # "canvas_edit" | "layers_draw"

        # -- Paneo manual (botón del medio, o clic izquierdo en área vacía con la
        # herramienta Seleccionar) -- disponible en CUALQUIER modo, ya que en
        # canvas_edit/layers_draw el clic izquierdo normal está tomado por los
        # handles/dibujo y ScrollHandDrag queda desactivado (NoDrag).
        self._panning = False
        self._pan_last_pos = QPoint()

        # -- Estado del modo Canvas --
        self._canvas_rect: QRectF | None = None
        self._canvas_mode = "free"  # "free" | "margin_external"
        self._canvas_resizable = True
        self._dragging_image = False
        self._drag_offset = QPointF()

        # -- Redimensionado genérico por handles (Canvas o figura seleccionada) --
        self._handle_rects: dict[str, QRect] = {}
        self._active_handle = None
        self._resize_apply_fn = None  # callable(QRectF) -- a dónde va el rect nuevo

        # -- Estado del modo Capas --
        self._active_tool = "select"  # "select"|"rect"|"ellipse"|"line"|"brush"
        self._draw_fill: QColor | None = QColor("#3498db")
        self._draw_stroke: QColor | None = QColor("#1a1a1a")
        self._stroke_width = 2
        self._brush_color = QColor("#3498db")
        self._brush_size = 12
        self._drawing_item = None
        self._draw_start_scene = QPointF()
        self._selected_item = None
        self._dragging_shape = False
        self._line_handle_rects: dict[str, QRect] = {}
        self._active_line_handle = None
        self._active_raster_item: QGraphicsPixmapItem | None = None
        self._raster_buffers: dict[int, QImage] = {}
        self._painting = False
        self._last_paint_scene = None

        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.NoDrag)
        # NoAnchor (no AnchorUnderMouse): el anclaje bajo el cursor se calcula a mano
        # en wheelEvent() -- el automático de Qt se descompensaba (el zoom terminaba
        # saltando hacia arriba-izquierda con una "curva" al usar Canvas/Capas, donde
        # dragMode es NoDrag y las scrollbars están ocultas) y se corrige llevando la
        # cuenta nosotros mismos en vez de depender de ese mecanismo interno.
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def _build_checker_tile(self) -> QPixmap:
        # Tile de 2x2 cuadros (no 1x1): así el patrón alterna correctamente al
        # repetirse con drawTiledPixmap, en vez de verse como un color sólido.
        square = 10
        return create_checkerboard_pixmap(square * 2, square * 2, square)

    def refresh_checker_theme(self):
        """Llamar si el tema/tokens de color cambian en caliente."""
        self._checker_tile = self._build_checker_tile()
        self._dark_bg_color = QColor(get_theme_token('fondo_principal', '#0a0a0a'))
        self.viewport().update()

    def drawBackground(self, painter: QPainter, rect: QRectF):
        # drawBackground() recibe el painter ya transformado por el zoom/paneo de la
        # vista (coordenadas de ESCENA) -- dibujar el tile ahí lo haría escalarse junto
        # con la imagen (los cuadros se agrandan/achican con el zoom, como si fueran
        # parte de la imagen). Reseteando la transformación se dibuja en coordenadas de
        # VIEWPORT (píxeles de pantalla), así el tamaño de los cuadros queda constante
        # sin importar cuánto zoom haya, igual que la cuadrícula de cualquier editor.
        painter.save()
        painter.resetTransform()
        viewport_rect = self.viewport().rect()
        # Oscuro en TODO el viewport primero -- lo de afuera del canvas ("espacio de
        # trabajo") ya no es cuadrícula, es fondo sólido (mismo tono que el resto de
        # la app). De paso, si el tiling de la cuadrícula llega a fallar en algún
        # frame (bug esporádico de drawTiledPixmap), nunca se ve "vacío": como
        # mínimo queda el oscuro de siempre, no un hueco en blanco/negro plano.
        painter.fillRect(viewport_rect, self._dark_bg_color)
        if self._canvas_rect is not None and self._pixmap_item is not None:
            canvas_vp = self._scene_rect_to_viewport(self._canvas_rect)
            painter.setClipRect(canvas_vp)
        painter.drawTiledPixmap(viewport_rect, self._checker_tile)
        painter.restore()

    def drawForeground(self, painter: QPainter, rect: QRectF):
        # El borde de referencia del canvas se ve SIEMPRE que hay una imagen cargada,
        # sin importar qué herramienta esté activa (Seleccionar/Rectángulo/Elipse/
        # Línea/Pincel) -- antes esto se cortaba apenas se entraba a layers_draw,
        # dejando el canvas invisible con cualquier herramienta que no fuera Canvas.
        if self._canvas_rect is not None and self._pixmap_item is not None:
            if self._interaction_mode == "canvas_edit":
                self._draw_canvas_overlay(painter)
            else:
                self._draw_canvas_passive_border(painter)
        if self._interaction_mode == "layers_draw":
            self._draw_shape_selection(painter)

    def _draw_canvas_passive_border(self, painter: QPainter):
        painter.save()
        painter.resetTransform()
        accent = QColor(get_theme_token("acento_primario", "#B9E640"))
        accent.setAlpha(150)
        canvas_vp = self._scene_rect_to_viewport(self._canvas_rect)
        painter.setPen(QPen(accent, 1, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(canvas_vp)
        painter.restore()

    def _draw_canvas_overlay(self, painter: QPainter):
        painter.save()
        painter.resetTransform()

        accent = QColor(get_theme_token("acento_primario", "#B9E640"))
        canvas_vp = self._scene_rect_to_viewport(self._canvas_rect)

        # Máscara semi-transparente fuera del canvas (path even-odd: viewport completo
        # menos el rect del canvas).
        mask_path = QPainterPath()
        mask_path.addRect(QRectF(self.viewport().rect()))
        mask_path.addRect(QRectF(canvas_vp))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 130))
        painter.drawPath(mask_path)

        # Borde punteado del canvas.
        pen = QPen(accent, 1.5, Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(canvas_vp)

        self._handle_rects = {}
        if self._canvas_resizable:
            self._handle_rects = self._paint_handles(painter, canvas_vp, accent)

        # Indicador "1080 x 1080" solo mientras se arrastra algo (handle o la imagen),
        # pegado a la esquina superior derecha del RECTÁNGULO del canvas -- no del
        # visor entero -- así viaja con el canvas en vez de quedar fijo en la pantalla.
        if self._active_handle is not None or self._dragging_image:
            self._draw_size_badge(painter, canvas_vp)

        painter.restore()

    def _draw_size_badge(self, painter: QPainter, canvas_vp: QRect):
        w_val = round(self._canvas_rect.width())
        h_val = round(self._canvas_rect.height())
        text = f"{w_val} x {h_val}"
        font = QFont(painter.font())
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        text_w = metrics.horizontalAdvance(text)
        badge_w, badge_h = text_w + 18, 24
        # Esquina superior derecha del canvas, con un pequeño margen hacia adentro;
        # si el canvas se sale del viewport por arriba/derecha, se clampa adentro
        # para que el texto no quede cortado.
        badge_x = min(canvas_vp.right() - badge_w - 6, self.viewport().width() - badge_w - 6)
        badge_x = max(6, badge_x)
        badge_y = max(6, canvas_vp.top() + 6)
        badge_rect = QRect(badge_x, badge_y, badge_w, badge_h)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 190))
        painter.drawRoundedRect(badge_rect, 5, 5)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(badge_rect, Qt.AlignCenter, text)

    def _draw_shape_selection(self, painter: QPainter):
        self._handle_rects = {}
        self._line_handle_rects = {}
        if self._selected_item is None or self._active_tool != "select":
            return
        painter.save()
        painter.resetTransform()
        accent = QColor(get_theme_token("acento_primario", "#B9E640"))

        if isinstance(self._selected_item, QGraphicsLineItem):
            line = self._selected_item.line()
            p1_vp = self.mapFromScene(line.p1())
            p2_vp = self.mapFromScene(line.p2())
            painter.setPen(QPen(accent, 1.5, Qt.DashLine))
            painter.drawLine(p1_vp, p2_vp)
            self._line_handle_rects = {
                "p1": self._draw_one_handle(painter, QPointF(p1_vp), accent),
                "p2": self._draw_one_handle(painter, QPointF(p2_vp), accent),
            }
        elif isinstance(self._selected_item, _SHAPE_ITEM_TYPES):
            rect_vp = self._scene_rect_to_viewport(self._selected_item.rect())
            painter.setPen(QPen(accent, 1.5, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect_vp)
            self._handle_rects = self._paint_handles(painter, rect_vp, accent)
        painter.restore()

    def _draw_one_handle(self, painter: QPainter, pt: QPointF, accent: QColor) -> QRect:
        half = _HANDLE_DRAW // 2
        draw_rect = QRect(int(pt.x() - half), int(pt.y() - half), _HANDLE_DRAW, _HANDLE_DRAW)
        painter.setPen(QPen(QColor("#111111"), 1))
        painter.setBrush(QBrush(accent))
        painter.drawEllipse(draw_rect)
        hit_half = _HANDLE_HIT // 2
        return QRect(int(pt.x() - hit_half), int(pt.y() - hit_half), _HANDLE_HIT, _HANDLE_HIT)

    def _paint_handles(self, painter: QPainter, vp_rect: QRect, accent: QColor) -> dict:
        handle_rects = {}
        points = self._handle_points(vp_rect)
        painter.setPen(QPen(QColor("#111111"), 1))
        painter.setBrush(QBrush(accent))
        half = _HANDLE_DRAW // 2
        for handle_id, pt in points.items():
            draw_rect = QRect(int(pt.x() - half), int(pt.y() - half), _HANDLE_DRAW, _HANDLE_DRAW)
            painter.drawRect(draw_rect)
            hit_half = _HANDLE_HIT // 2
            handle_rects[handle_id] = QRect(
                int(pt.x() - hit_half), int(pt.y() - hit_half), _HANDLE_HIT, _HANDLE_HIT
            )
        return handle_rects

    def _scene_rect_to_viewport(self, r: QRectF) -> QRect:
        return self.mapFromScene(r).boundingRect()

    def _handle_points(self, vp_rect: QRect) -> dict:
        left, top, right, bottom = vp_rect.left(), vp_rect.top(), vp_rect.right(), vp_rect.bottom()
        cx, cy = vp_rect.center().x(), vp_rect.center().y()
        return {
            "nw": QPointF(left, top), "n": QPointF(cx, top), "ne": QPointF(right, top),
            "w": QPointF(left, cy), "e": QPointF(right, cy),
            "sw": QPointF(left, bottom), "s": QPointF(cx, bottom), "se": QPointF(right, bottom),
        }

    def set_pixmap(self, pixmap: QPixmap):
        if pixmap is None or pixmap.isNull():
            self.clear()
            return
        self._scene.clear()
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._native_size = pixmap.size()
        # La escena se hace más grande que la imagen (margen del 200% del propio
        # tamaño a cada lado) para poder paneAR más allá de sus bordes -- igual que en
        # DowP 1, en vez de quedar atado a los límites exactos de la imagen.
        w, h = pixmap.width(), pixmap.height()
        margin_x, margin_y = w * 2, h * 2
        self._scene.setSceneRect(QRectF(-margin_x, -margin_y, w + margin_x * 2, h + margin_y * 2))
        self._user_zoomed = False
        # Una imagen nueva invalida cualquier estado de canvas/capas de la anterior --
        # los items de capas ya se borraron con self._scene.clear() arriba. Esto deja
        # el canvas inicializado a su tamaño nativo (editable de entrada, sin tener
        # que abrir ningún popover primero) ANTES de encuadrar la vista.
        self._reset_edit_state()
        self._fit_canvas_into_view()

    def image_size(self):
        return self._native_size

    def clear(self):
        self._scene.clear()
        self._pixmap_item = None
        self._native_size = None
        self._user_zoomed = False
        self._reset_edit_state()

    def _reset_edit_state(self):
        # "pan" por defecto -- el canvas queda inicializado (para el borde de
        # referencia siempre visible, ver drawForeground) pero NO editable hasta que
        # se abra el control de Canvas explícitamente (ver set_interaction_mode /
        # image_tools_view.py::_on_canvas_popover_opened). Navegar (zoom/paneo) con
        # una imagen recién cargada nunca debe quedar "tomado" por handles de canvas.
        self._interaction_mode = "pan"
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self._handle_rects = {}
        self._line_handle_rects = {}
        self._active_handle = None
        self._active_line_handle = None
        self._dragging_image = False
        self._dragging_shape = False
        self._painting = False
        self._selected_item = None
        self._drawing_item = None
        self._active_raster_item = None
        self._raster_buffers = {}
        if self._native_size is not None:
            w, h = self._native_size.width(), self._native_size.height()
            self._canvas_rect = QRectF(0, 0, w, h)
            self._canvas_mode = "free"
            self._canvas_resizable = True
        else:
            self._canvas_rect = None

    def _fit_to_window(self):
        if self._pixmap_item is not None:
            self.fitInView(self._pixmap_item, Qt.KeepAspectRatio)

    # ------------------------------------------------------------------
    # Modo de interacción
    # ------------------------------------------------------------------
    def set_interaction_mode(self, mode: str):
        """"pan" (default -- navegación normal; el canvas se ve solo como borde de
        referencia, sin handles) | "canvas_edit" (control de Canvas abierto:
        handles/arrastre de imagen activos) | "layers_draw" (herramienta Capas).
        Quien active canvas_edit/layers_draw es responsable de empujar el estado real
        justo después (canvas: CanvasPopoverContent.sync(); capas: set_active_tool/
        set_draw_style) -- no hay geometría nueva por defecto aquí."""
        assert mode in ("pan", "canvas_edit", "layers_draw")
        if mode == self._interaction_mode:
            return
        self._interaction_mode = mode
        self.setDragMode(QGraphicsView.ScrollHandDrag if mode == "pan" else QGraphicsView.NoDrag)
        self._handle_rects = {}
        self._line_handle_rects = {}
        self._active_handle = None
        self._active_line_handle = None
        self._dragging_image = False
        self._dragging_shape = False
        if self._panning:
            self._end_pan()
        self._painting = False
        if mode != "layers_draw":
            self._selected_item = None
        self.viewport().update()

    # ------------------------------------------------------------------
    # Modo edición de canvas
    # ------------------------------------------------------------------
    def apply_canvas_state(self, canvas_rect: QRectF, mode: str, resizable: bool,
                            image_pos: QPointF, image_scale: tuple = (1.0, 1.0)):
        """Empuja un estado completo de canvas (llamado desde canvas_popover.py al
        cambiar de opción o editar un campo) -- atómico, para no dejar el overlay en un
        estado intermedio inconsistente entre canvas_rect/posición/escala."""
        self._canvas_rect = QRectF(canvas_rect)
        self._canvas_mode = mode
        self._canvas_resizable = resizable
        if self._pixmap_item is not None:
            sx, sy = image_scale
            self._pixmap_item.setTransform(QTransform().scale(sx, sy))
            self._pixmap_item.setPos(image_pos)
        self._ensure_scene_covers(self._canvas_rect)
        self._fit_canvas_into_view()
        self.viewport().update()

    def get_canvas_state(self) -> dict | None:
        """Inverso de apply_canvas_state() -- captura el estado actual para poder
        guardarlo por archivo (ver ImageToolsTab._on_canvas_edited). None si no hay
        imagen/canvas cargado."""
        if self._pixmap_item is None or self._canvas_rect is None:
            return None
        transform = self._pixmap_item.transform()
        return {
            "canvas_rect": QRectF(self._canvas_rect),
            "mode": self._canvas_mode,
            "resizable": self._canvas_resizable,
            "image_pos": self._pixmap_item.pos(),
            "image_scale": (transform.m11(), transform.m22()),
        }

    def _ensure_scene_covers(self, rect: QRectF):
        """Agranda sceneRect (nunca la achica) para que `rect` quede cómodamente
        adentro, con margen de paneo -- si no, Qt clampa el zoom/scroll a los límites
        fijados en set_pixmap() según el tamaño NATIVO de la imagen, y tanto el zoom
        como el paneo se sienten rotos apenas el canvas (o una figura/capa) crece más
        allá de eso (presets grandes, márgenes generosos, arrastrar algo lejos, etc.)."""
        if rect is None:
            return
        current = self._scene.sceneRect()
        if current.contains(rect):
            return
        margin = max(rect.width(), rect.height()) * 0.5 + 100
        needed = rect.adjusted(-margin, -margin, margin, margin)
        self._scene.setSceneRect(current.united(needed))

    def _fit_canvas_into_view(self):
        if self._pixmap_item is None or self._canvas_rect is None or self._user_zoomed:
            return
        union_rect = self._canvas_rect.united(self._pixmap_item.sceneBoundingRect())
        margin = max(union_rect.width(), union_rect.height()) * 0.15 + 20
        padded = union_rect.adjusted(-margin, -margin, margin, margin)
        self.fitInView(padded, Qt.KeepAspectRatio)

    # ------------------------------------------------------------------
    # Modo Capas -- configuración de herramientas
    # ------------------------------------------------------------------
    def set_active_tool(self, tool: str):
        assert tool in ("select", "rect", "ellipse", "line", "brush")
        self._active_tool = tool
        if tool != "select":
            self._selected_item = None
        self.viewport().update()

    def set_draw_style(self, fill: QColor | None, stroke: QColor | None, stroke_width: int):
        self._draw_fill = fill
        self._draw_stroke = stroke
        self._stroke_width = max(0, stroke_width)

    def set_brush_style(self, color: QColor, size: int):
        self._brush_color = color
        self._brush_size = max(1, size)

    def set_active_raster_layer(self, item: QGraphicsPixmapItem | None):
        """A qué capa raster pinta el Pincel -- None hace que el próximo trazo cree
        una capa nueva."""
        self._active_raster_item = item

    def selected_item(self):
        return self._selected_item

    def select_item(self, item):
        """Setter público para que ImageToolsTab pueda seleccionar una figura desde el
        panel de Capas (clic en una fila) sin tocar el estado interno directo."""
        self._selected_item = item
        self.viewport().update()

    def active_raster_layer(self):
        return self._active_raster_item

    def base_pixmap_item(self):
        """El QGraphicsPixmapItem de la imagen cargada -- para que ImageToolsTab la
        registre como "Capa 0" en el LayerStack sin acceder a un atributo privado."""
        return self._pixmap_item

    def add_scene_item(self, item):
        """Agrega un QGraphicsItem ya armado externamente (ej. una capa de Fondo
        creada por background_dialog.py) a la escena, sin exponer self._scene."""
        self._scene.addItem(item)

    # ------------------------------------------------------------------
    # Interacción de mouse
    # ------------------------------------------------------------------
    def wheelEvent(self, event):
        if self._pixmap_item is None:
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = _ZOOM_STEP if delta > 0 else (1.0 / _ZOOM_STEP)
        current_scale = self.transform().m11()
        new_scale = current_scale * factor
        if new_scale < _MIN_SCALE or new_scale > _MAX_SCALE:
            return
        self._user_zoomed = True

        # Anclaje bajo el cursor calculado a mano (ver NoAnchor en __init__): guardamos
        # qué punto de la ESCENA está bajo el cursor antes de escalar, y después
        # movemos la vista para que ese mismo punto vuelva a quedar bajo el cursor --
        # así el zoom siempre queda centrado en el mouse, sin depender del mecanismo
        # automático de Qt.
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        old_scene_pos = self.mapToScene(pos)
        self.scale(factor, factor)
        new_scene_pos = self.mapToScene(pos)
        delta_scene = new_scene_pos - old_scene_pos
        self.translate(delta_scene.x(), delta_scene.y())

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._user_zoomed = False
            if self._canvas_rect is not None:
                self._fit_canvas_into_view()
            else:
                self._fit_to_window()
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        # El botón del medio siempre paneA, sin importar el modo/herramienta activa
        # -- en canvas_edit y layers_draw el click izquierdo está tomado por los
        # handles/dibujo, así que sin esto no había NINGUNA forma de recorrer la
        # imagen mientras se usa Canvas o Capas (quedaba "trabada").
        if event.button() == Qt.MiddleButton and self._pixmap_item is not None:
            self._start_pan(event.pos())
            return
        if self._interaction_mode == "canvas_edit" and event.button() == Qt.LeftButton:
            self._press_canvas_edit(event.pos())
            return
        if self._interaction_mode == "layers_draw" and event.button() == Qt.LeftButton:
            self._press_layers_draw(event.pos())
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            self._do_pan(event.pos())
            return
        if self._interaction_mode == "canvas_edit":
            self._move_canvas_edit(event.pos())
            return
        if self._interaction_mode == "layers_draw":
            self._move_layers_draw(event.pos())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning and event.button() in (Qt.MiddleButton, Qt.LeftButton):
            self._end_pan()
            return
        if self._interaction_mode == "canvas_edit" and (self._active_handle is not None or self._dragging_image):
            self._active_handle = None
            self._dragging_image = False
            # Un solo disparo aquí (no en cada _apply_canvas_resize/_resize_margin,
            # que corren en cada mouseMove mientras se arrastra) -- "la interacción
            # manual terminó, ve a leer el estado completo con get_canvas_state()".
            self.canvas_edited.emit()
            return
        if self._interaction_mode == "layers_draw":
            handled = self._release_layers_draw()
            if handled:
                return
        super().mouseReleaseEvent(event)

    # -- Canvas: press/move (misma lógica de siempre, ahora en métodos aparte) --
    def _press_canvas_edit(self, pos):
        for handle_id, rect in self._handle_rects.items():
            if rect.contains(pos):
                self._active_handle = handle_id
                self._resize_apply_fn = self._apply_canvas_resize
                return
        if self._pixmap_item is not None:
            img_vp = self.mapFromScene(self._pixmap_item.sceneBoundingRect()).boundingRect()
            if img_vp.contains(pos):
                self._dragging_image = True
                self._drag_offset = self.mapToScene(pos) - self._pixmap_item.pos()
                return
        # Clic fuera de handles/imagen: paneA en vez de no hacer nada -- mismo
        # criterio que _press_select en modo Capas.
        self._start_pan(pos)

    def _move_canvas_edit(self, pos):
        if self._active_handle is not None:
            self._resize_canvas(self._active_handle, self.mapToScene(pos))
            self.viewport().update()
        elif self._dragging_image and self._pixmap_item is not None:
            new_pos = self.mapToScene(pos) - self._drag_offset
            self._pixmap_item.setPos(new_pos)
            self._ensure_scene_covers(self._pixmap_item.sceneBoundingRect())
            self.viewport().update()

    def _apply_canvas_resize(self, new_rect: QRectF):
        self._canvas_rect = new_rect
        self._ensure_scene_covers(new_rect)
        self.size_dragged.emit(round(new_rect.width()), round(new_rect.height()))

    def _resize_canvas(self, handle_id: str, scene_pos: QPointF):
        if self._canvas_rect is None:
            return
        if self._canvas_mode == "margin_external":
            # Los modificadores (Shift/Alt/Ctrl) son específicos del modo libre
            # (Personalizado/presets/Sin ajuste) -- el margen ya es simétrico por
            # definición, no hay mucho que agregarle ahí.
            self._resize_margin(handle_id, scene_pos)
            return
        modifiers = QApplication.keyboardModifiers()
        if modifiers & Qt.ShiftModifier:
            new_rect = self._compute_uniform_centered_resize(self._canvas_rect, handle_id, scene_pos)
        elif modifiers & Qt.AltModifier:
            new_rect = self._compute_axis_centered_resize(self._canvas_rect, handle_id, scene_pos)
        else:
            new_rect = self._compute_free_resize(self._canvas_rect, handle_id, scene_pos)
        if modifiers & Qt.ControlModifier:
            new_rect = self._snap_to_image_edges(new_rect, handle_id)
        self._apply_canvas_resize(new_rect)

    def _image_center(self) -> QPointF:
        if self._pixmap_item is not None:
            return self._pixmap_item.sceneBoundingRect().center()
        return self._canvas_rect.center() if self._canvas_rect is not None else QPointF(0, 0)

    def _compute_uniform_centered_resize(self, rect: QRectF, handle_id: str, scene_pos: QPointF) -> QRectF:
        """Shift: escala los 4 lados a la vez (mantiene la proporción del canvas),
        centrado en el centro de la IMAGEN -- no del canvas, para que crecer/encoger
        siempre quede simétrico respecto a la foto sin importar dónde esté el canvas."""
        center = self._image_center()
        h_align, v_align = _HANDLE_ANCHORS[handle_id]
        half_w, half_h = rect.width() / 2, rect.height() / 2
        if h_align != "center" and v_align != "center":
            # Esquina: usa la distancia diagonal, sigue el movimiento real del mouse
            # en vez de solo su componente horizontal.
            orig_dist = math.hypot(half_w, half_h) or 1.0
            new_dist = math.hypot(scene_pos.x() - center.x(), scene_pos.y() - center.y())
            k = new_dist / orig_dist
        elif h_align != "center":
            orig_edge_dist = half_w if half_w > 0 else 1.0
            new_edge_dist = abs(scene_pos.x() - center.x())
            k = new_edge_dist / orig_edge_dist
        elif v_align != "center":
            orig_edge_dist = half_h if half_h > 0 else 1.0
            new_edge_dist = abs(scene_pos.y() - center.y())
            k = new_edge_dist / orig_edge_dist
        else:
            k = 1.0
        k = max(k, _MIN_SIZE / max(rect.width(), rect.height(), 1))
        new_half_w, new_half_h = half_w * k, half_h * k
        return QRectF(center.x() - new_half_w, center.y() - new_half_h, new_half_w * 2, new_half_h * 2)

    def _compute_axis_centered_resize(self, rect: QRectF, handle_id: str, scene_pos: QPointF) -> QRectF:
        """Alt: escala solo el eje que se está arrastrando (el lado opuesto se mueve
        espejado), centrado en el centro de la imagen -- a diferencia de Shift, el
        otro eje (perpendicular) no se toca, así que no mantiene la proporción."""
        center = self._image_center()
        h_align, v_align = _HANDLE_ANCHORS[handle_id]
        r = QRectF(rect)
        if h_align != "center":
            new_half_w = max(_MIN_SIZE / 2, abs(scene_pos.x() - center.x()))
            r.setLeft(center.x() - new_half_w)
            r.setRight(center.x() + new_half_w)
        if v_align != "center":
            new_half_h = max(_MIN_SIZE / 2, abs(scene_pos.y() - center.y()))
            r.setTop(center.y() - new_half_h)
            r.setBottom(center.y() + new_half_h)
        return r

    def _snap_to_image_edges(self, rect: QRectF, handle_id: str) -> QRectF:
        """Ctrl: si el borde que se está moviendo queda cerca del borde correspondiente
        de la imagen, lo pega exacto -- el umbral es en píxeles de PANTALLA (no de
        escena) para que se sienta igual de "pegajoso" sin importar el zoom."""
        if self._pixmap_item is None:
            return rect
        img = self._pixmap_item.sceneBoundingRect()
        scale = max(self.transform().m11(), 0.001)
        snap = _SNAP_PX / scale
        h_align, v_align = _HANDLE_ANCHORS[handle_id]
        r = QRectF(rect)
        if h_align == "left" and abs(r.left() - img.left()) < snap:
            r.setLeft(img.left())
        elif h_align == "right" and abs(r.right() - img.right()) < snap:
            r.setRight(img.right())
        if v_align == "top" and abs(r.top() - img.top()) < snap:
            r.setTop(img.top())
        elif v_align == "bottom" and abs(r.bottom() - img.bottom()) < snap:
            r.setBottom(img.bottom())
        return r

    def _resize_margin(self, handle_id: str, scene_pos: QPointF):
        """Solo "Añadir Margen Externo" -- el canvas crece/decrece simétrico
        alrededor de la imagen, que nunca se toca (a diferencia del extinto "Margen
        Interno", que la encogía; se sacó por pedido del usuario: con el canvas
        arrastrable de entrada, recortar espacio vacío ya se hace a mano sin
        necesidad de un modo aparte que además distorsionaba la proporción)."""
        if self._pixmap_item is None:
            return
        img_rect = self._pixmap_item.sceneBoundingRect()
        h_align, v_align = _HANDLE_ANCHORS[handle_id]
        deltas = []
        if h_align == "left":
            deltas.append(img_rect.left() - scene_pos.x())
        elif h_align == "right":
            deltas.append(scene_pos.x() - img_rect.right())
        if v_align == "top":
            deltas.append(img_rect.top() - scene_pos.y())
        elif v_align == "bottom":
            deltas.append(scene_pos.y() - img_rect.bottom())
        if not deltas:
            return
        margin = max(0, round(sum(deltas) / len(deltas)))
        self._canvas_rect = img_rect.adjusted(-margin, -margin, margin, margin)
        self._ensure_scene_covers(self._canvas_rect)
        self.margin_dragged.emit(margin)

    def _compute_free_resize(self, rect: QRectF, handle_id: str, scene_pos: QPointF) -> QRectF:
        """Matemática de redimensionar-por-handle compartida entre el canvas
        (Personalizado/presets) y una figura rect/elipse seleccionada en modo Capas:
        esquina mueve ancho+alto anclando la esquina opuesta, borde mueve una sola
        dimensión anclando el borde opuesto."""
        r = QRectF(rect)
        h_align, v_align = _HANDLE_ANCHORS[handle_id]
        if h_align == "left":
            r.setLeft(min(scene_pos.x(), r.right() - _MIN_SIZE))
        elif h_align == "right":
            r.setRight(max(scene_pos.x(), r.left() + _MIN_SIZE))
        if v_align == "top":
            r.setTop(min(scene_pos.y(), r.bottom() - _MIN_SIZE))
        elif v_align == "bottom":
            r.setBottom(max(scene_pos.y(), r.top() + _MIN_SIZE))
        return r

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._user_zoomed:
            # El canvas se ve siempre que exista (borde de referencia o editable, ver
            # drawForeground), así que el encuadre lo tiene en cuenta sin importar el
            # modo -- no solo mientras el control de Canvas está abierto.
            if self._canvas_rect is not None:
                self._fit_canvas_into_view()
            else:
                self._fit_to_window()

    # ------------------------------------------------------------------
    # Modo Capas -- press/move/release
    # ------------------------------------------------------------------
    def _press_layers_draw(self, pos):
        scene_pos = self.mapToScene(pos)
        if self._active_tool == "select":
            self._press_select(pos, scene_pos)
        elif self._active_tool in ("rect", "ellipse"):
            self._draw_start_scene = scene_pos
            self._drawing_item = self._make_shape_item(self._active_tool, QRectF(scene_pos, scene_pos))
            self._scene.addItem(self._drawing_item)
        elif self._active_tool == "line":
            self._draw_start_scene = scene_pos
            item = QGraphicsLineItem(QLineF(scene_pos, scene_pos))
            item.setPen(self._line_pen())
            self._scene.addItem(item)
            self._drawing_item = item
        elif self._active_tool == "brush":
            self._begin_brush_stroke(scene_pos)

    def _press_select(self, pos, scene_pos):
        for handle_id, rect in self._handle_rects.items():
            if rect.contains(pos):
                self._active_handle = handle_id
                self._resize_apply_fn = self._apply_shape_resize
                return
        for handle_id, rect in self._line_handle_rects.items():
            if rect.contains(pos):
                self._active_line_handle = handle_id
                return
        item = self._scene.itemAt(scene_pos, self.transform())
        if item is not None and item is not self._pixmap_item:
            self._selected_item = item
            self._dragging_shape = True
            self._drag_offset = scene_pos
            self.shape_selected.emit(item)
        else:
            self._selected_item = None
            self.shape_selected.emit(None)
            # Clic en área vacía con Seleccionar activo: en vez de no hacer nada,
            # paneA -- mismo criterio que el botón del medio, para poder recorrer la
            # imagen sin salir de la herramienta ni de Modo Capas.
            self._start_pan(pos)
        self.viewport().update()

    # ------------------------------------------------------------------
    # Paneo manual (ver mousePressEvent/mouseMoveEvent/mouseReleaseEvent)
    # ------------------------------------------------------------------
    def _start_pan(self, pos):
        self._panning = True
        self._pan_last_pos = QPoint(pos)
        self.viewport().setCursor(Qt.ClosedHandCursor)

    def _do_pan(self, pos):
        delta = pos - self._pan_last_pos
        self._pan_last_pos = QPoint(pos)
        h = self.horizontalScrollBar()
        v = self.verticalScrollBar()
        h.setValue(h.value() - delta.x())
        v.setValue(v.value() - delta.y())

    def _end_pan(self):
        self._panning = False
        self.viewport().unsetCursor()

    def _make_shape_item(self, kind: str, rect: QRectF):
        item = QGraphicsRectItem(rect) if kind == "rect" else QGraphicsEllipseItem(rect)
        item.setBrush(QBrush(self._draw_fill) if self._draw_fill is not None else QBrush(Qt.NoBrush))
        item.setPen(self._shape_pen())
        return item

    def _shape_pen(self) -> QPen:
        if self._draw_stroke is None or self._stroke_width <= 0:
            return QPen(Qt.NoPen)
        return QPen(self._draw_stroke, self._stroke_width)

    def _line_pen(self) -> QPen:
        color = self._draw_stroke if self._draw_stroke is not None else QColor("#1a1a1a")
        return QPen(color, max(1, self._stroke_width))

    def _move_layers_draw(self, pos):
        scene_pos = self.mapToScene(pos)
        if (self._active_handle is not None or self._active_line_handle is not None
                or self._dragging_shape or self._drawing_item is not None or self._painting):
            # Igual que en modo Canvas: si se dibuja/arrastra/pinta más allá de los
            # límites originales de la escena (fijados según el tamaño nativo de la
            # imagen en set_pixmap), hay que agrandarla o el zoom/paneo se clampa raro
            # apenas el cursor sale de esa zona.
            self._ensure_scene_covers(QRectF(scene_pos.x() - 50, scene_pos.y() - 50, 100, 100))
        if self._active_handle is not None:
            base_rect = self._selected_item.rect() if self._selected_item is not None else QRectF()
            new_rect = self._compute_free_resize(base_rect, self._active_handle, scene_pos)
            if self._resize_apply_fn:
                self._resize_apply_fn(new_rect)
            self.viewport().update()
        elif self._active_line_handle is not None and isinstance(self._selected_item, QGraphicsLineItem):
            line = self._selected_item.line()
            if self._active_line_handle == "p1":
                self._selected_item.setLine(QLineF(scene_pos, line.p2()))
            else:
                self._selected_item.setLine(QLineF(line.p1(), scene_pos))
            self.viewport().update()
        elif self._dragging_shape and self._selected_item is not None:
            delta = scene_pos - self._drag_offset
            self._drag_offset = scene_pos
            self._translate_item(self._selected_item, delta)
            self.viewport().update()
        elif self._drawing_item is not None:
            rect = QRectF(self._draw_start_scene, scene_pos).normalized()
            if isinstance(self._drawing_item, QGraphicsLineItem):
                self._drawing_item.setLine(QLineF(self._draw_start_scene, scene_pos))
            else:
                self._drawing_item.setRect(rect)
        elif self._painting:
            self._paint_brush_segment(scene_pos)

    def _apply_shape_resize(self, new_rect: QRectF):
        if isinstance(self._selected_item, _SHAPE_ITEM_TYPES):
            self._selected_item.setRect(new_rect)

    def _translate_item(self, item, delta: QPointF):
        if isinstance(item, _SHAPE_ITEM_TYPES):
            item.setRect(item.rect().translated(delta))
        elif isinstance(item, QGraphicsLineItem):
            line = item.line()
            item.setLine(QLineF(line.p1() + delta, line.p2() + delta))
        else:
            item.setPos(item.pos() + delta)

    def _release_layers_draw(self) -> bool:
        if self._active_handle is not None:
            self._active_handle = None
            self._resize_apply_fn = None
            return True
        if self._active_line_handle is not None:
            self._active_line_handle = None
            return True
        if self._dragging_shape:
            self._dragging_shape = False
            return True
        if self._drawing_item is not None:
            item = self._drawing_item
            self._drawing_item = None
            kind = "line" if isinstance(item, QGraphicsLineItem) else \
                ("ellipse" if isinstance(item, QGraphicsEllipseItem) else "rect")
            # Descarta figuras degeneradas (click sin arrastre real).
            too_small = False
            if isinstance(item, QGraphicsLineItem):
                line = item.line()
                too_small = QLineF(line.p1(), line.p2()).length() < 2
            else:
                r = item.rect()
                too_small = r.width() < 2 and r.height() < 2
            if too_small:
                self._scene.removeItem(item)
                return True
            self.shape_created.emit(item, kind)
            return True
        if self._painting:
            self._painting = False
            self._last_paint_scene = None
            return True
        return False

    # -- Pincel: pinta sobre un QImage propio de la capa activa --
    def _begin_brush_stroke(self, scene_pos: QPointF):
        if self._active_raster_item is None or id(self._active_raster_item) not in self._raster_buffers:
            self._create_raster_layer()
        self._painting = True
        self._last_paint_scene = scene_pos
        self._paint_dot(scene_pos)

    def _create_raster_layer(self):
        size = self._native_size
        if size is None or self._pixmap_item is None:
            return
        image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        item = QGraphicsPixmapItem(QPixmap.fromImage(image))
        item.setPos(self._pixmap_item.pos())
        self._scene.addItem(item)
        self._raster_buffers[id(item)] = image
        self._active_raster_item = item
        self.raster_layer_created.emit(item)

    def _paint_dot(self, scene_pos: QPointF):
        item = self._active_raster_item
        image = self._raster_buffers.get(id(item)) if item is not None else None
        if item is None or image is None:
            return
        local = scene_pos - item.pos()
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(self._brush_color))
        r = self._brush_size / 2
        painter.drawEllipse(local, r, r)
        painter.end()
        item.setPixmap(QPixmap.fromImage(image))

    def _paint_brush_segment(self, scene_pos: QPointF):
        item = self._active_raster_item
        image = self._raster_buffers.get(id(item)) if item is not None else None
        if item is None or image is None or self._last_paint_scene is None:
            return
        p1 = self._last_paint_scene - item.pos()
        p2 = scene_pos - item.pos()
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(self._brush_color, self._brush_size, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(p1, p2)
        painter.end()
        item.setPixmap(QPixmap.fromImage(image))
        self._last_paint_scene = scene_pos
