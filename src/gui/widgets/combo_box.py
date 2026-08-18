# src/gui/widgets/combo_box.py
import os
from PySide6.QtCore import Qt, QRect, QSize, QObject
from PySide6.QtGui import QPainter, QColor, QPixmap, QPalette
from PySide6.QtWidgets import (
    QComboBox, QStyle, QStyleOptionComboBox, QStyledItemDelegate, 
    QStyleOptionViewItem, QApplication
)
from PySide6.QtSvg import QSvgRenderer

from gui.styles import get_theme_token


class CheckmarkComboDelegate(QStyledItemDelegate):
    """
    Delegado global para QComboBox que:
    1. Dibuja un fondo sutilmente contrastado y texto blanco brillante en la opción activa.
    2. Dibuja el icono vectorial 'check_small.svg' en verde lima DowP (#B9E640) a la derecha de la opción seleccionada.
    3. Trunca el texto con '...' si el espacio es reducido para garantizar que nunca solape el checkmark.
    """

    _cached_check_pixmap = None

    def __init__(self, combo=None, parent=None):
        target_parent = parent or (combo if isinstance(combo, QObject) else None)
        super().__init__(target_parent)
        self._combo = combo if isinstance(combo, QComboBox) else None
        if CheckmarkComboDelegate._cached_check_pixmap is None:
            CheckmarkComboDelegate._cached_check_pixmap = self._create_check_pixmap()

    def _get_combo(self, option=None):
        if self._combo:
            return self._combo
        if option and hasattr(option, "widget") and isinstance(option.widget, QComboBox):
            return option.widget
        if isinstance(self.parent(), QComboBox):
            return self.parent()
        return None

    @staticmethod
    def _create_check_pixmap():
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        svg_path = os.path.join(base_dir, "assets", "icons", "svg", "check_small.svg")
        if not os.path.exists(svg_path):
            return None
        # Renderizado en alta resolución (36x36) para nitidez vectorial perfecta
        size = 36
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        renderer = QSvgRenderer(svg_path)
        renderer.render(painter)

        # Colorear con el verde lima primario de DowP (#B9E640)
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

        total_w = text_w + 54
        icon = index.data(Qt.DecorationRole)
        if icon and not icon.isNull():
            total_w += 24
        return QSize(max(hint.width(), total_w), max(hint.height(), 26))

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        combo = self._get_combo(option)
        is_current = (combo is not None and index.row() == combo.currentIndex())
        is_hovered = bool(opt.state & QStyle.State_Selected)

        raw_text = opt.text
        opt.text = ""  # Vaciar texto para controlar el dibujado de fondo y elipsis

        widget = option.widget
        style = widget.style() if widget else QApplication.style()

        # 1. Dibujado de Fondo:
        if is_hovered:
            style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)
        elif is_current:
            # Opción activa: fondo contrastado suave redondeado
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing)
            bg_rect = opt.rect.adjusted(2, 1, -2, -1)
            painter.setBrush(QColor(255, 255, 255, 22))
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

        # 3. Dibujar el texto elidido con espacio reservado a la derecha
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

        if is_hovered:
            text_color = opt.palette.color(QPalette.Normal, QPalette.HighlightedText)
            if text_color.lightness() < 40:
                text_color = QColor("#ffffff")
        elif is_current:
            text_color = QColor("#ffffff")  # Blanco puro brillante para la opción activa
        else:
            text_color = QColor("#c5c5c5")  # Gris claro estándar

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


class AutoPopupComboBox(QComboBox):
    """QComboBox que desacopla el ancho del popup (desplegable) del ancho de la caja cerrada,
    haciendo que el popup siempre se ajuste al contenido de sus opciones.

    - Caja cerrada: tamaño/layout libre (puede ser ancha o compacta según el layout).
    - Popup: en `showPopup()`, calcula el ancho necesario para el ítem más largo (+ padding e íconos)
      y redimensiona el contenedor del popup a esa medida exacta, en lugar de heredar el ancho total
      de la caja cerrada.
    - Caja cerrada, TEXTO: `paintEvent()` dibuja la etiqueta actual a mano en el rect real disponible
      (SC_ComboBoxEditField) para evitar recortes prematuros causados por el padding del QSS."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.setItemDelegate(CheckmarkComboDelegate(self))

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
        return max_width + extra

    def showPopup(self):
        super().showPopup()
        container = self.view().window()
        if container and self.count() > 0:
            popup_w = self._widest_item_text_width()
            rect = container.geometry()
            container.setGeometry(rect.x(), rect.y(), popup_w, rect.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        text = opt.currentText
        opt.currentText = ""  # el texto se dibuja a mano más abajo, con el rect real

        self.style().drawComplexControl(QStyle.ComplexControl.CC_ComboBox, opt, painter, self)
        self.style().drawControl(QStyle.ControlElement.CE_ComboBoxLabel, opt, painter, self)

        if not text:
            return

        rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox, opt, QStyle.SubControl.SC_ComboBoxEditField, self
        )
        # Si hay icono, desplazar el inicio del texto para que no se dibuje encima del icono
        if not opt.currentIcon.isNull():
            icon_size = opt.iconSize if (hasattr(opt, "iconSize") and opt.iconSize.isValid() and opt.iconSize.width() > 0) else self.iconSize()
            icon_w = icon_size.width() if icon_size.isValid() and icon_size.width() > 0 else 16
            rect.setLeft(rect.left() + icon_w + 6)

        # Margen mínimo de seguridad para que no toque exactamente la línea divisoria
        rect.setRight(rect.right() - 2)

        # Usar color personalizado si la opción tiene uno asignado (ej. etiquetas de color)
        custom_color = self.itemData(self.currentIndex(), Qt.UserRole + 1)
        if custom_color and isinstance(custom_color, str) and custom_color.startswith("#"):
            from PySide6.QtGui import QColor
            painter.setPen(QColor(custom_color))
        else:
            group = self.palette().ColorGroup.Normal if self.isEnabled() else self.palette().ColorGroup.Disabled
            painter.setPen(self.palette().color(group, self.palette().ColorRole.Text))

        elided = self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, max(0, rect.width()))
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, elided)
