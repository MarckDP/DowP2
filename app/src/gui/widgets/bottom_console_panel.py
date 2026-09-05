# src/gui/widgets/bottom_console_panel.py
from PySide6.QtCore import QPoint, QEasingCurve, QPropertyAnimation, QRect, Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout


class ConsoleToggleBar(QFrame):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("consoleToggleBar")
        self._clickable = True
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(24)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.label = QLabel(self.tr("Consola"))
        self.label.setObjectName("consoleToggleLabel")
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)

    def mouseReleaseEvent(self, event):
        if self._clickable and event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def set_clickable(self, clickable):
        self._clickable = clickable
        self.setCursor(Qt.PointingHandCursor if clickable else Qt.ArrowCursor)


class BottomConsolePanel(QFrame):
    TALL_WINDOW_THRESHOLD = 850
    COMPACT_CONTENT_HEIGHT = 190

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("bottomConsolePanel")
        self._overlay_parent = parent
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._is_docked = False
        self._is_open = False
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.toggle_bar = ConsoleToggleBar()
        self.toggle_bar.clicked.connect(self.toggle_compact_panel)
        layout.addWidget(self.toggle_bar)

        self.content = QFrame()
        self.content.setObjectName("consoleContent")
        self.content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._build_content(self.content)

        layout.addWidget(self.content, 1)

        self._height_anim = QPropertyAnimation(self.content, b"maximumHeight")
        self._height_anim.setDuration(240)
        self._height_anim.setEasingCurve(QEasingCurve.InOutCubic)

        self.overlay_panel = QFrame(self._overlay_parent if self._overlay_parent else self)
        self.overlay_panel.setObjectName("consoleOverlayPanel")
        overlay_layout = QVBoxLayout(self.overlay_panel)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.setSpacing(0)

        self.overlay_toggle_bar = ConsoleToggleBar()
        self.overlay_toggle_bar.clicked.connect(self.toggle_compact_panel)
        overlay_layout.addWidget(self.overlay_toggle_bar)

        self.overlay_content = QFrame()
        self.overlay_content.setObjectName("consoleContent")
        self._build_content(self.overlay_content)
        overlay_layout.addWidget(self.overlay_content, 1)

        self.overlay_panel.hide()
        self.overlay_panel.raise_()

        self._overlay_anim = QPropertyAnimation(self.overlay_panel, b"geometry")
        self._overlay_anim.setDuration(240)
        self._overlay_anim.setEasingCurve(QEasingCurve.InOutCubic)

        self.set_compact_mode()

    def _build_content(self, content):
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(14, 12, 14, 12)
        content_layout.setSpacing(0)

        placeholder = QLabel(self.tr("Área reservada"))
        placeholder.setObjectName("consolePlaceholder")
        placeholder.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(placeholder)

    def update_for_window_size(self, parent_height):
        if parent_height >= self.TALL_WINDOW_THRESHOLD:
            self.set_docked_mode()
        else:
            self.set_compact_mode()
            self._sync_overlay_geometry()

    def set_docked_mode(self):
        if self._is_docked:
            return

        self._height_anim.stop()
        self._overlay_anim.stop()
        self._is_docked = True
        self._is_open = True
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.toggle_bar.show()
        self.toggle_bar.set_clickable(False)
        self.overlay_panel.hide()
        self.content.setMaximumHeight(16777215)
        self.content.show()

    def set_compact_mode(self):
        if not self._is_docked and not self._is_open:
            self.content.hide()
            self.content.setMaximumHeight(0)
            self.overlay_panel.hide()
            self.toggle_bar.show()
            self.toggle_bar.set_clickable(True)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.setFixedHeight(self.toggle_bar.height())
            return

        self._height_anim.stop()
        self._overlay_anim.stop()
        was_docked = self._is_docked
        self._is_docked = False
        if was_docked:
            self._is_open = False
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(self.toggle_bar.height())
        self.content.hide()
        self.content.setMaximumHeight(0)
        if self._is_open:
            self.toggle_bar.hide()
            self.overlay_panel.show()
            self.overlay_panel.raise_()
            self._sync_overlay_geometry()
        else:
            self.overlay_panel.hide()
            self.toggle_bar.show()
            self.toggle_bar.set_clickable(True)

    def toggle_compact_panel(self):
        if self._is_docked:
            return

        self._is_open = not self._is_open
        self._animate_overlay()

    def _overlay_geometry(self, expanded):
        parent = self._overlay_parent or self.parentWidget()
        if not parent:
            return QRect()

        bar_pos = self.toggle_bar.mapTo(parent, QPoint(0, 0))
        content_height = self.COMPACT_CONTENT_HEIGHT if expanded else 0

        # El overlay ocupa todo el ancho y llega hasta el fondo real del parent
        y_top = bar_pos.y() - content_height
        total_h = parent.height() - y_top
        return QRect(0, y_top, parent.width(), total_h)

    def _animate_overlay(self):
        self._overlay_anim.stop()
        was_visible = self.overlay_panel.isVisible()
        self.overlay_panel.show()
        self.overlay_panel.raise_()

        start_rect = self.overlay_panel.geometry()
        if not was_visible or not start_rect.isValid() or start_rect.height() == 0:
            start_rect = self._overlay_geometry(not self._is_open)

        end_rect = self._overlay_geometry(self._is_open)
        self._overlay_anim.setStartValue(start_rect)
        self._overlay_anim.setEndValue(end_rect)

        if self._is_open:
            self.toggle_bar.hide()
        else:
            self._overlay_anim.finished.connect(self._hide_overlay_after_collapse)

        self._overlay_anim.start()

    def _sync_overlay_geometry(self):
        if self._is_docked or not self._is_open:
            return
        self.overlay_panel.setGeometry(self._overlay_geometry(True))
        # Garantizar z-order: consola siempre por encima del panel de recodificación
        self.overlay_panel.raise_()

    def _hide_overlay_after_collapse(self):
        if not self._is_open and not self._is_docked:
            self.overlay_panel.hide()
            self.toggle_bar.show()

        try:
            self._overlay_anim.finished.disconnect(self._hide_overlay_after_collapse)
        except RuntimeError:
            pass
