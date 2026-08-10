# src/gui/dialogs/subclip_dialog.py
import os
import math
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QWidget,
    QSizePolicy, QLineEdit, QFrame, QSplitter, QToolButton, QMenu, QApplication
)
from PySide6.QtCore import Qt, QUrl, QSize, QTimer, Signal
from PySide6.QtGui import QPixmap, QIcon, QPainter, QColor, QPen
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget

from gui.styles import get_theme_token
from gui.widgets.animated_button import AnimatedButton
from gui.tabs.editing_media.editing_media_icons import get_svg_icon
from gui.tabs.editing_media.waveform_widget import AudioWaveformWidget
from core.tabs.editing_media.waveform_cache_manager import WaveformCacheManager
from core.services.editor_integration_manager import EditorIntegrationManager
from core.logger.logger_manager import logger

class SubclipWaveformWidget(AudioWaveformWidget):
    """Forma de onda extendida para edición de subclips con sombreado de In/Out y arrastre con mouse."""
    
    range_changed = Signal(float, float)  # Emite (in_ratio, out_ratio)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.in_ratio = 0.0
        self.out_ratio = 1.0
        self._drag_mode = "none"  # "none", "in", "out", "range"
        self._drag_offset = 0.0

    def set_range_ratios(self, in_r: float, out_r: float):
        self.in_ratio = max(0.0, min(in_r, 1.0))
        self.out_ratio = max(self.in_ratio, min(out_r, 1.0))
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            w = self.width()
            if w <= 0:
                return
            x = event.position().x()
            ratio = max(0.0, min(x / w, 1.0))
            
            x_in = self.in_ratio * w
            x_out = self.out_ratio * w
            
            if abs(x - x_in) <= 12:
                self._drag_mode = "in"
            elif abs(x - x_out) <= 12:
                self._drag_mode = "out"
            elif x_in < x < x_out:
                self._drag_mode = "range"
                self._drag_offset = ratio - self.in_ratio
                self.seek_requested.emit(ratio)
            else:
                self._drag_mode = "none"
                self.seek_requested.emit(ratio)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            w = self.width()
            if w <= 0:
                return
            x = event.position().x()
            ratio = max(0.0, min(x / w, 1.0))
            
            if self._drag_mode == "in":
                self.in_ratio = min(ratio, self.out_ratio - 0.01)
                self.range_changed.emit(self.in_ratio, self.out_ratio)
                self.update()
            elif self._drag_mode == "out":
                self.out_ratio = max(ratio, self.in_ratio + 0.01)
                self.range_changed.emit(self.in_ratio, self.out_ratio)
                self.update()
            elif self._drag_mode == "range":
                range_span = self.out_ratio - self.in_ratio
                new_in = max(0.0, min(ratio - self._drag_offset, 1.0 - range_span))
                self.in_ratio = new_in
                self.out_ratio = new_in + range_span
                self.range_changed.emit(self.in_ratio, self.out_ratio)
                self.seek_requested.emit(ratio)
                self.update()
            else:
                self.seek_requested.emit(ratio)

    def mouseReleaseEvent(self, event):
        self._drag_mode = "none"

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return
            
        # Fondo oscuro limpio
        painter.fillRect(0, 0, w, h, QColor("#141414"))
        
        x_in = int(self.in_ratio * w)
        x_out = int(self.out_ratio * w)
        
        # Sombrear región fuera de rango
        dark_overlay = QColor(0, 0, 0, 160)
        painter.fillRect(0, 0, x_in, h, dark_overlay)
        painter.fillRect(x_out, 0, max(0, w - x_out), h, dark_overlay)
        
        # Sombrear región seleccionada entre In y Out
        highlight = QColor(185, 230, 64, 30)
        painter.fillRect(x_in, 0, max(1, x_out - x_in), h, highlight)
        
        # Dibujar picos de la forma de onda
        if self.peaks:
            num_bars = len(self.peaks)
            step = w / (num_bars - 1) if num_bars > 1 else w
            bar_width = max(1, int(step * 0.65))
            mid_y = h / 2
            
            for i, peak in enumerate(self.peaks):
                val = max(0.06, min(peak, 1.0))
                bar_h = val * h
                x = int(i * step)
                y = int(mid_y - (bar_h / 2))
                
                if x_in <= x <= x_out:
                    color = QColor(get_theme_token('acento_primario', '#B9E640'))
                else:
                    color = QColor('#444444')
                    
                painter.setPen(Qt.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(x, y, bar_width, int(bar_h), 1, 1)

        # Línea de In (Verde con agarrador)
        pen_in = QPen(QColor('#1DC038'), 2, Qt.SolidLine)
        painter.setPen(pen_in)
        painter.drawLine(x_in, 0, x_in, h)
        painter.setBrush(QColor('#1DC038'))
        painter.drawRect(x_in - 3, 0, 6, 8)
        
        # Línea de Out (Rojo con agarrador)
        pen_out = QPen(QColor('#FF5555'), 2, Qt.SolidLine)
        painter.setPen(pen_out)
        painter.drawLine(x_out, 0, x_out, h)
        painter.setBrush(QColor('#FF5555'))
        painter.drawRect(x_out - 3, h - 8, 6, 8)
        
        # Línea de Playhead (Blanca)
        playhead_x = int(self._playback_ratio * w)
        pen_ph = QPen(QColor('#FFFFFF'), 2, Qt.SolidLine)
        painter.setPen(pen_ph)
        painter.drawLine(playhead_x, 0, playhead_x, h)

        painter.end()


class SubclipItemWidget(QWidget):
    """Elemento individual de la lista de subclips creados."""
    def __init__(self, index: int, name: str, in_sec: float, out_sec: float, on_preview, on_delete, on_rename, parent=None):
        super().__init__(parent)
        self.setFixedHeight(58)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 4, 6, 4)
        layout.setSpacing(2)

        # Fila superior: play + nombre editable + botón eliminar
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(6)

        self.btn_play = QPushButton()
        self.btn_play.setFixedSize(22, 22)
        self.btn_play.setIcon(get_svg_icon("play_arrow.svg"))
        self.btn_play.setIconSize(QSize(14, 14))
        self.btn_play.setStyleSheet(f"""
            QPushButton {{
                background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                border: 1px solid {get_theme_token('borde_sutil', '#333333')};
                border-radius: 11px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('acento_primario', '#B9E640')};
            }}
        """)
        self.btn_play.clicked.connect(lambda: on_preview(index))
        top_row.addWidget(self.btn_play)
        
        self.txt_name = QLineEdit(name)
        self.txt_name.setStyleSheet("""
            QLineEdit {
                background: #222;
                color: #B9E640;
                border: 1px solid #333;
                border-radius: 4px;
                padding: 1px 4px;
                font-size: 11px;
                font-weight: bold;
            }
            QLineEdit:focus {
                border: 1px solid #B9E640;
            }
        """)
        self.txt_name.setFixedHeight(20)
        self.txt_name.textChanged.connect(lambda t: on_rename(index, t))
        top_row.addWidget(self.txt_name, 1)

        btn_del = QPushButton()
        btn_del.setIcon(get_svg_icon("delete.svg"))
        btn_del.setIconSize(QSize(15, 15))
        btn_del.setFixedSize(22, 22)
        btn_del.setToolTip("Eliminar subclip")
        btn_del.setStyleSheet("""
            QPushButton { background: transparent; border: none; border-radius: 4px; }
            QPushButton:hover { background: rgba(229,57,53,160); }
        """)
        btn_del.clicked.connect(lambda: on_delete(index))
        top_row.addWidget(btn_del)
        layout.addLayout(top_row)

        # Fila inferior: tiempos
        dur = out_sec - in_sec
        in_fmt = self._format_time(in_sec)
        out_fmt = self._format_time(out_sec)
        lbl = QLabel(f"{in_fmt} ➔ {out_fmt} ({dur:.2f}s)")
        lbl.setStyleSheet("color: #999; font-size: 11px;")
        layout.addWidget(lbl)

    def _format_time(self, seconds: float) -> str:
        ms = int((seconds % 1) * 1000)
        total_sec = int(seconds)
        s = total_sec % 60
        m = (total_sec // 60) % 60
        h = total_sec // 3600
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


class SubclipEditorDialog(QDialog):
    """Diálogo Modal para recortar partes de un medio (In/Out points) y enviar subclips."""
    
    def __init__(self, media_path: str, media_type: str = "video", duration_sec: float = 0.0, existing_subclips: list = None, initial_in_sec: float = None, initial_out_sec: float = None, parent=None):
        super().__init__(parent)
        self.media_path = media_path
        self.media_type = media_type.lower()
        self.duration_sec = duration_sec or 1.0
        self.in_sec = initial_in_sec if initial_in_sec is not None else 0.0
        self.out_sec = initial_out_sec if initial_out_sec is not None else self.duration_sec
        self.subclips = list(existing_subclips) if existing_subclips else []

        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setWindowTitle(f"Edición de Subclips - {os.path.basename(media_path)}")
        self.resize(960, 600)
        self.setMinimumSize(800, 480)
        self.old_pos = None

        borde_color = get_theme_token('borde_normal', '#3d3d3d')
        self.setStyleSheet("""
            QDialog {
                background-color: #141414;
                border: 1px solid %s;
                border-radius: 12px;
            }
        """ % borde_color)
        
        self.init_ui()
        self.init_media_player()
        self.load_waveform()

    def title_mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.old_pos = event.globalPosition().toPoint()

    def title_mouseMoveEvent(self, event):
        if self.old_pos is not None:
            delta = event.globalPosition().toPoint() - self.old_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.old_pos = event.globalPosition().toPoint()

    def title_mouseReleaseEvent(self, event):
        self.old_pos = None

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Barra de Título Customizada (Sin Bordes) ─────────────────────────
        title_bar = QWidget()
        title_bar.setObjectName("subclipTitleBar")
        title_bar.setFixedHeight(42)
        borde_sutil = get_theme_token('borde_sutil', '#2d2d2d')
        title_bar.setStyleSheet("""
            QWidget#subclipTitleBar {
                background-color: #1e1e1e;
                border-top-left-radius: 12px;
                border-top-right-radius: 12px;
                border-bottom: 1px solid %s;
            }
        """ % borde_sutil)
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(14, 0, 14, 0)

        title_lbl = QLabel(f"Edición de Subclips (In/Out) — {os.path.basename(self.media_path)}")
        title_lbl.setStyleSheet("font-weight: bold; font-size: 13px; color: #ffffff;")
        tb_layout.addWidget(title_lbl)
        tb_layout.addStretch()

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(26, 26)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #c62828;
                color: white;
                font-size: 12px;
                font-weight: bold;
                border: none;
                border-radius: 13px;
            }
            QPushButton:hover { background-color: #e53935; }
        """)
        btn_close.clicked.connect(self.reject)
        tb_layout.addWidget(btn_close)

        title_bar.mousePressEvent   = self.title_mousePressEvent
        title_bar.mouseMoveEvent    = self.title_mouseMoveEvent
        title_bar.mouseReleaseEvent = self.title_mouseReleaseEvent
        main_layout.addWidget(title_bar)

        # ── Contenido Principal ────────────────────────────────────────────────
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(14, 14, 14, 14)
        content_layout.setSpacing(12)

        splitter = QSplitter(Qt.Horizontal)
        content_layout.addWidget(splitter)

        # ── Columna Izquierda: Reproductor + Waveform + Controles In/Out ──────
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        # Área de Video / Vista Previa
        self.preview_container = QFrame()
        borde_norm = get_theme_token('borde_normal', '#2d2d2d')
        self.preview_container.setStyleSheet("""
            QFrame {
                background-color: #0d0d0d;
                border: 1px solid %s;
                border-radius: 8px;
            }
        """ % borde_norm)
        prev_layout = QVBoxLayout(self.preview_container)
        prev_layout.setContentsMargins(0, 0, 0, 0)

        self.video_widget = QVideoWidget()
        prev_layout.addWidget(self.video_widget)
        
        if self.media_type != "video":
            self.video_widget.setVisible(False)
            self.lbl_audio_art = QLabel(self.tr("Vista Previa de Audio"))
            self.lbl_audio_art.setAlignment(Qt.AlignCenter)
            self.lbl_audio_art.setStyleSheet("color: #89b4fa; font-weight: bold; font-size: 16px;")
            prev_layout.addWidget(self.lbl_audio_art, 1)

        left_layout.addWidget(self.preview_container, 1)

        # Form de onda interactivo (Waveform)
        self.waveform_widget = SubclipWaveformWidget()
        self.waveform_widget.seek_requested.connect(self._on_waveform_seek)
        self.waveform_widget.range_changed.connect(self._on_waveform_range_changed)
        left_layout.addWidget(self.waveform_widget)

        # Barra de Controles e Información de Tiempos
        ctrl_bar = QHBoxLayout()
        ctrl_bar.setSpacing(6)

        # Botón Play/Pause
        self.btn_play = QPushButton()
        self.btn_play.setFixedSize(34, 34)
        self.btn_play.setIcon(get_svg_icon("play_arrow.svg"))
        self.btn_play.setIconSize(QSize(18, 18))
        self.btn_play.clicked.connect(self._toggle_play_pause)
        from gui.styles import apply_player_play_button_style
        apply_player_play_button_style(self.btn_play, is_playing=False, icon_size=18)
        ctrl_bar.addWidget(self.btn_play)
        
        ctrl_bar.addSpacing(8)

        # Volume control
        from gui.widgets.volume_control import VolumeControlWidget
        self.volume_control = VolumeControlWidget(initial_volume=100, slider_width=60)
        self.volume_control.volume_changed.connect(self._on_volume_changed)
        ctrl_bar.addWidget(self.volume_control)
        
        ctrl_bar.addStretch()

        # Botones In [I] y Out [O] and inputs
        self.btn_set_in = QPushButton(self.tr("[ I ] In"))
        self.btn_set_in.setFixedHeight(28)
        self.btn_set_in.setToolTip(self.tr("Establecer punto de entrada (Tecla I)"))
        self.btn_set_in.setStyleSheet("""
            QPushButton {
                background-color: #1a271a;
                border: 1px solid #1DC038;
                color: #1DC038;
                font-weight: bold;
                border-radius: 6px;
                padding: 0 8px;
            }
            QPushButton:hover { background-color: #1DC038; color: white; }
        """)
        self.btn_set_in.clicked.connect(self._set_in_point)
        ctrl_bar.addWidget(self.btn_set_in)

        _time_style = "font-size: 12px; padding: 2px 4px; border-radius: 6px; background: #1e1e1e; border: 1px solid #333;"
        self.input_time_start = QLineEdit(self._format_seconds_ms(self.in_sec))
        self.input_time_start.setFixedSize(90, 28)
        self.input_time_start.setAlignment(Qt.AlignCenter)
        self.input_time_start.setStyleSheet(_time_style)
        self.input_time_start.editingFinished.connect(self._on_time_input_changed)
        ctrl_bar.addWidget(self.input_time_start)

        sep = QLabel("—")
        sep.setAlignment(Qt.AlignCenter)
        sep.setStyleSheet("color: #666; font-size: 15px;")
        ctrl_bar.addWidget(sep)

        self.input_time_end = QLineEdit(self._format_seconds_ms(self.out_sec))
        self.input_time_end.setFixedSize(90, 28)
        self.input_time_end.setAlignment(Qt.AlignCenter)
        self.input_time_end.setStyleSheet(_time_style)
        self.input_time_end.editingFinished.connect(self._on_time_input_changed)
        ctrl_bar.addWidget(self.input_time_end)

        self.btn_set_out = QPushButton(self.tr("[ O ] Out"))
        self.btn_set_out.setFixedHeight(28)
        self.btn_set_out.setToolTip(self.tr("Establecer punto de salida (Tecla O)"))
        self.btn_set_out.setStyleSheet("""
            QPushButton {
                background-color: #2b1a1a;
                border: 1px solid #FF5555;
                color: #FF5555;
                font-weight: bold;
                border-radius: 6px;
                padding: 0 8px;
            }
            QPushButton:hover { background-color: #FF5555; color: white; }
        """)
        self.btn_set_out.clicked.connect(self._set_out_point)
        ctrl_bar.addWidget(self.btn_set_out)

        ctrl_bar.addSpacing(8)

        # Botón para Añadir Subclip
        self.btn_add_subclip = QPushButton()
        self.btn_add_subclip.setIcon(get_svg_icon("add.svg"))
        self.btn_add_subclip.setIconSize(QSize(18, 18))
        self.btn_add_subclip.setFixedSize(34, 34)
        self.btn_add_subclip.setToolTip(self.tr("Añadir subclip"))
        self.btn_add_subclip.setStyleSheet("""
            QPushButton { background-color: #1DC038; border: none; border-radius: 17px; }
            QPushButton:hover { background-color: #B9E640; }
        """)
        self.btn_add_subclip.clicked.connect(self._add_current_subclip)
        ctrl_bar.addWidget(self.btn_add_subclip)
        
        ctrl_bar.addStretch()
        
        # Reloj global
        self.lbl_time_info = QLabel("00:00:00 / 00:00:00")
        self.lbl_time_info.setStyleSheet("color: #cdd6f4; font-size: 11px; font-weight: bold;")
        ctrl_bar.addWidget(self.lbl_time_info)

        left_layout.addLayout(ctrl_bar)
        splitter.addWidget(left_widget)

        # ── Columna Derecha: Lista de Subclips Guardados + Enviar NLE ─────────
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        lbl_list_title = QLabel(self.tr("Subclips del Medio"))
        lbl_list_title.setStyleSheet("font-weight: bold; font-size: 13px; color: white;")
        right_layout.addWidget(lbl_list_title)

        self.list_subclips = QListWidget()
        self.list_subclips.setStyleSheet("""
            QListWidget {
                background-color: #121212;
                border: 1px solid %s;
                border-radius: 12px;
                outline: none;
            }
            QListWidget::item {
                background-color: #1a1a1a;
                border-bottom: 1px solid #222;
                border-radius: 0px;
                padding: 0px;
                margin: 0px;
            }
            QListWidget::item:selected {
                background-color: #1b3b22;
                border-bottom: 1px solid #224;
            }
        """ % borde_norm)
        right_layout.addWidget(self.list_subclips, 1)

        # Botón Split de Envío a Editores
        self.btn_send = QToolButton()
        self.btn_send.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_send.setPopupMode(QToolButton.MenuButtonPopup)
        self.btn_send.setFixedHeight(38)
        self.btn_send.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # Send button
        bg_elem = get_theme_token('fondo_elemento', '#2d2d2d')
        select_bg = get_theme_token('seleccion_fondo', '#3d3d3d')
        
        self.btn_send.setStyleSheet("""
            QToolButton {
                background-color: %s;
                border: 1px solid #444444;
                border-radius: 8px;
                color: #ffffff;
                font-weight: bold;
                padding-left: 10px;
            }
            QToolButton::menu-button {
                border-left: 1px solid #444444;
                width: 22px;
                border-top-right-radius: 8px;
                border-bottom-right-radius: 8px;
            }
            QToolButton:hover {
                background-color: %s;
            }
        """ % (bg_elem, select_bg))
        
        self.send_menu = QMenu(self.btn_send)
        self.action_send_single = self.send_menu.addAction(self.tr("Enviar solo subclip actual"))
        self.btn_send.setMenu(self.send_menu)
        
        self.btn_send.clicked.connect(self._on_send_subclips_clicked)
        self.action_send_single.triggered.connect(self._on_send_single_subclip_clicked)
        
        right_layout.addWidget(self.btn_send)
        splitter.addWidget(right_widget)

        splitter.setSizes([600, 320])
        main_layout.addWidget(content_widget, 1)
        self._update_send_button()
        self._refresh_subclip_list()

    def init_media_player(self):
        self.media_player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.media_player.setAudioOutput(self.audio_output)
        
        if self.media_type == "video":
            self.media_player.setVideoOutput(self.video_widget)
            
        self.media_player.setSource(QUrl.fromLocalFile(self.media_path))
        self.media_player.positionChanged.connect(self._on_player_position_changed)
        self.media_player.durationChanged.connect(self._on_player_duration_changed)

    def load_waveform(self):
        self.waveform_widget.set_audio_path(self.media_path)
        mgr = WaveformCacheManager.get_instance()
        peaks = mgr.get_cached_peaks(self.media_path)
        if peaks is not None:
            self.waveform_widget.set_peaks(peaks)
        else:
            self.waveform_widget.set_loading(True)
            mgr.waveform_loaded.connect(self._on_waveform_loaded)
            mgr.request_waveform(self.media_path)

    def _on_waveform_loaded(self, path: str, peaks: list):
        if path == self.media_path:
            self.waveform_widget.set_peaks(peaks)

    def keyPressEvent(self, event):
        """Maneja las atajos de teclado I (In), O (Out) y Espacio (Play/Pause)."""
        key = event.key()
        if key == Qt.Key_I:
            self._set_in_point()
        elif key == Qt.Key_O:
            self._set_out_point()
        elif key == Qt.Key_Space:
            self._toggle_play_pause()
        else:
            super().keyPressEvent(event)

    def _toggle_play_pause(self):
        if self.media_player.playbackState() == QMediaPlayer.PlayingState:
            self.media_player.pause()
            self.btn_play.setIcon(get_svg_icon("play_arrow.svg"))
        else:
            self.media_player.play()
            self.btn_play.setIcon(get_svg_icon("pause.svg"))

    def _set_in_point(self):
        pos_sec = self.media_player.position() / 1000.0
        if pos_sec >= self.out_sec:
            pos_sec = max(0.0, self.out_sec - 0.5)
        self.in_sec = pos_sec
        self._update_waveform_range()
        self._update_time_label()

    def _set_out_point(self):
        pos_sec = self.media_player.position() / 1000.0
        if pos_sec <= self.in_sec:
            pos_sec = min(self.duration_sec, self.in_sec + 0.5)
        self.out_sec = pos_sec
        self._update_waveform_range()
        self._update_time_label()

    def _update_waveform_range(self):
        if self.duration_sec > 0:
            in_r = self.in_sec / self.duration_sec
            out_r = self.out_sec / self.duration_sec
            self.waveform_widget.set_range_ratios(in_r, out_r)

    def _on_waveform_seek(self, ratio: float):
        if self.duration_sec > 0:
            pos_ms = int(ratio * self.duration_sec * 1000)
            self.media_player.setPosition(pos_ms)

    def _on_waveform_range_changed(self, in_r: float, out_r: float):
        if self.duration_sec > 0:
            self.in_sec = in_r * self.duration_sec
            self.out_sec = out_r * self.duration_sec
            self._update_time_label()

    def _on_player_position_changed(self, pos_ms: int):
        pos_sec = pos_ms / 1000.0
        if self.duration_sec > 0:
            ratio = pos_sec / self.duration_sec
            self.waveform_widget.set_playback_ratio(ratio)
        self._update_time_label()

    def _on_player_duration_changed(self, dur_ms: int):
        if dur_ms > 0:
            self.duration_sec = dur_ms / 1000.0
            if self.out_sec > self.duration_sec or self.out_sec <= 0:
                self.out_sec = self.duration_sec
            self._update_waveform_range()
            self._update_time_label()

    def _update_time_label(self):
        pos_sec = self.media_player.position() / 1000.0
        cur_fmt = self._format_seconds(pos_sec)
        dur_fmt = self._format_seconds(self.duration_sec)
        
        self.lbl_time_info.setText(f"{cur_fmt} / {dur_fmt}")
        if not self.input_time_start.hasFocus():
            self.input_time_start.setText(self._format_seconds_ms(self.in_sec))
        if not self.input_time_end.hasFocus():
            self.input_time_end.setText(self._format_seconds_ms(self.out_sec))

    def _format_seconds(self, seconds: float) -> str:
        s = int(seconds) % 60
        m = (int(seconds) // 60) % 60
        h = int(seconds) // 3600
        return f"{h:02d}:{m:02d}:{s:02d}"
        
    def _format_seconds_ms(self, seconds: float) -> str:
        ms = int((seconds % 1) * 1000)
        s = int(seconds) % 60
        m = (int(seconds) // 60) % 60
        h = int(seconds) // 3600
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

    def _parse_time_ms(self, time_str: str) -> float:
        try:
            parts = time_str.split(":")
            if len(parts) == 3:
                h = float(parts[0])
                m = float(parts[1])
                s = float(parts[2])
                return h * 3600 + m * 60 + s
        except Exception:
            pass
        return None

    def _on_time_input_changed(self):
        new_in = self._parse_time_ms(self.input_time_start.text())
        new_out = self._parse_time_ms(self.input_time_end.text())
        
        if new_in is not None:
            self.in_sec = max(0.0, min(new_in, self.duration_sec))
        if new_out is not None:
            self.out_sec = max(0.0, min(new_out, self.duration_sec))
            
        if self.in_sec >= self.out_sec:
            self.in_sec = max(0.0, self.out_sec - 0.5)
            
        self._update_waveform_range()
        self._update_time_label()

    def _on_volume_changed(self, value):
        float_val = value if isinstance(value, float) else value / 100.0
        self.audio_output.setVolume(float_val)

    def _add_current_subclip(self):
        if self.out_sec <= self.in_sec:
            return
            
        count = len(self.subclips) + 1
        sub_name = f"{os.path.splitext(os.path.basename(self.media_path))[0]}_clip{count:02d}"
        
        clip_data = {
            "name": sub_name,
            "in": self.in_sec,
            "out": self.out_sec
        }
        self.subclips.append(clip_data)
        self._refresh_subclip_list()
        self._update_send_button()

    def _refresh_subclip_list(self):
        self.list_subclips.clear()
        for idx, sc in enumerate(self.subclips):
            item = QListWidgetItem(self.list_subclips)
            w = SubclipItemWidget(
                index=idx,
                name=sc["name"],
                in_sec=sc["in"],
                out_sec=sc["out"],
                on_preview=self._preview_subclip,
                on_delete=self._delete_subclip,
                on_rename=self._rename_subclip
            )
            item.setSizeHint(QSize(220, 66))
            self.list_subclips.setItemWidget(item, w)

    def _preview_subclip(self, index: int):
        if 0 <= index < len(self.subclips):
            sc = self.subclips[index]
            self.media_player.setPosition(int(sc["in"] * 1000))
            self.media_player.play()
            self.btn_play.setIcon(get_svg_icon("pause.svg"))

    def _delete_subclip(self, index: int):
        if 0 <= index < len(self.subclips):
            self.subclips.pop(index)
            self._refresh_subclip_list()
            self._update_send_button()

    def _rename_subclip(self, index: int, new_name: str):
        if 0 <= index < len(self.subclips):
            self.subclips[index]["name"] = new_name

    def get_subclips(self) -> list:
        """Devuelve la lista actual de subclips creados."""
        return list(self.subclips)

    def _update_send_button(self):
        editor_mgr = EditorIntegrationManager.get_instance()
        active = editor_mgr.active_editor if editor_mgr else None
        
        if not active:
            self.btn_send.setText(self.tr("Ningún editor conectado"))
            self.btn_send.setIcon(QIcon())
            self.btn_send.setEnabled(False)
            return

        icon_file = "premiere pro.svg" if active == "premiere" else "davinci resolve.svg"
        
        count = len(self.subclips)
        if count > 0:
            self.btn_send.setText(f"Enviar ({count}) subclips")
        else:
            self.btn_send.setText(f"Enviar rango actual")
            
        icon = get_svg_icon(icon_file)
        if not icon.isNull():
            self.btn_send.setIcon(icon)
            self.btn_send.setIconSize(QSize(20, 20))
            
        self.btn_send.setEnabled(True)

    def _on_send_subclips_clicked(self):
        editor_mgr = EditorIntegrationManager.get_instance()
        if not editor_mgr or not editor_mgr.active_editor:
            return

        items_to_send = self.subclips if self.subclips else [{
            "name": f"{os.path.splitext(os.path.basename(self.media_path))[0]}_range",
            "in": self.in_sec,
            "out": self.out_sec
        }]
        
        payload = {
            "filePath": self.media_path.replace('\\', '/'),
            "subclips": items_to_send
        }
        
        logger.info(f"[SubclipDialog] Enviando {len(items_to_send)} subclips a {editor_mgr.active_editor}")
        editor_mgr.send_subclips(payload)
        self.accept()

    def _on_send_single_subclip_clicked(self):
        editor_mgr = EditorIntegrationManager.get_instance()
        if not editor_mgr or not editor_mgr.active_editor:
            return
            
        payload = {
            "filePath": self.media_path.replace('\\', '/'),
            "subclips": [{
                "name": f"{os.path.splitext(os.path.basename(self.media_path))[0]}_range",
                "in": self.in_sec,
                "out": self.out_sec
            }]
        }
        
        logger.info(f"[SubclipDialog] Enviando rango actual como subclip a {editor_mgr.active_editor}")
        editor_mgr.send_subclips(payload)
        self.accept()

    def closeEvent(self, event):
        self.media_player.stop()
        super().closeEvent(event)
