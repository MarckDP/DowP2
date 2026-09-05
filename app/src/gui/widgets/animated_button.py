# src/gui/widgets/animated_button.py
from PySide6.QtWidgets import QPushButton, QGraphicsOpacityEffect
from PySide6.QtCore import QPropertyAnimation, QEasingCurve, Qt, QEvent

class AnimatedButton(QPushButton):
    """
    QPushButton subclass that implements a clean, smooth opacity fade transition on hover.
    Provides theme-agnostic micro-interactions without using glows.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setCursor(Qt.PointingHandCursor if self.isEnabled() else Qt.ArrowCursor)
        
        # Configure opacity effect
        self._opacity_effect = QGraphicsOpacityEffect(self)
        # Set idle opacity (0.85) if enabled, otherwise disabled style handles it
        self._opacity_effect.setOpacity(0.85 if self.isEnabled() else 1.0)
        self._opacity_effect.setEnabled(self.isEnabled())
        self.setGraphicsEffect(self._opacity_effect)
        
        # Opacity transition animation
        self._anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._anim.setDuration(120) # Fast, responsive fade (120ms)
        self._anim.setEasingCurve(QEasingCurve.OutQuad)

    def enterEvent(self, event):
        if self.isEnabled():
            self._anim.stop()
            self._anim.setEndValue(1.0) # Hovered state (fully opaque/lit)
            self._anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.isEnabled():
            self._anim.stop()
            self._anim.setEndValue(0.85) # Idle state (subtly dimmed)
            self._anim.start()
        super().leaveEvent(event)

    def changeEvent(self, event):
        if event.type() == QEvent.EnabledChange:
            enabled = self.isEnabled()
            self.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
            self._opacity_effect.setEnabled(enabled)
            if enabled:
                # Reset opacity to standard idle state when re-enabled
                # (Or fully opaque if hovered immediately, but 0.85 is standard)
                self._opacity_effect.setOpacity(0.85)
        super().changeEvent(event)
