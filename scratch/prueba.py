# scratch/prueba.py
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QComboBox, QGroupBox, QSlider, QStyledItemDelegate,
    QPushButton, QCheckBox, QRadioButton, QTabBar, QStyleOptionViewItem,
    QStyle
)
from PySide6.QtCore import Qt, QObject, QEvent, QRect, QSize
from PySide6.QtGui import QPainter, QColor, QPixmap, QPalette
from PySide6.QtSvg import QSvgRenderer

from gui.styles import load_stylesheet, create_colored_circle_icon, update_label_combobox_style, get_theme_token


# ─── 1. Delegado con Checkmark Verde DowP y Resaltado Contrastado Activo ───
class CheckmarkComboDelegate(QStyledItemDelegate):
    """Dibuja el elemento del combo asegurando:
    1. Resaltado de fondo suave y texto blanco brillante en la opción activa (incluso sin pasar el mouse).
    2. Icono SVG 'check_small.svg' en verde lima característico de DowP (#B9E640) a la derecha de la opción seleccionada.
    3. Truncado inteligente con '...' que nunca solapa el checkmark."""

    _cached_check_pixmap = None

    def __init__(self, combo: QComboBox, parent=None):
        super().__init__(parent or combo)
        self._combo = combo
        if CheckmarkComboDelegate._cached_check_pixmap is None:
            CheckmarkComboDelegate._cached_check_pixmap = self._create_check_pixmap()

    @staticmethod
    def _create_check_pixmap():
        svg_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src', 'assets', 'icons', 'svg', 'check_small.svg'))
        if not os.path.exists(svg_path):
            return None
        # Renderizado en alta resolución (36x36) para nitidez vectorial perfecta
        size = 36
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        renderer = QSvgRenderer(svg_path)
        renderer.render(painter)
        
        # Colorear en verde lima icónico de DowP (#B9E640)
        dowp_green = get_theme_token("acento_primario", "#B9E640")
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor(dowp_green))
        painter.end()
        return pixmap

    def sizeHint(self, option, index):
        """Calcula el ancho necesario para el texto completo + icono + checkmark."""
        hint = super().sizeHint(option, index)
        text = index.data(Qt.DisplayRole) or ""
        fm = option.fontMetrics
        text_w = fm.horizontalAdvance(text)
        
        # Padding izquierdo (12) + icono opcional (22) + texto + espacio checkmark (36) + padding derecho (12)
        total_w = text_w + 50
        icon = index.data(Qt.DecorationRole)
        if icon and not icon.isNull():
            total_w += 24
        return QSize(max(hint.width(), total_w), max(hint.height(), 26))

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        is_current = (index.row() == self._combo.currentIndex())
        is_hovered = bool(opt.state & QStyle.State_Selected)

        raw_text = opt.text
        opt.text = ""  # Vaciar texto para controlar el pintado de fondo

        widget = option.widget
        style = widget.style() if widget else QApplication.style()

        # 1. Dibujado de Fondo:
        if is_hovered:
            # Hover interactivo del mouse (estilo QSS)
            style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)
        elif is_current:
            # Opción activa: fondo contrastado sutil redondeado sin necesidad de tener el mouse encima
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing)
            bg_rect = opt.rect.adjusted(2, 1, -2, -1)
            painter.setBrush(QColor(255, 255, 255, 22))  # Fondo gris translúcido suave
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(bg_rect, 4, 4)
            painter.restore()
        else:
            style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)

        # 2. Dibujar icono del item si tiene (ej. etiquetas de colores)
        left_offset = 10
        if not opt.icon.isNull():
            icon_size = opt.decorationSize
            icon_rect = QRect(
                opt.rect.left() + left_offset,
                opt.rect.top() + (opt.rect.height() - icon_size.height()) // 2,
                icon_size.width(),
                icon_size.height()
            )
            opt.icon.paint(painter, icon_rect, Qt.AlignCenter)
            left_offset += icon_size.width() + 8

        # 3. Dibujar el texto completo con elipsis si el espacio no alcanza
        check_reserved_space = 36
        avail_width = max(10, opt.rect.width() - left_offset - check_reserved_space)
        elided_text = opt.fontMetrics.elidedText(raw_text, Qt.ElideRight, avail_width)

        text_rect = QRect(
            opt.rect.left() + left_offset,
            opt.rect.top(),
            avail_width,
            opt.rect.height()
        )

        painter.save()
        painter.setFont(opt.font)
        
        # Color del texto según estado:
        if is_hovered:
            text_color = opt.palette.color(QPalette.Normal, QPalette.HighlightedText)
            if text_color.lightness() < 40:
                text_color = QColor("#ffffff")
        elif is_current:
            text_color = QColor("#ffffff")  # Blanco puro brillante para la opción seleccionada
        else:
            text_color = QColor("#c5c5c5")  # Gris claro estándar para las demás opciones

        painter.setPen(text_color)
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, elided_text)
        painter.restore()

        # 4. Si este elemento es el actualmente seleccionado, dibujar el checkmark
        if is_current and self._cached_check_pixmap:
            painter.save()
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.setRenderHint(QPainter.Antialiasing)

            icon_display_size = 18
            margin_right = 10
            x = option.rect.right() - margin_right - icon_display_size
            y = option.rect.top() + (option.rect.height() - icon_display_size) // 2

            painter.drawPixmap(x, y, icon_display_size, icon_display_size, self._cached_check_pixmap)
            painter.restore()


# ─── 2. AutoPopupComboBox Mejorado para Checkmarks ───────────
class TestAutoPopupComboBox(QComboBox):
    """QComboBox cuyo popup siempre se abre con el ancho exacto de la opción más larga
    + el espacio del checkmark para que NUNCA se recorte el texto."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeAdjustPolicy(QComboBox.AdjustToContents)

    def _widest_item_text_width(self) -> int:
        fm = self.fontMetrics()
        max_width = 0
        has_icons = False
        for i in range(self.count()):
            text = self.itemText(i)
            w = fm.horizontalAdvance(text)
            if not self.itemIcon(i).isNull():
                has_icons = True
            if w > max_width:
                max_width = w

        # Margen para padding izquierdo (14), espacio de checkmark derecho (36) y scrollbar
        extra = 58
        if has_icons:
            extra += 24
        if self.count() > self.maxVisibleItems():
            extra += 16
        return max(self.width(), max_width + extra)

    def showPopup(self):
        super().showPopup()
        container = self.view().window()
        if container and self.count() > 0:
            popup_w = self._widest_item_text_width()
            rect = container.geometry()
            container.setGeometry(rect.x(), rect.y(), popup_w, rect.height())


# ─── 3. Corrección de Franjas y Bordes Nativos de Windows ─────
class _ComboPopupMaskFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            obj.setMask(obj.rect())
        return False


class HandCursorInstaller(QObject):
    _TARGET_TYPES = (QPushButton, QCheckBox, QRadioButton, QComboBox, QTabBar)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mask_filter = _ComboPopupMaskFilter(self)

    def _setup_combo(self, combo: QComboBox):
        if not isinstance(combo.itemDelegate(), CheckmarkComboDelegate):
            combo.setItemDelegate(CheckmarkComboDelegate(combo))
        if combo.view() and combo.view().window():
            container = combo.view().window()
            container.setAttribute(Qt.WA_TranslucentBackground, True)
            container.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
            container.installEventFilter(self._mask_filter)

    def eventFilter(self, obj, event):
        ev_type = event.type()
        if ev_type == QEvent.Type.ChildAdded:
            child = event.child()
            if isinstance(child, QComboBox):
                self._setup_combo(child)
            if isinstance(child, self._TARGET_TYPES):
                child.setCursor(Qt.PointingHandCursor)
        elif ev_type in (QEvent.Type.Show, QEvent.Type.Polish):
            if isinstance(obj, QComboBox):
                self._setup_combo(obj)
        return False


# ─── 4. Aplicación de Prueba ─────────────────────────────────
app = QApplication(sys.argv)
app.setStyle("Fusion")
app.installEventFilter(HandCursorInstaller(app))

win = QMainWindow()
win.setWindowTitle("Comparador de ComboBox: Con Estilo DowP (SVG Checkmark Verde) vs Nativo Fusion")
win.resize(1100, 750)

central_widget = QWidget()
root_layout = QVBoxLayout(central_widget)
root_layout.setContentsMargins(15, 15, 15, 15)
root_layout.setSpacing(10)

# Barra superior con control de ancho interactivo
ctrl_bar = QHBoxLayout()
lbl_slider = QLabel("<b>Ajustar Ancho de Prueba en Vivo (Slider):</b>")
slider_w = QSlider(Qt.Horizontal)
slider_w.setRange(100, 450)
slider_w.setValue(200)
slider_w.setFixedWidth(250)
lbl_val = QLabel("200 px")
lbl_val.setStyleSheet("font-weight: bold; min-width: 50px;")

ctrl_bar.addWidget(lbl_slider)
ctrl_bar.addWidget(slider_w)
ctrl_bar.addWidget(lbl_val)
ctrl_bar.addStretch()
root_layout.addLayout(ctrl_bar)

# Contenedor de paneles lado a lado
panels_layout = QHBoxLayout()
panels_layout.setSpacing(15)

items_prueba = [
    "★ Mejor Compatible (1080p60 H.264 / AAC 320kbps)",
    "Solo Video - 4K 2160p60 HDR",
    "Audio AAC 320kbps",
    "Opción de Texto Muy Largo para Probar Truncado en Espacios Reducidos",
    "Normal"
]

# -------------------------------------------------------------
# Panel Izquierdo: CON ESTILO DOWP
# -------------------------------------------------------------
group_dowp = QGroupBox("CON Estilo DowP 2.0 (QSS + Checkmark Verde DowP + Resaltado)")
layout_dowp = QVBoxLayout(group_dowp)
layout_dowp.setSpacing(8)

layout_dowp.addWidget(QLabel("<b>1. Ancho Compacto Fijo (150 px):</b>"))
cb_dowp_150 = QComboBox()
cb_dowp_150.setFixedWidth(150)
cb_dowp_150.addItems(items_prueba)
layout_dowp.addWidget(cb_dowp_150)

layout_dowp.addWidget(QLabel("<b>2. Ancho Medio Fijo (220 px):</b>"))
cb_dowp_220 = QComboBox()
cb_dowp_220.setFixedWidth(220)
cb_dowp_220.addItems(items_prueba)
layout_dowp.addWidget(cb_dowp_220)

layout_dowp.addWidget(QLabel("<b>3. AutoPopupComboBox (Auto-expandible + Resaltado Activo):</b>"))
cb_dowp_dyn_auto = TestAutoPopupComboBox()
cb_dowp_dyn_auto.setFixedWidth(200)
cb_dowp_dyn_auto.addItems(items_prueba)
layout_dowp.addWidget(cb_dowp_dyn_auto)

layout_dowp.addWidget(QLabel("<b>4. QComboBox Estándar Fijo (Ancho con Slider):</b>"))
cb_dowp_dyn_std = QComboBox()
cb_dowp_dyn_std.setFixedWidth(200)
cb_dowp_dyn_std.addItems(items_prueba)
layout_dowp.addWidget(cb_dowp_dyn_std)

layout_dowp.addWidget(QLabel("<b>5. Selector de Etiquetas (Con Íconos Circulares y Color):</b>"))
cb_dowp_tags = TestAutoPopupComboBox()
cb_dowp_tags.setFixedWidth(200)
cb_dowp_tags.addItem("Etiqueta", "")
cb_dowp_tags.addItem(create_colored_circle_icon("#3388ff", 12), "Pruebas", "")
cb_dowp_tags.setItemData(1, "#3388ff", Qt.UserRole + 1)
cb_dowp_tags.addItem(create_colored_circle_icon("#ff5555", 12), "Importante", "")
cb_dowp_tags.setItemData(2, "#ff5555", Qt.UserRole + 1)
cb_dowp_tags.addItem(create_colored_circle_icon("#B9E640", 12), "Finalizado", "")
cb_dowp_tags.setItemData(3, "#B9E640", Qt.UserRole + 1)
cb_dowp_tags.setCurrentIndex(1)
cb_dowp_tags.currentIndexChanged.connect(lambda idx: update_label_combobox_style(cb_dowp_tags))
layout_dowp.addWidget(cb_dowp_tags)

layout_dowp.addStretch()

# Aplicar el stylesheet al panel de DowP
qss = load_stylesheet("dark")
group_dowp.setStyleSheet(qss)
panels_layout.addWidget(group_dowp)

# -------------------------------------------------------------
# Panel Derecho: SIN ESTILO (Fusion Puro / Nativo)
# -------------------------------------------------------------
group_native = QGroupBox("SIN Estilo (Nativo Fusion sin QSS)")
layout_native = QVBoxLayout(group_native)
layout_native.setSpacing(8)

layout_native.addWidget(QLabel("<b>1. Ancho Compacto (150 px):</b>"))
cb_native_150 = QComboBox()
cb_native_150.setFixedWidth(150)
cb_native_150.addItems(items_prueba)
layout_native.addWidget(cb_native_150)

layout_native.addWidget(QLabel("<b>2. Ancho Medio (220 px):</b>"))
cb_native_220 = QComboBox()
cb_native_220.setFixedWidth(220)
cb_native_220.addItems(items_prueba)
layout_native.addWidget(cb_native_220)

layout_native.addWidget(QLabel("<b>3. AutoPopupComboBox (Ancho dinámico con Slider):</b>"))
cb_native_dyn_auto = TestAutoPopupComboBox()
cb_native_dyn_auto.setFixedWidth(200)
cb_native_dyn_auto.addItems(items_prueba)
layout_native.addWidget(cb_native_dyn_auto)

layout_native.addWidget(QLabel("<b>4. QComboBox Estándar (Ancho dinámico con Slider):</b>"))
cb_native_dyn_std = QComboBox()
cb_native_dyn_std.setFixedWidth(200)
cb_native_dyn_std.addItems(items_prueba)
layout_native.addWidget(cb_native_dyn_std)

layout_native.addWidget(QLabel("<b>5. Selector de Etiquetas (Con Íconos Circulares y Color):</b>"))
cb_native_tags = TestAutoPopupComboBox()
cb_native_tags.setFixedWidth(200)
cb_native_tags.addItem("Etiqueta", "")
cb_native_tags.addItem(create_colored_circle_icon("#3388ff", 12), "Pruebas", "")
cb_native_tags.setItemData(1, "#3388ff", Qt.UserRole + 1)
cb_native_tags.addItem(create_colored_circle_icon("#ff5555", 12), "Importante", "")
cb_native_tags.setItemData(2, "#ff5555", Qt.UserRole + 1)
cb_native_tags.addItem(create_colored_circle_icon("#B9E640", 12), "Finalizado", "")
cb_native_tags.setItemData(3, "#B9E640", Qt.UserRole + 1)
layout_native.addWidget(cb_native_tags)

layout_native.addStretch()
panels_layout.addWidget(group_native)

root_layout.addLayout(panels_layout)

# Conectar el slider para redimensionar los combos dinámicos en vivo
def on_slider_changed(val):
    lbl_val.setText(f"{val} px")
    cb_dowp_dyn_auto.setFixedWidth(val)
    cb_dowp_dyn_std.setFixedWidth(val)
    cb_native_dyn_auto.setFixedWidth(val)
    cb_native_dyn_std.setFixedWidth(val)

slider_w.valueChanged.connect(on_slider_changed)

win.setCentralWidget(central_widget)
win.show()

sys.exit(app.exec())