# src/gui/tabs/editing_media/preview_panel.py
import os
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QSizePolicy
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QPixmap

from core.logger.logger_manager import logger
from gui.styles import get_theme_token

try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PySide6.QtMultimediaWidgets import QVideoWidget
    MULTIMEDIA_AVAILABLE = True
except ImportError as e:
    MULTIMEDIA_AVAILABLE = False
    logger.warning(f"PreviewPanel: QtMultimedia no está disponible en este sistema: {e}")


class PreviewContainerWidget(QFrame):
    """Contenedor de vista previa cuadrado con soporte para imágenes y reproducción de video real."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("previewContainer")
        
        # Sizing Policy para forzar un diseño cuadrado
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(200)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)
        
        # Fondo oscuro y bordes redondeados
        self.setStyleSheet(f"""
            QFrame#previewContainer {{
                background-color: {get_theme_token('fondo_principal', '#0a0a0a')};
                border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-radius: 12px;
            }}
        """)
        
        # 1. Widget de Imagen / Placeholder
        self.placeholder_label = QLabel()
        self.placeholder_label.setAlignment(Qt.AlignCenter)
        self.placeholder_label.setWordWrap(True)
        self.layout.addWidget(self.placeholder_label)
        
        # 2. Widget de Video Real
        self.video_widget = None
        self.media_player = None
        self.audio_output = None
        
        if MULTIMEDIA_AVAILABLE:
            try:
                self.video_widget = QVideoWidget()
                self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                self.video_widget.setVisible(False)
                self.layout.addWidget(self.video_widget)
                
                self.media_player = QMediaPlayer(self)
                self.audio_output = QAudioOutput(self)
                self.media_player.setAudioOutput(self.audio_output)
                self.media_player.setVideoOutput(self.video_widget)
                
                # Bajar el volumen por defecto a un nivel agradable (10%) para evitar sustos
                self.audio_output.setVolume(0.1)
                
                # Hacer que el video se reproduzca en bucle continuo
                self.media_player.setLoops(QMediaPlayer.Infinite)
            except Exception as ex:
                logger.error(f"PreviewPanel: Error inicializando reproductores multimedia: {ex}")
                self.video_widget = None
        
        self.show_default_state()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self.width()
        if w > 0:
            if hasattr(self, "_last_width") and self._last_width == w:
                return
            self._last_width = w
            self.setFixedHeight(w)

    def stop_media(self):
        """Detiene cualquier reproducción de video activa."""
        if self.media_player:
            try:
                self.media_player.stop()
            except Exception:
                pass

    def show_default_state(self):
        self.stop_media()
        if self.video_widget:
            self.video_widget.setVisible(False)
        self.placeholder_label.setVisible(True)
        self.placeholder_label.setPixmap(QPixmap())
        self.placeholder_label.setText(
            "Selecciona un archivo multimedia\npara ver su vista previa"
        )
        self.placeholder_label.setStyleSheet("color: #6c7086; font-size: 13px;")

    def show_image_preview(self, path: str):
        self.stop_media()
        if self.video_widget:
            self.video_widget.setVisible(False)
        
        self.placeholder_label.setVisible(True)
        self.placeholder_label.setText("")
        
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                self.width() - 10,
                self.height() - 10,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.placeholder_label.setPixmap(scaled)
        else:
            self.placeholder_label.setText(f"[ Error al cargar Imagen ]\n\n{os.path.basename(path)}")
            self.placeholder_label.setStyleSheet("color: #ff6c6b; font-weight: bold; font-size: 13px;")

    def show_video_preview(self, path: str):
        if self.video_widget and self.media_player:
            self.placeholder_label.setVisible(False)
            self.video_widget.setVisible(True)
            try:
                self.media_player.setSource(QUrl.fromLocalFile(path))
                self.media_player.play()
                logger.debug(f"PreviewPanel: Reproduciendo video preview: {path}")
            except Exception as e:
                logger.error(f"PreviewPanel: Error reproduciendo video: {e}")
                self.show_video_placeholder(path)
        else:
            self.show_video_placeholder(path)

    def show_video_placeholder(self, path: str):
        self.stop_media()
        if self.video_widget:
            self.video_widget.setVisible(False)
        self.placeholder_label.setVisible(True)
        self.placeholder_label.setPixmap(QPixmap())
        name = os.path.basename(path)
        self.placeholder_label.setText(f"▶ [ Previsualización de Video ]\n\n{name}")
        self.placeholder_label.setStyleSheet(f"color: {get_theme_token('acento_primario', '#B9E640')}; font-weight: bold; font-size: 13px;")

    def show_audio_preview(self, path: str):
        self.stop_media()
        if self.video_widget:
            self.video_widget.setVisible(False)
        self.placeholder_label.setVisible(True)
        self.placeholder_label.setPixmap(QPixmap())
        name = os.path.basename(path)
        self.placeholder_label.setText(f"🎵 [ Detalle de Audio ]\n\n{name}")
        self.placeholder_label.setStyleSheet("color: #f5c2e7; font-weight: bold; font-size: 13px;")
