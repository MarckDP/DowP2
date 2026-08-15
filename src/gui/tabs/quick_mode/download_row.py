# src/gui/tabs/quick_mode/download_row.py
import os
import re
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QImage, QPixmap, QIcon

from core.logger.logger_manager import logger
from gui.styles import get_theme_token
from gui.tabs.advanced_process.video_details_components import ThumbnailLoaderThread
from core.tabs.quick_mode.quick_mode_logic import reveal_in_file_manager


class QuickThumbnailWidget(QWidget):
    """
    Widget de tamaño fijo para mostrar la miniatura del medio
    y una etiqueta flotante de duración en la esquina inferior derecha.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(96, 54)
        
        # Etiqueta base de la imagen
        self.thumb_label = QLabel(self)
        self.thumb_label.setFixedSize(96, 54)
        self.thumb_label.setScaledContents(False)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        
        # Etiqueta de duración superpuesta
        self.duration_label = QLabel(self)
        self.duration_label.setStyleSheet("""
            background-color: rgba(0, 0, 0, 0.75);
            color: #ffffff;
            font-size: 8px;
            font-weight: bold;
            border-radius: 3px;
            padding: 1px 3px;
        """)
        self.duration_label.setAlignment(Qt.AlignCenter)
        self.duration_label.hide()
        
        self.thumb_label.setGeometry(0, 0, 96, 54)
        self._set_default_thumbnail()
        
    def _set_default_thumbnail(self):
        icon_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "assets", "icons", "svg", "movie.svg")
        icon_path = os.path.normpath(icon_path)
        
        bg_color = get_theme_token('fondo_principal', '#121212')
        borde_color = get_theme_token('borde', '#2d2d2d')
        
        self.thumb_label.setStyleSheet(f"""
            QLabel {{
                background-color: {bg_color};
                border: 1px solid {borde_color};
                border-radius: 4px;
            }}
        """)
        
        if os.path.exists(icon_path):
            pixmap = QIcon(icon_path).pixmap(24, 24)
            self.thumb_label.setPixmap(pixmap)
        else:
            self.thumb_label.setText("🎞️")
            
    def set_duration(self, duration_sec):
        if not duration_sec:
            self.duration_label.hide()
            return
        try:
            seconds = int(float(duration_sec))
            h = seconds // 3600
            m = (seconds % 3600) // 60
            s = seconds % 60
            if h > 0:
                formatted = f"{h}:{m:02d}:{s:02d}"
            else:
                formatted = f"{m:02d}:{s:02d}"
            self.duration_label.setText(formatted)
            self.duration_label.adjustSize()
            
            # Posicionar en la esquina inferior derecha
            lbl_w = self.duration_label.width()
            lbl_h = self.duration_label.height()
            self.duration_label.setGeometry(96 - lbl_w - 4, 54 - lbl_h - 4, lbl_w, lbl_h)
            self.duration_label.show()
        except Exception:
            self.duration_label.hide()
            
    def set_pixmap(self, pixmap):
        self.thumb_label.setText("")
        self.thumb_label.setStyleSheet("background-color: transparent; border: none;")
        scaled = pixmap.scaled(96, 54, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.thumb_label.setPixmap(scaled)


class QuickDownloadRow(QFrame):
    """Tarjeta individual de descarga con miniatura, progreso y botones de acción."""
    close_requested = Signal(object)    # Emitido al pulsar X
    reveal_requested = Signal(object)   # Emitido al pulsar botón de carpeta

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("queueItemCard")
        self.original_title = title
        self._thumb_loaded = False
        self._thumb_loading = False
        self.thumb_thread = None
        self._duration_set = False
        self.downloaded_filepath = None
        self._is_completed = False
        self._is_error = False
        self.init_ui(title)

    def init_ui(self, title):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 8, 10, 8)
        main_layout.setSpacing(12)

        # Miniatura a la izquierda
        self.thumb_widget = QuickThumbnailWidget(self)
        main_layout.addWidget(self.thumb_widget)

        # Detalles en el centro
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)

        # Fila superior: Título y Estado
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet(f"color: {get_theme_token('texto_principal', '#dddddd')}; font-weight: bold;")
        self.title_lbl.setWordWrap(False)
        self.title_lbl.setToolTip(title)
        
        self.status_lbl = QLabel(self.tr("En espera") if hasattr(self, "tr") else "En espera")
        self.status_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.status_lbl.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#aaaaaa')}; font-size: 10px;")
        
        top_layout.addWidget(self.title_lbl, 1)
        top_layout.addWidget(self.status_lbl)
        content_layout.addLayout(top_layout)

        # Barra de progreso intermedia
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        content_layout.addWidget(self.progress_bar)

        # Fila inferior: Info y Porcentaje
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        self.info_lbl = QLabel("")
        self.info_lbl.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#888888')}; font-size: 10px;")
        
        self.percent_lbl = QLabel("0%")
        self.percent_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.percent_lbl.setStyleSheet(f"color: {get_theme_token('acento_primario', '#B9E640')}; font-size: 10px; font-weight: bold;")
        
        bottom_layout.addWidget(self.info_lbl, 1)
        bottom_layout.addWidget(self.percent_lbl)
        content_layout.addLayout(bottom_layout)

        main_layout.addLayout(content_layout, 1)

        # --- Botones de acción a la derecha ---
        actions_layout = QVBoxLayout()
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(4)
        actions_layout.setAlignment(Qt.AlignCenter)

        icon_dir = os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "assets", "icons", "svg"
        ))
        _action_btn_style = f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 6px;
                padding: 2px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('fondo_hover', '#2a2a2a')};
            }}
        """

        # Botón de abrir carpeta (oculto hasta que la descarga termine)
        self.btn_reveal = QPushButton()
        self.btn_reveal.setFixedSize(24, 24)
        self.btn_reveal.setToolTip(self.tr("Abrir ubicación del archivo") if hasattr(self, "tr") else "Abrir ubicación del archivo")
        self.btn_reveal.setStyleSheet(_action_btn_style)
        _folder_icon = os.path.join(icon_dir, "folder_open.svg")
        if os.path.exists(_folder_icon):
            self.btn_reveal.setIcon(QIcon(_folder_icon))
            self.btn_reveal.setIconSize(QSize(16, 16))
        else:
            self.btn_reveal.setText("📂")
        self.btn_reveal.hide()
        self.btn_reveal.clicked.connect(lambda: self.reveal_requested.emit(self))

        # Botón X (cerrar / quitar de la lista)
        self.btn_close = QPushButton()
        self.btn_close.setFixedSize(24, 24)
        self.btn_close.setToolTip(self.tr("Quitar de la lista") if hasattr(self, "tr") else "Quitar de la lista")
        self.btn_close.setStyleSheet(_action_btn_style)
        _close_icon = os.path.join(icon_dir, "close.svg")
        if os.path.exists(_close_icon):
            self.btn_close.setIcon(QIcon(_close_icon))
            self.btn_close.setIconSize(QSize(14, 14))
        else:
            self.btn_close.setText("✕")
        self.btn_close.clicked.connect(lambda: self.close_requested.emit(self))

        actions_layout.addWidget(self.btn_reveal)
        actions_layout.addWidget(self.btn_close)
        main_layout.addLayout(actions_layout)

        self.setStyleSheet(f"""
            QFrame#queueItemCard {{
                background-color: {get_theme_token('fondo_principal', '#121212')};
                border: 1px solid {get_theme_token('borde', '#2d2d2d')};
                border-radius: 6px;
            }}
            QLabel {{
                color: {get_theme_token('texto_principal', '#dddddd')};
            }}
            QProgressBar {{
                background-color: {get_theme_token('progreso_fondo', '#0f0f0f')};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {get_theme_token('progreso_inicio', '#35d6b8')},
                    stop:1 {get_theme_token('progreso_fin', '#138f7d')});
                border-radius: 3px;
            }}
        """)

    def mark_completed(self, filepath=None):
        """Marca este item como completado y muestra el botón de carpeta."""
        self._is_completed = True
        if filepath:
            self.downloaded_filepath = filepath
        if self.downloaded_filepath:
            if os.path.exists(self.downloaded_filepath):
                self.btn_reveal.show()
            else:
                # Si las extensiones temporales cambiaron al fusionar con ffmpeg, verificar el directorio destino
                parent = os.path.dirname(self.downloaded_filepath)
                if parent and os.path.exists(parent):
                    self.btn_reveal.show()

    def mark_error(self):
        """Marca este item como error."""
        self._is_error = True

    def update_progress(self, percent, info="", status=None):
        percent = max(0, min(100, int(percent)))
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(percent)
        self.percent_lbl.setText(f"{percent}%")
        if info:
            self.info_lbl.setText(info)
            self.info_lbl.setToolTip(info)
        if status:
            self.status_lbl.setText(status)

    def update_metadata_from_dict(self, info):
        if not info:
            return
            
        title = info.get("title")
        if title and (self.original_title == (self.tr("Descarga directa") if hasattr(self, "tr") else "Descarga directa") or not self.original_title):
            self.original_title = title
            metrics = self.title_lbl.fontMetrics()
            elided = metrics.elidedText(title, Qt.ElideRight, self.title_lbl.width() or 300)
            self.title_lbl.setText(elided)
            self.title_lbl.setToolTip(title)
            
        duration_sec = info.get("duration")
        if duration_sec and not self._duration_set:
            self.thumb_widget.set_duration(duration_sec)
            self._duration_set = True
            
        if not self._thumb_loaded and not self._thumb_loading:
            thumb_url = None
            thumbs = info.get("thumbnails") or []
            valid = [t for t in thumbs if t.get("url")]
            if valid:
                valid.sort(key=lambda t: (t.get("width") or 0) * (t.get("height") or 0))
                thumb_url = valid[0]["url"]
            else:
                thumb_url = info.get("thumbnail")
                
            if thumb_url:
                self.load_thumbnail(thumb_url)

    def load_thumbnail(self, url):
        if not url or self._thumb_loaded or self._thumb_loading:
            return
        self._thumb_loading = True
        
        fallback_urls = []
        match = re.match(r'(https?://i\.ytimg\.com/vi/[^/]+/)([^?]+)', url)
        if match:
            base = match.group(1)
            primary = base + "default.jpg"
            fallback_urls = [base + "mqdefault.jpg", url]
        else:
            primary = url
            
        self.thumb_thread = ThumbnailLoaderThread(primary, fallback_urls=fallback_urls)
        
        def on_finished(content, error):
            self._thumb_loading = False
            if content:
                self._thumb_loaded = True
                img = QImage.fromData(content)
                if not img.isNull():
                    pix = QPixmap.fromImage(img)
                    self.thumb_widget.set_pixmap(pix)
            if self.thumb_thread:
                self.thumb_thread.deleteLater()
            self.thumb_thread = None
            
        self.thumb_thread.finished.connect(on_finished)
        self.thumb_thread.start()

    def destroy_row(self):
        if self.thumb_thread:
            try:
                self.thumb_thread.finished.disconnect()
            except Exception:
                pass
            try:
                if self.thumb_thread.isRunning():
                    self.thumb_thread.quit()
                    self.thumb_thread.wait()
            except RuntimeError:
                pass
            self.thumb_thread = None
