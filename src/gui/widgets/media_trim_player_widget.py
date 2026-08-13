# src/gui/widgets/media_trim_player_widget.py
import os
import math
import array
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QFrame, QSizePolicy, QScrollArea, QSlider, QGraphicsView, QGraphicsScene,
    QToolButton, QMenu
)
from PySide6.QtCore import Qt, QUrl, QSize, QSizeF, QTimer, Signal, QEvent, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QPainterPath
from PySide6.QtMultimedia import (
    QMediaPlayer, QAudioOutput, QMediaMetaData, QAudioBufferOutput, QAudioFormat
)
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem

from gui.styles import get_theme_token, apply_player_play_button_style
from gui.tabs.editing_media.editing_media_icons import get_svg_icon
from gui.widgets.timeline_ruler import TimelineRulerWidget
from gui.widgets.audio_meter import MultiChannelMeterWidget
from gui.widgets.volume_control import VolumeControlWidget
from core.tabs.editing_media.waveform_cache_manager import WaveformCacheManager
from core.logger.logger_manager import logger

# (typecode, bytes_per_sample, offset, scale) para convertir muestras PCM crudas a -1.0..1.0
# según el QAudioFormat.SampleFormat que entregue el backend de Qt Multimedia en cada buffer.
_SAMPLE_FORMAT_INFO = {
    QAudioFormat.SampleFormat.UInt8: ('B', 1, 128.0, 128.0),
    QAudioFormat.SampleFormat.Int16: ('h', 2, 0.0, 32768.0),
    QAudioFormat.SampleFormat.Int32: ('i', 4, 0.0, 2147483648.0),
    QAudioFormat.SampleFormat.Float: ('f', 4, 0.0, 1.0),
}


def _channel_peaks_from_buffer(buf) -> list:
    """Calcula el pico lineal (0.0-1.0) de cada canal de un QAudioBuffer entregado en vivo
    durante la reproducción, respetando el conteo real de canales y el formato de muestra."""
    fmt = buf.format()
    channels = fmt.channelCount()
    if channels <= 0:
        return []

    info = _SAMPLE_FORMAT_INFO.get(fmt.sampleFormat())
    if info is None:
        return [0.0] * channels
    typecode, sample_bytes, offset, scale = info

    raw = bytes(buf.constData())
    usable_len = (len(raw) // sample_bytes) * sample_bytes
    if usable_len < sample_bytes * channels:
        return [0.0] * channels

    try:
        samples = array.array(typecode)
        samples.frombytes(raw[:usable_len])
    except Exception:
        return [0.0] * channels

    peaks = []
    for ch in range(channels):
        channel_samples = samples[ch::channels]
        if channel_samples:
            peak_raw = max(abs(max(channel_samples) - offset), abs(min(channel_samples) - offset))
            peaks.append(min(peak_raw / scale, 1.0))
        else:
            peaks.append(0.0)
    return peaks


class TrimWaveformWidget(QWidget):
    """Forma de onda profesional con pares min/max, estilo SoundQ/Premiere.

    Clic izquierdo: seek / arrastrar handles In-Out / arrastrar el rango completo.
    Clic derecho + arrastre: seleccionar un nuevo rango In-Out desde cero.
    """

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
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)  # Líneas nítidas

        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return

        # Autocorrección: si ya tenemos picos crudos pero todavía no se remuestrearon a
        # columnas de píxeles, es porque llegaron (set_hires_peaks) mientras el widget aún
        # no tenía un ancho real asignado por el layout (p.ej. primera carga, tab recién
        # mostrado). _resample_to_width() se queda callado en ese caso y nada lo reintentaba
        # después, dejando el waveform en blanco hasta la próxima carga. Como paintEvent solo
        # se dispara con un tamaño ya válido, es el lugar seguro para completar el remuestreo.
        if self._hires_peaks and not self._display_peaks:
            self._resample_to_width()

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


class _CheckerboardFrame(QFrame):
    """Contenedor del área de video que pinta una cuadrícula tipo 'transparencia' (estilo
    Photoshop) de fondo, en vez de un color plano. Así se distingue a simple vista el lienzo
    real del video de un área vacía/sin señal (que de otro modo también se vería negra)."""

    SQUARE = 10
    COLOR_A = QColor(42, 42, 42)
    COLOR_B = QColor(30, 30, 30)

    def __init__(self, border_color: str, radius: int = 8, parent=None):
        super().__init__(parent)
        self._border_color = QColor(border_color)
        self._radius = radius

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        painter.setClipPath(path)

        size = self.SQUARE
        cols = int(rect.width() // size) + 2
        rows = int(rect.height() // size) + 2
        for row in range(rows):
            for col in range(cols):
                color = self.COLOR_A if (row + col) % 2 == 0 else self.COLOR_B
                painter.fillRect(col * size, row * size, size, size, color)

        painter.setClipping(False)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(self._border_color, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        painter.end()


class _TransparentVideoView(QGraphicsView):
    """QGraphicsView de fondo transparente que aloja un QGraphicsVideoItem, ajustado y
    centrado manteniendo su proporción de aspecto (letterbox/pillarbox) al redimensionar.

    A diferencia de QVideoWidget (que siempre pinta las franjas sobrantes en negro sólido, sin
    dejar ver lo que hay detrás), este view no pinta nada fuera del propio fotograma de video,
    así que la cuadrícula de transparencia de `_CheckerboardFrame` (pintada detrás) se ve en
    esas franjas — permitiendo distinguir a simple vista si un video es vertical, cuadrado u
    horizontal en vez de perderlo contra un fondo negro uniforme.
    """

    def __init__(self, scene: QGraphicsScene, video_item: QGraphicsVideoItem, parent=None):
        super().__init__(scene, parent)
        self._video_item = video_item
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("QGraphicsView { background: transparent; border: none; }")
        self.viewport().setAutoFillBackground(False)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.refit()

    def refit(self):
        """Centra y escala el ítem de video dentro del viewport a mano (en vez de usar
        fitInView + zoom del view): el sceneRect siempre coincide exactamente con el tamaño
        del viewport, así que nunca queda espacio de sobra por el que se pueda hacer scroll,
        y el video queda perfectamente centrado tanto en horizontal como en vertical."""
        vp_w = self.viewport().width()
        vp_h = self.viewport().height()
        if vp_w <= 0 or vp_h <= 0:
            return

        self.scene().setSceneRect(0, 0, vp_w, vp_h)

        native = self._video_item.nativeSize()
        if native.isEmpty() or native.width() <= 0 or native.height() <= 0:
            # Tamaño nativo aún desconocido: ocupar todo el viewport: en cuanto se conozca
            # (nativeSizeChanged) se reajustará al tamaño real.
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


class MediaTrimPlayerWidget(QWidget):
    """
    Reproductor de video/audio con extractor de waveform de alta resolución y selección de
    rango In/Out (recorte). Extraído de la columna izquierda del editor de Subclips
    (gui/dialogs/subclip_dialog.py) para poder reutilizarse en otros lugares (p.ej. la pestaña
    de Herramientas Multimedia) sin arrastrar la columna de subclips guardados / envío a editor.

    Expone `self.ctrl_bar` (QHBoxLayout) para que quien lo use pueda insertar controles propios
    adicionales (p.ej. un botón "Añadir subclip") en la barra de controles inferior.
    """

    range_changed = Signal(float, float)  # in_sec, out_sec
    playing_changed = Signal(bool)

    def __init__(self, parent=None, card_style: bool = False):
        super().__init__(parent)
        self.media_path = ""
        self.media_type = "video"
        self.duration_sec = 1.0
        self.fps = 30.0
        self.in_sec = 0.0
        self.out_sec = 1.0
        self.pending_download = False
        # Rango (in_sec, out_sec) que se está previsualizando en bucle; None si no hay ninguno activo.
        self._preview_loop_range = None
        self._hires_signal_connected = False
        self._first_frame_rendered = False
        self._card_style = card_style
        self._active_audio_track = 0

        self.setFocusPolicy(Qt.StrongFocus)

        self._init_ui()
        self._init_media_player()

    # ------------------------------------------------------------------
    # Construcción de la interfaz
    # ------------------------------------------------------------------
    def _init_ui(self):
        left_layout = QVBoxLayout(self)
        if self._card_style:
            # Tarjeta con el mismo fondo/borde/radio que el resto de paneles de la app
            # (p.ej. la cola de medios o el panel de opciones en Herramientas Multimedia).
            self.setObjectName("mediaTrimPlayerWidget")
            self.setAttribute(Qt.WA_StyledBackground, True)
            bg_color = get_theme_token('fondo_secundario', '#1e1e1e')
            border_color = get_theme_token('borde_normal', '#2d2d2d')
            self.setStyleSheet(f"""
                QWidget#mediaTrimPlayerWidget {{
                    background-color: {bg_color};
                    border: 1px solid {border_color};
                    border-radius: 8px;
                }}
            """)
            left_layout.setContentsMargins(8, 8, 8, 8)
        else:
            left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        # Área de Video / Vista Previa
        borde_norm = get_theme_token('borde_normal', '#2d2d2d')
        self.preview_container = _CheckerboardFrame(borde_norm, radius=8)
        prev_layout = QVBoxLayout(self.preview_container)
        prev_layout.setContentsMargins(0, 0, 0, 0)

        # QGraphicsView + QGraphicsVideoItem en vez de QVideoWidget: así las franjas de
        # letterbox/pillarbox quedan transparentes y dejan ver la cuadrícula de fondo.
        self.video_scene = QGraphicsScene(self)
        self.video_scene.setBackgroundBrush(Qt.NoBrush)
        self.video_item = QGraphicsVideoItem()
        self.video_scene.addItem(self.video_item)
        self.video_item.nativeSizeChanged.connect(self._on_video_native_size_changed)

        self.video_widget = _TransparentVideoView(self.video_scene, self.video_item)
        self.video_widget.setVisible(False)
        prev_layout.addWidget(self.video_widget)

        self.lbl_audio_art = QLabel(self.tr("Vista Previa de Audio"))
        self.lbl_audio_art.setAlignment(Qt.AlignCenter)
        self.lbl_audio_art.setStyleSheet("color: #89b4fa; font-weight: bold; font-size: 16px; background: transparent;")
        self.lbl_audio_art.setVisible(False)
        prev_layout.addWidget(self.lbl_audio_art, 1)

        left_layout.addWidget(self.preview_container, 1)

        # Controles de Zoom (Arriba del Waveform)
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

        self.waveform_widget = TrimWaveformWidget()
        self.waveform_widget.seek_requested.connect(self._on_waveform_seek)
        self.waveform_widget.range_changed.connect(self._on_waveform_range_changed)
        self.scroll_area.setWidget(self.waveform_widget)

        # Envoltorio del scroll_area para poder superponerle el botón de selección de pista
        # de audio como una "chip" flotante en la esquina superior izquierda de la waveform.
        wave_wrapper = QWidget()
        wave_wrapper_layout = QVBoxLayout(wave_wrapper)
        wave_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wave_wrapper_layout.addWidget(self.scroll_area)

        self.btn_audio_track = QToolButton(wave_wrapper)
        self.btn_audio_track.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.btn_audio_track.setPopupMode(QToolButton.InstantPopup)
        self.btn_audio_track.setCursor(Qt.PointingHandCursor)
        self.btn_audio_track.setToolTip(self.tr("Seleccionar pista de audio"))
        self.btn_audio_track.setFixedHeight(20)
        self.btn_audio_track.setStyleSheet("""
            QToolButton {
                background-color: rgba(20, 20, 20, 200);
                border: 1px solid #444;
                border-radius: 5px;
                color: #cdd6f4;
                font-size: 10px;
                font-weight: bold;
                padding: 2px 6px;
            }
            QToolButton:hover { background-color: rgba(185, 230, 64, 200); color: #141414; border-color: #B9E640; }
            QToolButton::menu-indicator { image: none; }
        """)
        self.audio_track_menu = QMenu(self.btn_audio_track)
        self.btn_audio_track.setMenu(self.audio_track_menu)
        self.btn_audio_track.setVisible(False)
        self.btn_audio_track.move(6, 6)
        self.btn_audio_track.adjustSize()
        self.btn_audio_track.raise_()

        wave_container.addWidget(wave_wrapper, 1)
        self.scroll_area.viewport().installEventFilter(self)
        # Sincronizar la regla de tiempo con el scroll
        self.scroll_area.horizontalScrollBar().valueChanged.connect(self._sync_ruler)

        self.audio_meter = MultiChannelMeterWidget()
        self.audio_meter.setFixedHeight(120)
        wave_container.addWidget(self.audio_meter)

        left_layout.addLayout(wave_container)

        # Barra de Controles e Información de Tiempos
        self.ctrl_bar = QHBoxLayout()
        self.ctrl_bar.setSpacing(6)

        # Botón Play/Pause
        self.btn_play = QPushButton()
        self.btn_play.setFixedSize(34, 34)
        self.btn_play.setIcon(get_svg_icon("play_arrow.svg"))
        self.btn_play.setIconSize(QSize(18, 18))
        self.btn_play.clicked.connect(self.toggle_play_pause)
        apply_player_play_button_style(self.btn_play, is_playing=False, icon_size=18)
        self.ctrl_bar.addWidget(self.btn_play)

        self.ctrl_bar.addSpacing(8)

        # Volume control
        self.volume_control = VolumeControlWidget(initial_volume=100, slider_width=60)
        self.volume_control.volume_changed.connect(self._on_volume_changed)
        self.ctrl_bar.addWidget(self.volume_control)

        self.ctrl_bar.addStretch()

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
        self.btn_set_in.clicked.connect(self.set_in_point)
        self.ctrl_bar.addWidget(self.btn_set_in)

        _time_style = "font-size: 12px; padding: 2px 4px; border-radius: 6px; background: #1e1e1e; border: 1px solid #333;"
        self.input_time_start = QLineEdit(self._format_seconds_ms(self.in_sec))
        self.input_time_start.setFixedSize(90, 28)
        self.input_time_start.setAlignment(Qt.AlignCenter)
        self.input_time_start.setStyleSheet(_time_style)
        self.input_time_start.editingFinished.connect(self._on_time_input_changed)
        self.ctrl_bar.addWidget(self.input_time_start)

        sep = QLabel("—")
        sep.setAlignment(Qt.AlignCenter)
        sep.setStyleSheet("color: #666; font-size: 15px;")
        self.ctrl_bar.addWidget(sep)

        self.input_time_end = QLineEdit(self._format_seconds_ms(self.out_sec))
        self.input_time_end.setFixedSize(90, 28)
        self.input_time_end.setAlignment(Qt.AlignCenter)
        self.input_time_end.setStyleSheet(_time_style)
        self.input_time_end.editingFinished.connect(self._on_time_input_changed)
        self.ctrl_bar.addWidget(self.input_time_end)

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
        self.btn_set_out.clicked.connect(self.set_out_point)
        self.ctrl_bar.addWidget(self.btn_set_out)

        self.ctrl_bar.addStretch()

        # Reloj global
        self.lbl_time_info = QLabel("00:00:00 / 00:00:00")
        self.lbl_time_info.setStyleSheet("color: #cdd6f4; font-size: 11px; font-weight: bold;")
        self.ctrl_bar.addWidget(self.lbl_time_info)

        left_layout.addLayout(self.ctrl_bar)

    def _init_media_player(self):
        self.media_player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_item)

        self.media_player.positionChanged.connect(self._on_player_position_changed)
        self.media_player.durationChanged.connect(self._on_player_duration_changed)
        self.media_player.mediaStatusChanged.connect(self._on_media_status_changed)
        self.media_player.tracksChanged.connect(self._rebuild_audio_track_menu)

        # Medidor de volumen en vivo: QAudioBufferOutput entrega los buffers de audio reales
        # que se están reproduciendo (con su conteo real de canales), en vez de estimar el
        # nivel a partir de la waveform pre-calculada (que siempre es mono/mezclada).
        self.audio_buffer_output = QAudioBufferOutput(self)
        self.media_player.setAudioBufferOutput(self.audio_buffer_output)
        self.audio_buffer_output.audioBufferReceived.connect(self._on_audio_buffer_received)

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    def load_media(self, media_path: str, media_type: str = "video", duration_sec: float = 0.0, fps: float = 30.0,
                    initial_in_sec: float = None, initial_out_sec: float = None):
        """Carga un nuevo archivo multimedia (detiene el anterior y reinicia waveform/rango)."""
        self.cleanup(stop_only=True)

        self.media_path = media_path or ""
        self.media_type = (media_type or "video").lower()
        self.duration_sec = duration_sec if duration_sec and duration_sec > 0 else 1.0
        self.fps = fps if fps and fps > 0 else 30.0
        self.in_sec = initial_in_sec if initial_in_sec is not None else 0.0
        self.out_sec = initial_out_sec if initial_out_sec is not None else self.duration_sec
        self.pending_download = False
        self._preview_loop_range = None
        self._first_frame_rendered = False
        self._active_audio_track = 0
        self.btn_audio_track.setVisible(False)
        self.audio_track_menu.clear()

        is_video = self.media_type in ("video", "video+audio", "imagen")
        self.video_widget.setVisible(is_video)
        self.lbl_audio_art.setVisible(not is_video)
        if not is_video:
            filename = os.path.basename(self.media_path)
            self.lbl_audio_art.setText(f"{self.tr('Pista de Audio')}: {filename}" if filename else self.tr("Vista Previa de Audio"))

        self.timeline_ruler.media_type = self.media_type
        self.timeline_ruler.is_video = is_video
        self.timeline_ruler.duration_sec = max(0.001, self.duration_sec)
        self.timeline_ruler.fps = self.fps
        self.timeline_ruler.show_hours = self.duration_sec >= 3600.0
        self.timeline_ruler.update()

        if self.media_path and os.path.exists(self.media_path):
            self.media_player.setSource(QUrl.fromLocalFile(self.media_path))
            if is_video:
                QTimer.singleShot(50, self._render_initial_frame)

        self._update_waveform_range()
        self._update_time_label()
        self.load_waveform()
        QTimer.singleShot(100, self._sync_ruler)

    def clear(self):
        """Detiene la reproducción y vacía el reproductor (sin archivo seleccionado)."""
        self.cleanup(stop_only=True)
        self.media_path = ""
        self.media_player.setSource(QUrl())
        self.video_widget.setVisible(False)
        self.lbl_audio_art.setVisible(False)
        self.waveform_widget.set_audio_path("")
        self.waveform_widget.set_saved_subclip_ratios([])
        self.lbl_time_info.setText("00:00:00 / 00:00:00")

    def set_fps(self, fps: float):
        if fps and fps > 0:
            self.fps = fps
            self.timeline_ruler.fps = fps
            self.timeline_ruler.update()

    def get_in_out(self):
        return self.in_sec, self.out_sec

    def set_in_out(self, in_sec: float, out_sec: float):
        self.in_sec = max(0.0, in_sec)
        self.out_sec = max(self.in_sec, out_sec)
        self._update_waveform_range()
        self._update_time_label()
        self.range_changed.emit(self.in_sec, self.out_sec)

    def is_playing(self) -> bool:
        return self.media_player.playbackState() == QMediaPlayer.PlayingState

    def set_pending(self, pending: bool):
        """Activa/desactiva el modo 'pendiente de descarga': deshabilita controles de edición
        y muestra el estado especial de descarga en la waveform (usado para medios remotos)."""
        self.pending_download = pending
        for w in (self.btn_play, self.btn_set_in, self.btn_set_out):
            w.setEnabled(not pending)
        self.waveform_widget.set_downloading(pending)

    def set_resolved_media_path(self, local_path: str, fps: float = None):
        """Reemplaza el medio pendiente por el archivo real ya descargado en alta calidad."""
        logger.info(f"[MediaTrimPlayerWidget] Medio resuelto en alta calidad: {local_path}")
        self.media_path = local_path
        if fps:
            self.set_fps(fps)
        self._first_frame_rendered = False
        self.media_player.setSource(QUrl.fromLocalFile(local_path))
        if self.media_type == "video":
            QTimer.singleShot(50, self._render_initial_frame)
        self.set_pending(False)
        self.load_waveform()

    def set_resolve_error(self, message: str):
        logger.error(f"[MediaTrimPlayerWidget] Error resolviendo el medio en alta calidad: {message}")
        self.waveform_widget.set_error(True, message)

    def set_saved_ranges(self, ranges: list):
        """Muestra en la waveform, de fondo, rangos ya guardados en otra parte (p.ej. subclips)."""
        self.waveform_widget.set_saved_subclip_ratios(ranges)

    def cleanup(self, stop_only: bool = False):
        """Desconecta señales del caché global de waveform y detiene reproducción/timers."""
        if not stop_only and self._hires_signal_connected:
            try:
                mgr = WaveformCacheManager.get_instance()
                mgr.hires_waveform_loaded.disconnect(self._on_hires_waveform_loaded)
            except Exception:
                pass
            self._hires_signal_connected = False

        self.waveform_widget.set_loading(False)
        self.waveform_widget.set_downloading(False)

        try:
            self.media_player.stop()
        except Exception:
            pass

        self.audio_meter.reset_levels()

    # ------------------------------------------------------------------
    # Reproducción
    # ------------------------------------------------------------------
    def _on_video_native_size_changed(self, size: QSizeF):
        """Se dispara cuando se conoce (o cambia) la resolución real del video: reajusta el
        QGraphicsView para que el fotograma quede centrado y a escala manteniendo su
        proporción de aspecto real (vertical, cuadrado u horizontal)."""
        self.video_widget.refit()

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
            if not self._first_frame_rendered:
                self._first_frame_rendered = True
                self._render_initial_frame()

    # ------------------------------------------------------------------
    # Selección de pista de audio (medios multipista)
    # ------------------------------------------------------------------
    def _rebuild_audio_track_menu(self):
        """Reconstruye el menú de pistas de audio disponibles; el botón solo se muestra
        cuando el medio tiene más de una pista (caso normal: se queda oculto)."""
        tracks = self.media_player.audioTracks()
        count = len(tracks)
        if count <= 1:
            self.btn_audio_track.setVisible(False)
            return

        active = self.media_player.activeAudioTrack()
        if active < 0:
            active = 0

        self.audio_track_menu.clear()
        for i, meta in enumerate(tracks):
            action = self.audio_track_menu.addAction(self._describe_audio_track(i, meta))
            action.setCheckable(True)
            action.setChecked(i == active)
            action.triggered.connect(lambda checked=False, idx=i: self._on_audio_track_selected(idx))

        self._active_audio_track = active
        self.btn_audio_track.setText(f"{self.tr('Pista')} {active + 1} ▾")
        self.btn_audio_track.adjustSize()
        self.btn_audio_track.setVisible(True)
        self.btn_audio_track.raise_()

    def _describe_audio_track(self, index: int, meta: QMediaMetaData) -> str:
        title = str(meta.stringValue(QMediaMetaData.Key.Title) or "").strip()
        lang = str(meta.stringValue(QMediaMetaData.Key.Language) or "").strip()
        codec = str(meta.stringValue(QMediaMetaData.Key.AudioCodec) or "").strip()

        label = f"{self.tr('Pista')} {index + 1}"
        extra = title or lang
        if extra:
            label += f" — {extra}"
        if codec:
            label += f" ({codec})"
        return label

    def _on_audio_track_selected(self, index: int):
        if index == self._active_audio_track:
            return
        self.media_player.setActiveAudioTrack(index)
        self._active_audio_track = index
        self.btn_audio_track.setText(f"{self.tr('Pista')} {index + 1} ▾")
        self.btn_audio_track.adjustSize()
        for i, action in enumerate(self.audio_track_menu.actions()):
            action.setChecked(i == index)
        # La waveform y el medidor reflejan la pista seleccionada: volver a extraerla.
        self.load_waveform()

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

    def _on_audio_buffer_received(self, buffer):
        """Actualiza el medidor multicanal con los niveles reales del buffer de audio que se
        está reproduciendo en este instante (llega solo mientras hay reproducción activa)."""
        if self.media_player.playbackState() != QMediaPlayer.PlayingState:
            return
        peaks = _channel_peaks_from_buffer(buffer)
        if not peaks:
            return
        self.audio_meter.set_channel_count(len(peaks))
        self.audio_meter.set_levels(peaks)

    def load_waveform(self):
        if not self.media_path:
            self.waveform_widget.set_audio_path("")
            return
        self.waveform_widget.set_audio_path(self.media_path)
        mgr = WaveformCacheManager.get_instance()
        # Intentar cargar alta resolución primero (de la pista de audio activa)
        hires = mgr.get_cached_hires_peaks(self.media_path, self._active_audio_track)
        if hires is not None:
            self.waveform_widget.set_hires_peaks(hires)
        else:
            self.waveform_widget.set_loading(True)
            if not self._hires_signal_connected:
                try:
                    mgr.hires_waveform_loaded.connect(self._on_hires_waveform_loaded)
                    self._hires_signal_connected = True
                except Exception:
                    pass
            mgr.request_hires_waveform(self.media_path, audio_track=self._active_audio_track)

    def _on_hires_waveform_loaded(self, path: str, peaks: list, audio_track: int = 0):
        # Descarta resultados de una pista que el usuario ya dejó de tener seleccionada
        # (p.ej. si cambió de pista mientras la anterior todavía se estaba extrayendo).
        if path == self.media_path and audio_track == self._active_audio_track:
            self.waveform_widget.set_hires_peaks(peaks)
            QTimer.singleShot(0, self._sync_ruler)

    def keyPressEvent(self, event):
        """Maneja los atajos de teclado I (In), O (Out) y Espacio (Play/Pause)."""
        key = event.key()
        if key == Qt.Key_I:
            self.set_in_point()
        elif key == Qt.Key_O:
            self.set_out_point()
        elif key == Qt.Key_Space:
            self.toggle_play_pause()
        else:
            super().keyPressEvent(event)

    def toggle_play_pause(self):
        # Salir siempre de la previsualización en bucle de un rango guardado al usar el play/pause normal.
        self._preview_loop_range = None
        if self.pending_download:
            return
        if self.media_player.playbackState() == QMediaPlayer.PlayingState:
            self.media_player.pause()
            self.btn_play.setIcon(get_svg_icon("play_arrow.svg"))
            self.audio_meter.reset_levels()
        else:
            self.media_player.play()
            self.btn_play.setIcon(get_svg_icon("pause.svg"))
        self.playing_changed.emit(self.media_player.playbackState() == QMediaPlayer.PlayingState)

    def preview_range(self, in_sec: float, out_sec: float):
        """Reproduce en bucle dentro de un rango dado hasta que el usuario mueva el cabezal
        manualmente fuera de él o use el play/pause normal."""
        self._preview_loop_range = (in_sec, out_sec)
        self.media_player.setPosition(int(in_sec * 1000))
        self.media_player.play()
        self.btn_play.setIcon(get_svg_icon("pause.svg"))

    def set_in_point(self):
        pos_sec = self.media_player.position() / 1000.0
        if pos_sec >= self.out_sec:
            pos_sec = max(0.0, self.out_sec - 0.5)
        self.in_sec = pos_sec
        self._update_waveform_range()
        self._update_time_label()
        self.range_changed.emit(self.in_sec, self.out_sec)

    def set_out_point(self):
        pos_sec = self.media_player.position() / 1000.0
        if pos_sec <= self.in_sec:
            pos_sec = min(self.duration_sec, self.in_sec + 0.5)
        self.out_sec = pos_sec
        self._update_waveform_range()
        self._update_time_label()
        self.range_changed.emit(self.in_sec, self.out_sec)

    def _update_waveform_range(self):
        if self.duration_sec > 0:
            in_r = self.in_sec / self.duration_sec
            out_r = self.out_sec / self.duration_sec
            self.waveform_widget.set_range_ratios(in_r, out_r)

    def _on_waveform_seek(self, ratio: float):
        if self.duration_sec > 0:
            pos_sec = ratio * self.duration_sec
            # Si el usuario mueve manualmente el cabezal fuera del rango que se está
            # previsualizando en bucle, se sale de ese modo de bucle.
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
            self.range_changed.emit(self.in_sec, self.out_sec)

    def _on_player_position_changed(self, pos_ms: int):
        pos_sec = pos_ms / 1000.0

        # Previsualización en bucle de un rango guardado: al llegar al final del rango,
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
            self.timeline_ruler.duration_sec = max(0.001, new_dur)
            self.timeline_ruler.show_hours = new_dur >= 3600.0
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

    def _parse_time_ms(self, time_str: str):
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
        self.range_changed.emit(self.in_sec, self.out_sec)

    def _on_volume_changed(self, value):
        float_val = value if isinstance(value, float) else value / 100.0
        self.audio_output.setVolume(float_val)
