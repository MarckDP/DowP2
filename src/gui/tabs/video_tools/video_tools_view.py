# src/gui/tabs/video_tools/video_tools_view.py
import os
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QSplitter,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QFrame,
    QMessageBox,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon

from gui.widgets.animated_button import AnimatedButton
from gui.widgets.bouncing_progress_bar import BouncingProgressBar
from gui.widgets.media_trim_player_widget import MediaTrimPlayerWidget
from gui.tabs.video_tools.media_queue_widget import MediaQueueWidget
from gui.tabs.video_tools.encoding_options_widget import EncodingOptionsWidget
from core.logger.logger_manager import logger
from core.utils.config_manager import get_config, save_config
from core.tabs.editing_media.ffprobe_metadata_manager import FFprobeMetadataManager

AUDIO_ONLY_EXTENSIONS = {".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a", ".opus", ".wma"}

class VideoToolsTab(QWidget):
    """
    Pestaña de Herramientas Multimedia / Recodificador (Diseño de 2 Columnas Unificadas).
    Organiza la interfaz en 2 paneles principales:
      - Columna Izquierda: Vista Previa Multimedia (arriba) + Cola de Medios Importados (abajo).
      - Columna Derecha: Panel de Opciones con Pestañas (Preajustes/Avanzados/Herramientas) + Cubo de Salida e Iniciar.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_preview_file = ""
        self.in_point_ms = 0
        self.out_point_ms = 0

        self.init_ui()
        self._load_saved_output_dir()
        FFprobeMetadataManager.get_instance().metadata_ready.connect(self._on_metadata_ready)

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # 1. Splitter Principal Horizontal (2 Columnas: Izquierda vs Derecha)
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setHandleWidth(6)

        # -------------------------------------------------------------
        # COLUMNA IZQUIERDA: Vista Previa (Arriba) + Cola de Medios (Abajo)
        # -------------------------------------------------------------
        self.left_splitter = QSplitter(Qt.Vertical)
        self.left_splitter.setHandleWidth(6)

        self.preview_widget = MediaTrimPlayerWidget(self, card_style=True)
        self.preview_widget.range_changed.connect(self._on_trim_range_changed)

        self.queue_widget = MediaQueueWidget(self)
        self.queue_widget.file_selected.connect(self._on_file_selected)

        self.left_splitter.addWidget(self.preview_widget)
        self.left_splitter.addWidget(self.queue_widget)
        self.left_splitter.setSizes([450, 300])

        # -------------------------------------------------------------
        # COLUMNA DERECHA: Opciones (Pestañas) + Cubo de Salida
        # -------------------------------------------------------------
        self.right_container = QWidget()
        right_layout = QVBoxLayout(self.right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        # 1. Panel Superior de Opciones con Pestañas
        self.options_widget = EncodingOptionsWidget(self)
        right_layout.addWidget(self.options_widget, 1)

        # 2. Cubo Inferior de Opciones de Salida y Ejecución
        # Reutiliza el mismo estilo (objectName) que el resto de la app para estos
        # componentes (definido en gui/themes/_base.qss), en vez de un stylesheet ad-hoc.
        self.output_card = QFrame()
        self.output_card.setObjectName("outputOptionsContainer")
        out_layout = QVBoxLayout(self.output_card)
        out_layout.setContentsMargins(10, 10, 10, 10)
        out_layout.setSpacing(8)

        lbl_out_title = QLabel(self.tr("Opciones de Salida y Procesamiento"))
        lbl_out_title.setObjectName("sectionTitle")
        out_layout.addWidget(lbl_out_title)

        grid_out = QGridLayout()
        grid_out.setSpacing(6)

        # Destino
        lbl_dest = QLabel(self.tr("Carpeta de Salida:"))
        lbl_dest.setObjectName("menuLabel")
        grid_out.addWidget(lbl_dest, 0, 0)
        self.txt_output_dir = QLineEdit()
        self.txt_output_dir.setPlaceholderText(self.tr("Seleccionar carpeta de destino..."))
        grid_out.addWidget(self.txt_output_dir, 0, 1)

        self.btn_browse_output = QPushButton(self.tr("Examinar"))
        self.btn_browse_output.setObjectName("pathToolButton")
        self.btn_browse_output.setCursor(Qt.PointingHandCursor)
        self.btn_browse_output.clicked.connect(self._on_browse_output_clicked)
        grid_out.addWidget(self.btn_browse_output, 0, 2)

        # Sufijo
        lbl_suffix = QLabel(self.tr("Sufijo del Nombre:"))
        lbl_suffix.setObjectName("menuLabel")
        grid_out.addWidget(lbl_suffix, 1, 0)
        self.txt_suffix = QLineEdit("_recoded")
        grid_out.addWidget(self.txt_suffix, 1, 1, 1, 2)

        out_layout.addLayout(grid_out)

        # Barra de Progreso Global
        lbl_progress = QLabel(self.tr("Progreso de Procesamiento:"))
        lbl_progress.setObjectName("menuLabel")
        out_layout.addWidget(lbl_progress)
        self.progress_bar = BouncingProgressBar()
        self.progress_bar.setObjectName("downloadProgressBar")
        self.progress_bar.setProperty("status", "wait")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(self.tr("En espera"))
        self.progress_bar.setTextVisible(True)
        out_layout.addWidget(self.progress_bar)

        # Botón Acción Principal Iniciar Recodificación
        self.btn_start = AnimatedButton(self.tr("Iniciar Recodificación"))
        self.btn_start.setObjectName("downloadButton")
        self.btn_start.setFixedHeight(36)
        self.btn_start.clicked.connect(self._on_start_recoding_clicked)
        out_layout.addWidget(self.btn_start)

        right_layout.addWidget(self.output_card)

        # Agregar ambas columnas al Splitter Principal Horizontal
        self.main_splitter.addWidget(self.left_splitter)
        self.main_splitter.addWidget(self.right_container)
        self.main_splitter.setSizes([500, 500])

        main_layout.addWidget(self.main_splitter)

    def _on_file_selected(self, filepath: str):
        self.current_preview_file = filepath
        if not filepath or not os.path.exists(filepath):
            self.preview_widget.clear()
            return

        ext = os.path.splitext(filepath)[1].lower()
        media_type = "audio" if ext in AUDIO_ONLY_EXTENSIONS else "video"

        meta = FFprobeMetadataManager.get_instance().get_metadata_instant(filepath, media_type)
        duration_sec = self._parse_duration_to_seconds(meta.get("duración", "0"))
        fps_val = self._parse_fps(meta.get("fps", "30"))
        if duration_sec <= 0:
            duration_sec = 1.0

        self.preview_widget.load_media(filepath, media_type, duration_sec, fps_val)

    def _on_trim_range_changed(self, in_sec: float, out_sec: float):
        self.in_point_ms = int(in_sec * 1000)
        self.out_point_ms = int(out_sec * 1000)
        logger.debug(f"VideoToolsTab: Trim points actualizados: In={self.in_point_ms}ms, Out={self.out_point_ms}ms")

    def _on_metadata_ready(self, path: str, meta: dict):
        if path == self.current_preview_file:
            self.preview_widget.set_fps(self._parse_fps(meta.get("fps", "30")))

    def _parse_duration_to_seconds(self, dur_str) -> float:
        if not dur_str or dur_str == "-":
            return 0.0
        if isinstance(dur_str, (int, float)):
            return float(dur_str)
        try:
            parts = str(dur_str).split(":")
            if len(parts) == 2:
                return float(parts[0]) * 60 + float(parts[1])
            elif len(parts) == 3:
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        except Exception:
            pass
        return 0.0

    def _parse_fps(self, fps_val) -> float:
        try:
            return float(str(fps_val).replace("fps", "").strip())
        except (ValueError, AttributeError):
            return 30.0

    def _on_browse_output_clicked(self):
        folder = QFileDialog.getExistingDirectory(self, self.tr("Seleccionar Carpeta de Salida"))
        if folder:
            self.txt_output_dir.setText(folder)
            config = get_config()
            config["video_tools_output_dir"] = folder
            save_config(config)

    def _load_saved_output_dir(self):
        config = get_config()
        saved = config.get("video_tools_output_dir", "")
        if saved and os.path.exists(saved):
            self.txt_output_dir.setText(saved)
        else:
            default_dir = os.path.join(os.path.expanduser("~"), "Videos")
            if os.path.exists(default_dir):
                self.txt_output_dir.setText(default_dir)

    def _on_start_recoding_clicked(self):
        files = self.queue_widget.get_all_filepaths()
        if not files:
            QMessageBox.warning(self, self.tr("Sin archivos"), self.tr("Por favor agrega al menos un archivo a la cola para iniciar la recodificación."))
            return

        out_dir = self.txt_output_dir.text().strip()
        if not out_dir or not os.path.exists(out_dir):
            QMessageBox.warning(self, self.tr("Carpeta inválida"), self.tr("Por favor selecciona una carpeta de salida válida."))
            return

        settings = self.options_widget.get_encoding_settings()
        suffix = self.txt_suffix.text().strip()

        logger.info(f"VideoToolsTab: Iniciando recodificación para {len(files)} archivos.")
        logger.info(f"Ajustes: {settings}, Destino: {out_dir}, Sufijo: {suffix}")
        
        QMessageBox.information(
            self,
            self.tr("Recodificación"),
            f"{self.tr('Configuración de 2 Paneles lista para recodificar')} {len(files)} {self.tr('archivos en')}:\n{out_dir}"
        )
