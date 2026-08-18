# src/gui/widgets/mode_selector.py
from PySide6.QtWidgets import QFrame, QWidget, QHBoxLayout, QPushButton
from PySide6.QtCore import Signal, QPropertyAnimation, QEasingCurve, QRect
from core.logger.logger_manager import logger

class ModeSelector(QFrame):
    mode_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        self.setObjectName("modeSelectorContainer")
        self.setFixedHeight(38)
        
        # Indicator frame that slides
        self.bg_indicator = QFrame(self)
        self.bg_indicator.setObjectName("modeIndicator")
        self.bg_indicator.hide() # Hidden until first layout/resize

        # Layout for buttons
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)
        
        self.btn_video_audio = QPushButton(self.tr("Video + Audio"), self)
        self.btn_audio = QPushButton(self.tr("Solo Audio"), self)
        self.btn_video = QPushButton(self.tr("Solo Video"), self)

        self.buttons = [self.btn_video_audio, self.btn_audio, self.btn_video]
        for btn in self.buttons:
            btn.setObjectName("modeButton")
            btn.setCheckable(True)
            btn.setFixedHeight(30)
            btn.clicked.connect(self.on_button_clicked)
            layout.addWidget(btn)

        self.btn_video_audio.setChecked(True)
        self.btn_video_audio.setProperty("active", "true")
        
        self.animation = None

    def on_button_clicked(self):
        sender = self.sender()
        if not sender: return
        
        for btn in self.buttons:
            is_active = (btn == sender)
            btn.setChecked(is_active)
            btn.setProperty("active", "true" if is_active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        
        self.animate_indicator(sender)
        self.mode_changed.emit(sender.text())

    def animate_indicator(self, button):
        self.bg_indicator.show()
        if self.animation:
            self.animation.stop()
            
        self.animation = QPropertyAnimation(self.bg_indicator, b"geometry")
        self.animation.setDuration(250)
        self.animation.setStartValue(self.bg_indicator.geometry())
        self.animation.setEndValue(button.geometry())
        self.animation.setEasingCurve(QEasingCurve.InOutCubic)
        self.animation.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Snap indicator to the active button immediately on resize
        for btn in self.buttons:
            if btn.isChecked():
                self.bg_indicator.setGeometry(btn.geometry())
                self.bg_indicator.show()
                break

    def current_mode(self):
        for btn in self.buttons:
            if btn.isChecked():
                return btn.text()
        return "Video + Audio"

    def set_mode(self, mode_text: str):
        for btn in self.buttons:
            if btn.text() == mode_text:
                btn.click()
                break
