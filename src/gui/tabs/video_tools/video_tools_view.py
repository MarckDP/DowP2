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
    QCheckBox,
)
from PySide6.QtCore import Qt, QSize, QUrl
from PySide6.QtGui import QIcon, QDesktopServices

from gui.widgets.animated_button import AnimatedButton
from gui.widgets.bouncing_progress_bar import BouncingProgressBar
from gui.widgets.combo_box import AutoPopupComboBox
from gui.styles import apply_folder_browse_button_style, apply_folder_open_button_style, create_colored_circle_icon, update_label_combobox_style
from gui.widgets.media_trim_player_widget import MediaTrimPlayerWidget
from gui.tabs.video_tools.media_queue_widget import MediaQueueWidget
from gui.tabs.video_tools.encoding_options_widget import EncodingOptionsWidget
from core.logger.logger_manager import logger
from core.utils.config_manager import get_config, save_config
from core.tabs.editing_media.ffprobe_metadata_manager import FFprobeMetadataManager
from core.utils.queue_manager import get_queue_manager, JobStatus

AUDIO_ONLY_EXTENSIONS = {".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a", ".opus", ".wma"}
CONTAINER_TO_EXTENSION = {
    "qtff": "mov",
    "asf": "wmv",
    "ps": "mpg",
}

class VideoToolsTab(QWidget):
    """
    Pestaña de Herramientas Multimedia / Recodificador (Diseño de 2 Columnas Unificadas).
    Organiza la interfaz en 2 paneles principales:
      - Columna Izquierda: Vista Previa Multimedia (arriba) + Cola de Medios Importados (abajo).
      - Columna Derecha: Panel de Opciones con Pestañas (Preajustes/Comprimir/Convertir/Proxies/Avanzado) + Cubo de Salida e Iniciar.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_preview_file = ""
        self.in_point_ms = 0
        self.out_point_ms = 0
        self._recode_jobs = set()  # Mantener track de los trabajos RECODE iniciados desde esta vista

        self.init_ui()
        self._load_saved_output_dir()
        self.load_labels()
        FFprobeMetadataManager.get_instance().metadata_ready.connect(self._on_metadata_ready)
        
        # Conectar señales del QueueManager
        qm = get_queue_manager()
        qm.job_progress_changed.connect(self._on_job_progress)
        qm.job_status_changed.connect(self._on_job_status)

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
        right_layout.setSpacing(10)

        # 1. Panel Superior de Opciones con Pestañas
        self.options_widget = EncodingOptionsWidget(self)
        self.options_widget.start_status_changed.connect(self._on_start_status_changed)
        right_layout.addWidget(self.options_widget, 1)

        # Recorte interactivo: siempre activo en Personalizado + Recortar (no hay casilla
        # de encendido). El panel Avanzado activa/desactiva el rectángulo sobre la vista
        # previa según su propia configuración (crop_edit_toggled) y sincroniza en vivo con
        # los campos Ancho/Alto en ambas direcciones: arrastrar el recorte actualiza los
        # campos (crop_rect_changed) y tipear los campos redimensiona el recorte
        # (crop_dimensions_changed).
        self.options_widget.tab_advanced.crop_edit_toggled.connect(self._on_crop_edit_toggled)
        self.options_widget.tab_advanced.crop_dimensions_changed.connect(self._on_crop_dimensions_changed)
        self.preview_widget.crop_rect_changed.connect(self._on_preview_crop_changed)

        # Marcas de agua interactivas: el panel Avanzado empuja el ESTILO (texto/fuente/
        # tamaño/color/opacidad, o archivo/escala/opacidad) hacia la vista previa; la
        # vista previa empuja de vuelta la POSICIÓN (arrastrada a mano) hacia el panel,
        # que la guarda como estado propio — a diferencia del recorte, no hace falta un
        # override por-llamada, get_settings() ya la lee directo (ver conversación:
        # esto también resuelve que "Guardar como preajuste" capture la posición actual).
        self.options_widget.tab_advanced.text_watermark_style_changed.connect(self._on_text_watermark_style_changed)
        self.options_widget.tab_advanced.image_watermark_style_changed.connect(self._on_image_watermark_style_changed)
        self.preview_widget.text_watermark_changed.connect(self._on_text_watermark_position_changed)
        self.preview_widget.image_watermark_changed.connect(self._on_image_watermark_position_changed)

        # 2. Cubo Inferior de Opciones de Salida y Ejecución
        self.output_card = QFrame(self.right_container)
        self.output_card.setObjectName("outputOptionsContainer")
        out_layout = QVBoxLayout(self.output_card)
        out_layout.setContentsMargins(14, 12, 14, 12)
        out_layout.setSpacing(10)

        lbl_out_title = QLabel(self.tr("Opciones de Salida y Procesamiento"), self.output_card)
        lbl_out_title.setObjectName("sectionTitle")
        out_layout.addWidget(lbl_out_title)

        grid_out = QGridLayout()
        grid_out.setSpacing(8)
        grid_out.setColumnStretch(1, 1)

        # Checkbox "Guardar en misma ruta"
        self.chk_same_path = QCheckBox(self.tr("Guardar en la misma ruta del medio original"), self.output_card)
        self.chk_same_path.setObjectName("menuLabel")
        grid_out.addWidget(self.chk_same_path, 0, 0, 1, 3)

        # Fila 1: Ruta + Selector de Etiquetas + Botones de Examinar/Abrir
        self.lbl_dest = QLabel(self.tr("Ruta:"), self.output_card)
        self.lbl_dest.setObjectName("menuLabel")
        grid_out.addWidget(self.lbl_dest, 1, 0)

        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        path_row.setContentsMargins(0, 0, 0, 0)

        self.txt_output_dir = QLineEdit(self.output_card)
        self.txt_output_dir.setPlaceholderText(self.tr("Seleccionar carpeta de destino..."))
        path_row.addWidget(self.txt_output_dir, 1)

        # ComboBox de Etiquetas
        self.combo_tags = AutoPopupComboBox(self.output_card)
        self.combo_tags.setObjectName("tagsComboBox")
        self.combo_tags.setPlaceholderText(self.tr("Etiqueta"))
        # Se construye con el parent directo al constructor, lo que hace que el ChildAdded del
        # filtro global de cursor (HandCursorInstaller, main.py) nunca se dispare (ver
        # advanced_recode_panel.py::_setup_fixed_combo) — se fija a mano acá.
        self.combo_tags.setCursor(Qt.PointingHandCursor)
        self.combo_tags.currentIndexChanged.connect(self._on_label_changed)

        # Botón para examinar carpeta
        self.btn_browse_output = QPushButton(self.output_card)
        self.btn_browse_output.setFixedSize(32, 32)
        self.btn_browse_output.setCursor(Qt.PointingHandCursor)
        apply_folder_browse_button_style(self.btn_browse_output, self.tr("Seleccionar carpeta de salida"))
        self.btn_browse_output.clicked.connect(self._on_browse_output_clicked)
        
        # Botón para abrir la carpeta
        self.btn_open_output = QPushButton(self.output_card)
        self.btn_open_output.setFixedSize(32, 32)
        self.btn_open_output.setCursor(Qt.PointingHandCursor)
        apply_folder_open_button_style(self.btn_open_output, self.tr("Abrir carpeta de salida en el explorador"))
        self.btn_open_output.clicked.connect(self._on_open_output_clicked)

        path_row.addWidget(self.btn_browse_output)
        path_row.addWidget(self.btn_open_output)
        path_row.addWidget(self.combo_tags)

        grid_out.addLayout(path_row, 1, 1, 1, 2)

        # Fila 2: Prefijo y Sufijo
        self.lbl_prefix = QLabel(self.tr("Prefijo:"), self.output_card)
        self.lbl_prefix.setObjectName("menuLabel")
        grid_out.addWidget(self.lbl_prefix, 2, 0)

        affixes_row = QHBoxLayout()
        affixes_row.setSpacing(10)
        affixes_row.setContentsMargins(0, 0, 0, 0)

        self.txt_prefix = QLineEdit(self.output_card)
        self.txt_prefix.setPlaceholderText("")

        self.lbl_suffix = QLabel(self.tr("Sufijo:"), self.output_card)
        self.lbl_suffix.setObjectName("menuLabel")
        self.txt_suffix = QLineEdit("_recoded", self.output_card)

        affixes_row.addWidget(self.txt_prefix, 1)
        affixes_row.addWidget(self.lbl_suffix)
        affixes_row.addWidget(self.txt_suffix, 1)

        grid_out.addLayout(affixes_row, 2, 1, 1, 2)
        
        self.chk_same_path.toggled.connect(self._on_same_path_toggled)

        out_layout.addLayout(grid_out)

        # Barra de Progreso Global
        self.progress_bar = BouncingProgressBar(self.output_card)
        self.progress_bar.setObjectName("downloadProgressBar")
        self.progress_bar.setProperty("status", "wait")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(self.tr("En espera"))
        self.progress_bar.setTextVisible(True)
        out_layout.addWidget(self.progress_bar)

        # Botón Acción Principal: un solo botón que cambia de rol — "Iniciar
        # Recodificación" mientras no hay nada corriendo, "Cancelar" mientras hay un
        # lote en curso (mismo botón, no dos aparte — ver _set_start_button_running).
        self._batch_active = False
        self.btn_start = AnimatedButton(self.tr("Iniciar Recodificación"), self.output_card)
        self.btn_start.setProperty("variant", "primary")
        self.btn_start.setObjectName("downloadButton")
        self.btn_start.setFixedHeight(36)
        self.btn_start.clicked.connect(self._on_start_button_clicked)
        out_layout.addWidget(self.btn_start)

        # Estado y texto inicial contextual del botón
        self._on_start_status_changed(*self.options_widget.get_current_status())

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
        self.options_widget.tab_advanced.set_source_media(meta, filepath)
        # preview_widget.load_media ya ocultó el rectángulo (el encuadre elegido no tiene
        # sentido para otro archivo); esto lo vuelve a mostrar de una para el archivo nuevo
        # si el recorte interactivo sigue activo (personalizado + Recortar es config. del
        # panel, no del archivo, así que no se "apaga" solo al cambiar de ítem).
        self.options_widget.tab_advanced.hide_apply_to_all_checkbox()
        self._on_crop_edit_toggled(self.options_widget.tab_advanced.is_crop_active())

    def _on_metadata_ready(self, path: str, meta: dict):
        if path == self.current_preview_file:
            self.preview_widget.set_fps(self._parse_fps(meta.get("fps", "30")))
            self.options_widget.tab_advanced.set_source_media(meta, path)
            # La metadata rápida inicial puede no traer resolución todavía; si el recorte
            # ya está activo, se re-arma ahora con la resolución real recién confirmada.
            self._on_crop_edit_toggled(self.options_widget.tab_advanced.is_crop_active())

    def _on_trim_range_changed(self, in_sec: float, out_sec: float):
        self.in_point_ms = int(in_sec * 1000)
        self.out_point_ms = int(out_sec * 1000)
        logger.debug(f"VideoToolsTab: Trim points actualizados: In={self.in_point_ms}ms, Out={self.out_point_ms}ms")

    def _on_crop_edit_toggled(self, enabled: bool):
        fw, fh = self.options_widget.tab_advanced.get_crop_target_fraction() if enabled else (None, None)
        self.preview_widget.set_crop_editing_enabled(enabled, fw, fh)

    def _on_crop_dimensions_changed(self, width_px: int, height_px: int):
        fw, fh = self.options_widget.tab_advanced.pixels_to_crop_fraction(width_px, height_px)
        if fw and fh:
            self.preview_widget.update_crop_size(fw, fh)

    def _on_preview_crop_changed(self):
        if self.preview_widget.has_custom_crop():
            self.options_widget.tab_advanced.show_apply_to_all_checkbox()
        crop_frac = self.preview_widget.get_crop_rect()
        if crop_frac is not None:
            self.options_widget.tab_advanced.sync_dimensions_from_crop(crop_frac)

    def _on_text_watermark_style_changed(self):
        style = self.options_widget.tab_advanced.get_text_watermark_style()
        self.preview_widget.set_text_watermark(
            style["enabled"], style["text"], style["font_family"],
            style["size_pct"], style["color"], style["opacity"],
        )

    def _on_image_watermark_style_changed(self):
        style = self.options_widget.tab_advanced.get_image_watermark_style()
        self.preview_widget.set_image_watermark(
            style["enabled"], style["image_path"], style["scale_pct"], style["opacity"],
        )

    def _on_text_watermark_position_changed(self):
        pos = self.preview_widget.get_text_watermark_position()
        if pos is not None:
            self.options_widget.tab_advanced.set_text_watermark_position(*pos)
        size_pct = self.preview_widget.get_text_watermark_size_pct()
        if size_pct is not None:
            self.options_widget.tab_advanced.set_text_watermark_size(size_pct)

    def _on_image_watermark_position_changed(self):
        pos = self.preview_widget.get_image_watermark_position()
        if pos is not None:
            self.options_widget.tab_advanced.set_image_watermark_position(*pos)
        size_pct = self.preview_widget.get_image_watermark_size_pct()
        if size_pct is not None:
            self.options_widget.tab_advanced.set_image_watermark_size(size_pct)

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

    def load_labels(self):
        """Carga las etiquetas configuradas en la aplicación en el combo de etiquetas con círculos de color."""
        if not hasattr(self, "combo_tags"):
            return
        from core.utils.config_manager import get_config
        from PySide6.QtGui import QColor

        self.combo_tags.blockSignals(True)
        current_text = self.combo_tags.currentText()
        self.combo_tags.clear()
        self.combo_tags.addItem(self.tr("Etiqueta"), "")

        config = get_config()
        labels = config.get("labels", [])
        for label in labels:
            name = label.get("name", "")
            path = label.get("path", "")
            color = label.get("color", "#B9E640")

            idx = self.combo_tags.count()
            icon = create_colored_circle_icon(color, size=12)
            self.combo_tags.addItem(icon, name, path)

            self.combo_tags.setItemData(idx, color, Qt.UserRole + 1)
            self.combo_tags.setItemData(idx, QColor(color), Qt.ForegroundRole)

        # Intentar restaurar selección si aún existe
        idx = self.combo_tags.findText(current_text)
        if idx >= 0:
            self.combo_tags.setCurrentIndex(idx)
        else:
            self.combo_tags.setCurrentIndex(0)

        self.combo_tags.blockSignals(False)
        self._update_combo_style()

    def _update_combo_style(self):
        """Actualiza el color de texto del combo según la etiqueta seleccionada."""
        if hasattr(self, "combo_tags"):
            update_label_combobox_style(self.combo_tags)

    def _on_label_changed(self, index):
        """Maneja el cambio de selección en el combobox de etiquetas."""
        self._update_combo_style()
        if self.chk_same_path.isChecked():
            return
        if index <= 0:
            self._load_saved_output_dir()
            self.txt_output_dir.setEnabled(True)
            self.btn_browse_output.setEnabled(True)
        else:
            path = self.combo_tags.currentData()
            if path:
                self.txt_output_dir.setText(path)
            self.txt_output_dir.setEnabled(False)
            self.btn_browse_output.setEnabled(False)

    def _on_browse_output_clicked(self):
        folder = QFileDialog.getExistingDirectory(self, self.tr("Seleccionar Carpeta de Salida"))
        if folder:
            if hasattr(self, "combo_tags"):
                self.combo_tags.setCurrentIndex(0)
            self.txt_output_dir.setText(folder)
            config = get_config()
            config["video_tools_output_dir"] = folder
            save_config(config)

    def _on_open_output_clicked(self):
        folder = self.txt_output_dir.text().strip()
        if folder and os.path.exists(folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _on_same_path_toggled(self, checked: bool):
        has_tag = hasattr(self, "combo_tags") and self.combo_tags.currentIndex() > 0
        self.lbl_dest.setEnabled(not checked)
        self.txt_output_dir.setEnabled((not checked) and (not has_tag))
        self.btn_browse_output.setEnabled((not checked) and (not has_tag))
        self.btn_open_output.setEnabled(not checked)
        if hasattr(self, "combo_tags"):
            self.combo_tags.setEnabled(not checked)
        
        config = get_config()
        config["video_tools_same_path"] = checked
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
                
        same_path = config.get("video_tools_same_path", False)
        self.chk_same_path.setChecked(same_path)
        self._on_same_path_toggled(same_path)

    def _on_start_status_changed(self, is_valid: bool, text: str):
        if getattr(self, "_recode_jobs", None):
            return
        if hasattr(self, "btn_start"):
            self.btn_start.setEnabled(is_valid)
            self.btn_start.setText(text)

    def _set_start_button_running(self, running: bool):
        """Un solo botón cambia de rol: "Iniciar Recodificación" <-> "Cancelar", en vez
        de mostrar/ocultar un segundo botón aparte."""
        self._batch_active = running
        if running:
            self.btn_start.setText(self.tr("Cancelar"))
            self.btn_start.setObjectName("redButton")
            self.btn_start.setEnabled(True)
        else:
            self.btn_start.setObjectName("downloadButton")
        self.btn_start.style().unpolish(self.btn_start)
        self.btn_start.style().polish(self.btn_start)

    def _on_start_button_clicked(self):
        if self._batch_active:
            self._on_cancel_recoding_clicked()
        else:
            self._on_start_recoding_clicked()

    def _on_start_recoding_clicked(self):
        is_valid, reason = self.options_widget.get_current_status()
        if not is_valid:
            QMessageBox.warning(self, self.tr("Configuración no válida"), reason)
            return

        files = self.queue_widget.get_all_filepaths()
        if not files:
            QMessageBox.warning(self, self.tr("Sin archivos"), self.tr("Por favor agrega al menos un archivo a la cola para iniciar la recodificación."))
            return

        out_dir = self.txt_output_dir.text().strip()
        same_path = self.chk_same_path.isChecked()
        
        if not same_path and (not out_dir or not os.path.exists(out_dir)):
            QMessageBox.warning(self, self.tr("Carpeta inválida"), self.tr("Por favor selecciona una carpeta de salida válida."))
            return

        settings = self.options_widget.get_encoding_settings()
        if not settings:
            QMessageBox.warning(self, self.tr("Sin configuración"), self.tr("Selecciona un preajuste o una configuración válida."))
            return

        # Recorte interactivo: si el usuario lo modificó en la vista previa y marcó
        # "Aplicar a todos", se reconstruye 'settings' completo con ese recorte ya
        # incluido (afecta a todo el lote); si no, cada archivo arma el suyo más abajo,
        # y solo el archivo previsualizado recibe el recorte personalizado.
        crop_frac = self.preview_widget.get_crop_rect()
        apply_crop_to_all = bool(settings.get("crop_apply_to_all")) and crop_frac is not None
        if apply_crop_to_all:
            settings = self.options_widget.tab_advanced.get_settings(crop_fraction_override=crop_frac)

        prefix = self.txt_prefix.text() if hasattr(self, "txt_prefix") else ""
        suffix = self.txt_suffix.text() if hasattr(self, "txt_suffix") else ""

        logger.info(f"VideoToolsTab: Iniciando recodificación para {len(files)} archivos. Misma ruta: {same_path}")
        
        qm = get_queue_manager()
        raw_container = settings.get("container", "mp4")
        container_ext = CONTAINER_TO_EXTENSION.get(raw_container, raw_container)
        
        for filepath in files:
            base_name = os.path.splitext(os.path.basename(filepath))[0]
            out_name = f"{prefix}{base_name}{suffix}.{container_ext}"
            
            if same_path:
                actual_out_dir = os.path.dirname(filepath)
            else:
                actual_out_dir = out_dir
                
            out_file = os.path.join(actual_out_dir, out_name)
            
            ext = os.path.splitext(filepath)[1].lower()
            media_type = "audio" if ext in AUDIO_ONLY_EXTENSIONS else "video"
            meta = FFprobeMetadataManager.get_instance().get_metadata_instant(filepath, media_type)
            duration_sec = self._parse_duration_to_seconds(meta.get("duración", "0"))
            
            file_settings = dict(settings)
            
            # Selección de pistas para medios multipista (definida antes del preset en la fuente):
            if filepath == self.current_preview_file:
                track_sel = self.preview_widget.get_audio_track_selection()
                if track_sel is not None:
                    file_settings["audio_track_selection"] = track_sel
                in_sec, out_sec = self.preview_widget.get_in_out()
                if in_sec > 0.05 or (duration_sec > 0 and out_sec < (duration_sec - 0.05)):
                    file_settings["trim_in_sec"] = in_sec
                    file_settings["trim_out_sec"] = out_sec
                if crop_frac is not None and not apply_crop_to_all:
                    crop_settings = self.options_widget.tab_advanced.get_settings(crop_fraction_override=crop_frac)
                    file_settings["video_args"] = crop_settings["video_args"]
            else:
                streams = meta.get("audio_streams", [])
                if len(streams) > 1:
                    preview_sel = self.preview_widget.get_audio_track_selection()
                    file_settings["audio_track_selection"] = preview_sel if preview_sel is not None else "all"

            config = {
                "input_path": filepath,
                "output_path": out_file,
                "settings": file_settings,
                "duration_sec": duration_sec,
                "title": f"Recode: {base_name}"
            }
            job_id = qm.add_job(config, "RECODE")
            self._recode_jobs.add(job_id)
            
            # Actualizamos visualmente la cola
            self.queue_widget.update_file_status(filepath, self.tr("En cola"))
            
        self._set_start_button_running(True)
        self.progress_bar.setProperty("status", "downloading")
        self.progress_bar.style().unpolish(self.progress_bar)
        self.progress_bar.style().polish(self.progress_bar)
        qm.start_queue()

    def _on_cancel_recoding_clicked(self):
        qm = get_queue_manager()
        for job_id in list(self._recode_jobs):
            job = qm.get_job(job_id)
            if job and job.status in (JobStatus.PENDING, JobStatus.RUNNING):
                qm.cancel_job(job_id)
        self.btn_start.setEnabled(False)
        self.progress_bar.setFormat(self.tr("Cancelando..."))

    def _on_job_progress(self, job_id: str, percent: float, speed: str, eta: str):
        if job_id in self._recode_jobs:
            self.progress_bar.setValue(int(percent))
            self.progress_bar.setFormat(f"{percent:.1f}% - {speed} - {eta}")

    def _on_job_status(self, job_id: str, status: str):
        if job_id not in self._recode_jobs:
            return
            
        qm = get_queue_manager()
        job = qm.get_job(job_id)
        if not job:
            return
            
        file_path = job.config.get("input_path")
        
        if status == JobStatus.RUNNING:
            self.queue_widget.update_file_status(file_path, self.tr("Procesando..."))
        elif status == JobStatus.COMPLETED:
            self.queue_widget.update_file_status(file_path, self.tr("Completado"))
            self._check_all_finished()
        elif status == JobStatus.FAILED:
            self.queue_widget.update_file_status(file_path, self.tr("Error"))
            self._check_all_finished()
        elif status == JobStatus.CANCELLED:
            self.queue_widget.update_file_status(file_path, self.tr("Cancelado"))
            self._check_all_finished()
            
    def _check_all_finished(self):
        qm = get_queue_manager()
        all_done = True
        for jid in list(self._recode_jobs):
            job = qm.get_job(jid)
            if job and job.status in (JobStatus.PENDING, JobStatus.RUNNING):
                all_done = False
                break
                
        if all_done:
            self._recode_jobs.clear()
            self._set_start_button_running(False)
            self._on_start_status_changed(*self.options_widget.get_current_status())
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat(self.tr("Finalizado"))
            self.progress_bar.setProperty("status", "wait")
            self.progress_bar.style().unpolish(self.progress_bar)
            self.progress_bar.style().polish(self.progress_bar)
