import os
import re
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
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt

from core.logger.logger_manager import logger
from core.utils.cleanup_manager import CleanupManager
from core.utils.config_manager import get_config
from core.ytdlp_logic.format_selectors import quick_format_selector
from gui.dialogs.playlist_selection_dialog import PlaylistSelectionDialog
from gui.styles import get_theme_token
from gui.tabs.advanced_process.output_options import OutputOptionsWidget
from gui.tabs.advanced_process.workers import AnalysisWorker, DownloadWorker
from gui.widgets.animated_button import AnimatedButton


class QuickDownloadRow(QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("queueItemCard")
        self.init_ui(title)

    def init_ui(self, title):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(5)

        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        self.title_lbl = QLabel(title)
        self.title_lbl.setWordWrap(False)
        self.title_lbl.setToolTip(title)
        self.status_lbl = QLabel(self.tr("En espera"))
        self.status_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top_layout.addWidget(self.title_lbl, 1)
        top_layout.addWidget(self.status_lbl)
        layout.addLayout(top_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        self.info_lbl = QLabel("")
        self.percent_lbl = QLabel("0%")
        self.percent_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bottom_layout.addWidget(self.info_lbl, 1)
        bottom_layout.addWidget(self.percent_lbl)
        layout.addLayout(bottom_layout)

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

        self.btn_download = AnimatedButton(self.tr("Descargar"))
        self.btn_download.setObjectName("analyzeButton")
        self.btn_download.setFixedWidth(120)
        self.btn_download.clicked.connect(self._on_download_clicked)

        layout.addWidget(QLabel(self.tr("URL:")))
        layout.addWidget(self.url_input, 1)
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
        self.quality_combo = QComboBox()
        layout.addWidget(self.quality_combo)

        self.chk_playlist_selector = QCheckBox(self.tr("Seleccionar playlist"))
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

        title = QLabel(self.tr("Descargas"))
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        self.activity_scroll = QScrollArea()
        self.activity_scroll.setWidgetResizable(True)
        self.activity_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.activity_scroll.setStyleSheet("border: none; background: transparent;")

        self.activity_container = QWidget()
        self.activity_layout = QVBoxLayout(self.activity_container)
        self.activity_layout.setContentsMargins(0, 0, 0, 0)
        self.activity_layout.setSpacing(8)
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

        if self.chk_playlist_selector.isChecked():
            self._start_playlist_selection(url)
        else:
            self._start_direct_download(url)

    def _start_playlist_selection(self, url):
        self._set_busy(True, self.tr("Analizando playlist..."))
        self.analysis_worker = AnalysisWorker(url, analyze_playlist=True, fast_mode=True)

        def on_finished(data, error):
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

        for idx, entry in enumerate(entries):
            title = entry.get("title") or entry.get("id") or entry.get("url") or self.tr(f"Item {idx + 1}")
            self.item_keys.append(entry.get("playlist_index") or (selected_indices[idx] + 1 if idx < len(selected_indices) else idx + 1))
            row = QuickDownloadRow(str(title), self.activity_container)
            self.activity_layout.insertWidget(self.activity_layout.count() - 1, row)
            self.item_rows.append(row)

        if self.item_rows:
            self.item_rows[0].update_progress(0, status=self.tr("Preparando"))

    def _clear_activity_rows(self):
        for row in self.item_rows:
            self.activity_layout.removeWidget(row)
            row.deleteLater()
        self.item_rows = []
        self.item_keys = []
        self.current_item_pos = 0
        self.completed_items = 0

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
                self.item_rows[row_idx].update_progress(
                    val,
                    info=f"{speed} - ETA: {eta}",
                    status=self.tr("Descargando"),
                )
            total = max(1, len(self.item_rows))
            global_percent = ((max(0, self.current_item_pos - 1) + (val / 100.0)) / total) * 100.0
            self.output_options.set_progress(
                int(global_percent),
                self.tr("{} de {}").format(max(1, self.current_item_pos), total),
                "downloading",
            )
        elif data.get("status") == "finished":
            if data.get("filename"):
                self.last_downloaded_filepath = data.get("filename")
            row_idx = self._resolve_progress_row(data)
            if row_idx is not None and 0 <= row_idx < len(self.item_rows):
                self.item_rows[row_idx].update_progress(100, status=self.tr("Procesando"))
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
            self.output_options.set_progress(0, self.tr(f"Error: {message}"), "error")
            logger.error(f"QuickModeTab: Error en descarga: {message}")
        self.download_worker = None

    def _set_busy(self, busy, message=None):
        self._set_controls_enabled(not busy)
        self._set_download_text(self.tr("Analizando...") if busy else self.tr("Descargar"))
        if message:
            self.output_options.set_progress(0, message, "running" if busy else "wait")

    def _set_controls_enabled(self, enabled):
        self.url_input.setEnabled(enabled)
        self.btn_download.setEnabled(enabled or self.is_downloading)
        self.output_options.btn_start_download.setEnabled(enabled or self.is_downloading)
        self.options_panel.setEnabled(enabled)
        self.output_options.output_path_input.setEnabled(enabled)
        self.output_options.btn_select_output_path.setEnabled(enabled)
        self.output_options.speed_limit_input.setEnabled(enabled)

    def _set_download_text(self, text):
        self.btn_download.setText(text)
        self.output_options.btn_start_download.setText(text)

    def _on_open_output_path_clicked(self):
        path = self.output_options.output_path_input.text().strip()
        if not path:
            return
        if self.last_downloaded_filepath and os.path.exists(self.last_downloaded_filepath):
            path = self.last_downloaded_filepath

        if os.path.exists(path):
            if os.name == "nt":
                os.startfile(path if os.path.isdir(path) else os.path.dirname(path))
            else:
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl.fromLocalFile(path if os.path.isdir(path) else os.path.dirname(path)))
