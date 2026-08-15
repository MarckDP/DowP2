# src/gui/widgets/combo_box.py
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QComboBox, QStyle, QStyleOptionComboBox

# Margen extra sobre el texto del ítem más largo para calcular el ancho "preferido"
# (sizeHint/minimumWidth) de la caja cerrada — deja aire para el padding y la flecha del QSS.
# Generoso a propósito: preferible una caja un poco más ancha de lo estrictamente necesario a
# que vuelva a cortar texto.
_CHROME_WIDTH = 70


class AutoPopupComboBox(QComboBox):
    """QComboBox que evita el recorte de texto tanto en la caja cerrada como en el popup
    desplegado, sin necesidad de que cada lugar que lo usa reserve manualmente el ancho.

    - Caja cerrada, ANCHO: `sizeHint()` + un `setMinimumWidth()` real forzado cada vez que
      cambian los ítems (un piso que el sistema de layouts de Qt sí respeta siempre).
    - Caja cerrada, TEXTO: `paintEvent()` dibuja la etiqueta actual a mano en vez de dejar
      que lo haga la rutina nativa de Qt (CE_ComboBoxLabel). Con el QSS de esta app (padding
      del QComboBox + subcontrol ::drop-down con su propio ancho), esa rutina nativa termina
      recortando el texto en un punto más angosto que el ancho real de la caja — se nota
      como espacio vacío entre el texto y la flecha en vez de que el texto llegue hasta ahí,
      incluso con texto corto que de sobra entraría. Se calcula el rect real disponible
      (SC_ComboBoxEditField) y se dibuja el texto ahí directamente, con elidido "…" solo si
      de verdad no entra. Este mismo patrón (texto dibujado a mano) ya lo usaba con éxito
      RichComboBox — acá se aplica de forma genérica a cualquier combo, no solo a los que
      necesitan íconos/colores por ítem.
    - Popup: `showPopup()` fuerza que la lista desplegada sea lo bastante ancha para su ítem
      más largo, en vez de heredar el ancho de la caja cerrada.

    Si un sitio de uso necesita además un `setFixedWidth()`/`setMaximumWidth()` propio
    (p.ej. para encajar en una barra compacta), esa llamada debe hacerse DESPUÉS de agregar
    los ítems — si no, el ancho mínimo forzado acá puede quedar por encima del máximo fijado
    ahí y el resultado es impredecible."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeAdjustPolicy(QComboBox.AdjustToContents)

    def _widest_item_text_width(self) -> int:
        fm = self.fontMetrics()
        max_width = 0
        for i in range(self.count()):
            item_width = fm.horizontalAdvance(self.itemText(i))
            if item_width > max_width:
                max_width = item_width
        return max_width

    def _sync_min_width(self):
        self.setMinimumWidth(self._widest_item_text_width() + _CHROME_WIDTH if self.count() else 0)

    def addItem(self, *args, **kwargs):
        super().addItem(*args, **kwargs)
        self._sync_min_width()

    def addItems(self, texts):
        super().addItems(texts)
        self._sync_min_width()

    def clear(self):
        super().clear()
        self._sync_min_width()

    def sizeHint(self):
        hint = super().sizeHint()
        needed = self._widest_item_text_width() + _CHROME_WIDTH
        if needed > hint.width():
            return QSize(needed, hint.height())
        return hint

    def showPopup(self):
        popup_width = max(self.width(), self._widest_item_text_width() + _CHROME_WIDTH)
        self.view().setMinimumWidth(popup_width)
        container = self.view().window()
        if container:
            container.setAttribute(Qt.WA_TranslucentBackground, True)
            container.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        super().showPopup()

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
        rect.setLeft(rect.left() + 5)
        rect.setRight(rect.right() - 5)

        group = self.palette().ColorGroup.Normal if self.isEnabled() else self.palette().ColorGroup.Disabled
        painter.setPen(self.palette().color(group, self.palette().ColorRole.Text))
        elided = self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, elided)
