# src/gui/tabs/image_tools/image_tools_view.py
import os
import shutil
import tempfile

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea, QApplication,
    QPushButton, QButtonGroup, QLineEdit, QFileDialog,
)
from PySide6.QtCore import Qt, QSize, QEvent, QUrl, QStandardPaths
from PySide6.QtGui import QDesktopServices, QPixmap

from core.utils.config_manager import get_config, save_config
from gui.styles import (
    get_theme_token, apply_folder_browse_button_style, apply_folder_open_button_style,
)
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
from gui.widgets.animated_button import AnimatedButton
from gui.widgets.bouncing_progress_bar import BouncingProgressBar
from gui.widgets.combo_box import AutoPopupComboBox
from gui.widgets.collapsible_panel import CollapsiblePanel
from gui.widgets.floating_panel import FloatingPanel
from gui.widgets.popover_button import PopoverTriggerButton
from gui.tabs.editing_media.preview_panel import PreviewContainerWidget
from gui.tabs.image_tools.image_queue_widget import ImageQueueWidget
from gui.tabs.image_tools.upscale_popover import UpscalePopoverContent
from gui.tabs.image_tools.rembg_popover import RembgPopoverContent
from gui.tabs.image_tools.canvas_popover import CanvasPopoverContent
from gui.tabs.image_tools.resize_popover import ResizePopoverContent
from gui.tabs.image_tools.convert_panel import ConvertPanel
from gui.tabs.image_tools.image_convert_worker import ImageConvertWorker
from gui.tabs.image_tools.canvas_flatten import build_flattened_image
from gui.tabs.image_tools.layers.layer_model import Layer, LayerStack
from gui.tabs.image_tools.layers.layers_panel import LayersPanel
from gui.tabs.image_tools.layers.background_dialog import BackgroundDialog

_COMPARE_CACHE_SIZE = 5


class _CompareCache:
    """Cache RAM chico para la vista antes/después (ver PreviewContainerWidget.
    show_compare_preview) -- evita recargar de disco/re-renderizar un vector o RAW
    en cada selección de la misma fila. A diferencia del cache de DowP1 (que solo
    guardaba el "antes"), acá se guardan ambos lados -- el "después" también se
    recargaba de disco en cada click en DowP1, un desperdicio real ya que el
    proceso mismo lo acaba de escribir. FIFO simple, tope 5 (mismo tamaño que
    DowP1), suficiente para un flujo de "comparar unas pocas filas por sesión"."""

    def __init__(self, max_size: int = _COMPARE_CACHE_SIZE):
        self._max_size = max_size
        self._entries: dict[str, tuple[QPixmap, QPixmap]] = {}
        self._order: list[str] = []

    def get(self, filepath: str) -> tuple[QPixmap | None, QPixmap | None]:
        entry = self._entries.get(filepath)
        return entry if entry else (None, None)

    def put(self, filepath: str, before: QPixmap, after: QPixmap):
        if before is None or after is None or before.isNull() or after.isNull():
            return
        if filepath not in self._entries and len(self._entries) >= self._max_size:
            oldest = self._order.pop(0)
            self._entries.pop(oldest, None)
        if filepath in self._order:
            self._order.remove(filepath)
        self._order.append(filepath)
        self._entries[filepath] = (before, after)

    def invalidate(self, filepath: str):
        """Descarta el par antes/después cacheado de `filepath` -- se llama al
        registrar un output_path NUEVO para un archivo (reconversión), para que
        Comparar no muestre el resultado anterior ya pisado en disco."""
        self._entries.pop(filepath, None)
        if filepath in self._order:
            self._order.remove(filepath)


class ImageToolsTab(QWidget):
    """Editor de Imagen.

    Layout: barra de herramientas vertical a la izquierda (ancho fijo 40px),
    vista previa al centro, panel derecho colapsable (cola de imágenes + opciones
    de formato encapsuladas), y panel inferior unificado de salida y conversión
    (política de conflicto, ruta de destino, progreso y botón Convertir)."""

    TOOLBAR_WIDTH = 40
    RIGHT_DOCKED_WIDTH = 380
    RIGHT_OVERLAY_MAX_WIDTH = 420
    # Ancho "cómodo" mínimo del preview antes de forzar el colapso a overlay -- no su
    # mínimo técnico absoluto, mismo criterio que PREVIEW_MIN_WIDTH en VideoToolsTab.
    PREVIEW_MIN_WIDTH = 480
    COLLAPSE_THRESHOLD_WIDTH = 760

    def __init__(self):
        super().__init__()
        self._current_filepath = None
        self._compare_cache = _CompareCache()
        # Fase 3 -- persistencia por archivo de formas/pincel (capas no-"image")
        # y de un Canvas editado a mano (arrastre de handles/imagen, a diferencia
        # de un preset del popover -- eso sigue siendo 100% de lote, ver
        # canvas_popover.py). Clave = filepath. Ver _on_file_selected/_on_canvas_edited.
        self._layer_snapshots: dict[str, list] = {}
        self._canvas_overrides: dict[str, dict] = {}
        self._flatten_temp_dir: str | None = None
        # Filepath -> si el resultado ya convertido de ese archivo usó IA
        # (reescalado por ahora, ver _on_convert_file_completed -- a futuro también
        # Eliminar Fondo cuando tenga ejecución conectada) -- determina si Comparar
        # arranca activado por defecto al mirar ese archivo (ver _on_file_selected).
        self._files_with_ai_edit: dict[str, bool] = {}
        self._active_convert_settings: dict | None = None
        self._build_ui()

    def _build_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(10, 10, 10, 10)
        outer_layout.setSpacing(8)

        # ── Fila superior: Toolbar vertical izquierda + Fila de cuerpo
        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(8)

        # ── Barra de herramientas vertical: botones cuadrados estándar 32x32
        # (mismo tamaño y proporciones que en el resto de la app), cada uno
        # despliega su propio panel flotante o activa su herramienta de dibujo.
        self.side_toolbar = QFrame()
        self.side_toolbar.setObjectName("imageToolsSideToolbar")
        self.side_toolbar.setFixedWidth(self.TOOLBAR_WIDTH)
        top_layout = QVBoxLayout(self.side_toolbar)
        top_layout.setContentsMargins(4, 10, 4, 10)
        top_layout.setSpacing(6)
        top_layout.setAlignment(Qt.AlignHCenter)

        def _make_sep():
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setFixedHeight(1)
            sep.setStyleSheet(f"background-color: {get_theme_token('borde_sutil', '#2d2d2d')}; border: none;")
            return sep

        self._popover_buttons = []

        self.selected_upscale_engine = None
        self.selected_upscale_model = None
        self.upscale_popover_content = UpscalePopoverContent()
        self.upscale_popover_content.selection_changed.connect(self._on_upscale_selection_changed)

        self.btn_upscale = PopoverTriggerButton(host=self, content=self.upscale_popover_content)
        self.btn_upscale.setFixedSize(32, 32)
        self.btn_upscale.setIconSize(QSize(18, 18))
        self.btn_upscale.setCursor(Qt.PointingHandCursor)
        self._style_upscale_button(is_valid=False)
        top_layout.addWidget(self.btn_upscale)
        self._popover_buttons.append(self.btn_upscale)

        self.selected_rembg_family = None
        self.selected_rembg_model = None
        self.rembg_popover_content = RembgPopoverContent()
        self.rembg_popover_content.selection_changed.connect(self._on_rembg_selection_changed)

        self.btn_rembg = PopoverTriggerButton(host=self, content=self.rembg_popover_content)
        self.btn_rembg.setFixedSize(32, 32)
        self.btn_rembg.setIconSize(QSize(18, 18))
        self.btn_rembg.setCursor(Qt.PointingHandCursor)
        self._style_rembg_button(is_valid=False)
        top_layout.addWidget(self.btn_rembg)
        self._popover_buttons.append(self.btn_rembg)

        # Redimensionar -- botón propio con popover (mismo patrón que Reescalar IA/
        # Eliminar Fondo IA arriba), separado del panel "Convertir" del panel
        # izquierdo: es una operación de tamaño aplicada a TODO el lote al exportar,
        # no una opción de codificación de un formato puntual (ver
        # gui/tabs/image_tools/resize_popover.py y convert_panel.py).
        self.resize_popover_content = ResizePopoverContent()
        self.resize_popover_content.selection_changed.connect(self._on_resize_selection_changed)

        self.btn_resize = PopoverTriggerButton(host=self, content=self.resize_popover_content)
        self.btn_resize.setFixedSize(32, 32)
        self.btn_resize.setIconSize(QSize(18, 18))
        self.btn_resize.setCursor(Qt.PointingHandCursor)
        self._style_resize_button(is_active=False)
        top_layout.addWidget(self.btn_resize)
        self._popover_buttons.append(self.btn_resize)

        top_layout.addWidget(_make_sep())

        self.selected_canvas_option = None
        self.canvas_popover_content = CanvasPopoverContent()
        self.canvas_popover_content.selection_changed.connect(self._on_canvas_selection_changed)

        self.layer_stack = LayerStack()
        self.layer_stack.layers_changed.connect(self._refresh_layers_panel)

        self.layers_panel = LayersPanel()
        self.layers_panel.draw_style_changed.connect(self._on_layers_draw_style_changed)
        self.layers_panel.brush_style_changed.connect(self._on_layers_brush_style_changed)
        self.layers_panel.layer_visibility_toggled.connect(self._on_layer_visibility_toggled)
        self.layers_panel.layer_opacity_changed.connect(self._on_layer_opacity_changed)
        self.layers_panel.layer_move_up_requested.connect(self._on_layer_move_up)
        self.layers_panel.layer_move_down_requested.connect(self._on_layer_move_down)
        self.layers_panel.layer_delete_requested.connect(self._on_layer_delete)
        self.layers_panel.layer_selected.connect(self._on_layer_row_selected)
        self.layers_panel.add_background_requested.connect(self._on_add_background_requested)

        # Toggle chico que solo muestra/oculta el panel flotante de Capas -- ya NO
        # decide qué herramienta está activa (eso es independiente, ver abajo), igual
        # que el panel de Capas de Photoshop: se puede mostrar/ocultar sin que afecte
        # qué herramienta tenés elegida. Arranca destildado/oculto (ver right_panel
        # más abajo) -- el usuario lo abre cuando lo necesita.
        self.btn_layers_panel = QPushButton()
        self.btn_layers_panel.setCheckable(True)
        self.btn_layers_panel.setFixedSize(32, 32)
        self.btn_layers_panel.setIconSize(QSize(18, 18))
        self.btn_layers_panel.setCursor(Qt.PointingHandCursor)
        self.btn_layers_panel.setToolTip(self.tr("Mostrar/ocultar panel de Capas"))
        self.btn_layers_panel.toggled.connect(self._on_layers_panel_toggled)
        self._style_layers_panel_button(False)
        top_layout.addWidget(self.btn_layers_panel)

        top_layout.addWidget(_make_sep())

        # Herramientas unificadas -- Seleccionar/Rectángulo/Elipse/Línea/Pincel/Canvas,
        # todas siempre visibles y mutuamente excluyentes, como la caja de
        # herramientas de un editor real: elegir una es solo "cambiar de
        # herramienta", no "entrar/salir de un modo aparte". Canvas ya no compite
        # como un sistema separado -- es una herramienta más del mismo grupo.
        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)
        self._tool_buttons = {}
        self._TOOL_ICONS = {
            "select": "arrow_menu_open.svg",
            "rect": "maximize.svg",
            "ellipse": "check_circle.svg",
            "line": "minus.svg",
            "brush": "edit.svg",
            "canvas": "grid_view.svg",
        }
        for key, tooltip in (
            ("select", self.tr("Seleccionar")),
            ("rect", self.tr("Rectángulo")),
            ("ellipse", self.tr("Elipse")),
            ("line", self.tr("Línea")),
            ("brush", self.tr("Pincel")),
            ("canvas", self.tr("Canvas — clic derecho: opciones")),
        ):
            if key == "canvas":
                # left_click_opens=False: clic izquierdo solo selecciona la
                # herramienta (como cualquier otra); clic derecho abre el menú de
                # opciones (Ajuste/Margen/Posición/Overflow), vía contextMenuEvent.
                btn = PopoverTriggerButton(host=self, content=self.canvas_popover_content, left_click_opens=False)
                btn.opened.connect(self._on_canvas_popover_opened)
                self._popover_buttons.append(btn)
            else:
                btn = QPushButton()
            btn.setCheckable(True)
            btn.setFixedSize(32, 32)
            btn.setIconSize(QSize(18, 18))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(tooltip)
            btn.toggled.connect(lambda checked, k=key: self._on_tool_toggled(k, checked))
            self._tool_group.addButton(btn)
            self._tool_buttons[key] = btn
            top_layout.addWidget(btn)
        self.btn_canvas = self._tool_buttons["canvas"]
        self._style_tool_buttons()
        self._tool_buttons["select"].setChecked(True)

        for btn in self._popover_buttons:
            btn.opened.connect(lambda b=btn: self._close_other_popovers(b))
        # Abrir Reescalar/Eliminar Fondo te saca de la herramienta que tuvieras activa
        # (incluido Canvas) y te deja en Seleccionar -- evita clics que dibujen/
        # redimensionen algo sin querer mientras estás mirando ese popover. Canvas NO
        # se agrega acá: abrir SU PROPIO popover no debe sacarte de la herramienta
        # Canvas (ver _on_canvas_popover_opened, que hace lo contrario: la activa).
        self.btn_upscale.opened.connect(self._reset_to_select_tool)
        self.btn_rembg.opened.connect(self._reset_to_select_tool)
        self.btn_resize.opened.connect(self._reset_to_select_tool)

        top_layout.addStretch()
        content_row.addWidget(self.side_toolbar)

        # ── Fila de cuerpo: preview + panel derecho colapsable ─────────────────────
        self.body_row = QWidget()
        body_layout = QHBoxLayout(self.body_row)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)

        # Columna del preview: fila de Título/Copiar arriba + preview abajo -- se
        # envuelve en su propio widget para que esa fila quede acotada al ancho del
        # preview (no de todo body_row, que también incluye el panel derecho).
        preview_column = QWidget()
        preview_column_layout = QVBoxLayout(preview_column)
        preview_column_layout.setContentsMargins(0, 0, 0, 0)
        preview_column_layout.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        lbl_title = QLabel(self.tr("Título:"))
        lbl_title.setObjectName("menuLabel")
        title_row.addWidget(lbl_title)
        self.entry_title = QLineEdit()
        self.entry_title.setPlaceholderText(self.tr("Nombre del archivo de salida"))
        self.entry_title.setEnabled(False)
        self.entry_title.editingFinished.connect(self._on_title_edited)
        title_row.addWidget(self.entry_title, 1)
        # Toggle -- por defecto SIEMPRE se ve el editor (formas/pincel/Canvas
        # siguen visibles y editables incluso después de convertir, ver
        # _on_file_selected/_show_editable_view); la comparación antes/después
        # queda como vista explícita bajo demanda, no como estado permanente.
        self.btn_compare_result = QPushButton(self.tr("Comparar"))
        self.btn_compare_result.setProperty("variant", "secondary")
        self.btn_compare_result.setCursor(Qt.PointingHandCursor)
        self.btn_compare_result.setToolTip(self.tr("Ver comparación antes/después del resultado"))
        self.btn_compare_result.setCheckable(True)
        self.btn_compare_result.setEnabled(False)
        self.btn_compare_result.toggled.connect(self._on_compare_toggled)
        title_row.addWidget(self.btn_compare_result)
        self.btn_copy_result = QPushButton(self.tr("Copiar"))
        self.btn_copy_result.setProperty("variant", "secondary")
        self.btn_copy_result.setCursor(Qt.PointingHandCursor)
        self.btn_copy_result.setToolTip(self.tr("Copiar la imagen resultante al portapapeles"))
        self.btn_copy_result.setEnabled(False)
        self.btn_copy_result.clicked.connect(self._on_copy_result_clicked)
        title_row.addWidget(self.btn_copy_result)
        preview_column_layout.addLayout(title_row)

        self.preview = PreviewContainerWidget()
        self.preview.set_fill_available_space(True)
        self.preview.set_zoomable(True)
        preview_column_layout.addWidget(self.preview, 1)

        body_layout.addWidget(preview_column, 1)

        self.queue_content = self._build_queue_content()
        self.right_panel = CollapsiblePanel(
            self.queue_content, edge="right",
            docked_size=self.RIGHT_DOCKED_WIDTH,
            overlay_max_width=self.RIGHT_OVERLAY_MAX_WIDTH,
        )
        body_layout.addWidget(self.right_panel, 0)

        # Panel "Capas": ventana flotante arrastrable (estilo panel de Photoshop), no
        # acoplada a ningún layout -- flota libremente sobre self.body_row, la mueve
        # el usuario agarrando su barra de título (ver gui/widgets/floating_panel.py).
        # preferred_side="left": al abrirse por primera vez aparece cerca de la barra
        # de herramientas/sobre el preview, no encima del panel derecho de cola+Convertir.
        self.layers_floating_panel = FloatingPanel(
            self.tr("Capas"), self.layers_panel, host=self.body_row, width=300, preferred_side="left",
        )
        self.layers_floating_panel.closed.connect(lambda: self.btn_layers_panel.setChecked(False))
        # Oculto por defecto -- self.btn_layers_panel ya nace destildado (ver arriba),
        # así que no hace falta forzar nada acá; alcanza con no mostrarlo.

        # Puente popover <-> visor para la edición visual de Canvas (ver
        # canvas_popover.py y ZoomableImageViewer.apply_canvas_state/margin_dragged/
        # size_dragged): el popover empuja el estado calculado, el visor devuelve los
        # valores en vivo mientras se arrastra un handle.
        viewer = self.preview.zoom_viewer
        self.canvas_popover_content.state_changed.connect(self._on_canvas_state_changed)
        viewer.margin_dragged.connect(self.canvas_popover_content.on_margin_dragged)
        viewer.size_dragged.connect(self.canvas_popover_content.on_size_dragged)
        # "El usuario tocó el canvas a mano" -- Fase 3, guardarlo como override
        # propio de ESTE archivo (no toca el preset de lote, ver canvas_popover.py).
        viewer.canvas_edited.connect(self._on_canvas_edited)

        # Puente panel de Capas <-> visor: figuras/trazos creados en el visor se
        # registran como capas; seleccionar en el visor resalta la fila correspondiente.
        viewer.shape_created.connect(self._on_shape_created)
        viewer.raster_layer_created.connect(self._on_raster_layer_created)
        viewer.shape_selected.connect(self._on_shape_selected)

        # El host del overlay es la pestaña completa (self), no self.body_row: Qt recorta
        # los hijos al área de su padre, así que si quedara colgado de body_row jamás podría
        # pintarse por encima de output_bar. Al no empujar ni redimensionar nada (es un
        # overlay flotante), cubre toda la altura disponible y el botón de borde queda
        # pegado al límite de la ventana (mismo comportamiento que en VideoToolsTab).
        self.right_panel.configure_container(self, body_layout, 1, dock_stretch=0)

        self.image_queue.file_selected.connect(self._on_file_selected)

        content_row.addWidget(self.body_row, 1)
        outer_layout.addLayout(content_row, 1)

        # ── Fila inferior: Barra unificada de salida y conversión
        self.output_bar = self._build_output_bar()
        outer_layout.addWidget(self.output_bar)

        QApplication.instance().installEventFilter(self)

    def _close_other_popovers(self, opened_btn):
        """Solo un popover de la franja superior abierto a la vez -- si se abre uno,
        se cierran los demás en vez de quedar superpuestos."""
        for btn in self._popover_buttons:
            if btn is not opened_btn and btn.is_open():
                btn.set_open(False)

    def _on_upscale_selection_changed(self, engine_key: str, model_key: str, is_valid: bool):
        self.selected_upscale_engine = engine_key or None
        self.selected_upscale_model = model_key or None
        self._style_upscale_button(is_valid)

    def _on_rembg_selection_changed(self, family_key: str, model_key: str, is_valid: bool):
        self.selected_rembg_family = family_key or None
        self.selected_rembg_model = model_key or None
        self._style_rembg_button(is_valid)

    def _on_resize_selection_changed(self, is_active: bool):
        self._style_resize_button(is_active)

    def _style_resize_button(self, is_active: bool):
        """Mismo criterio visual que _style_upscale_button/_style_rembg_button --
        verde cuando el preset elegido en el popover no es "No escalar (Original)"
        (el default), gris si lo es."""
        if is_active:
            self.btn_resize.setIcon(get_colored_svg_icon("minimize.svg", "#000000", size=18))
            self.btn_resize.setToolTip(self.tr("Redimensionar — activo"))
            self.btn_resize.setStyleSheet(f"""
                QPushButton {{
                    min-width: 32px; max-width: 32px;
                    min-height: 32px; max-height: 32px;
                    background-color: {get_theme_token('acento_secundario', '#1DC038')};
                    border: none;
                    border-radius: 6px;
                    padding: 0px;
                }}
                QPushButton:hover {{
                    background-color: {get_theme_token('acento_primario', '#B9E640')};
                }}
            """)
        else:
            self.btn_resize.setIcon(get_colored_svg_icon("minimize.svg", "#6c7086", size=18))
            self.btn_resize.setToolTip(self.tr("Redimensionar"))
            self.btn_resize.setStyleSheet(f"""
                QPushButton {{
                    min-width: 30px; max-width: 30px;
                    min-height: 30px; max-height: 30px;
                    background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                    border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                    border-radius: 6px;
                    padding: 0px;
                }}
                QPushButton:hover {{
                    background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')};
                }}
            """)

    def _style_rembg_button(self, is_valid: bool):
        """Mismo criterio visual que _style_upscale_button -- ver ese método."""
        if is_valid:
            self.btn_rembg.setIcon(get_colored_svg_icon("content_cut.svg", "#000000", size=18))
            self.btn_rembg.setToolTip(self.tr("Eliminar Fondo (IA) — configuración lista"))
            self.btn_rembg.setStyleSheet(f"""
                QPushButton {{
                    min-width: 32px; max-width: 32px;
                    min-height: 32px; max-height: 32px;
                    background-color: {get_theme_token('acento_secundario', '#1DC038')};
                    border: none;
                    border-radius: 6px;
                    padding: 0px;
                }}
                QPushButton:hover {{
                    background-color: {get_theme_token('acento_primario', '#B9E640')};
                }}
            """)
        else:
            self.btn_rembg.setIcon(get_colored_svg_icon("content_cut.svg", "#6c7086", size=18))
            self.btn_rembg.setToolTip(self.tr("Eliminar Fondo (IA)"))
            self.btn_rembg.setStyleSheet(f"""
                QPushButton {{
                    min-width: 30px; max-width: 30px;
                    min-height: 30px; max-height: 30px;
                    background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                    border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                    border-radius: 6px;
                    padding: 0px;
                }}
                QPushButton:hover {{
                    background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')};
                }}
            """)

    def _style_upscale_button(self, is_valid: bool):
        """Mismo criterio visual que apply_edit_subclip_button_style (verde acento +
        ícono oscuro cuando hay una configuración lista para usarse, gris neutro si
        no) -- sin reusar esa función porque está atada a "edit.svg"/textos de
        subclip, no genérica."""
        if is_valid:
            self.btn_upscale.setIcon(get_colored_svg_icon("zoom_in.svg", "#000000", size=18))
            self.btn_upscale.setToolTip(self.tr("Reescalar con IA — configuración lista"))
            self.btn_upscale.setStyleSheet(f"""
                QPushButton {{
                    min-width: 32px; max-width: 32px;
                    min-height: 32px; max-height: 32px;
                    background-color: {get_theme_token('acento_secundario', '#1DC038')};
                    border: none;
                    border-radius: 6px;
                    padding: 0px;
                }}
                QPushButton:hover {{
                    background-color: {get_theme_token('acento_primario', '#B9E640')};
                }}
            """)
        else:
            self.btn_upscale.setIcon(get_colored_svg_icon("zoom_in.svg", "#6c7086", size=18))
            self.btn_upscale.setToolTip(self.tr("Reescalar con IA"))
            self.btn_upscale.setStyleSheet(f"""
                QPushButton {{
                    min-width: 30px; max-width: 30px;
                    min-height: 30px; max-height: 30px;
                    background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                    border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                    border-radius: 6px;
                    padding: 0px;
                }}
                QPushButton:hover {{
                    background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')};
                }}
            """)

    def _on_canvas_selection_changed(self, option: str, is_valid: bool):
        self.selected_canvas_option = option if is_valid else None

    def _on_canvas_state_changed(self, state: dict):
        # El popover (combo/campos) volvió a ser la fuente de verdad para el
        # archivo actual -- si tenía un override manual guardado (arrastre de
        # handle/imagen, Fase 3), se descarta: elegir un preset o tocar un campo
        # es "quiero esto en vez de mi ajuste a mano", no "sumale esto a mi
        # ajuste a mano". Sin este descarte, _build_source_overrides seguía
        # aplicando el override viejo al convertir aunque el editor mostrara en
        # pantalla el preset nuevo (bug reportado: "salió con el ajuste de antes
        # sumando las opciones nuevas").
        if self._current_filepath:
            self._canvas_overrides.pop(self._current_filepath, None)
        viewer = self.preview.zoom_viewer
        viewer.apply_canvas_state(
            state["canvas_rect"], state["mode"], state["resizable"],
            state["image_pos"], state["image_scale"],
        )

    def _snapshot_layers_for(self, filepath: str | None):
        """Guarda las formas/trazos (capas no-"image") que tenga ACTUALMENTE el
        visor bajo la clave `filepath` -- usado tanto al cambiar de selección
        (_on_file_selected) como al exportar sin haber cambiado de fila
        (_on_convert_clicked), mismo criterio en los dos casos."""
        if not filepath:
            return
        non_base = [l for l in self.layer_stack.layers if l.kind != "image"]
        if non_base:
            self._layer_snapshots[filepath] = non_base
        elif filepath in self._layer_snapshots:
            del self._layer_snapshots[filepath]

    def _on_canvas_edited(self):
        """El usuario terminó de arrastrar un handle/la imagen del Canvas -- a
        diferencia de elegir un preset del popover (eso sigue siendo de lote,
        Fase 2), esto queda guardado solo para el archivo actualmente abierto."""
        if not self._current_filepath:
            return
        state = self.preview.zoom_viewer.get_canvas_state()
        if state is not None:
            self._canvas_overrides[self._current_filepath] = state

    def _on_tool_toggled(self, key: str, checked: bool):
        """Maneja los 6 botones de herramienta (Seleccionar/Rectángulo/Elipse/Línea/
        Pincel/Canvas) -- son mutuamente excluyentes por el QButtonGroup, así que
        elegir cualquiera es solo "cambiar de herramienta", sin ningún concepto de
        "modo" aparte que activar/desactivar."""
        if not checked:
            return
        self._style_tool_buttons()
        # Guard: el grupo fija "select" como estado inicial durante _build_ui(),
        # antes de que self.preview/self.layers_panel existan.
        if not hasattr(self, "preview") or not hasattr(self, "layers_panel"):
            return
        viewer = self.preview.zoom_viewer
        if key == "canvas":
            viewer.set_interaction_mode("canvas_edit")
        else:
            viewer.set_interaction_mode("layers_draw")
            viewer.set_active_tool(key)
            self.layers_panel.set_active_tool_ui(key)

    def _current_tool_key(self) -> str:
        for key, btn in self._tool_buttons.items():
            if btn.isChecked():
                return key
        return "select"

    def _reset_to_select_tool(self):
        """Conectado a Reescalar/Eliminar Fondo -- abrir esos popovers te devuelve a
        Seleccionar (sea cual sea la herramienta que tuvieras, incluido Canvas), para
        que un clic mientras mirás ese popover no dibuje/redimensione nada solo."""
        if not self._tool_buttons["select"].isChecked():
            self._tool_buttons["select"].setChecked(True)

    def _style_tool_buttons(self):
        accent = get_theme_token('acento_primario', '#B9E640')
        bg = get_theme_token('fondo_elemento', '#2d2d2d')
        border = get_theme_token('borde_normal', '#2d2d2d')
        for key, btn in self._tool_buttons.items():
            icon_name = self._TOOL_ICONS[key]
            if btn.isChecked():
                btn.setIcon(get_colored_svg_icon(icon_name, "#000000", size=18))
                btn.setStyleSheet(f"""
                    QPushButton {{
                        min-width: 32px; max-width: 32px;
                        min-height: 32px; max-height: 32px;
                        background-color: {accent};
                        border: none;
                        border-radius: 6px;
                        padding: 0px;
                    }}
                """)
            else:
                btn.setIcon(get_colored_svg_icon(icon_name, "#6c7086", size=18))
                btn.setStyleSheet(f"""
                    QPushButton {{
                        min-width: 30px; max-width: 30px;
                        min-height: 30px; max-height: 30px;
                        background-color: {bg};
                        border: 1px solid {border};
                        border-radius: 6px;
                        padding: 0px;
                    }}
                    QPushButton:hover {{ background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')}; }}
                """)

    def _on_canvas_popover_opened(self):
        """Clic derecho en Canvas -- abre el menú de opciones (Ajuste/Margen/
        Posición/Overflow); si Canvas no era la herramienta activa, la selecciona
        también, para ver el efecto de lo que se configura. Cerrar el menú NO cambia
        de herramienta -- eso lo maneja solo elegir otro botón del grupo."""
        if not self.btn_canvas.isChecked():
            self.btn_canvas.setChecked(True)
        self.canvas_popover_content.sync()

    def _on_layers_panel_toggled(self, checked: bool):
        """Muestra/oculta el panel flotante de Capas -- independiente de qué
        herramienta esté activa (igual que el panel de Capas de Photoshop)."""
        self._style_layers_panel_button(checked)
        if checked:
            self.layers_floating_panel.show_panel()
        else:
            self.layers_floating_panel.hide_panel()

    def _style_layers_panel_button(self, checked: bool):
        icon = "view_list.svg" if checked else "list_alt.svg"
        color = get_theme_token('acento_primario', '#B9E640') if checked else "#6c7086"
        self.btn_layers_panel.setIcon(get_colored_svg_icon(icon, color, size=18))
        border = get_theme_token('acento_primario', '#B9E640') if checked else get_theme_token('borde_normal', '#2d2d2d')
        self.btn_layers_panel.setStyleSheet(f"""
            QPushButton {{
                min-width: 30px; max-width: 30px;
                min-height: 30px; max-height: 30px;
                background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')};
            }}
        """)

    # ------------------------------------------------------------------
    # Puente LayerStack <-> LayersPanel <-> ZoomableImageViewer
    # ------------------------------------------------------------------
    def _refresh_layers_panel(self):
        self.layers_panel.rebuild_rows(self.layer_stack.layers)

    def _find_layer(self, layer_id: int) -> Layer | None:
        return next((l for l in self.layer_stack.layers if l.id == layer_id), None)

    def _on_layers_draw_style_changed(self, fill, stroke, width: int):
        self.preview.zoom_viewer.set_draw_style(fill, stroke, width)

    def _on_layers_brush_style_changed(self, color, size: int):
        self.preview.zoom_viewer.set_brush_style(color, size)

    def _on_shape_created(self, item, kind: str):
        label_map = {"rect": self.tr("Rectángulo"), "ellipse": self.tr("Elipse"), "line": self.tr("Línea")}
        n = sum(1 for l in self.layer_stack.layers if l.kind == "shape") + 1
        name = f"{label_map.get(kind, kind.title())} {n}"
        self.layer_stack.add_layer(Layer(name, "shape", item))

    def _on_raster_layer_created(self, item):
        n = sum(1 for l in self.layer_stack.layers if l.kind == "raster") + 1
        self.layer_stack.add_layer(Layer(f"{self.tr('Pincel')} {n}", "raster", item))

    def _on_shape_selected(self, item):
        layer = self.layer_stack.layer_for_item(item) if item is not None else None
        self.layers_panel.select_row(layer.id if layer else None)

    def _on_layer_row_selected(self, layer_id: int):
        layer = self._find_layer(layer_id)
        if layer is None:
            return
        self.layer_stack.set_active(layer)
        self.layers_panel.select_row(layer_id)
        viewer = self.preview.zoom_viewer
        if layer.kind == "raster":
            viewer.set_active_raster_layer(layer.graphics_item)
        if layer.kind == "shape":
            viewer.select_item(layer.graphics_item)

    def _on_layer_visibility_toggled(self, layer_id: int, visible: bool):
        layer = self._find_layer(layer_id)
        if layer is not None:
            layer.set_visible(visible)

    def _on_layer_opacity_changed(self, layer_id: int, percent: int):
        layer = self._find_layer(layer_id)
        if layer is not None:
            layer.set_opacity(percent / 100.0)

    def _on_layer_move_up(self, layer_id: int):
        layer = self._find_layer(layer_id)
        if layer is not None:
            self.layer_stack.move_up(layer)

    def _on_layer_move_down(self, layer_id: int):
        layer = self._find_layer(layer_id)
        if layer is not None:
            self.layer_stack.move_down(layer)

    def _on_add_background_requested(self):
        viewer = self.preview.zoom_viewer
        size = viewer.image_size()
        if size is None:
            return
        dialog = BackgroundDialog(size.width(), size.height(), self)
        if not dialog.exec():
            return
        item = dialog.build_layer_item()
        viewer.add_scene_item(item)
        n = sum(1 for l in self.layer_stack.layers if l.kind == "fill") + 1
        # index=0: un Fondo siempre va al fondo del stack, debajo de todo lo demás.
        self.layer_stack.add_layer(Layer(f"{self.tr('Fondo')} {n}", "fill", item), index=0)

    def _on_layer_delete(self, layer_id: int):
        layer = self._find_layer(layer_id)
        if layer is None:
            return
        viewer = self.preview.zoom_viewer
        if viewer.selected_item() is layer.graphics_item:
            viewer.select_item(None)
        if viewer.active_raster_layer() is layer.graphics_item:
            viewer.set_active_raster_layer(None)
        self.layer_stack.remove_layer(layer)

    def eventFilter(self, obj, event):
        """Cierra cualquier popover de la franja superior (Reescalar IA, Eliminar
        Fondo IA, ...) al clickear afuera de su botón y de su contenido -- mismo
        patrón que quick_mode_view.py para su popover de "Recodificar" (respeta
        popups internos, ej. el desplegable de los combos)."""
        if event.type() == QEvent.MouseButtonPress and QApplication.activePopupWidget() is None:
            pos = event.globalPos()
            for btn in getattr(self, "_popover_buttons", []):
                if not btn.is_open():
                    continue
                btn_rect, content_rect = btn.global_rects()
                if not btn_rect.contains(pos) and not content_rect.contains(pos):
                    btn.set_open(False)
        return super().eventFilter(obj, event)

    def _on_file_selected(self, filepath: str):
        old_filepath = self._current_filepath
        self._current_filepath = filepath
        self._refresh_title_and_copy_button(filepath)

        # Fase 3 -- antes de tocar nada, guardar las formas/trazos (capas no-
        # "image") que tuviera el archivo que se estaba mirando hasta ahora.
        # El Canvas manual ya quedó guardado al vuelo en _on_canvas_edited, no
        # hace falta repetirlo acá.
        self._snapshot_layers_for(old_filepath)
        self.layer_stack.clear()

        # A diferencia del diseño anterior (y de DowP1), un archivo ya convertido
        # NO pasa a mostrar la comparación antes/después de forma permanente --
        # el editor (con las formas/pincel/Canvas del usuario) sigue siendo la
        # vista por defecto, como en Photoshop: convertís y podés seguir editando.
        # Comparar es una acción explícita (ver btn_compare_result/
        # _on_compare_toggled)... EXCEPTO si el resultado de este archivo incluyó
        # IA (reescalado por ahora, ver _files_with_ai_edit/
        # _on_convert_file_completed -- a futuro también Eliminar Fondo, cuando
        # tenga su ejecución conectada): ahí Comparar arranca activado, porque ver
        # el antes/después es lo primero que se quiere confirmar de un resultado
        # generado por IA.
        self._show_editable_view(filepath)
        auto_compare = (
            bool(filepath)
            and bool(self.image_queue.get_output_path(filepath))
            and self._files_with_ai_edit.get(filepath, False)
        )
        self.btn_compare_result.blockSignals(True)
        self.btn_compare_result.setChecked(auto_compare)
        self.btn_compare_result.blockSignals(False)
        if auto_compare:
            self._show_compare_view(filepath)

    def _show_editable_view(self, filepath: str):
        """Carga el editor normal (imagen + formas/pincel/Canvas restaurados) para
        `filepath` -- llamado desde _on_file_selected y también al destildar
        Comparar (_on_compare_toggled) para volver desde la vista de comparación
        sin perder nada de lo ya restaurado."""
        if not filepath:
            self.preview.show_default_state()
            return

        self.preview.show_image_preview(filepath)
        viewer = self.preview.zoom_viewer
        # show_image_preview() vuelve a cargar el pixmap del visor -- eso ya deja
        # el canvas inicializado a su tamaño nativo (como borde de referencia) y
        # el modo en "pan" por su cuenta (ver ZoomableImageViewer._reset_edit_state);
        # acá solo hace falta reaplicar la herramienta que estuviera activa.
        current_tool = self._current_tool_key()
        if current_tool == "canvas":
            viewer.set_interaction_mode("canvas_edit")
        else:
            viewer.set_interaction_mode("layers_draw")
            viewer.set_active_tool(current_tool)
            self.layers_panel.set_active_tool_ui(current_tool)
        size = viewer.image_size()
        if size is not None:
            self.canvas_popover_content.set_reference_image_size(size.width(), size.height())
        # El Canvas NO se resetea a un estado fijo acá a propósito: desde que un
        # preset del menú (clic derecho) pasó a ser una configuración de LOTE (ver
        # canvas_popover_content.get_settings(), usada por Convertir para TODOS los
        # archivos), resetearlo al cambiar de fila borraba esa elección apenas se
        # miraba otro archivo. Si este archivo tiene un Canvas editado a mano
        # (_canvas_overrides, Fase 3) se reaplica tal cual; si no, se llama sync()
        # (no solo si el popover está abierto) para que el overlay se reajuste al
        # tamaño nativo de CADA archivo con el mismo preset elegido -- visualmente
        # confirma que "se aplica a todos, adaptado por archivo".
        canvas_override = self._canvas_overrides.get(filepath)
        if canvas_override is not None:
            viewer.apply_canvas_state(
                canvas_override["canvas_rect"], canvas_override["mode"],
                canvas_override["resizable"], canvas_override["image_pos"],
                canvas_override["image_scale"],
            )
        else:
            self.canvas_popover_content.sync()
        base_item = viewer.base_pixmap_item()
        if base_item is not None:
            self.layer_stack.add_layer(Layer(self.tr("Imagen Base"), "image", base_item))
        # Fase 3 -- reponer las formas/trazos que este archivo ya tenía.
        for layer in self._layer_snapshots.get(filepath, []):
            viewer.add_scene_item(layer.graphics_item)
            self.layer_stack.add_layer(layer)

    def _show_compare_view(self, filepath: str):
        """Muestra la comparación antes/después de `filepath` -- usado tanto por el
        toggle manual (_on_compare_toggled) como por la activación automática
        cuando el trabajo incluyó IA (ver _files_with_ai_edit)."""
        output_path = self.image_queue.get_output_path(filepath)
        if not output_path:
            return
        before_pix, after_pix = self._compare_cache.get(filepath)
        self.preview.show_compare_preview(filepath, output_path, before_pix, after_pix)
        if before_pix is None or after_pix is None:
            # Cache miss -- preview_panel ya cargó de disco/re-renderizó; se
            # guardan los pixmaps recién usados para la próxima vez.
            cv = self.preview.compare_viewer
            self._compare_cache.put(filepath, cv.before_pixmap(), cv.after_pixmap())

    def _on_compare_toggled(self, checked: bool):
        """Comparar (título/botones, ver _build_ui) -- vista bajo demanda, no
        permanente: destildar vuelve al editor tal cual estaba (_show_editable_view
        reaplica las formas/Canvas restauradas, no se pierde nada)."""
        filepath = self._current_filepath
        if not filepath:
            return
        if checked:
            self._show_compare_view(filepath)
        else:
            # No se recarga nada -- la escena del editor (formas/pincel/Canvas)
            # nunca se tocó mientras se mostraba Comparar (show_compare_preview()
            # solo oculta el widget, no vacía la escena), así que alcanza con
            # volver a mostrarlo tal cual estaba.
            self.preview.show_zoom_viewer_only()

    def _refresh_title_and_copy_button(self, filepath: str):
        """Título editable (default = nombre del archivo) y botones Copiar/Comparar
        (solo habilitados si ese archivo ya tiene un resultado convertido) -- se
        llama en cada cambio de selección y también al completarse una conversión
        (ver _on_convert_file_completed) para la fila que se está mirando."""
        has_file = bool(filepath)
        has_output = has_file and bool(self.image_queue.get_output_path(filepath))
        self.entry_title.setEnabled(has_file)
        self.entry_title.setText(self.image_queue.get_title(filepath) if has_file else "")
        self.btn_copy_result.setEnabled(has_output)
        self.btn_compare_result.setEnabled(has_output)

    def _on_title_edited(self):
        if self._current_filepath:
            self.image_queue.set_title(self._current_filepath, self.entry_title.text())

    def _on_copy_result_clicked(self):
        if not self._current_filepath:
            return
        output_path = self.image_queue.get_output_path(self._current_filepath)
        if not output_path:
            return
        pixmap = QPixmap(output_path)
        if not pixmap.isNull():
            QApplication.clipboard().setPixmap(pixmap)

    def _build_queue_content(self) -> QWidget:
        """Lista de imágenes (arriba) + panel "Convertir" con opciones de formato
        encapsuladas (abajo). Las acciones globales de destino/conversión viven
        en la barra inferior de la pestaña."""
        container = QFrame()
        container.setObjectName("unifiedQueuePanel")
        bg_color = get_theme_token('fondo_secundario', '#1e1e1e')
        border_color = get_theme_token('borde_normal', '#2d2d2d')
        container.setStyleSheet(f"""
            QFrame#unifiedQueuePanel {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
        """)
        
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.image_queue = ImageQueueWidget()
        layout.addWidget(self.image_queue, 1)

        # Divisor sutil entre la lista y las opciones
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background-color: {get_theme_token('borde_sutil', '#2d2d2d')}; max-height: 1px; border: none;")
        layout.addWidget(sep)

        self.convert_panel = ConvertPanel()
        self.convert_panel.validity_changed.connect(self._on_convert_validity_changed)
        layout.addWidget(self.convert_panel, 0)

        self._convert_worker = None
        self._update_convert_button_state()
        self.image_queue.queue_updated.connect(lambda _count: self._update_convert_button_state())
        return container

    def _build_output_bar(self) -> QFrame:
        """Panel inferior unificado de salida y conversión -- política de conflicto,
        ruta de destino con botones de examinar/abrir, botón de acción Convertir/Cancelar
        y barra de progreso BouncingProgressBar (mismo estilo y experiencia que
        Modo Rápido, Proceso Avanzado y Herramientas de Video)."""
        card = QFrame()
        card.setObjectName("imageToolsOutputBar")
        border_color = get_theme_token('borde_normal', '#2d2d2d')
        bg_color = get_theme_token('fondo_secundario', '#1e1e1e')
        card.setStyleSheet(f"""
            QFrame#imageToolsOutputBar {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 8, 12, 8)
        card_layout.setSpacing(6)

        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(8)

        # 1. Si existe (política de conflicto)
        lbl_conflict = QLabel(self.tr("Si existe:"))
        lbl_conflict.setObjectName("menuLabel")
        controls_row.addWidget(lbl_conflict)

        self.combo_conflict_policy = AutoPopupComboBox()
        self.combo_conflict_policy.addItem(self.tr("Sobrescribir"), "sobrescribir")
        self.combo_conflict_policy.addItem(self.tr("Conservar"), "conservar")
        self.combo_conflict_policy.addItem(self.tr("Omitir"), "omitir")
        self.combo_conflict_policy.setCurrentIndex(1)  # "Conservar" por defecto
        self.combo_conflict_policy.setFixedHeight(32)
        self.combo_conflict_policy.setToolTip(self.tr(
            "• Sobrescribir: reemplaza el archivo existente (con respaldo reversible).\n"
            "• Conservar: guarda el nuevo archivo como 'nombre (1).ext'.\n"
            "• Omitir: no convierte ese archivo."
        ))
        controls_row.addWidget(self.combo_conflict_policy)

        # 2. Ruta de destino + Examinar + Abrir
        lbl_path = QLabel(self.tr("Ruta:"))
        lbl_path.setObjectName("menuLabel")
        controls_row.addWidget(lbl_path)

        self.entry_output_folder = QLineEdit()
        self.entry_output_folder.setPlaceholderText(self.tr("Ruta de destino"))
        self.entry_output_folder.setFixedHeight(32)
        
        # Cargar ruta desde config, o usar Imágenes por defecto
        config = get_config()
        saved_path = config.get("image_tools_output_path", "")
        if not saved_path or not os.path.isdir(saved_path):
            saved_path = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
        self.entry_output_folder.setText(saved_path)
        self.entry_output_folder.editingFinished.connect(self._save_output_path)
        
        controls_row.addWidget(self.entry_output_folder, 1)

        self.btn_browse_output_folder = QPushButton()
        self.btn_browse_output_folder.setFixedSize(32, 32)
        self.btn_browse_output_folder.setCursor(Qt.PointingHandCursor)
        apply_folder_browse_button_style(self.btn_browse_output_folder, self.tr("Elegir carpeta de destino"))
        self.btn_browse_output_folder.clicked.connect(self._on_browse_output_folder)
        controls_row.addWidget(self.btn_browse_output_folder)

        self.btn_open_output_folder = QPushButton()
        self.btn_open_output_folder.setFixedSize(32, 32)
        self.btn_open_output_folder.setCursor(Qt.PointingHandCursor)
        apply_folder_open_button_style(self.btn_open_output_folder, self.tr("Abrir carpeta de destino"))
        self.btn_open_output_folder.clicked.connect(self._on_open_output_folder)
        controls_row.addWidget(self.btn_open_output_folder)

        # 3. Botones de acción: Convertir y Cancelar
        self.btn_convert = AnimatedButton(self.tr("Convertir"))
        self.btn_convert.setProperty("variant", "primary")
        self.btn_convert.setCursor(Qt.PointingHandCursor)
        self.btn_convert.setFixedHeight(32)
        self.btn_convert.setMinimumWidth(130)
        self.btn_convert.clicked.connect(self._on_convert_clicked)
        controls_row.addWidget(self.btn_convert)

        self.btn_convert_cancel = QPushButton(self.tr("Cancelar"))
        self.btn_convert_cancel.setProperty("variant", "danger")
        self.btn_convert_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_convert_cancel.setFixedHeight(32)
        self.btn_convert_cancel.setVisible(False)
        self.btn_convert_cancel.clicked.connect(self._on_convert_cancel_clicked)
        controls_row.addWidget(self.btn_convert_cancel)

        card_layout.addLayout(controls_row)

        # 4. Barra de progreso BouncingProgressBar
        self.progress_bar = BouncingProgressBar()
        self.progress_bar.setObjectName("downloadProgressBar")
        self.progress_bar.setProperty("status", "wait")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(self.tr("En espera"))
        self.progress_bar.setTextVisible(True)
        card_layout.addWidget(self.progress_bar)

        return card

    def _on_browse_output_folder(self):
        current = self.entry_output_folder.text().strip()
        start = current if os.path.isdir(current) else QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
        selected = QFileDialog.getExistingDirectory(self, self.tr("Elegir carpeta de destino"), start)
        if selected:
            self.entry_output_folder.setText(selected)
            self._save_output_path()
            
    def _save_output_path(self):
        path = self.entry_output_folder.text().strip()
        if os.path.isdir(path):
            config = get_config()
            config["image_tools_output_path"] = path
            save_config(config)

    def _on_open_output_folder(self):
        path = self.entry_output_folder.text().strip()
        if path and os.path.isdir(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ------------------------------------------------------------------
    # Convertir
    # ------------------------------------------------------------------
    def _on_convert_validity_changed(self, _is_valid: bool):
        self._update_convert_button_state()

    def _update_convert_button_state(self):
        """Habilita "Convertir" solo si la cola tiene archivos y las opciones
        actuales son válidas (ej. ICO necesita al menos un tamaño tildado, ver
        ConvertPanel.is_valid()) -- mismo criterio que validity_changed ya usa
        Herramientas de Video para su propio Convertir."""
        if not hasattr(self, "btn_convert") or self._convert_worker is not None:
            return  # una conversión en curso o UI en construcción.
        has_files = bool(self.image_queue.get_all_filepaths()) if hasattr(self, "image_queue") else False
        is_valid = self.convert_panel.is_valid() if hasattr(self, "convert_panel") else True
        self.btn_convert.setEnabled(has_files and is_valid)

    def _build_source_overrides(self, filepaths: list[str]) -> dict[str, str] | None:
        """Aplana a un PNG temporal cada archivo del lote que tenga formas/pincel
        guardados (self._layer_snapshots) o un Canvas editado a mano
        (self._canvas_overrides) -- ImageConvertWorker leerá de ahí en vez del
        archivo original para ESE archivo (ver source_overrides en
        image_convert_worker.py); el resto de la cola sigue el camino normal, sin
        pasar por acá. El pixmap base se recarga con preview.load_pixmap_for_path()
        usando el mismo tamaño disponible que usó show_image_preview() al mostrar
        cada archivo -- mismas coordenadas en las que quedaron dibujadas las formas."""
        to_flatten = [
            fp for fp in filepaths
            if self._layer_snapshots.get(fp) or fp in self._canvas_overrides
        ]
        if not to_flatten:
            return None

        avail_w = max(50, self.preview.width() - 10)
        avail_h = max(50, self.preview.height() - 10)
        self._flatten_temp_dir = tempfile.mkdtemp(prefix="dowp_canvas_flatten_")
        overrides = {}
        for fp in to_flatten:
            base_pixmap = self.preview.load_pixmap_for_path(fp, avail_w, avail_h)
            if base_pixmap is None or base_pixmap.isNull():
                continue
            canvas_state = self._canvas_overrides.get(fp)
            layers = self._layer_snapshots.get(fp, [])
            image = build_flattened_image(base_pixmap, canvas_state, layers)
            temp_path = os.path.join(self._flatten_temp_dir, f"{len(overrides)}.png")
            if image.save(temp_path, "PNG"):
                overrides[fp] = temp_path
        return overrides or None

    def _on_convert_clicked(self):
        filepaths = self.image_queue.get_all_filepaths()
        if not filepaths or self._convert_worker is not None:
            return
        settings = {
            **self.resize_popover_content.get_settings(),
            **self.upscale_popover_content.get_settings(),
            **self.canvas_popover_content.get_settings(),
            **self.convert_panel.get_settings(),
            "output_folder": self.entry_output_folder.text().strip(),
            "conflict_policy": self.combo_conflict_policy.currentData() or "conservar",
        }

        # Fase 3 -- el archivo que se está mirando en este momento puede tener
        # ediciones sin "confirmar" (nunca se cambió de fila para disparar el
        # snapshot automático de _on_file_selected); se fuerza acá para que
        # tampoco quede afuera del aplanado de abajo.
        self._snapshot_layers_for(self._current_filepath)

        titles = {fp: self.image_queue.get_title(fp) for fp in filepaths}
        source_overrides = self._build_source_overrides(filepaths)
        # Para saber, al completarse cada archivo, si ESTE lote usó IA -- ver
        # _on_convert_file_completed/_files_with_ai_edit.
        self._active_convert_settings = settings
        self._convert_worker = ImageConvertWorker(
            filepaths, settings, titles=titles, source_overrides=source_overrides, parent=self,
        )
        self._convert_worker.file_status_changed.connect(self._on_convert_file_status)
        self._convert_worker.file_completed.connect(self._on_convert_file_completed)
        self._convert_worker.finished_signal.connect(self._on_convert_finished)

        self.btn_convert.setEnabled(False)
        self.btn_convert_cancel.setVisible(True)
        self.btn_convert_cancel.setEnabled(True)
        self.progress_bar.setProperty("status", "running")
        self.progress_bar.setRange(0, len(filepaths))
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(self.tr("Convirtiendo 0/{0}...").format(len(filepaths)))
        self._convert_total = len(filepaths)
        self._convert_done = 0

        self._convert_worker.start()

    def _on_convert_cancel_clicked(self):
        if self._convert_worker is not None:
            self._convert_worker.cancel()
            self.btn_convert_cancel.setEnabled(False)
            self.progress_bar.setFormat(self.tr("Cancelando..."))

    def _on_convert_file_status(self, filepath: str, status_text: str):
        self.image_queue.update_file_status(filepath, status_text)
        self._convert_done += 1
        self.progress_bar.setValue(self._convert_done)
        self.progress_bar.setFormat(
            self.tr("Convirtiendo {0}/{1}...").format(self._convert_done, self._convert_total)
        )

    def _on_convert_file_completed(self, input_path: str, output_path: str):
        """Registra el resultado de una conversión exitosa -- a propósito NO
        interrumpe una edición en curso (como en Photoshop), EXCEPTO cuando el
        lote usó IA (reescalado por ahora -- Eliminar Fondo todavía no tiene
        ejecución conectada, ver rembg_popover.py): ahí si el usuario está
        mirando justo esta fila, Comparar se activa solo para mostrar el
        resultado de una vez. Invalida el cache de comparación por si ya había
        un resultado previo de una reconversión."""
        self.image_queue.set_output_path(input_path, output_path)
        self._compare_cache.invalidate(input_path)
        uses_ai = bool(self._active_convert_settings and self._active_convert_settings.get("upscale_enabled"))
        self._files_with_ai_edit[input_path] = uses_ai
        if input_path != self._current_filepath:
            return
        self._refresh_title_and_copy_button(input_path)
        if uses_ai:
            self.btn_compare_result.blockSignals(True)
            self.btn_compare_result.setChecked(True)
            self.btn_compare_result.blockSignals(False)
            self._show_compare_view(input_path)

    def _on_convert_finished(self, completed: int, total: int):
        if self._flatten_temp_dir is not None:
            shutil.rmtree(self._flatten_temp_dir, ignore_errors=True)
            self._flatten_temp_dir = None
        self._convert_worker = None
        self.btn_convert_cancel.setVisible(False)
        self.btn_convert_cancel.setEnabled(True)
        self.progress_bar.setValue(total)
        self.progress_bar.setProperty("status", "done")
        self.progress_bar.setFormat(self.tr("Completado: {0}/{1} archivos").format(completed, total))
        self._update_convert_button_state()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_responsive_mode()

    def minimumSizeHint(self):
        """Se sobrescribe para SIEMPRE reportar el piso "sin panel derecho acoplado"
        (mismo criterio y mismo motivo que VideoToolsTab.minimumSizeHint()): si no lo
        hiciéramos, Qt propagaría el piso "acoplado" (más ancho, por el ancho fijo de
        right_panel) como mínimo de toda la ventana, y un resize() de un solo salto
        grande->chico quedaría atascado sin llegar a disparar el colapso a overlay.
        TOOLBAR_WIDTH sí se suma siempre -- a diferencia de right_panel, la barra de
        herramientas nunca colapsa/sale del layout."""
        base = super().minimumSizeHint()
        if not hasattr(self, "preview"):
            return base
        width = self.TOOLBAR_WIDTH + self.preview.minimumSizeHint().width()
        return QSize(width, base.height())

    def _update_responsive_mode(self):
        if not hasattr(self, "right_panel"):
            return
        threshold = max(self.COLLAPSE_THRESHOLD_WIDTH, self.TOOLBAR_WIDTH + self.RIGHT_DOCKED_WIDTH + self.PREVIEW_MIN_WIDTH)
        want_docked = self.width() >= threshold
        if want_docked != self.right_panel.is_docked():
            self.right_panel.set_mode(docked=want_docked)
        self.right_panel.sync_overlay_geometry()
        for btn in getattr(self, "_popover_buttons", []):
            if btn.is_open():
                btn.reposition()
        if hasattr(self, "layers_floating_panel") and self.layers_floating_panel.isVisible():
            self.layers_floating_panel.clamp_to_host()
