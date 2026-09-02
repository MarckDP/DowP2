# src/gui/tabs/image_tools/image_tools_view.py
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea, QApplication,
    QPushButton, QButtonGroup,
)
from PySide6.QtCore import Qt, QSize, QEvent

from gui.styles import get_theme_token
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
from gui.widgets.collapsible_panel import CollapsiblePanel
from gui.widgets.floating_panel import FloatingPanel
from gui.widgets.popover_button import PopoverTriggerButton
from gui.tabs.editing_media.preview_panel import PreviewContainerWidget
from gui.tabs.image_tools.image_queue_widget import ImageQueueWidget
from gui.tabs.image_tools.upscale_popover import UpscalePopoverContent
from gui.tabs.image_tools.rembg_popover import RembgPopoverContent
from gui.tabs.image_tools.canvas_popover import CanvasPopoverContent
from gui.tabs.image_tools.layers.layer_model import Layer, LayerStack
from gui.tabs.image_tools.layers.layers_panel import LayersPanel
from gui.tabs.image_tools.layers.background_dialog import BackgroundDialog


class ImageToolsTab(QWidget):
    """Editor de Imagen.

    Layout tipo Herramientas de Video: franja superior de opciones (arriba, siempre
    visible), y debajo una fila con el panel izquierdo (lista de medios + controles,
    ancho fijo ~35%) y la vista previa a la derecha (el resto del espacio). El panel
    izquierdo colapsa a un overlay flotante en ventanas angostas -- mismo mecanismo
    ya usado en VideoToolsTab (ver gui/widgets/collapsible_panel.py), sin combinarlo
    con un splitter arrastrable: ancho fijo mientras está acoplado, por decisión
    explícita (mismo criterio que el panel de Opciones en Herramientas de Video)."""

    LEFT_DOCKED_WIDTH = 380
    LEFT_OVERLAY_MAX_WIDTH = 420
    # Ancho "cómodo" mínimo del preview antes de forzar el colapso a overlay -- no su
    # mínimo técnico absoluto, mismo criterio que PREVIEW_MIN_WIDTH en VideoToolsTab.
    PREVIEW_MIN_WIDTH = 480
    COLLAPSE_THRESHOLD_WIDTH = 760

    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # ── Franja superior de opciones: un botón chico por función, cada uno
        # despliega su propio panel flotante (no empuja nada) -- ver popover_button.py.
        # El resto de los botones (Eliminar Fondo IA, Canvas, etc.) se agregan en
        # pasos aparte; este es el primero, de prueba.
        self.top_strip = QFrame()
        self.top_strip.setObjectName("imageToolsTopStrip")
        self.top_strip.setFixedHeight(46)
        top_layout = QHBoxLayout(self.top_strip)
        top_layout.setContentsMargins(12, 0, 12, 0)
        top_layout.setSpacing(6)

        self._popover_buttons = []

        self.selected_upscale_engine = None
        self.selected_upscale_model = None
        self.upscale_popover_content = UpscalePopoverContent()
        self.upscale_popover_content.selection_changed.connect(self._on_upscale_selection_changed)

        self.btn_upscale = PopoverTriggerButton(host=self, content=self.upscale_popover_content)
        self.btn_upscale.setFixedSize(28, 28)
        self.btn_upscale.setIconSize(QSize(16, 16))
        self.btn_upscale.setCursor(Qt.PointingHandCursor)
        self._style_upscale_button(is_valid=False)
        top_layout.addWidget(self.btn_upscale)
        self._popover_buttons.append(self.btn_upscale)

        self.selected_rembg_family = None
        self.selected_rembg_model = None
        self.rembg_popover_content = RembgPopoverContent()
        self.rembg_popover_content.selection_changed.connect(self._on_rembg_selection_changed)

        self.btn_rembg = PopoverTriggerButton(host=self, content=self.rembg_popover_content)
        self.btn_rembg.setFixedSize(28, 28)
        self.btn_rembg.setIconSize(QSize(16, 16))
        self.btn_rembg.setCursor(Qt.PointingHandCursor)
        self._style_rembg_button(is_valid=False)
        top_layout.addWidget(self.btn_rembg)
        self._popover_buttons.append(self.btn_rembg)

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
        # qué herramienta tenés elegida. Arranca chequeado recién después de crear
        # self.right_panel más abajo (no existe todavía en este punto).
        self.btn_layers_panel = QPushButton()
        self.btn_layers_panel.setCheckable(True)
        self.btn_layers_panel.setFixedSize(28, 28)
        self.btn_layers_panel.setIconSize(QSize(16, 16))
        self.btn_layers_panel.setCursor(Qt.PointingHandCursor)
        self.btn_layers_panel.setToolTip(self.tr("Mostrar/ocultar panel de Capas"))
        self.btn_layers_panel.toggled.connect(self._on_layers_panel_toggled)
        self._style_layers_panel_button(False)
        top_layout.addWidget(self.btn_layers_panel)

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
            btn.setFixedSize(28, 28)
            btn.setIconSize(QSize(16, 16))
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

        top_lbl = QLabel(self.tr("Más opciones próximamente"))
        top_lbl.setStyleSheet("color: #888888; font-size: 12px;")
        top_layout.addWidget(top_lbl)
        top_layout.addStretch()
        main_layout.addWidget(self.top_strip)

        QApplication.instance().installEventFilter(self)

        # ── Fila de cuerpo: panel izquierdo colapsable + preview ──────────────────
        self.body_row = QWidget()
        body_layout = QHBoxLayout(self.body_row)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)

        self.left_content = self._build_left_content()
        self.left_panel = CollapsiblePanel(
            self.left_content, edge="left",
            docked_size=self.LEFT_DOCKED_WIDTH,
            overlay_max_width=self.LEFT_OVERLAY_MAX_WIDTH,
        )
        body_layout.addWidget(self.left_panel, 0)

        self.preview = PreviewContainerWidget()
        self.preview.set_fill_available_space(True)
        self.preview.set_zoomable(True)
        body_layout.addWidget(self.preview, 1)

        # Panel "Capas": ventana flotante arrastrable (estilo panel de Photoshop), no
        # acoplada a ningún layout -- flota libremente sobre self.body_row, la mueve
        # el usuario agarrando su barra de título (ver gui/widgets/floating_panel.py).
        self.right_panel = FloatingPanel(self.tr("Capas"), self.layers_panel, host=self.body_row, width=260)
        self.right_panel.closed.connect(lambda: self.btn_layers_panel.setChecked(False))
        # Visible por defecto -- recién ahora existe self.right_panel, así que el
        # toggle (creado más arriba) se deja en False hasta este punto para no
        # dispararse contra un panel que todavía no existía.
        self.btn_layers_panel.setChecked(True)

        # Puente popover <-> visor para la edición visual de Canvas (ver
        # canvas_popover.py y ZoomableImageViewer.apply_canvas_state/margin_dragged/
        # size_dragged): el popover empuja el estado calculado, el visor devuelve los
        # valores en vivo mientras se arrastra un handle.
        viewer = self.preview.zoom_viewer
        self.canvas_popover_content.state_changed.connect(self._on_canvas_state_changed)
        viewer.margin_dragged.connect(self.canvas_popover_content.on_margin_dragged)
        viewer.size_dragged.connect(self.canvas_popover_content.on_size_dragged)

        # Puente panel de Capas <-> visor: figuras/trazos creados en el visor se
        # registran como capas; seleccionar en el visor resalta la fila correspondiente.
        viewer.shape_created.connect(self._on_shape_created)
        viewer.raster_layer_created.connect(self._on_raster_layer_created)
        viewer.shape_selected.connect(self._on_shape_selected)

        self.left_panel.configure_container(self.body_row, body_layout, 0, dock_stretch=0)

        self.image_queue.file_selected.connect(self._on_file_selected)

        main_layout.addWidget(self.body_row, 1)

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

    def _style_rembg_button(self, is_valid: bool):
        """Mismo criterio visual que _style_upscale_button -- ver ese método."""
        if is_valid:
            self.btn_rembg.setIcon(get_colored_svg_icon("content_cut.svg", "#000000", size=16))
            self.btn_rembg.setToolTip(self.tr("Eliminar Fondo (IA) — configuración lista"))
            self.btn_rembg.setStyleSheet(f"""
                QPushButton {{
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
            self.btn_rembg.setIcon(get_colored_svg_icon("content_cut.svg", "#6c7086", size=16))
            self.btn_rembg.setToolTip(self.tr("Eliminar Fondo (IA)"))
            self.btn_rembg.setStyleSheet(f"""
                QPushButton {{
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
            self.btn_upscale.setIcon(get_colored_svg_icon("zoom_in.svg", "#000000", size=16))
            self.btn_upscale.setToolTip(self.tr("Reescalar con IA — configuración lista"))
            self.btn_upscale.setStyleSheet(f"""
                QPushButton {{
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
            self.btn_upscale.setIcon(get_colored_svg_icon("zoom_in.svg", "#6c7086", size=16))
            self.btn_upscale.setToolTip(self.tr("Reescalar con IA"))
            self.btn_upscale.setStyleSheet(f"""
                QPushButton {{
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
        viewer = self.preview.zoom_viewer
        viewer.apply_canvas_state(
            state["canvas_rect"], state["mode"], state["resizable"],
            state["image_pos"], state["image_scale"],
        )

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
                btn.setIcon(get_colored_svg_icon(icon_name, "#000000", size=16))
                btn.setStyleSheet(f"""
                    QPushButton {{ background-color: {accent}; border: none; border-radius: 6px; padding: 0px; }}
                """)
            else:
                btn.setIcon(get_colored_svg_icon(icon_name, "#6c7086", size=16))
                btn.setStyleSheet(f"""
                    QPushButton {{ background-color: {bg}; border: 1px solid {border}; border-radius: 6px; padding: 0px; }}
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
            self.right_panel.show_panel()
        else:
            self.right_panel.hide_panel()

    def _style_layers_panel_button(self, checked: bool):
        icon = "view_list.svg" if checked else "list_alt.svg"
        color = get_theme_token('acento_primario', '#B9E640') if checked else "#6c7086"
        self.btn_layers_panel.setIcon(get_colored_svg_icon(icon, color, size=16))
        border = get_theme_token('acento_primario', '#B9E640') if checked else get_theme_token('borde_normal', '#2d2d2d')
        self.btn_layers_panel.setStyleSheet(f"""
            QPushButton {{
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
        # El estado de Canvas (tamaño/margen/posición) y las capas dibujadas eran
        # relativos a la imagen anterior -- resetear evita un overlay/capas con
        # medidas o contenido que ya no tienen sentido para el archivo nuevo.
        self.canvas_popover_content.reset_to_none()
        self.layer_stack.clear()
        if filepath:
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
            if self.btn_canvas.is_open():
                self.canvas_popover_content.sync()
            base_item = viewer.base_pixmap_item()
            if base_item is not None:
                self.layer_stack.add_layer(Layer(self.tr("Imagen Base"), "image", base_item))
        else:
            self.preview.show_default_state()

    def _build_left_content(self) -> QWidget:
        """Lista de imágenes (arriba, copiada de MediaQueueWidget/Herramientas de
        Video) + controles (abajo) -- los controles quedan como placeholder por ahora,
        se conectan a la lógica real de conversión/IA en un paso aparte."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.image_queue = ImageQueueWidget()
        layout.addWidget(self.image_queue, 1)

        controls_scroll = QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setFrameShape(QScrollArea.NoFrame)

        controls_placeholder = QWidget()
        controls_layout = QVBoxLayout(controls_placeholder)
        controls_lbl = QLabel(self.tr("Controles (Próximamente)"))
        controls_lbl.setAlignment(Qt.AlignCenter)
        controls_lbl.setStyleSheet("color: #888888; font-size: 12px; padding: 20px;")
        controls_layout.addWidget(controls_lbl)
        controls_scroll.setWidget(controls_placeholder)

        layout.addWidget(controls_scroll, 1)
        return container

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_responsive_mode()

    def minimumSizeHint(self):
        """Se sobrescribe para SIEMPRE reportar el piso "sin panel izquierdo acoplado"
        (mismo criterio y mismo motivo que VideoToolsTab.minimumSizeHint()): si no lo
        hiciéramos, Qt propagaría el piso "acoplado" (más ancho, por el ancho fijo de
        left_panel) como mínimo de toda la ventana, y un resize() de un solo salto
        grande->chico quedaría atascado sin llegar a disparar el colapso a overlay."""
        base = super().minimumSizeHint()
        if not hasattr(self, "preview"):
            return base
        width = self.preview.minimumSizeHint().width()
        return QSize(width, base.height())

    def _update_responsive_mode(self):
        if not hasattr(self, "left_panel"):
            return
        threshold = max(self.COLLAPSE_THRESHOLD_WIDTH, self.LEFT_DOCKED_WIDTH + self.PREVIEW_MIN_WIDTH)
        want_docked = self.width() >= threshold
        if want_docked != self.left_panel.is_docked():
            self.left_panel.set_mode(docked=want_docked)
        self.left_panel.sync_overlay_geometry()
        for btn in getattr(self, "_popover_buttons", []):
            if btn.is_open():
                btn.reposition()
        if hasattr(self, "right_panel") and self.right_panel.isVisible():
            self.right_panel.clamp_to_host()
