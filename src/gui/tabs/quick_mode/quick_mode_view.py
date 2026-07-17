import os
import platform
import re
import subprocess
import threading

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QImage, QPixmap, QIcon

from core.logger.logger_manager import logger
from core.utils.cleanup_manager import CleanupManager
from core.utils.config_manager import get_config
from core.ytdlp_logic.format_selectors import quick_format_selector
from gui.dialogs.playlist_selection_dialog import PlaylistSelectionDialog
from gui.styles import get_theme_token
from gui.tabs.advanced_process.output_options import OutputOptionsWidget
from gui.tabs.advanced_process.video_details_components import RichComboBox, RichTextDelegate, ThumbnailLoaderThread
from gui.tabs.advanced_process.workers import AnalysisWorker, DownloadWorker
from gui.widgets.animated_button import AnimatedButton


class QuickThumbnailWidget(QWidget):
    """
    Widget de tamaño fijo para mostrar la miniatura del medio
    y una etiqueta flotante de duración en la esquina inferior derecha.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(96, 54)
        
        # Etiqueta base de la imagen (sin scaledContents para evitar deformar iconos)
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
        # Redimensionar la imagen real manteniendo relación de aspecto
        scaled = pixmap.scaled(96, 54, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.thumb_label.setPixmap(scaled)


def reveal_in_file_manager(path):
    """Abre el gestor de archivos y selecciona/marca el archivo dado. Multiplataforma."""
    path = os.path.normpath(path)
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.Popen(["explorer", "/select,", path])
        elif system == "Darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            # Linux: intentar DBus FileManager1, fallback a xdg-open del directorio
            try:
                subprocess.Popen([
                    "dbus-send", "--session", "--dest=org.freedesktop.FileManager1",
                    "--type=method_call", "/org/freedesktop/FileManager1",
                    "org.freedesktop.FileManager1.ShowItems",
                    f"array:string:file://{path}", "string:"
                ])
            except Exception:
                folder = os.path.dirname(path)
                subprocess.Popen(["xdg-open", folder])
    except Exception as e:
        logger.warning(f"No se pudo revelar archivo en el gestor: {e}")


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
        self.downloaded_filepath = None  # Ruta del archivo descargado
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
        
        self.status_lbl = QLabel(self.tr("En espera"))
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
                border-radius: 12px;
                padding: 2px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('fondo_hover', '#2a2a2a')};
            }}
        """

        # Botón de abrir carpeta (oculto hasta que la descarga termine)
        self.btn_reveal = QPushButton()
        self.btn_reveal.setFixedSize(24, 24)
        self.btn_reveal.setToolTip(self.tr("Abrir ubicación del archivo"))
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
        self.btn_close.setToolTip(self.tr("Quitar de la lista"))
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
                border-radius: 8px;
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
        if self.downloaded_filepath and os.path.exists(self.downloaded_filepath):
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
            
        # 1. Actualizar título si es genérico
        title = info.get("title")
        if title and (self.original_title == self.tr("Descarga directa") or not self.original_title):
            self.original_title = title
            metrics = self.title_lbl.fontMetrics()
            elided = metrics.elidedText(title, Qt.ElideRight, self.title_lbl.width() or 300)
            self.title_lbl.setText(elided)
            self.title_lbl.setToolTip(title)
            
        # 2. Actualizar duración
        duration_sec = info.get("duration")
        if duration_sec and not self._duration_set:
            self.thumb_widget.set_duration(duration_sec)
            self._duration_set = True
            
        # 3. Actualizar miniatura
        if not self._thumb_loaded and not self._thumb_loading:
            thumb_url = None
            thumbs = info.get("thumbnails") or []
            valid = [t for t in thumbs if t.get("url")]
            if valid:
                # Ordenar por tamaño de menor a mayor (baja calidad primero)
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
        
        import re
        fallback_urls = []
        match = re.match(r'(https?://i\.ytimg\.com/vi/[^/]+/)([^?]+)', url)
        if match:
            base = match.group(1)
            # Miniatura de baja calidad de YouTube (default.jpg 120x90 es súper rápida de cargar)
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


class QuickModeTab(QWidget):
    def __init__(self):
        super().__init__()
        self.download_worker = None
        self.analysis_worker = None
        self.cancellation_event = threading.Event()
        self.is_downloading = False
        self.last_request_data = None
        self.last_downloaded_filepath = None
        self.item_rows = []
        self.item_keys = []
        self.current_item_pos = 0
        self.completed_items = 0
        self.init_ui()

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(15, 10, 15, 10)
        self.main_layout.setSpacing(8)

        self.url_panel = self._build_url_panel()
        self.options_panel = self._build_options_panel()
        self.activity_panel = self._build_activity_panel()
        self.output_options = OutputOptionsWidget()

        self.main_layout.addWidget(self.url_panel)
        self.main_layout.addWidget(self.options_panel)
        self.main_layout.addWidget(self.activity_panel, 1)
        self.main_layout.addWidget(self.output_options)

        # Aplicar el estilo de caja redondeada ("cuadro") a los paneles
        self.options_panel.setAttribute(Qt.WA_StyledBackground, True)
        self.activity_panel.setAttribute(Qt.WA_StyledBackground, True)
        
        borde_color = get_theme_token('borde_normal', '#2d2d2d')
        fondo_color = get_theme_token('fondo_secundario', '#1e1e1e')
        box_style = f"""
            QFrame#analysisOptionsBar {{
                background-color: {fondo_color};
                border: 1px solid {borde_color};
                border-radius: 12px;
            }}
        """
        self.options_panel.setStyleSheet(box_style)
        self.activity_panel.setStyleSheet(box_style)

        self.output_options.btn_start_download.setText(self.tr("Descargar"))
        self.output_options.btn_start_download.setEnabled(True)
        self.output_options.btn_start_download.clicked.connect(self._on_download_clicked)
        self.output_options.btn_open_output_path.clicked.disconnect()
        self.output_options.btn_open_output_path.clicked.connect(self._on_open_output_path_clicked)

        self._on_mode_changed(self.mode_combo.currentIndex())

    def _build_url_panel(self):
        panel = QWidget()
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(self.tr("Pega una URL para descargar directamente"))
        self.url_input.returnPressed.connect(self._on_download_clicked)

        # Botón circular conmutable para activar el recorte de fragmentos
        self.btn_cut = QPushButton()
        self.btn_cut.setCheckable(True)
        self.btn_cut.setFixedSize(34, 34)
        self.btn_cut.setToolTip(self.tr("Activar recorte de fragmento"))
        
        _icon_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..",
            "assets", "icons", "svg", "content_cut.svg"
        )
        _icon_path = os.path.normpath(_icon_path)
        if os.path.exists(_icon_path):
            self.btn_cut.setIcon(QIcon(_icon_path))
            self.btn_cut.setIconSize(QSize(18, 18))
        else:
            self.btn_cut.setText("✂")
            
        self.btn_cut.setStyleSheet(f"""
            QPushButton {{
                background-color: {get_theme_token('fondo_secundario', '#1e1e1e')};
                border: 1px solid {get_theme_token('borde', '#2d2d2d')};
                border-radius: 17px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('fondo_hover', '#2a2a2a')};
            }}
            QPushButton:checked {{
                background-color: #2e7d32;
                border-color: #4caf50;
            }}
            QPushButton:checked:hover {{
                background-color: #388e3c;
            }}
            QPushButton:disabled {{
                background-color: #555;
            }}
        """)

        self.btn_download = AnimatedButton(self.tr("Descargar"))
        self.btn_download.setObjectName("analyzeButton")
        self.btn_download.setFixedWidth(120)
        self.btn_download.clicked.connect(self._on_download_clicked)

        layout.addWidget(QLabel(self.tr("URL:")))
        layout.addWidget(self.url_input, 1)
        layout.addWidget(self.btn_cut)
        layout.addWidget(self.btn_download)
        return panel

    def _build_options_panel(self):
        panel = QFrame()
        panel.setObjectName("analysisOptionsBar")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(15, 6, 15, 6)
        layout.setSpacing(12)

        layout.addWidget(QLabel(self.tr("Modo:")))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem(self.tr("Video + Audio"), "video+audio")
        self.mode_combo.addItem(self.tr("Solo Audio"), "audio_only")
        self.mode_combo.addItem(self.tr("Solo Video"), "video_only")
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        layout.addWidget(self.mode_combo)

        layout.addWidget(QLabel(self.tr("Calidad:")))
        self.quality_combo = RichComboBox()
        self.quality_combo.setItemDelegate(RichTextDelegate())
        layout.addWidget(self.quality_combo)

        self.chk_playlist_selector = QCheckBox(self.tr("Seleccionar playlist"))
        self.chk_playlist_selector.toggled.connect(self._on_playlist_selector_toggled)
        layout.addWidget(self.chk_playlist_selector)

        self.chk_thumb_file = QCheckBox(self.tr("Guardar miniatura"))
        layout.addWidget(self.chk_thumb_file)

        self.chk_thumb_only = QCheckBox(self.tr("Solo miniatura"))
        self.chk_thumb_only.toggled.connect(self._on_thumbnail_only_toggled)
        layout.addWidget(self.chk_thumb_only)

        layout.addStretch(1)
        return panel

    def _build_activity_panel(self):
        panel = QFrame()
        panel.setObjectName("analysisOptionsBar")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # Barra de encabezado con botón "Limpiar todo"
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)
        header_layout.addStretch(1)

        icon_dir = os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "assets", "icons", "svg"
        ))
        self.btn_clear_all = QPushButton(self.tr("Limpiar"))
        self.btn_clear_all.setFixedHeight(22)
        self.btn_clear_all.setToolTip(self.tr("Cancelar descargas activas y limpiar la lista"))
        _delete_icon = os.path.join(icon_dir, "delete.svg")
        if os.path.exists(_delete_icon):
            self.btn_clear_all.setIcon(QIcon(_delete_icon))
            self.btn_clear_all.setIconSize(QSize(14, 14))
        self.btn_clear_all.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {get_theme_token('texto_secundario', '#888888')};
                border: 1px solid {get_theme_token('borde', '#2d2d2d')};
                border-radius: 6px;
                padding: 2px 10px;
                font-size: 10px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('fondo_hover', '#2a2a2a')};
                color: #ff6b6b;
                border-color: #ff6b6b;
            }}
        """)
        self.btn_clear_all.clicked.connect(self._on_clear_all_clicked)
        self.btn_clear_all.hide()  # Ocultar hasta que haya items
        header_layout.addWidget(self.btn_clear_all)
        layout.addLayout(header_layout)

        self.activity_scroll = QScrollArea()
        self.activity_scroll.setWidgetResizable(True)
        self.activity_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.activity_scroll.setStyleSheet("border: none; background: transparent;")

        self.activity_container = QWidget()
        self.activity_layout = QVBoxLayout(self.activity_container)
        self.activity_layout.setContentsMargins(0, 0, 0, 0)
        self.activity_layout.setSpacing(8)
        
        # Etiqueta de marcador de posición (placeholder) cuando no hay descargas
        self.empty_lbl = QLabel(self.tr("Aquí aparecerán tus descargas"))
        self.empty_lbl.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#888888')}; font-size: 11px;")
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        self.activity_layout.addWidget(self.empty_lbl)
        
        self.activity_layout.addStretch(1)
        self.activity_scroll.setWidget(self.activity_container)
        layout.addWidget(self.activity_scroll, 1)
        return panel

    def _on_mode_changed(self, index):
        mode = self.mode_combo.itemData(index) or "video+audio"
        current = self.quality_combo.currentData()
        self.quality_combo.clear()

        self.quality_combo.addItem(self.tr("Mejor compatible") + " ✨", "best_compatible")
        self.quality_combo.addItem(self.tr("Máxima calidad"), "best")
        if mode != "audio_only":
            self.quality_combo.addItem("4K (2160p)", "2160")
            self.quality_combo.addItem("2K (1440p)", "1440")
            self.quality_combo.addItem("1080p", "1080")
            self.quality_combo.addItem("720p", "720")
            self.quality_combo.addItem("480p", "480")
            self.quality_combo.addItem("360p", "360")
        else:
            self.quality_combo.addItem(self.tr("Alta"), "320")
            self.quality_combo.addItem(self.tr("Media"), "192")
            self.quality_combo.addItem(self.tr("Baja"), "128")

        if current:
            idx = self.quality_combo.findData(current)
            if idx >= 0:
                self.quality_combo.setCurrentIndex(idx)

    def _on_thumbnail_only_toggled(self, checked):
        self.mode_combo.setEnabled(not checked)
        self.quality_combo.setEnabled(not checked)
        self.chk_thumb_file.setEnabled(not checked)

    def _on_download_clicked(self):
        if self.is_downloading:
            self._cancel_download()
            return

        url = self.url_input.text().strip()
        if not url:
            self.output_options.set_progress(0, self.tr("Pega una URL primero"), "error")
            return

        if self.btn_cut.isChecked():
            self._start_cut_analysis(url)
        elif self.chk_playlist_selector.isChecked():
            self._start_playlist_selection(url)
        else:
            self._start_direct_download(url)

    def _start_cut_analysis(self, url):
        self._set_busy(True, self.tr("Analizando video para recorte..."))
        self.analysis_worker = AnalysisWorker(url, analyze_playlist=False, fast_mode=True)
        
        def on_finished(data, error):
            if self.analysis_worker:
                self.analysis_worker.deleteLater()
            self.analysis_worker = None
            
            if error:
                self._set_busy(False)
                self.output_options.set_progress(0, self.tr(f"Error al analizar: {error}"), "error")
                return
                
            self._open_cut_dialog_and_download(url, data)
            
        self.analysis_worker.finished.connect(on_finished)
        self.analysis_worker.start()

    def _open_cut_dialog_and_download(self, url, data):
        # 1. Buscar la miniatura del video
        thumb_url = None
        thumbs = data.get("thumbnails") or []
        valid_thumbs = [t for t in thumbs if t.get("url")]
        if valid_thumbs:
            valid_thumbs.sort(key=lambda t: (t.get("width") or 0) * (t.get("height") or 0), reverse=True)
            thumb_url = valid_thumbs[0]["url"]
        else:
            thumb_url = data.get("thumbnail")

        # Descargar miniatura de manera síncrona pero rápida para pasarla al diálogo
        pixmap = None
        if thumb_url:
            try:
                import requests
                from PySide6.QtGui import QImage, QPixmap
                resp = requests.get(thumb_url, timeout=3)
                resp.raise_for_status()
                img = QImage.fromData(resp.content)
                if not img.isNull():
                    pixmap = QPixmap.fromImage(img)
            except Exception as e:
                logger.warning(f"QuickModeTab: No se pudo descargar miniatura para FragmentDialog: {e}")

        # 2. Encontrar stream_url para la vista previa del reproductor
        formats = data.get("formats") or []
        preview_format = None
        for f in formats:
            if f.get("url") and not f.get("url", "").startswith("rtmp") and f.get("acodec") != "none" and f.get("vcodec") != "none":
                h = f.get("height") or 0
                if 360 <= h <= 720:
                    preview_format = f
                    break
        if not preview_format:
            for f in formats:
                if f.get("url") and f.get("vcodec") != "none":
                    preview_format = f
                    break
        stream_url = preview_format.get("url", "") if preview_format else ""

        # 3. Lanzar FragmentDialog con un overlay semitransparente sobre la ventana principal
        from gui.dialogs.fragment_dialog import FragmentDialog
        
        dialog = FragmentDialog(
            self,
            stream_url=stream_url,
            thumbnail_pixmap=pixmap,
            duration=data.get("duration", 0),
            fps=data.get("fps", 30) or 30,
            source_url=data.get("webpage_url", url),
        )

        main_win = self.window()
        overlay = None
        try:
            from PySide6.QtWidgets import QWidget as _QWidget
            overlay = _QWidget(main_win)
            overlay.setStyleSheet("background-color: rgba(0, 0, 0, 160);")
            overlay.setGeometry(main_win.rect())
            overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            overlay.show()
            overlay.raise_()
        except Exception:
            overlay = None

        result = dialog.exec()

        if overlay is not None:
            try:
                overlay.hide()
                overlay.deleteLater()
            except Exception:
                pass

        # 4. Si el usuario guarda el fragmento
        if result:
            frag_data = dialog.get_fragments_data()
            selected_fragments = frag_data["fragments"]
            fragment_mode = frag_data["mode"]
            
            # Construimos la petición de descarga
            req = self._build_request_data(url=url, title=data.get("title", ""), is_playlist=False)
            req["selected_fragments"] = selected_fragments
            req["fragment_mode"] = fragment_mode
            
            # Limpiamos e iniciamos descarga
            self.is_downloading = True
            self._set_busy(False)
            self._set_download_text(self.tr("Cancelar"))
            
            # Iniciamos la descarga pasándole la info analizada para rellenar la tarjeta
            self._start_worker(req, selected_entries=[data], selected_indices=[0])
        else:
            self._set_busy(False)
            self.output_options.set_progress(0, self.tr("Recorte cancelado"), "wait")

    def _start_playlist_selection(self, url):
        self._set_busy(True, self.tr("Analizando playlist..."))
        self.analysis_worker = AnalysisWorker(url, analyze_playlist=True, fast_mode=True)

        def on_finished(data, error):
            if self.analysis_worker:
                self.analysis_worker.deleteLater()
            self.analysis_worker = None
            if error:
                self._set_busy(False)
                self.output_options.set_progress(0, self.tr(f"Error: {error}"), "error")
                return

            entries = data.get("entries") or []
            if len(entries) <= 1:
                self._set_busy(False)
                self._start_direct_download(url)
                return

            dialog = PlaylistSelectionDialog(data, self)
            if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.result_data:
                self._set_busy(False)
                self.output_options.set_progress(0, self.tr("Selección cancelada"), "wait")
                return

            selected = dialog.result_data.get("selected_indices", [])
            if not selected:
                self._set_busy(False)
                self.output_options.set_progress(0, self.tr("No se seleccionaron medios"), "error")
                return

            req = self._build_request_data(
                url=data.get("original_url", data.get("webpage_url", url)),
                title=data.get("title") or self.tr("Playlist"),
                is_playlist=True,
                playlist_items=",".join(str(i + 1) for i in selected),
                playlist_mode=dialog.result_data.get("playlist_mode"),
                playlist_quality=dialog.result_data.get("playlist_quality"),
            )
            selected_entries = [entries[i] for i in selected if 0 <= i < len(entries)]
            self._start_worker(req, selected_entries=selected_entries, selected_indices=selected)

        self.analysis_worker.finished.connect(on_finished)
        self.analysis_worker.start()

    def _start_direct_download(self, url):
        req = self._build_request_data(
            url=url,
            title="",
            is_playlist=False,
        )
        self._start_worker(req, selected_entries=[{"title": self.tr("Descarga directa")}], selected_indices=[0])

    def _build_request_data(self, url, title="", is_playlist=False, playlist_items=None,
                            playlist_mode=None, playlist_quality=None):
        mode = playlist_mode or self.mode_combo.currentData() or "video+audio"
        quality = playlist_quality or self.quality_combo.currentData() or "best_compatible"

        if self.chk_thumb_only.isChecked():
            mode = "thumbnail_only"
            format_selector = "best"
        else:
            format_selector = quick_format_selector(mode, quality)

        output_path = self.output_options.output_path_input.text()
        request_title = title
        if is_playlist and title:
            safe_folder = re.sub(r'[<>:"/\\|?*#]', '', str(title)).strip() or self.tr("Playlist")
            output_path = os.path.join(output_path, safe_folder)
            request_title = ""

        config = get_config()
        req = {
            "url": url,
            "title": request_title,
            "mode": mode,
            "output_path": output_path,
            "format_selector": format_selector,
            "speed_limit": f"{int(self.output_options.speed_limit_input.value() * 1024)}K" if self.output_options.speed_limit_input.value() > 0 else None,
            "download_thumbnail_file": self.chk_thumb_file.isChecked() or self.chk_thumb_only.isChecked(),
            "embed_metadata": config.get("embed_metadata", True),
            "embed_thumbnail": config.get("embed_thumbnail", True),
            "remove_sponsors": config.get("remove_sponsors", False),
            "is_playlist": is_playlist,
            "force_audio_extract": mode == "audio_only",
            "audio_ext": "mp3" if mode == "audio_only" and quality in ("320", "192", "128") else None,
            "video_ext": "mp4" if mode != "audio_only" else None,
            "selected_fragments": [],
            "fragment_mode": None,
        }
        if playlist_items:
            req["playlist_items"] = playlist_items
        return req

    def _start_worker(self, request_data, selected_entries=None, selected_indices=None):
        self.cancellation_event.clear()
        self.last_request_data = request_data.copy()
        self.last_downloaded_filepath = None
        self._prepare_activity_rows(selected_entries or [], selected_indices or [])
        self.download_worker = DownloadWorker(request_data, self.cancellation_event)
        self.download_worker.progress.connect(self._on_download_progress)
        self.download_worker.finished.connect(self._on_download_finished)
        self.is_downloading = True
        self._set_controls_enabled(False)
        self._set_download_text(self.tr("Cancelar"))
        self.output_options.set_progress(0, self.tr("Iniciando descarga..."), "running")
        self.download_worker.start()

    def _prepare_activity_rows(self, entries, selected_indices):
        self._clear_activity_rows()
        self.item_keys = []
        self.current_item_pos = 1 if entries else 0
        self.completed_items = 0
        self.empty_lbl.hide()
        self.btn_clear_all.show()

        for idx, entry in enumerate(entries):
            title = entry.get("title") or entry.get("id") or entry.get("url") or self.tr(f"Item {idx + 1}")
            self.item_keys.append(entry.get("playlist_index") or (selected_indices[idx] + 1 if idx < len(selected_indices) else idx + 1))
            row = QuickDownloadRow(str(title), self.activity_container)
            row.update_metadata_from_dict(entry)
            row.close_requested.connect(self._on_row_close_requested)
            row.reveal_requested.connect(self._on_row_reveal_requested)
            self.activity_layout.insertWidget(self.activity_layout.count() - 1, row)
            self.item_rows.append(row)

        if self.item_rows:
            self.item_rows[0].update_progress(0, status=self.tr("Preparando"))

    def _clear_activity_rows(self):
        for row in self.item_rows:
            if hasattr(row, "destroy_row"):
                row.destroy_row()
            self.activity_layout.removeWidget(row)
            row.deleteLater()
        self.item_rows = []
        self.item_keys = []
        self.current_item_pos = 0
        self.completed_items = 0
        self.empty_lbl.show()
        self.btn_clear_all.hide()

    def _cancel_download(self):
        if self.download_worker:
            self.cancellation_event.set()
        self.is_downloading = False
        self._set_controls_enabled(True)
        self._set_download_text(self.tr("Descargar"))
        self.output_options.set_progress(0, self.tr("Cancelando descarga..."), "wait")

    def _on_download_progress(self, data):
        if data.get("status") == "downloading":
            from core.ytdlp_logic.analyzer import strip_ansi_codes
            p_str = strip_ansi_codes(data.get("_percent_str", "0%")).replace("%", "").strip()
            try:
                val = float(p_str)
            except Exception:
                val = 0
            speed = strip_ansi_codes(data.get("_speed_str", "")).strip() or "..."
            eta = strip_ansi_codes(data.get("_eta_str", "")).strip() or "..."
            row_idx = self._resolve_progress_row(data)
            if row_idx is not None and 0 <= row_idx < len(self.item_rows):
                self.current_item_pos = row_idx + 1
                row = self.item_rows[row_idx]
                row.update_progress(
                    val,
                    info=f"{speed} - ETA: {eta}",
                    status=self.tr("Descargando"),
                )
                info = data.get("info_dict")
                if info:
                    row.update_metadata_from_dict(info)
            total = max(1, len(self.item_rows))
            global_percent = ((max(0, self.current_item_pos - 1) + (val / 100.0)) / total) * 100.0
            self.output_options.set_progress(
                int(global_percent),
                self.tr("{} de {}").format(max(1, self.current_item_pos), total),
                "downloading",
            )
        elif data.get("status") == "finished":
            filepath = data.get("filename")
            if filepath:
                self.last_downloaded_filepath = filepath
            row_idx = self._resolve_progress_row(data)
            if row_idx is not None and 0 <= row_idx < len(self.item_rows):
                row = self.item_rows[row_idx]
                row.update_progress(100, status=self.tr("Procesando"))
                if filepath:
                    row.downloaded_filepath = filepath
                info = data.get("info_dict")
                if info:
                    row.update_metadata_from_dict(info)
                self.completed_items = max(self.completed_items, row_idx + 1)
                self.current_item_pos = min(len(self.item_rows), row_idx + 2)
            total = max(1, len(self.item_rows))
            self.output_options.set_progress(
                int((self.completed_items / total) * 100),
                self.tr("{} de {}").format(min(total, self.completed_items + 1), total),
                "downloading",
            )

    def _resolve_progress_row(self, data):
        if len(self.item_rows) <= 1:
            return 0 if self.item_rows else None
        info = data.get("info_dict") or {}
        playlist_index = info.get("playlist_index")
        if playlist_index in self.item_keys:
            return self.item_keys.index(playlist_index)
        return max(0, min(len(self.item_rows) - 1, self.current_item_pos - 1))

    def _on_download_finished(self, success, message):
        self.is_downloading = False
        self._set_controls_enabled(True)
        self._set_download_text(self.tr("Descargar"))
        if success:
            for row in self.item_rows:
                row.update_progress(100, status=self.tr("Completado"))
                row.mark_completed()
            title = self.last_request_data.get("title", "").strip()
            output_dir = self.last_request_data.get("output_path", "")
            if title and output_dir:
                keep_thumb = self.last_request_data.get("download_thumbnail_file", False)
                CleanupManager.cleanup_ytdlp_temp_files(output_dir, title, keep_thumbnail=keep_thumb)
                CleanupManager.deferred_cleanup(output_dir, title, keep_thumbnail=keep_thumb)
            self.output_options.set_progress(100, self.tr("Descarga completada con éxito"), "done")
            logger.info("QuickModeTab: Descarga finalizada con éxito.")
        else:
            if self.item_rows:
                idx = max(0, min(len(self.item_rows) - 1, self.current_item_pos - 1))
                self.item_rows[idx].update_progress(0, status=self.tr("Error"))
                self.item_rows[idx].mark_error()
            self.output_options.set_progress(0, self.tr(f"Error: {message}"), "error")
            logger.error(f"QuickModeTab: Error en descarga: {message}")
        if self.download_worker:
            self.download_worker.deleteLater()
        self.download_worker = None

    def _set_busy(self, busy, message=None):
        self._set_controls_enabled(not busy)
        self._set_download_text(self.tr("Analizando...") if busy else self.tr("Descargar"))
        if message:
            self.output_options.set_progress(0, message, "running" if busy else "wait")

    def _on_playlist_selector_toggled(self, checked):
        """Cuando playlist está activa, deshabilitar y desactivar el corte de fragmento."""
        if checked:
            self.btn_cut.setChecked(False)
            self.btn_cut.setEnabled(False)
        else:
            self.btn_cut.setEnabled(True)

    def _set_controls_enabled(self, enabled):
        self.url_input.setEnabled(enabled)
        self.btn_download.setEnabled(enabled or self.is_downloading)
        self.output_options.btn_start_download.setEnabled(enabled or self.is_downloading)
        self.options_panel.setEnabled(enabled)
        self.output_options.output_path_input.setEnabled(enabled)
        self.output_options.btn_select_output_path.setEnabled(enabled)
        self.output_options.speed_limit_input.setEnabled(enabled)
        # btn_cut: solo habilitar si playlist_selector no está activo
        if enabled:
            self.btn_cut.setEnabled(not self.chk_playlist_selector.isChecked())
        else:
            self.btn_cut.setEnabled(False)

    def _set_download_text(self, text):
        self.btn_download.setText(text)
        self.output_options.btn_start_download.setText(text)

    def _on_open_output_path_clicked(self):
        path = self.output_options.output_path_input.text().strip()
        if not path:
            return
        if self.last_downloaded_filepath and os.path.exists(self.last_downloaded_filepath):
            reveal_in_file_manager(self.last_downloaded_filepath)
            return

        if os.path.exists(path):
            if os.name == "nt":
                os.startfile(path if os.path.isdir(path) else os.path.dirname(path))
            else:
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl.fromLocalFile(path if os.path.isdir(path) else os.path.dirname(path)))

    # --- Handlers de acciones por fila ---

    def _on_row_close_requested(self, row):
        """Quitar un item de la lista. Si estaba descargándose activamente, cancela."""
        if row not in self.item_rows:
            return
        idx = self.item_rows.index(row)
        # Si es el único item y está descargando, cancelar toda la descarga
        if self.is_downloading and len(self.item_rows) == 1:
            self._cancel_download()
        # Remover de las listas de tracking
        self.item_rows.pop(idx)
        if idx < len(self.item_keys):
            self.item_keys.pop(idx)
        # Remover widget
        row.destroy_row()
        self.activity_layout.removeWidget(row)
        row.deleteLater()
        # Actualizar visibilidad
        if not self.item_rows:
            self.empty_lbl.show()
            self.btn_clear_all.hide()

    def _on_row_reveal_requested(self, row):
        """Abrir el gestor de archivos y seleccionar el archivo descargado."""
        if row.downloaded_filepath and os.path.exists(row.downloaded_filepath):
            reveal_in_file_manager(row.downloaded_filepath)

    def _on_clear_all_clicked(self):
        """Cancelar descargas activas y limpiar toda la lista."""
        if self.is_downloading:
            self._cancel_download()
        self._clear_activity_rows()
