# src/gui/tabs/editing_media/preview_panel.py
import os
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QHBoxLayout, QSizePolicy, QWidget, QPushButton, QSlider
from PySide6.QtCore import Qt, QUrl, QSize
from PySide6.QtGui import QPixmap, QIcon

from core.logger.logger_manager import logger
from gui.styles import get_theme_token

try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PySide6.QtMultimediaWidgets import QVideoWidget
    MULTIMEDIA_AVAILABLE = True
except ImportError as e:
    MULTIMEDIA_AVAILABLE = False
    logger.warning(f"PreviewPanel: QtMultimedia no está disponible en este sistema: {e}")

_SVG_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "assets", "icons", "svg"
))

def get_svg_icon(name: str) -> QIcon:
    path = os.path.join(_SVG_DIR, name)
    return QIcon(path) if os.path.exists(path) else QIcon()


class PreviewContainerWidget(QFrame):
    """Contenedor de vista previa rectangular (panorámico) con soporte para imágenes y reproducción de video real con controles."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("previewContainer")
        
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(120)
        
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
        self._is_dragging_slider = False
        self._last_volume = 10
        
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

        # 3. Controles del Reproductor de Video
        self.controls_widget = QWidget()
        self.controls_widget.setVisible(False)
        controls_v = QVBoxLayout(self.controls_widget)
        controls_v.setContentsMargins(4, 2, 4, 2)
        controls_v.setSpacing(4)

        # Barra de tiempo
        self.time_slider = QSlider(Qt.Horizontal)
        self.time_slider.setRange(0, 100)
        self.time_slider.setValue(0)
        self.time_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border-radius: 2px;
                height: 4px;
                background: #444;
            }
            QSlider::sub-page:horizontal {
                background: #1DC038;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #fff;
                width: 10px;
                margin-top: -3px;
                margin-bottom: -3px;
                border-radius: 5px;
            }
        """)
        self.time_slider.sliderPressed.connect(self._on_slider_pressed)
        self.time_slider.sliderMoved.connect(self._on_slider_moved)
        self.time_slider.sliderReleased.connect(self._on_slider_released)
        controls_v.addWidget(self.time_slider)

        # Fila inferior: Play, Tiempo, Volumen
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(6)

        # Botón Play/Pausa
        self.btn_play_pause = QPushButton()
        self.btn_play_pause.setIcon(get_svg_icon("pause.svg"))
        self.btn_play_pause.setIconSize(QSize(14, 14))
        self.btn_play_pause.setFixedSize(26, 26)
        self.btn_play_pause.setStyleSheet("""
            QPushButton {
                background-color: #1DC038;
                border: none;
                border-radius: 13px;
            }
            QPushButton:hover {
                background-color: #B9E640;
            }
        """)
        self.btn_play_pause.clicked.connect(self.toggle_play_pause)
        btn_layout.addWidget(self.btn_play_pause)

        # Etiqueta de tiempo
        self.lbl_video_time = QLabel("00:00 / 00:00")
        self.lbl_video_time.setStyleSheet("font-size: 11px; color: #a6adc8; background: transparent; border: none;")
        btn_layout.addWidget(self.lbl_video_time)

        btn_layout.addStretch(1)

        # Icono de volumen (botón silenciador)
        self.btn_vol = QPushButton("🔊")
        self.btn_vol.setFixedSize(22, 22)
        self.btn_vol.setStyleSheet("background: transparent; border: none; font-size: 12px; color: #a6adc8;")
        self.btn_vol.clicked.connect(self.toggle_mute)
        btn_layout.addWidget(self.btn_vol)

        # Slider de volumen
        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setFixedWidth(60)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(10) # 10%
        self.vol_slider.valueChanged.connect(self._on_volume_changed)
        self.vol_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border-radius: 2px;
                height: 4px;
                background: #444;
            }
            QSlider::sub-page:horizontal {
                background: #1DC038;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #fff;
                width: 8px;
                margin-top: -2px;
                margin-bottom: -2px;
                border-radius: 4px;
            }
        """)
        btn_layout.addWidget(self.vol_slider)

        controls_v.addLayout(btn_layout)
        self.layout.addWidget(self.controls_widget)

        if MULTIMEDIA_AVAILABLE and self.media_player:
            self.media_player.positionChanged.connect(self._on_position_changed)
            self.media_player.durationChanged.connect(self._on_duration_changed)
            self.media_player.playbackStateChanged.connect(self._on_playback_state_changed)
        
        self.show_default_state()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self.width()
        if w > 0:
            avail_h = int(w * 0.6)
            self.setFixedHeight(avail_h)
            if hasattr(self, "_current_image_path") and self._current_image_path and self.placeholder_label.isVisible():
                pixmap = QPixmap(self._current_image_path)
                if not pixmap.isNull():
                    scaled = pixmap.scaled(
                        max(50, w - 10),
                        max(50, avail_h - 10),
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation
                    )
                    self.placeholder_label.setPixmap(scaled)

    def stop_media(self):
        """Detiene cualquier reproducción de video activa."""
        self._current_image_path = None
        if self.media_player:
            try:
                self.media_player.stop()
            except Exception:
                pass

    def show_default_state(self):
        self.stop_media()
        if self.video_widget:
            self.video_widget.setVisible(False)
        if hasattr(self, "controls_widget"):
            self.controls_widget.setVisible(False)
        self.placeholder_label.setVisible(True)
        self.placeholder_label.setPixmap(QPixmap())
        self.placeholder_label.setText(
            "Selecciona un archivo multimedia\npara ver su vista previa"
        )
        self.placeholder_label.setStyleSheet("color: #6c7086; font-size: 13px;")

    def show_image_preview(self, path: str):
        self.stop_media()
        self._current_image_path = path
        if self.video_widget:
            self.video_widget.setVisible(False)
        if hasattr(self, "controls_widget"):
            self.controls_widget.setVisible(False)
        
        self.placeholder_label.setVisible(True)
        self.placeholder_label.setText("")
        
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            avail_w = max(50, self.width() - 10)
            avail_h = max(50, self.height() - 10)
            scaled = pixmap.scaled(
                avail_w,
                avail_h,
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
            if hasattr(self, "controls_widget"):
                self.controls_widget.setVisible(True)
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
        if hasattr(self, "controls_widget"):
            self.controls_widget.setVisible(False)
        self.placeholder_label.setVisible(True)
        self.placeholder_label.setPixmap(QPixmap())
        name = os.path.basename(path)
        self.placeholder_label.setText(f"▶ [ Previsualización de Video ]\n\n{name}")
        self.placeholder_label.setStyleSheet(f"color: {get_theme_token('acento_primario', '#B9E640')}; font-weight: bold; font-size: 13px;")

    def show_audio_preview(self, path: str):
        self.stop_media()
        if self.video_widget:
            self.video_widget.setVisible(False)
        if hasattr(self, "controls_widget"):
            self.controls_widget.setVisible(False)
        self.placeholder_label.setVisible(True)
        self.placeholder_label.setPixmap(QPixmap())
        name = os.path.basename(path)
        self.placeholder_label.setText(f"🎵 [ Detalle de Audio ]\n\n{name}")
        self.placeholder_label.setStyleSheet("color: #f5c2e7; font-weight: bold; font-size: 13px;")

    # Métodos de Control del Reproductor de Video
    def toggle_play_pause(self):
        if not self.media_player:
            return
        if self.media_player.playbackState() == QMediaPlayer.PlayingState:
            self.media_player.pause()
        else:
            self.media_player.play()

    def toggle_mute(self):
        if not self.audio_output:
            return
        if self.vol_slider.value() > 0:
            self._last_volume = self.vol_slider.value()
            self.vol_slider.setValue(0)
        else:
            self.vol_slider.setValue(self._last_volume if self._last_volume > 0 else 10)

    def _on_volume_changed(self, value):
        if self.audio_output:
            self.audio_output.setVolume(value / 100.0)
            if value == 0:
                self.btn_vol.setText("🔇")
            elif value < 40:
                self.btn_vol.setText("🔈")
            elif value < 80:
                self.btn_vol.setText("🔉")
            else:
                self.btn_vol.setText("🔊")

    def _on_position_changed(self, position):
        if not self._is_dragging_slider and self.media_player:
            self.time_slider.setValue(position)
            self._update_time_label(position, self.media_player.duration())

    def _on_duration_changed(self, duration):
        self.time_slider.setRange(0, duration)
        self._update_time_label(self.time_slider.value(), duration)

    def _update_time_label(self, position, duration):
        pos_str = self._format_time(position)
        dur_str = self._format_time(duration)
        self.lbl_video_time.setText(f"{pos_str} / {dur_str}")

    def _format_time(self, ms):
        if ms < 0:
            ms = 0
        s = ms // 1000
        m = s // 60
        s = s % 60
        h = m // 60
        m = m % 60
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _on_slider_pressed(self):
        self._is_dragging_slider = True

    def _on_slider_moved(self, position):
        if self.media_player:
            self._update_time_label(position, self.media_player.duration())

    def _on_slider_released(self):
        self._is_dragging_slider = False
        if self.media_player:
            self.media_player.setPosition(self.time_slider.value())

    def _on_playback_state_changed(self, state):
        if state == QMediaPlayer.PlayingState:
            self.btn_play_pause.setIcon(get_svg_icon("pause.svg"))
        else:
            self.btn_play_pause.setIcon(get_svg_icon("play_arrow.svg"))
