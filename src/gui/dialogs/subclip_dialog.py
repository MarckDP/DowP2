# src/gui/dialogs/subclip_dialog.py
import os
import math
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QWidget,
    QSizePolicy, QLineEdit, QFrame, QSplitter, QToolButton, QMenu, QApplication, QScrollArea
)
from PySide6.QtCore import Qt, QUrl, QSize, QTimer, Signal, QEvent
from PySide6.QtGui import QPixmap, QIcon, QPainter, QColor, QPen
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget

from gui.styles import get_theme_token
from gui.widgets.animated_button import AnimatedButton
from gui.widgets.send_state_button import SendButtonState
from gui.tabs.editing_media.editing_media_icons import get_svg_icon
from core.tabs.editing_media.waveform_cache_manager import WaveformCacheManager
from core.services.editor_integration_manager import EditorIntegrationManager
from core.logger.logger_manager import logger

class SubclipWaveformWidget(QWidget):
    """Forma de onda profesional con pares min/max, estilo SoundQ/Premiere."""
    
    seek_requested = Signal(float)
    range_changed = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.in_ratio = 0.0
        self.out_ratio = 1.0
        self._drag_mode = "none"
        self._drag_offset = 0.0
        self.zoom_y = 1.0
        self._playback_ratio = 0.0
        
        # Datos de alta resolución: lista de tuplas (min, max) normalizadas -1..1
        self._hires_peaks = []  # Datos crudos de alta res
        self._display_peaks = []  # Re-muestreados al ancho actual

        # Rangos (in_ratio, out_ratio) de subclips ya guardados, para mostrarlos de fondo
        # con baja opacidad mientras se crea uno nuevo.
        self._saved_subclip_ratios = []
        
        self.is_loading = False
        self.loading_phase = 0.0
        self.audio_path = ""

        # Estados de descarga en alta calidad (medios remotos pendientes) y error
        self.is_downloading = False
        self.is_error = False
        self.error_message = ""
        
        self.setMinimumHeight(50)
        self.setMaximumHeight(16777215)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        from PySide6.QtCore import QTimer
        self.loading_timer = QTimer(self)
        self.loading_timer.setInterval(30)
        self.loading_timer.timeout.connect(self._animate_loading)

    def set_loading(self, loading: bool):
        self.is_loading = loading
        if loading:
            self._hires_peaks = []
            self._display_peaks = []
            if not self.loading_timer.isActive():
                self.loading_timer.start()
        else:
            self.loading_timer.stop()
        self.update()

    def _animate_loading(self):
        import math
        self.loading_phase += 0.15
        if self.loading_phase > 2 * math.pi:
            self.loading_phase -= 2 * math.pi
        self.update()

    def set_downloading(self, downloading: bool):
        """Activa/desactiva la animación de 'descargando medio en alta calidad', distinta a la de carga de waveform local."""
        self.is_downloading = downloading
        if downloading:
            self.is_error = False
            self._hires_peaks = []
            self._display_peaks = []
            if not self.loading_timer.isActive():
                self.loading_timer.start()
        elif not self.is_loading:
            self.loading_timer.stop()
        self.update()

    def hideEvent(self, event):
        super().hideEvent(event)
        if hasattr(self, "loading_timer") and self.loading_timer.isActive():
            self.loading_timer.stop()

    def set_error(self, is_error: bool, message: str = ""):
        """Muestra un estado de error (p.ej. falló la descarga en alta calidad) en la zona de la waveform."""
        self.is_error = is_error
        self.error_message = message
        if is_error:
            self.is_downloading = False
            self.is_loading = False
            self.loading_timer.stop()
        self.update()

    def set_audio_path(self, path: str):
        self.audio_path = path or ""
        self._hires_peaks = []
        self._display_peaks = []
        if not path:
            self.set_loading(False)
        self.update()

    def set_hires_peaks(self, peaks: list):
        """Asigna picos min/max de alta resolución y re-muestrea."""
        self._hires_peaks = list(peaks) if peaks else []
        self._resample_to_width()
        self.set_loading(False)
        self.update()

    def _resample_to_width(self):
        """Re-muestrea _hires_peaks al número de columnas de píxeles del widget."""
        if not self._hires_peaks:
            self._display_peaks = []
            return
        w = self.width()
        if w <= 0:
            return
        n = len(self._hires_peaks)
        target = w  # 1 columna por píxel
        if n == target:
            self._display_peaks = list(self._hires_peaks)
            return
        
        self._display_peaks = []
        if target <= n:
            # Downsampling: tomar el pico mínimo y máximo del bloque
            for i in range(target):
                start_f = i * n / target
                end_f = (i + 1) * n / target
                start_idx = int(start_f)
                end_idx = max(start_idx + 1, int(end_f))
                end_idx = min(end_idx, n)
                
                block_min = 0.0
                block_max = 0.0
                for j in range(start_idx, end_idx):
                    mn, mx = self._hires_peaks[j]
                    if mn < block_min:
                        block_min = mn
                    if mx > block_max:
                        block_max = mx
                self._display_peaks.append((block_min, block_max))
        else:
            # Upsampling (Zoom in profundo): Interpolación lineal suave entre picos
            for i in range(target):
                pos = i * (n - 1) / max(1, target - 1)
                idx = int(pos)
                frac = pos - idx
                if idx >= n - 1:
                    self._display_peaks.append(self._hires_peaks[-1])
                else:
                    mn1, mx1 = self._hires_peaks[idx]
                    mn2, mx2 = self._hires_peaks[idx + 1]
                    interp_min = mn1 * (1.0 - frac) + mn2 * frac
                    interp_max = mx1 * (1.0 - frac) + mx2 * frac
                    self._display_peaks.append((interp_min, interp_max))

    def resizeEvent(self, event):
        self._resample_to_width()
        self.update()

    def set_range_ratios(self, in_r: float, out_r: float):
        self.in_ratio = max(0.0, min(in_r, 1.0))
        self.out_ratio = max(self.in_ratio, min(out_r, 1.0))
        self.update()

    def set_saved_subclip_ratios(self, ranges: list):
        """Actualiza los rangos (in_ratio, out_ratio) de los subclips ya guardados, dibujados
        de fondo con baja opacidad para poder ver cuántos hay y dónde están mientras se crean más."""
        self._saved_subclip_ratios = list(ranges) if ranges else []
        self.update()

    def set_playback_ratio(self, ratio: float):
        self._playback_ratio = max(0.0, min(ratio, 1.0))
        self.update()

    def get_playback_ratio(self) -> float:
        return self._playback_ratio

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            w = self.width()
            if w <= 0:
                return
            x = event.position().x()
            y = event.position().y()
            ratio = max(0.0, min(x / w, 1.0))
            
            x_in = self.in_ratio * w
            x_out = self.out_ratio * w
            
            if abs(x - x_in) <= 10:
                self._drag_mode = "in"
            elif abs(x - x_out) <= 10:
                self._drag_mode = "out"
            elif y <= 16 and x_in <= x <= x_out:
                # Arrastrar el rango de selección desde la barra/agarrador superior sin mover el playhead
                self._drag_mode = "range"
                self._drag_offset = ratio - self.in_ratio
            else:
                self._drag_mode = "none"
                self.seek_requested.emit(ratio)
                
        elif event.button() == Qt.RightButton:
            w = self.width()
            if w > 0:
                x = event.position().x()
                ratio = max(0.0, min(x / w, 1.0))
                self._drag_mode = "right_click_select"
                self._right_click_start = ratio
                self.in_ratio = ratio
                self.out_ratio = ratio
                self.range_changed.emit(self.in_ratio, self.out_ratio)
                self.update()

    def mouseMoveEvent(self, event):
        w = self.width()
        if w <= 0:
            return
        x = event.position().x()
        y = event.position().y()
        ratio = max(0.0, min(x / w, 1.0))
        x_in = self.in_ratio * w
        x_out = self.out_ratio * w

        if event.buttons() & Qt.LeftButton:
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
                self.update()
            else:
                self.seek_requested.emit(ratio)
        elif event.buttons() & Qt.RightButton:
            if getattr(self, "_drag_mode", "") == "right_click_select":
                start_r = getattr(self, "_right_click_start", ratio)
                self.in_ratio = min(start_r, ratio)
                self.out_ratio = max(start_r, ratio)
                # Para evitar que el rango sea 0 si soltamos en el mismo pixel
                if self.in_ratio == self.out_ratio:
                    self.out_ratio = min(self.in_ratio + 0.001, 1.0)
                self.range_changed.emit(self.in_ratio, self.out_ratio)
                self.update()
        else:
            # Feedback visual de cursores al pasar por encima
            if abs(x - x_in) <= 10 or abs(x - x_out) <= 10:
                self.setCursor(Qt.SizeHorCursor)
            elif y <= 16 and x_in <= x <= x_out:
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            if getattr(self, "_drag_mode", "") == "right_click_select":
                # Si el usuario solo hizo clic (sin arrastrar) reseteamos el In/Out
                if abs(self.in_ratio - self.out_ratio) < 0.005:
                    self.in_ratio = 0.0
                    self.out_ratio = 1.0
                    self.range_changed.emit(self.in_ratio, self.out_ratio)
                    self.update()
        self._drag_mode = "none"

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            w = self.width()
            if w <= 0:
                return
            x = event.position().x()
            y = event.position().y()
            
            x_in = self.in_ratio * w
            x_out = self.out_ratio * w
            
            # Si hace doble clic en el área del agarrador superior, resetear in/out
            if y <= 16 and x_in <= x <= x_out:
                self.in_ratio = 0.0
                self.out_ratio = 1.0
                self.range_changed.emit(self.in_ratio, self.out_ratio)
                self.update()

    def paintEvent(self, event):
        import math
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)  # Líneas nítidas
        
        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return
            
        # Fondo oscuro
        painter.fillRect(0, 0, w, h, QColor("#0d0d0d"))
        
        mid_y = h / 2.0
        x_in = int(self.in_ratio * w)
        x_out = int(self.out_ratio * w)

        # Subclips ya guardados: franjas de baja opacidad de fondo, para ver cuántos hay
        # y dónde están mientras se crea uno nuevo.
        saved_color = QColor(64, 169, 230, 45)
        saved_border = QPen(QColor(64, 169, 230, 120), 1, Qt.DashLine)
        for sub_in_r, sub_out_r in self._saved_subclip_ratios:
            sx_in = int(sub_in_r * w)
            sx_out = int(sub_out_r * w)
            painter.fillRect(sx_in, 0, max(1, sx_out - sx_in), h, saved_color)
            painter.setPen(saved_border)
            painter.drawLine(sx_in, 0, sx_in, h)
            painter.drawLine(sx_out, 0, sx_out, h)

        # Fondo sutil de la zona seleccionada
        highlight = QColor(185, 230, 64, 15)
        painter.fillRect(x_in, 0, max(1, x_out - x_in), h, highlight)
        
        # Línea central (eje 0)
        painter.setPen(QPen(QColor(60, 60, 60), 1))
        painter.drawLine(0, int(mid_y), w, int(mid_y))
        
        if self.is_downloading:
            # Animación de "descargando medio en alta calidad" (distinta a la carga de waveform local):
            # barra de progreso indeterminada que recorre el ancho del widget.
            bar_h = 4
            bar_y = int(mid_y - bar_h / 2)
            painter.fillRect(0, bar_y, w, bar_h, QColor(40, 40, 40))
            sweep_w = max(40, int(w * 0.18))
            phase_ratio = (math.sin(self.loading_phase) + 1) / 2.0  # 0..1
            sweep_x = int(phase_ratio * max(1, w - sweep_w))
            painter.fillRect(sweep_x, bar_y, sweep_w, bar_h, QColor(get_theme_token('acento_primario', '#B9E640')))

            painter.setPen(QPen(QColor('#cdd6f4')))
            painter.drawText(self.rect(), Qt.AlignCenter, "Descargando medio en alta calidad...")
        elif self.is_error:
            painter.setPen(QPen(QColor('#FF5555'), 1))
            painter.drawLine(0, int(mid_y), w, int(mid_y))
            painter.setPen(QPen(QColor('#FF8888')))
            msg = self.error_message or "Error al descargar el medio en alta calidad."
            painter.drawText(self.rect(), Qt.AlignCenter, f"Error al descargar el medio en alta calidad.\n{msg}" if self.error_message else msg)
        elif self.is_loading:
            # Animación de carga: onda sinusoidal
            pen = QPen(QColor(get_theme_token('acento_primario', '#B9E640')))
            pen.setWidth(1)
            for x in range(w):
                val = math.sin(x * 0.05 + self.loading_phase) * 0.3
                pulse = math.sin(self.loading_phase * 0.5) * 0.1 + 0.9
                amp = val * pulse * (h / 2.0) * 0.7
                col = QColor(get_theme_token('acento_primario', '#B9E640'))
                alpha = int(100 + 50 * math.sin(self.loading_phase + x * 0.02))
                col.setAlpha(max(30, min(alpha, 200)))
                pen.setColor(col)
                painter.setPen(pen)
                painter.drawLine(x, int(mid_y - amp), x, int(mid_y + amp))
        elif self._display_peaks:
            # Dibujar forma de onda profesional: línea vertical por píxel (solo las visibles en pantalla)
            acento = QColor(get_theme_token('acento_primario', '#B9E640'))
            dim_color = QColor(acento)
            dim_color.setAlpha(50)
            
            rect = event.rect()
            start_x = max(0, rect.left() - 2)
            end_x = min(len(self._display_peaks), rect.right() + 2)
            
            for x in range(start_x, end_x):
                mn, mx = self._display_peaks[x]
                
                # Aplicar zoom vertical
                mn_z = max(-1.0, mn * self.zoom_y)
                mx_z = min(1.0, mx * self.zoom_y)
                
                y_top = int(mid_y - mx_z * (h / 2.0 - 2))
                y_bot = int(mid_y - mn_z * (h / 2.0 - 2))
                
                # Asegurar al menos 1px de altura
                if y_top == y_bot:
                    y_top -= 1
                
                if x_in <= x <= x_out:
                    painter.setPen(QPen(acento, 1))
                else:
                    painter.setPen(QPen(dim_color, 1))
                
                painter.drawLine(x, y_top, x, y_bot)
        
        # Barra superior y Agarrador Central de Selección (Range Drag Handle)
        if x_out - x_in > 4:
            painter.fillRect(x_in, 0, x_out - x_in, 3, QColor(185, 230, 64, 200))
            center_x = (x_in + x_out) // 2
            pill_w = min(36, max(16, (x_out - x_in) - 8))
            pill_x = center_x - (pill_w // 2)
            
            if pill_w >= 14:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor('#B9E640'))
                painter.drawRoundedRect(pill_x, 0, pill_w, 10, 3, 3)
                
                # Muescas de agarre (|||) en el centro
                painter.setPen(QPen(QColor('#141414'), 1))
                painter.drawLine(center_x - 3, 3, center_x - 3, 7)
                painter.drawLine(center_x, 3, center_x, 7)
                painter.drawLine(center_x + 3, 3, center_x + 3, 7)

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
        
        # Playhead (Blanco)
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
    
    def __init__(self, media_path: str, media_type: str = "video", duration_sec: float = 0.0, fps: float = 30.0, existing_subclips: list = None, initial_in_sec: float = None, initial_out_sec: float = None, pending_download: bool = False, display_name: str = None, parent=None):
        super().__init__(parent)
        self.media_path = media_path
        self.media_type = media_type.lower()
        self.duration_sec = duration_sec or 1.0
        self.fps = fps if fps > 0 else 30.0
        self.in_sec = initial_in_sec if initial_in_sec is not None else 0.0
        self.out_sec = initial_out_sec if initial_out_sec is not None else self.duration_sec
        self.subclips = list(existing_subclips) if existing_subclips else []
        # Rango (in_sec, out_sec) del subclip que se está previsualizando en bucle desde la
        # lista de subclips guardados; None cuando no hay una previsualización en bucle activa.
        self._preview_loop_range = None
        # Modo "pendiente": el medio es remoto y aún se está descargando en alta calidad en segundo plano.
        self.pending_download = pending_download
        self._display_name = display_name or os.path.basename(media_path) or "Medio remoto"

        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setWindowTitle(f"Edición de Subclips - {self._display_name}")
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
        self._update_waveform_range()

        if self.pending_download:
            logger.info(f"[SubclipDialog] Ventana abierta en modo pendiente de descarga para '{self._display_name}'.")
            self._set_pending_state(True)
        else:
            self.load_waveform()
        QTimer.singleShot(100, self._sync_ruler)  # Sync inicial tras layout

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

        self.title_lbl = QLabel(f"Edición de Subclips (In/Out) — {self._display_name}")
        self.title_lbl.setStyleSheet("font-weight: bold; font-size: 13px; color: #ffffff;")
        tb_layout.addWidget(self.title_lbl)
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

        # Controles de Zoom (Arriba del Waveform)
        from PySide6.QtWidgets import QSlider
        zoom_bar = QHBoxLayout()
        zoom_bar.setContentsMargins(0, 0, 0, 0)
        
        lbl_zoom_icon = QLabel()
        icon_zoom = get_svg_icon("zoom_in.svg")
        if not icon_zoom.isNull():
            lbl_zoom_icon.setPixmap(icon_zoom.pixmap(16, 16))
        else:
            lbl_zoom_icon.setText("🔍")
        zoom_bar.addWidget(lbl_zoom_icon)
        
        self.slider_zoom_x = QSlider(Qt.Horizontal)
        self.slider_zoom_x.setRange(100, 5000)
        self.slider_zoom_x.setValue(100)
        self.slider_zoom_x.setFixedWidth(100)
        self.slider_zoom_x.setToolTip("Zoom Horizontal")
        self.slider_zoom_x.setStyleSheet("""
            QSlider::groove:horizontal { border: 1px solid #333; height: 4px; background: #222; border-radius: 2px; }
            QSlider::handle:horizontal { background: #B9E640; width: 12px; margin: -4px 0; border-radius: 6px; }
        """)
        self.slider_zoom_x.valueChanged.connect(self._on_zoom_x_changed)
        zoom_bar.addWidget(self.slider_zoom_x)
        
        zoom_bar.addSpacing(16)
        
        lbl_zoom_y_icon = QLabel("dB")
        lbl_zoom_y_icon.setStyleSheet("color: #888; font-size: 11px; font-weight: bold;")
        zoom_bar.addWidget(lbl_zoom_y_icon)

        self.slider_zoom_y = QSlider(Qt.Horizontal)
        self.slider_zoom_y.setRange(10, 500)
        self.slider_zoom_y.setValue(100)
        self.slider_zoom_y.setFixedWidth(80)
        self.slider_zoom_y.setToolTip("Ganancia Visual (Zoom Y)")
        self.slider_zoom_y.setStyleSheet("""
            QSlider::groove:horizontal { border: 1px solid #333; height: 4px; background: #222; border-radius: 2px; }
            QSlider::handle:horizontal { background: #1DC038; width: 12px; margin: -4px 0; border-radius: 6px; }
        """)
        self.slider_zoom_y.valueChanged.connect(self._on_zoom_y_changed)
        zoom_bar.addWidget(self.slider_zoom_y)
        
        zoom_bar.addStretch()
        left_layout.addLayout(zoom_bar)

        # Regla de tiempo (Timeline Ruler)
        from gui.widgets.timeline_ruler import TimelineRulerWidget
        self.timeline_ruler = TimelineRulerWidget(
            media_type=self.media_type,
            duration_sec=self.duration_sec,
            fps=self.fps
        )
        left_layout.addWidget(self.timeline_ruler)

        # Área con scroll para el Waveform y el vúmetro
        wave_container = QHBoxLayout()
        wave_container.setContentsMargins(0, 0, 0, 0)
        wave_container.setSpacing(8)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setFixedHeight(130)
        self.scroll_area.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:horizontal {
                border: none; background: #222; height: 10px; margin: 0px 0px 0 0px; border-radius: 5px;
            }
            QScrollBar::handle:horizontal {
                background: #555; min-width: 20px; border-radius: 5px;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                border: none; background: none; width: 0px;
            }
        """)

        self.waveform_widget = SubclipWaveformWidget()
        self.waveform_widget.seek_requested.connect(self._on_waveform_seek)
        self.waveform_widget.range_changed.connect(self._on_waveform_range_changed)
        self.scroll_area.setWidget(self.waveform_widget)
        
        wave_container.addWidget(self.scroll_area, 1)
        self.scroll_area.viewport().installEventFilter(self)
        # Sincronizar la regla de tiempo con el scroll
        self.scroll_area.horizontalScrollBar().valueChanged.connect(self._sync_ruler)

        from gui.widgets.audio_meter import AudioVolumeMeterWidget
        self.audio_meter = AudioVolumeMeterWidget()
        self.audio_meter.setFixedHeight(120)
        wave_container.addWidget(self.audio_meter)

        left_layout.addLayout(wave_container)

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
        self.btn_set_in = QPushButton()
        self.btn_set_in.setIcon(get_svg_icon("arrow_menu_open.svg"))
        self.btn_set_in.setIconSize(QSize(20, 20))
        self.btn_set_in.setFixedSize(32, 28)
        self.btn_set_in.setToolTip(self.tr("Establecer punto de entrada (Tecla I)"))
        self.btn_set_in.setStyleSheet("""
            QPushButton {
                background-color: #1a271a;
                border: 1px solid #1DC038;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #1DC038; }
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

        self.btn_set_out = QPushButton()
        self.btn_set_out.setIcon(get_svg_icon("arrow_menu_close.svg"))
        self.btn_set_out.setIconSize(QSize(20, 20))
        self.btn_set_out.setFixedSize(32, 28)
        self.btn_set_out.setToolTip(self.tr("Establecer punto de salida (Tecla O)"))
        self.btn_set_out.setStyleSheet("""
            QPushButton {
                background-color: #2b1a1a;
                border: 1px solid #FF5555;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #FF5555; }
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
        content_layout.addWidget(left_widget, 70)

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
        self._send_state = SendButtonState(self.btn_send, restore_callback=self._update_send_button)

        right_layout.addWidget(self.btn_send)
        content_layout.addWidget(right_widget, 30)

        main_layout.addWidget(content_widget, 1)
        self._update_send_button()
        self._refresh_subclip_list()

    def init_media_player(self):
        self.media_player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.media_player.setAudioOutput(self.audio_output)
        
        if self.media_type == "video":
            self.media_player.setVideoOutput(self.video_widget)

        if self.media_path and os.path.exists(self.media_path):
            self.media_player.setSource(QUrl.fromLocalFile(self.media_path))
            if self.media_type == "video":
                QTimer.singleShot(50, self._render_initial_frame)

        self.media_player.positionChanged.connect(self._on_player_position_changed)
        self.media_player.durationChanged.connect(self._on_player_duration_changed)
        self.media_player.mediaStatusChanged.connect(self._on_media_status_changed)
        
        # Timer para actualizar el medidor de volumen si está reproduciendo
        self.meter_timer = QTimer(self)
        self.meter_timer.setInterval(16)  # ~60 FPS para fluidez
        self.meter_timer.timeout.connect(self._update_volume_meter)

    def _render_initial_frame(self):
        """Forzar al reproductor de video a decodificar y presentar el primer fotograma en QVideoWidget."""
        if self.media_type == "video" and self.media_player:
            state = self.media_player.playbackState()
            if state == QMediaPlayer.PlaybackState.StoppedState:
                pos_ms = int(self.in_sec * 1000) if self.in_sec > 0 else 0
                self.media_player.pause()
                self.media_player.setPosition(pos_ms)

    def _on_media_status_changed(self, status):
        if self.media_type == "video" and status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            if not getattr(self, "_first_frame_rendered", False):
                self._first_frame_rendered = True
                self._render_initial_frame()

    def eventFilter(self, obj, event):
        if obj == self.scroll_area.viewport() and event.type() == QEvent.Type.Wheel:
            modifiers = event.modifiers()
            # Scroll normal -> Zoom X
            if modifiers == Qt.NoModifier:
                delta = event.angleDelta().y()
                if delta != 0:
                    old_zoom = self.slider_zoom_x.value()
                    step_val = max(20, int(old_zoom * 0.15))
                    zoom_step = step_val if delta > 0 else -step_val
                    new_zoom = max(self.slider_zoom_x.minimum(), min(old_zoom + zoom_step, self.slider_zoom_x.maximum()))
                    if new_zoom != old_zoom:
                        is_playing = self.media_player.playbackState() == QMediaPlayer.PlayingState
                        if is_playing:
                            self.slider_zoom_x.setValue(new_zoom)
                            QTimer.singleShot(0, self._center_scroll_on_playhead)
                        else:
                            # Zoom enfocado en la posición del ratón cuando está pausado
                            h_bar = self.scroll_area.horizontalScrollBar()
                            mouse_x = event.position().x()
                            old_w = self.waveform_widget.width()
                            old_wave_x = h_bar.value() + mouse_x
                            target_ratio = old_wave_x / old_w if old_w > 0 else 0.5
                            
                            self.slider_zoom_x.setValue(new_zoom)
                            QTimer.singleShot(0, lambda r=target_ratio, mx=mouse_x: self._center_scroll_on_ratio(r, mx))
                    return True
            # Alt/Shift + Scroll -> Pan Horizontal
            elif modifiers in (Qt.ShiftModifier, Qt.AltModifier):
                h_bar = self.scroll_area.horizontalScrollBar()
                delta = event.angleDelta().y()
                if delta != 0:
                    h_bar.setValue(h_bar.value() - delta)
                    return True
        return super().eventFilter(obj, event)

    def _center_scroll_on_playhead(self):
        """Centra la vista del scroll area sobre el cabezal de reproducción."""
        h_bar = self.scroll_area.horizontalScrollBar()
        viewport_w = self.scroll_area.viewport().width()
        new_waveform_w = self.waveform_widget.width()
        new_playhead_x = self.waveform_widget._playback_ratio * new_waveform_w
        target_scroll = int(new_playhead_x - viewport_w / 2)
        h_bar.setValue(max(0, min(target_scroll, h_bar.maximum())))
        self._sync_ruler()

    def _center_scroll_on_ratio(self, ratio: float, mouse_x: float):
        """Mantiene exactamente bajo el puntero del ratón el punto del audio donde se hizo zoom."""
        h_bar = self.scroll_area.horizontalScrollBar()
        new_waveform_w = self.waveform_widget.width()
        new_mouse_x = ratio * new_waveform_w
        target_scroll = int(new_mouse_x - mouse_x)
        h_bar.setValue(max(0, min(target_scroll, h_bar.maximum())))
        self._sync_ruler()

    def _on_zoom_x_changed(self, value):
        zoom = value / 100.0
        base_width = self.scroll_area.viewport().width()
        new_width = int(base_width * zoom)
        self.waveform_widget.setMinimumWidth(new_width)
        # Sincronizar la regla después del cambio de zoom
        QTimer.singleShot(0, self._sync_ruler)

    def _sync_ruler(self):
        """Sincroniza la regla de tiempo con el scroll y el tamaño del waveform."""
        self.timeline_ruler.set_sync(
            scroll_offset=self.scroll_area.horizontalScrollBar().value(),
            waveform_width=self.waveform_widget.width(),
            viewport_width=self.scroll_area.viewport().width()
        )

    def _on_zoom_y_changed(self, value):
        zoom = value / 100.0
        self.waveform_widget.zoom_y = zoom
        self.waveform_widget.update()

    def _update_volume_meter(self):
        if self.media_player.playbackState() == QMediaPlayer.PlayingState:
            peaks = self.waveform_widget._hires_peaks
            if peaks:
                ratio = self.waveform_widget.get_playback_ratio()
                idx = int(ratio * (len(peaks) - 1))
                if 0 <= idx < len(peaks):
                    mn, mx = peaks[idx]
                    val = max(abs(mn), abs(mx)) * self.waveform_widget.zoom_y
                    self.audio_meter.set_level(min(val, 1.0))
        else:
            self.audio_meter.set_level(0.0)

    def load_waveform(self):
        self.waveform_widget.set_audio_path(self.media_path)
        mgr = WaveformCacheManager.get_instance()
        # Intentar cargar alta resolución primero
        hires = mgr.get_cached_hires_peaks(self.media_path)
        if hires is not None:
            self.waveform_widget.set_hires_peaks(hires)
        else:
            self.waveform_widget.set_loading(True)
            if not getattr(self, "_hires_signal_connected", False):
                try:
                    mgr.hires_waveform_loaded.connect(self._on_hires_waveform_loaded)
                    self._hires_signal_connected = True
                except Exception:
                    pass
            mgr.request_hires_waveform(self.media_path)

    def _on_hires_waveform_loaded(self, path: str, peaks: list):
        if path == self.media_path:
            self.waveform_widget.set_hires_peaks(peaks)
            QTimer.singleShot(0, self._sync_ruler)

    def _cleanup_waveform_signals(self):
        """Desconecta las señales del singleton global de caché para evitar fugas y descargas fatales."""
        if getattr(self, "_hires_signal_connected", False):
            try:
                mgr = WaveformCacheManager.get_instance()
                mgr.hires_waveform_loaded.disconnect(self._on_hires_waveform_loaded)
            except Exception:
                pass
            self._hires_signal_connected = False

        if hasattr(self, "waveform_widget") and self.waveform_widget:
            self.waveform_widget.set_loading(False)
            self.waveform_widget.set_downloading(False)

        if hasattr(self, "media_player") and self.media_player:
            try:
                self.media_player.stop()
            except Exception:
                pass

        if hasattr(self, "meter_timer") and self.meter_timer and self.meter_timer.isActive():
            self.meter_timer.stop()

    def closeEvent(self, event):
        self._cleanup_waveform_signals()
        super().closeEvent(event)

    def reject(self):
        self._cleanup_waveform_signals()
        super().reject()

    def accept(self):
        self._cleanup_waveform_signals()
        super().accept()

    def _set_pending_state(self, pending: bool):
        """Activa/desactiva el modo 'pendiente de descarga': deshabilita controles de edición/envío
        y muestra el estado especial de descarga en la waveform (el botón de cerrar sigue disponible)."""
        self.pending_download = pending
        for w in (self.btn_play, self.btn_set_in, self.btn_set_out, self.btn_add_subclip):
            w.setEnabled(not pending)
        if pending:
            self.btn_send.setEnabled(False)
        else:
            self._update_send_button()
        self.waveform_widget.set_downloading(pending)

    def set_resolved_media_path(self, local_path: str):
        """
        Reemplaza el medio pendiente por el archivo real ya descargado en alta calidad:
        recarga el reproductor (lo que recalcula duración real vía durationChanged),
        refresca el FPS y vuelve a extraer la waveform de alta resolución del archivo correcto.
        """
        logger.info(f"[SubclipDialog] Medio resuelto en alta calidad: {local_path}")
        self.media_path = local_path
        self._display_name = os.path.basename(local_path) or self._display_name
        self.setWindowTitle(f"Edición de Subclips - {self._display_name}")
        if hasattr(self, "title_lbl"):
            self.title_lbl.setText(f"Edición de Subclips (In/Out) — {self._display_name}")

        try:
            from core.tabs.editing_media.ffprobe_metadata_manager import FFprobeMetadataManager
            meta = FFprobeMetadataManager.get_instance().get_metadata_instant(local_path, self.media_type)
            fps_str = str(meta.get("fps", "")).replace("fps", "").strip()
            if fps_str:
                self.fps = float(fps_str)
                self.timeline_ruler.fps = self.fps
                self.timeline_ruler.update()
        except Exception as e:
            logger.error(f"[SubclipDialog] No se pudo refrescar el FPS tras la descarga: {e}")

        self._first_frame_rendered = False
        self.media_player.setSource(QUrl.fromLocalFile(local_path))
        if self.media_type == "video":
            QTimer.singleShot(50, self._render_initial_frame)
        self._set_pending_state(False)
        self.load_waveform()

    def set_resolve_error(self, message: str):
        """Muestra el error de descarga en la waveform; los controles quedan deshabilitados."""
        logger.error(f"[SubclipDialog] Error resolviendo el medio en alta calidad: {message}")
        self.waveform_widget.set_error(True, message)

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
        # Usar el play/pause "normal" de la ventana siempre sale de la previsualización en
        # bucle de un subclip (si había una activa).
        self._preview_loop_range = None
        if self.media_player.playbackState() == QMediaPlayer.PlayingState:
            self.media_player.pause()
            self.btn_play.setIcon(get_svg_icon("play_arrow.svg"))
            self.meter_timer.stop()
            self.audio_meter.set_level(0.0)
        else:
            self.media_player.play()
            self.btn_play.setIcon(get_svg_icon("pause.svg"))
            self.meter_timer.start()

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
            pos_sec = ratio * self.duration_sec
            # Si el usuario mueve manualmente el cabezal fuera del rango del subclip que se
            # está previsualizando en bucle, se sale de ese modo de bucle.
            if self._preview_loop_range is not None:
                lo, hi = self._preview_loop_range
                if pos_sec < lo or pos_sec > hi:
                    self._preview_loop_range = None
            self.media_player.setPosition(int(pos_sec * 1000))

    def _on_waveform_range_changed(self, in_r: float, out_r: float):
        if self.duration_sec > 0:
            self.in_sec = in_r * self.duration_sec
            self.out_sec = out_r * self.duration_sec
            self._update_time_label()

    def _on_player_position_changed(self, pos_ms: int):
        pos_sec = pos_ms / 1000.0

        # Previsualización en bucle de un subclip guardado: al llegar al final del rango,
        # volver al inicio en vez de seguir reproduciendo más allá de él.
        if self._preview_loop_range is not None:
            lo, hi = self._preview_loop_range
            if pos_sec >= hi:
                self.media_player.setPosition(int(lo * 1000))
                return

        if self.duration_sec > 0:
            ratio = pos_sec / self.duration_sec
            self.waveform_widget.set_playback_ratio(ratio)
        self._update_time_label()

    def _on_player_duration_changed(self, dur_ms: int):
        if dur_ms > 0:
            new_dur = dur_ms / 1000.0
            # Si out_sec estaba "al final" de la duración anterior, o es inválido, actualizarlo al nuevo final
            if abs(self.out_sec - self.duration_sec) < 0.05 or self.out_sec > new_dur or self.out_sec <= 0:
                self.out_sec = new_dur
            self.duration_sec = new_dur
            self._update_waveform_range()
            self._update_saved_subclip_ratios()
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

        self._update_saved_subclip_ratios()

    def _update_saved_subclip_ratios(self):
        """Envía a la waveform los rangos de los subclips ya guardados para mostrarlos de
        fondo con baja opacidad."""
        if self.duration_sec <= 0:
            return
        ranges = [(sc["in"] / self.duration_sec, sc["out"] / self.duration_sec) for sc in self.subclips]
        self.waveform_widget.set_saved_subclip_ratios(ranges)

    def _preview_subclip(self, index: int):
        if 0 <= index < len(self.subclips):
            sc = self.subclips[index]
            # Reproduce en bucle dentro del rango del subclip hasta que el usuario mueva el
            # cabezal manualmente fuera de él o use el play normal de la ventana.
            self._preview_loop_range = (sc["in"], sc["out"])
            self.media_player.setPosition(int(sc["in"] * 1000))
            self.media_player.play()
            self.btn_play.setIcon(get_svg_icon("pause.svg"))
            self.meter_timer.start()

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

        if active == "premiere":
            icon_file = "premiere pro.svg"
        elif active == "aftereffects":
            icon_file = "after effects.svg"
        else:
            icon_file = "davinci resolve.svg"
        
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

    def _send_subclip_payload(self, payload: dict, log_desc: str):
        """Envía el payload de subclips mostrando el estado animado en btn_send y cerrando el diálogo en éxito."""
        editor_mgr = EditorIntegrationManager.get_instance()
        if not editor_mgr or not editor_mgr.active_editor:
            return
        if self.pending_download:
            logger.warning("[SubclipDialog] Envío bloqueado: el medio aún se está descargando en alta calidad.")
            return

        logger.info(f"[SubclipDialog] {log_desc} a {editor_mgr.active_editor}")
        self._send_state.start("Enviando")

        ok = False
        try:
            ok = editor_mgr.send_subclips(payload)
        except Exception as e:
            logger.error(f"[SubclipDialog] Excepción enviando subclips: {e}")
            ok = False

        if ok:
            logger.info("[SubclipDialog] Subclips enviados correctamente.")
        else:
            logger.error("[SubclipDialog] Error al enviar los subclips al editor.")

        self._send_state.finish(ok, "Éxito" if ok else "Error")
        if ok:
            QTimer.singleShot(1200, self.accept)

    def _on_send_subclips_clicked(self):
        items_to_send = self.subclips if self.subclips else [{
            "name": f"{os.path.splitext(os.path.basename(self.media_path))[0]}_range",
            "in": self.in_sec,
            "out": self.out_sec
        }]
        payload = {
            "filePath": self.media_path.replace('\\', '/'),
            "subclips": items_to_send
        }
        self._send_subclip_payload(payload, f"Enviando {len(items_to_send)} subclips")

    def _on_send_single_subclip_clicked(self):
        payload = {
            "filePath": self.media_path.replace('\\', '/'),
            "subclips": [{
                "name": f"{os.path.splitext(os.path.basename(self.media_path))[0]}_range",
                "in": self.in_sec,
                "out": self.out_sec
            }]
        }
        self._send_subclip_payload(payload, "Enviando rango actual como subclip")

    def closeEvent(self, event):
        self.media_player.stop()
        self.meter_timer.stop()
        super().closeEvent(event)

    def accept(self):
        self.media_player.stop()
        if hasattr(self, "meter_timer") and self.meter_timer:
            self.meter_timer.stop()
        super().accept()

    def reject(self):
        self.media_player.stop()
        self.meter_timer.stop()
        super().reject()
