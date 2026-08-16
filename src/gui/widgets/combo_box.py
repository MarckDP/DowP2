# src/gui/widgets/combo_box.py
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QComboBox, QStyle, QStyleOptionComboBox


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

        # Margen para padding interno, bordes redondeados y scrollbar si aplica
        extra = 34
        if has_icons:
            extra += 24
        if self.count() > self.maxVisibleItems():
            extra += 16
        return max(50, max_width + extra)

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
