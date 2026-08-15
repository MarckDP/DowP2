# src/gui/tabs/advanced_process/video_details_components.py
import os
import requests
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QSizePolicy, QComboBox, QStyledItemDelegate, QStyle, QStyleOptionComboBox
)
from PySide6.QtCore import Qt, Signal, QThread, QSize
from PySide6.QtGui import QPixmap, QImage, QIcon, QPainter, QColor, QFontMetrics
from PySide6.QtSvg import QSvgRenderer
from gui.styles import get_theme_token, apply_cut_button_style
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
from gui.widgets.combo_box import AutoPopupComboBox

class ThumbnailLoaderThread(QThread):
    finished = Signal(bytes, str) # content, error
    
    def __init__(self, url, fallback_urls=None):
        super().__init__()
        self.url = url
        self.fallback_urls = fallback_urls or []
        
    def run(self):
        urls_to_try = [self.url] + self.fallback_urls
        last_error = ""
        for url in urls_to_try:
            try:
                resp = requests.get(url, timeout=10)
                resp.raise_for_status()
                if resp.content:
                    self.finished.emit(resp.content, "")
                    return
            except Exception as e:
                last_error = str(e)
        self.finished.emit(b"", last_error)

class RichTextDelegate(QStyledItemDelegate):
    """
    Delegate avanzado que permite pintar etiquetas con colores específicos.
    [Combinado] -> Azul
    [Multi-Idioma] -> Violeta
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tag_colors = {
            self.tr("[Combinado]"): get_theme_token("etiqueta_combinado", "#3498db"),
            self.tr("[Multi-Idioma]"): get_theme_token("etiqueta_multi_idioma", "#9b59b6"),
        }
        # Cargar Iconos
        _icon_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "assets", "icons", "svg")
        self.star_pixmap = self._get_colored_icon(os.path.join(_icon_dir, "star.svg"), "#58cf5c") # Verde
        self.warning_pixmap = self._get_colored_icon(os.path.join(_icon_dir, "warning.svg"), "#ddb745") # Ámbar/Amarillo

    def _get_colored_icon(self, path, color_hex):
        if not os.path.exists(path): return None
        size = 16
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        renderer = QSvgRenderer(path)
        renderer.render(painter)
        
        # Colorear
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor(color_hex))
        painter.end()
        return pixmap

    def paint(self, painter, option, index):
        painter.save()
        
        # Dibujar fondo de selección/hover estándar sin el texto
        self.initStyleOption(option, index)
        text = option.text  # Guardar el texto original
        option.text = ""    # Limpiar para que el estilo base no lo dibuje
        
        option.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget)
        
        rect = option.rect
        rect.setLeft(rect.left() + 10) # Margen izquierdo
        
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Dividir el texto por espacios para buscar etiquetas
        parts = text.split(' ')
        current_x = rect.left()
        
        font = painter.font()
        
        for part in parts:
            if not part: continue
            
            # Limpiar posibles caracteres pegados para la comparación
            clean_part = part.strip()
            
            # ¿Es un icono especial?
            icon = None
            if "✨" in clean_part: icon = self.star_pixmap
            elif "⚠️" in clean_part: icon = self.warning_pixmap
            
            if icon:
                # Dibujar icono en lugar de texto
                painter.drawPixmap(current_x, rect.top() + (rect.height()-16)//2, icon)
                current_x += 20
                continue

            # ¿Es una etiqueta con color?
            color = self.tag_colors.get(clean_part, None)
            
            if color:
                painter.setPen(QIcon().theme().color(color) if hasattr(QIcon(), 'theme') else color)
                font.setBold(True)
                painter.setFont(font)
            else:
                # Color de texto normal según el estado de la opción (seleccionada o no)
                if option.state & QStyle.StateFlag.State_Selected:
                    painter.setPen(option.palette.highlightedText().color())
                else:
                    painter.setPen(option.palette.text().color())
                font.setBold(False)
                painter.setFont(font)
            
            # Dibujar la parte
            painter.drawText(current_x, rect.top(), rect.width(), rect.height(), 
                             Qt.AlignVCenter, part)
            
            # Avanzar X según el ancho del texto dibujado
            fm = QFontMetrics(font)
            current_x += fm.horizontalAdvance(part + " ")
            
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(size.height() + 15) # Padding vertical
        return size

class ResponsiveThumbnail(QWidget):
    clicked_cut = Signal()  # Emitida al pulsar el botón de recorte

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 180)
        
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        
        self._pixmap = None
        self._cut_button_allowed = True

        self.thumb_label = QLabel(self)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setObjectName("thumbnailLabel")
        self.thumb_label.setText(self.tr("Sin Vista Previa"))
        
        self.duration_label = QLabel("", self)
        self.duration_label.setObjectName("durationLabel")
        self.duration_label.hide()

        # Botón overlay flotante sobre la miniatura del video — circular, como el
        # badge de "play" que ya usa esta misma convención en fragment_dialog.py.
        self.btn_cut = QPushButton(self)
        self.btn_cut.setFixedSize(40, 40)
        self.btn_cut.setToolTip(self.tr("Recortar fragmento"))
        self.btn_cut.hide()
        self.btn_cut.clicked.connect(self.clicked_cut)
        self.btn_cut.setIconSize(QSize(22, 22))
        apply_cut_button_style(self.btn_cut, "normal", icon_size=22, shape="circular")

    def set_cut_status(self, status):
        apply_cut_button_style(self.btn_cut, status, icon_size=22, shape="circular")

    def set_duration(self, text):
        if text:
            self.duration_label.setText(text)
            self.duration_label.adjustSize()
            self.duration_label.show()
        else:
            self.duration_label.hide()
        self._update_layout()

    def set_cut_button_visible(self, visible):
        self._cut_button_allowed = visible
        if visible:
            if self._pixmap and not self._pixmap.isNull():
                self.btn_cut.show()
        else:
            self.btn_cut.hide()

    def set_pixmap(self, pixmap):
        self._pixmap = pixmap
        self.thumb_label.setText("")
        if getattr(self, '_cut_button_allowed', True):
            self.btn_cut.show()
        else:
            self.btn_cut.hide()
        self._update_pixmap()
        
    def set_text(self, text):
        self._pixmap = None
        self.thumb_label.setPixmap(QPixmap())
        self.thumb_label.setText(text)
        self.btn_cut.hide()

    def _update_pixmap(self):
        if self._pixmap and not self._pixmap.isNull():
            self.thumb_label.setPixmap(self._pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _update_layout(self):
        self.thumb_label.setGeometry(self.rect())
        btn_size = self.btn_cut.width()
        self.btn_cut.move(self.width() - btn_size - 8, 8)
        if not self.duration_label.isHidden():
            self.duration_label.move(
                self.width() - self.duration_label.width() - 8,
                self.height() - self.duration_label.height() - 8
            )

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return int(width * 9 / 16)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_pixmap()
        self._update_layout()

    def sizeHint(self):
        return QSize(320, 180)

class RichComboBox(AutoPopupComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tag_colors = {
            self.tr("[Combinado]"): get_theme_token("etiqueta_combinado", "#3498db"),
            self.tr("[Multi-Idioma]"): get_theme_token("etiqueta_multi_idioma", "#9b59b6"),
        }
        _icon_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "assets", "icons", "svg")
        self.star_pixmap = self._get_colored_icon(os.path.join(_icon_dir, "star.svg"), "#4CAF50")
        self.warning_pixmap = self._get_colored_icon(os.path.join(_icon_dir, "warning.svg"), "#FFC107")

    def _get_colored_icon(self, path, color_hex):
        if not os.path.exists(path): return None
        size = 16
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer = QSvgRenderer(path)
        renderer.render(painter)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor(color_hex))
        painter.end()
        return pixmap

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        
        text = opt.currentText
        opt.currentText = ""
        
        self.style().drawComplexControl(QStyle.ComplexControl.CC_ComboBox, opt, painter, self)
        self.style().drawControl(QStyle.ControlElement.CE_ComboBoxLabel, opt, painter, self)
        
        rect = self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, opt, QStyle.SubControl.SC_ComboBoxEditField, self)
        rect.setLeft(rect.left() + 5)
        rect.setRight(rect.right() - 5)
        
        painter.save()
        painter.setClipRect(rect)
        
        parts = text.split(' ')
        current_x = rect.left()
        font = painter.font()
        
        for part in parts:
            if not part: continue
            clean_part = part.strip()
            
            icon = None
            if "✨" in clean_part: icon = self.star_pixmap
            elif "⚠️" in clean_part: icon = self.warning_pixmap
            
            if icon:
                if current_x + 20 <= rect.right():
                    painter.drawPixmap(current_x, rect.top() + (rect.height()-16)//2, icon)
                current_x += 20
                continue

            color = self.tag_colors.get(clean_part, None)
            
            if color:
                painter.setPen(QIcon().theme().color(color) if hasattr(QIcon(), 'theme') else color)
                font.setBold(True)
                painter.setFont(font)
            else:
                painter.setPen(self.palette().text().color())
                font.setBold(False)
                painter.setFont(font)
                
            fm = QFontMetrics(font)
            if current_x < rect.right():
                available = rect.right() - current_x
                # Red de seguridad: si la palabra no entra entera, elidir con "…" en vez de
                # dejar que setClipRect() la corte a mitad de carácter sin aviso visual.
                draw_part = part if fm.horizontalAdvance(part) <= available else \
                    fm.elidedText(part, Qt.TextElideMode.ElideRight, available)
                painter.drawText(current_x, rect.top(), available, rect.height(),
                                 Qt.AlignmentFlag.AlignVCenter, draw_part)

            current_x += fm.horizontalAdvance(part + " ")
            
        painter.restore()
