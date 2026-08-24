# src/gui/tabs/editing_media/preview_panel.py
import os
from PySide6.QtWidgets import (
    QFrame, QLabel, QVBoxLayout, QHBoxLayout, QSizePolicy, QWidget, QPushButton, QSlider,
    QGraphicsScene, QGraphicsView
)
from PySide6.QtCore import Qt, QUrl, QSize, QSizeF
from PySide6.QtGui import QPixmap, QIcon, QPainter, QColor

from core.logger.logger_manager import logger
from core.utils.paths import get_src_dir
from gui.styles import (
    get_theme_token,
    apply_player_play_button_style,
    apply_player_loop_button_style,
    apply_edit_subclip_button_style,
    create_checkerboard_pixmap,
)
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
from gui.widgets.volume_control import VolumeControlWidget

try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
    MULTIMEDIA_AVAILABLE = True
except ImportError as e:
    MULTIMEDIA_AVAILABLE = False
    logger.warning(f"PreviewPanel: QtMultimedia no está disponible en este sistema: {e}")

_SVG_DIR = os.path.join(get_src_dir(), "assets", "icons", "svg")

def get_svg_icon(name: str) -> QIcon:
    path = os.path.join(_SVG_DIR, name)
    return QIcon(path) if os.path.exists(path) else QIcon()


class _PreviewVideoView(QGraphicsView):
    """Vista gráfica para renderizar video en el mismo buffer 2D de Qt sin crear ventana nativa HWND."""
    def __init__(self, scene: QGraphicsScene, video_item: QGraphicsVideoItem, parent=None):
        super().__init__(scene, parent)
        self._video_item = video_item
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("QGraphicsView { background: transparent; border: none; }")
        self.viewport().setAutoFillBackground(False)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def refit(self):
        vp_w = self.viewport().width()
        vp_h = self.viewport().height()
        if vp_w <= 0 or vp_h <= 0:
            return

        self.scene().setSceneRect(0, 0, vp_w, vp_h)
        native = self._video_item.nativeSize()
        if native.isEmpty() or native.width() <= 0 or native.height() <= 0:
            self._video_item.setSize(QSizeF(vp_w, vp_h))
            self._video_item.setPos(0, 0)
            return

        scale = min(vp_w / native.width(), vp_h / native.height())
        scaled_w = native.width() * scale
        scaled_h = native.height() * scale
        self._video_item.setSize(QSizeF(scaled_w, scaled_h))
        self._video_item.setPos((vp_w - scaled_w) / 2.0, (vp_h - scaled_h) / 2.0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refit()


class PreviewContainerWidget(QFrame):
    """Contenedor de vista previa rectangular (panorámico) con soporte para imágenes y reproducción de video real con controles."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("previewContainer")
        
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(140)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        # Fondo oscuro y bordes redondeados
        self.setStyleSheet(f"""
            QFrame#previewContainer {{
                background-color: {get_theme_token('fondo_principal', '#0a0a0a')};
                border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-radius: 6px;
            }}
        """)
        
        # 1. Widget de Estado Vacío Estilizado (Centrado Absoluto)
        self.empty_state_widget = QWidget()
        self.empty_state_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        empty_outer = QVBoxLayout(self.empty_state_widget)
        empty_outer.setContentsMargins(0, 0, 0, 0)
        empty_outer.setSpacing(0)
        empty_outer.addStretch(1)

        empty_inner = QWidget()
        empty_inner_layout = QVBoxLayout(empty_inner)
        empty_inner_layout.setContentsMargins(10, 0, 10, 0)
        empty_inner_layout.setSpacing(6)
        empty_inner_layout.setAlignment(Qt.AlignCenter)

        self.lbl_empty_icon = QLabel()
        self.lbl_empty_icon.setAlignment(Qt.AlignCenter)
        empty_ico = get_colored_svg_icon("play_arrow.svg", "#444444", size=36)
        if not empty_ico.isNull():
            self.lbl_empty_icon.setPixmap(empty_ico.pixmap(36, 36))
        empty_inner_layout.addWidget(self.lbl_empty_icon)

        self.lbl_empty_title = QLabel(self.tr("Vista Previa"))
        self.lbl_empty_title.setAlignment(Qt.AlignCenter)
        self.lbl_empty_title.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {get_theme_token('texto_secundario', '#777777')};")
        empty_inner_layout.addWidget(self.lbl_empty_title)

        self.lbl_empty_desc = QLabel(self.tr("Selecciona un archivo multimedia de la lista\npara reproducirlo o ver su detalle"))
        self.lbl_empty_desc.setAlignment(Qt.AlignCenter)
        self.lbl_empty_desc.setStyleSheet("font-size: 11px; color: #555555;")
        empty_inner_layout.addWidget(self.lbl_empty_desc)

        empty_outer.addWidget(empty_inner, 0, Qt.AlignCenter)
        empty_outer.addStretch(1)

        self.layout.addWidget(self.empty_state_widget, 1)

        # 2. Widget de Imagen / Placeholder
        self.placeholder_label = QLabel()
        self.placeholder_label.setAlignment(Qt.AlignCenter)
        self.placeholder_label.setWordWrap(True)
        self.placeholder_label.setVisible(False)
        self.layout.addWidget(self.placeholder_label, 1)
        
        # 2. Widget de Video Real Integrado en Qt
        self.video_widget = None
        self.video_scene = None
        self.video_item = None
        self.media_player = None
        self.audio_output = None
        self._is_dragging_slider = False
        self._last_volume = 10
        
        if MULTIMEDIA_AVAILABLE:
            try:
                self.video_scene = QGraphicsScene(self)
                self.video_scene.setBackgroundBrush(Qt.NoBrush)
                self.video_item = QGraphicsVideoItem()
                self.video_scene.addItem(self.video_item)
                self.video_item.nativeSizeChanged.connect(lambda s: self.video_widget.refit() if self.video_widget else None)

                self.video_widget = _PreviewVideoView(self.video_scene, self.video_item, self)
                self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                self.video_widget.setVisible(False)
                self.layout.addWidget(self.video_widget)
                
                self.media_player = QMediaPlayer(self)
                self.audio_output = QAudioOutput(self)
                self.media_player.setAudioOutput(self.audio_output)
                self.media_player.setVideoOutput(self.video_item)
                
                # Bajar el volumen por defecto a un nivel agradable (10%) para evitar sustos
                self.audio_output.setVolume(0.1)
                
                # Desactivar bucle de video por defecto
                self.media_player.setLoops(1)

            except Exception as ex:
                logger.error(f"PreviewPanel: Error inicializando reproductores multimedia: {ex}")
                self.video_widget = None

        # 3. Controles del Reproductor de Video
        self.controls_widget = QWidget()
        self.controls_widget.setVisible(False)
        controls_v = QVBoxLayout(self.controls_widget)
        controls_v.setContentsMargins(8, 2, 8, 8)
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
        btn_layout.setSpacing(4)

        # Botón Play/Pausa
        self.btn_play_pause = QPushButton()
        self.btn_play_pause.setIconSize(QSize(14, 14))
        self.btn_play_pause.setFixedSize(24, 24)
        apply_player_play_button_style(self.btn_play_pause, is_playing=True, icon_size=14)
        self.btn_play_pause.clicked.connect(self.toggle_play_pause)
        btn_layout.addWidget(self.btn_play_pause)

        # Botón Loop/Repetir
        self._video_loop_active = False  # Por defecto desactivado
        self.btn_loop = QPushButton()
        self.btn_loop.setIconSize(QSize(14, 14))
        self.btn_loop.setFixedSize(24, 24)
        apply_player_loop_button_style(self.btn_loop, is_active=False, icon_size=14)

        self.btn_loop.clicked.connect(self._toggle_video_loop)
        btn_layout.addWidget(self.btn_loop)

        # Botón Editar Subclip
        self.btn_edit_subclip = QPushButton()
        self.btn_edit_subclip.setIconSize(QSize(14, 14))
        self.btn_edit_subclip.setFixedSize(24, 24)
        self._has_subclips = False
        apply_edit_subclip_button_style(self.btn_edit_subclip, has_subclips=False, icon_size=14)
        btn_layout.addWidget(self.btn_edit_subclip)

        # Etiqueta de tiempo
        self.lbl_video_time = QLabel("00:00 / 00:00")
        self.lbl_video_time.setStyleSheet("font-size: 11px; color: #a6adc8; background: transparent; border: none;")
        self.lbl_video_time.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        btn_layout.addWidget(self.lbl_video_time)

        btn_layout.addStretch(1)

        # Control de Volumen Unificado
        self.volume_control = VolumeControlWidget(initial_volume=10, slider_width=50)
        self.volume_control.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.volume_control.volume_changed.connect(self._on_volume_changed)
        btn_layout.addWidget(self.volume_control)

        controls_v.addLayout(btn_layout)
        self.layout.addWidget(self.controls_widget)

        if MULTIMEDIA_AVAILABLE and self.media_player:
            self.media_player.positionChanged.connect(self._on_position_changed)
            self.media_player.durationChanged.connect(self._on_duration_changed)
            self.media_player.playbackStateChanged.connect(self._on_playback_state_changed)
            # El bucle se maneja manualmente (en vez de confiar en QMediaPlayer.setLoops(),
            # cuya aplicación en caliente resultaba poco fiable con algunos backends: a veces
            # había que activar/desactivar el botón más de una vez para que surtiera efecto).
            self.media_player.mediaStatusChanged.connect(self._on_media_status_changed_loop)
        
        self.show_default_state()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self.width()
        if w > 0:
            avail_h = int(w * 0.6)
            self.setFixedHeight(avail_h)
            if hasattr(self, "volume_control") and self.volume_control:
                self.volume_control.set_slider_visible(w >= 280)
            if hasattr(self, "lbl_video_time") and self.lbl_video_time:
                self.lbl_video_time.setVisible(w >= 230)
            if hasattr(self, "_current_movie") and self._current_movie and self.placeholder_label.isVisible():
                movie = self._current_movie
                orig_size = movie.currentImage().size()
                if orig_size.isValid() and not orig_size.isEmpty():
                    scaled_size = orig_size.scaled(max(50, w - 10), max(50, avail_h - 10), Qt.KeepAspectRatio)
                    movie.setScaledSize(scaled_size)
            elif hasattr(self, "_current_image_path") and self._current_image_path and self.placeholder_label.isVisible():
                pixmap = QPixmap(self._current_image_path)
                if not pixmap.isNull():
                    scaled = pixmap.scaled(
                        max(50, w - 10),
                        max(50, avail_h - 10),
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation
                    )
                    self.placeholder_label.setPixmap(scaled)
            elif hasattr(self, "video_widget") and self.video_widget and self.video_widget.isVisible():
                self.video_widget.refit()

    def stop_media(self):
        """Detiene cualquier reproducción de video o animación GIF activa."""
        self._current_image_path = None
        if hasattr(self, "_current_movie") and self._current_movie:
            try:
                self._current_movie.stop()
            except Exception:
                pass
            self._current_movie = None
        if hasattr(self, "placeholder_label") and self.placeholder_label:
            self.placeholder_label.setMovie(None)

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
        if hasattr(self, "empty_state_widget"):
            self.empty_state_widget.setVisible(True)
        self.placeholder_label.setVisible(False)
        self.placeholder_label.setPixmap(QPixmap())

    def show_image_preview(self, path: str):
        self.stop_media()
        self._current_image_path = path
        if hasattr(self, "empty_state_widget"):
            self.empty_state_widget.setVisible(False)
        if self.video_widget:
            self.video_widget.setVisible(False)
        if hasattr(self, "controls_widget"):
            self.controls_widget.setVisible(False)
        
        self.placeholder_label.setVisible(True)
        self.placeholder_label.setText("")
        
        # Reproducir animación si es un GIF animado
        if path.lower().endswith(".gif"):
            from PySide6.QtGui import QMovie
            movie = QMovie(path)
            if movie.isValid():
                self._current_movie = movie
                movie.jumpToFrame(0)
                orig_size = movie.currentImage().size()
                avail_w = max(50, self.width() - 10)
                avail_h = max(50, self.height() - 10)
                if orig_size.isValid() and not orig_size.isEmpty():
                    scaled_size = orig_size.scaled(avail_w, avail_h, Qt.KeepAspectRatio)
                    movie.setScaledSize(scaled_size)
                else:
                    movie.setScaledSize(QSize(avail_w, avail_h))
                self.placeholder_label.setMovie(movie)
                movie.start()
                return

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
            # Dibujar el patrón de ajedrez debajo de la imagen para mostrar transparencias claramente
            bg = create_checkerboard_pixmap(scaled.width(), scaled.height(), square_size=10)
            painter = QPainter(bg)
            painter.drawPixmap(0, 0, scaled)
            painter.end()
            self.placeholder_label.setPixmap(bg)
        else:
            self.placeholder_label.setText(f"[ Error al cargar Imagen ]\n\n{os.path.basename(path)}")
            self.placeholder_label.setStyleSheet("color: #ff6c6b; font-weight: bold; font-size: 13px;")

    def show_video_preview(self, path: str):
        if self.video_widget and self.media_player:
            if hasattr(self, "empty_state_widget"):
                self.empty_state_widget.setVisible(False)
            self.placeholder_label.setVisible(False)
            self.video_widget.setVisible(True)
            self.video_widget.refit()
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
        if hasattr(self, "empty_state_widget"):
            self.empty_state_widget.setVisible(False)
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
        if hasattr(self, "empty_state_widget"):
            self.empty_state_widget.setVisible(False)
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
        if hasattr(self, "volume_control"):
            self.volume_control.toggle_mute()

    def _on_volume_changed(self, value):
        # value puede ser flotante (0.0 a 1.0) o entero (0 a 100)
        float_val = value if isinstance(value, float) else value / 100.0
        if self.audio_output:
            self.audio_output.setVolume(float_val)

    def _on_position_changed(self, position):
        if not self._is_dragging_slider and self.media_player:
            self.time_slider.setValue(position)
            self._update_time_label(position, self.media_player.duration())

    def _on_duration_changed(self, duration):
        self.time_slider.setRange(0, duration)
        self._update_time_label(self.time_slider.value(), duration)

    def _update_time_label(self, position, duration):
        show_hours = bool(duration and duration >= 3600000)
        pos_str = self._format_time(position, show_hours)
        dur_str = self._format_time(duration, show_hours)
        self.lbl_video_time.setText(f"{pos_str} / {dur_str}")

    def _format_time(self, ms, show_hours=False):
        if not ms or ms < 0:
            ms = 0
        ms = int(ms)
        s = ms // 1000
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        if show_hours or h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _on_slider_pressed(self):
        self._is_dragging_slider = True
        if self.media_player:
            self._was_playing_before_drag = (self.media_player.playbackState() == QMediaPlayer.PlayingState)
            if self._was_playing_before_drag:
                self.media_player.pause()

    def _on_slider_moved(self, position):
        if self.media_player:
            self.media_player.setPosition(position)
            self._update_time_label(position, self.media_player.duration())

    def _on_slider_released(self):
        self._is_dragging_slider = False
        if self.media_player:
            self.media_player.setPosition(self.time_slider.value())
            if getattr(self, "_was_playing_before_drag", False):
                self.media_player.play()

    def _on_playback_state_changed(self, state):
        is_playing = (state == QMediaPlayer.PlayingState)
        apply_player_play_button_style(self.btn_play_pause, is_playing=is_playing, icon_size=14)

    def set_edit_subclip_active(self, has_subclips: bool):
        """Actualiza la apariencia 'encendida/apagada' del botón de editar subclips según si
        el medio actualmente mostrado ya tiene subclips guardados."""
        self._has_subclips = has_subclips
        apply_edit_subclip_button_style(self.btn_edit_subclip, has_subclips=has_subclips, icon_size=14)

    def _toggle_video_loop(self):
        """Alterna entre reproducción en bucle y reproducción única."""
        self._video_loop_active = not self._video_loop_active
        apply_player_loop_button_style(self.btn_loop, is_active=self._video_loop_active, icon_size=14)

    def _on_media_status_changed_loop(self, status):
        """Reinicia manualmente la reproducción al llegar al final si el bucle está activo.
        Esto evita depender de QMediaPlayer.setLoops(), que no siempre aplicaba el cambio
        de inmediato al alternar el botón durante la reproducción."""
        if status == QMediaPlayer.MediaStatus.EndOfMedia and getattr(self, "_video_loop_active", False):
            self.media_player.setPosition(0)
            self.media_player.play()
