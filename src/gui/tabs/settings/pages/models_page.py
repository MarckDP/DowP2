# src/gui/tabs/settings/pages/models_page.py
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea,
    QPushButton, QMessageBox, QProgressBar
)
from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from core.utils.i18n import logger
from core.utils.cache_manager import format_bytes
from core.utils.paths import get_models_dir
from core.constants import REMBG_MODEL_FAMILIES, UPSCALING_TOOLS
from core.setup.models_setup import (
    is_rembg_model_installed, is_rembg_model_gated, download_rembg_model, delete_rembg_model,
    is_upscaling_engine_installed, download_upscaling_engine, delete_upscaling_engine,
    get_folder_size,
)


class ModelDownloadWorker(QThread):
    """Descarga un modelo/motor sin bloquear la UI. `row_id` viaja en ambas señales
    para que varias filas puedan descargar en paralelo sin cruzar su progreso."""
    finished_signal = Signal(bool, str, str)   # success, message, row_id
    numeric_progress_signal = Signal(int, str)  # percent, row_id

    def __init__(self, row_id: str, download_func, info: dict, parent=None):
        super().__init__(parent)
        self.row_id = row_id
        self.download_func = download_func
        self.info = info

    def run(self):
        try:
            def cb(pct):
                self.numeric_progress_signal.emit(pct, self.row_id)
            success, msg = self.download_func(self.info, progress_callback=cb)
            self.finished_signal.emit(success, msg, self.row_id)
        except Exception as e:
            logger.error(f"ModelDownloadWorker: Error descargando '{self.row_id}': {e}")
            self.finished_signal.emit(False, str(e), self.row_id)


class ModelRow(QFrame):
    """Fila para un modelo rembg o un motor de upscaling. `gated=True` lo muestra
    bloqueado (sin acciones) para variantes que necesitan cuenta/login externo."""
    download_requested = Signal(str)  # row_id

    def __init__(self, row_id: str, title: str, path_for_size: str, gated: bool = False, parent=None):
        super().__init__(parent)
        self.row_id = row_id
        self.path_for_size = path_for_size
        self.gated = gated
        self.setObjectName("settingsCard")
        self._build_ui(title)
        self.refresh_status()

    def _build_ui(self, title: str):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        info_vbox = QVBoxLayout()
        info_vbox.setSpacing(4)

        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 13px;")
        info_vbox.addWidget(self.lbl_title)

        self.lbl_status = QLabel()
        self.lbl_status.setStyleSheet("font-size: 11px;")
        info_vbox.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.hide()
        info_vbox.addWidget(self.progress_bar)

        layout.addLayout(info_vbox, 1)

        if self.gated:
            lbl_locked = QLabel(self.tr("🔒 Requiere cuenta (próximamente)"))
            lbl_locked.setStyleSheet("color: #888888; font-size: 11px; font-style: italic;")
            layout.addWidget(lbl_locked, 0, Qt.AlignVCenter)
            return

        self.btn_download = QPushButton(self.tr("Descargar"))
        self.btn_download.setFixedHeight(28)
        self.btn_download.setFixedWidth(90)
        self.btn_download.setCursor(Qt.PointingHandCursor)
        self.btn_download.clicked.connect(lambda: self.download_requested.emit(self.row_id))

        self.btn_folder = QPushButton(self.tr("Carpeta"))
        self.btn_folder.setFixedHeight(28)
        self.btn_folder.setFixedWidth(80)
        self.btn_folder.setCursor(Qt.PointingHandCursor)
        self.btn_folder.clicked.connect(self._open_folder)

        self.btn_delete = QPushButton(self.tr("Eliminar"))
        self.btn_delete.setFixedHeight(28)
        self.btn_delete.setFixedWidth(80)
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.setProperty("variant", "danger")
        # Sin acción propia: quien crea la fila (ModelsPage) conecta este botón a su
        # callback de borrado, porque necesita saber si es un modelo rembg o un motor
        # de upscaling completo para llamar a la función de borrado correcta.

        layout.addWidget(self.btn_download, 0, Qt.AlignVCenter)
        layout.addWidget(self.btn_folder, 0, Qt.AlignVCenter)
        layout.addWidget(self.btn_delete, 0, Qt.AlignVCenter)

    def _folder_to_open(self) -> str:
        return self.path_for_size if os.path.isdir(self.path_for_size) else os.path.dirname(self.path_for_size)

    def _open_folder(self):
        folder = self._folder_to_open()
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def is_installed(self) -> bool:
        return os.path.exists(self.path_for_size) and (
            os.path.isdir(self.path_for_size) or os.path.getsize(self.path_for_size) > 1024
        )

    def refresh_status(self):
        if self.gated:
            return
        if self.is_installed():
            size = get_folder_size(self.path_for_size)
            self.lbl_status.setText(f"✓ {self.tr('Instalado')} ({format_bytes(size)})")
            self.lbl_status.setStyleSheet("color: #4CAF50; font-size: 11px; font-weight: bold;")
            self.btn_download.setText(self.tr("Reinstalar"))
            self.btn_folder.setDisabled(False)
            self.btn_delete.setDisabled(False)
        else:
            self.lbl_status.setText(self.tr("No descargado"))
            self.lbl_status.setStyleSheet("color: #888888; font-size: 11px;")
            self.btn_download.setText(self.tr("Descargar"))
            self.btn_folder.setDisabled(True)
            self.btn_delete.setDisabled(True)

    def set_downloading(self, is_downloading: bool):
        if self.gated:
            return
        self.btn_download.setDisabled(is_downloading)
        self.btn_delete.setDisabled(is_downloading)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(is_downloading)
        if is_downloading:
            self.lbl_status.setText(self.tr("Descargando..."))
            self.lbl_status.setStyleSheet("color: #FFC107; font-size: 11px; font-weight: bold;")

    def set_progress(self, pct: int):
        self.progress_bar.setValue(pct)


class ModelsPage(QWidget):
    """Pestaña de Ajustes para descargar/gestionar modelos de IA (rembg, upscaling).
    Los modelos nunca se descargan solos -- solo cuando el usuario aprieta Descargar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: dict[str, ModelRow] = {}
        self.row_info: dict[str, dict] = {}          # row_id -> info dict (model_info / tool_info)
        self.row_kind: dict[str, str] = {}            # row_id -> "rembg" | "upscaling"
        self._workers: dict[str, ModelDownloadWorker] = {}
        self._build_ui()

    def _build_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(12)

        title_label = QLabel(self.tr("Modelos de Inteligencia Artificial"))
        title_label.setObjectName("settingsTitle")
        self.main_layout.addWidget(title_label)

        line = QFrame()
        line.setObjectName("settingsDivider")
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        self.main_layout.addWidget(line)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        scroll_content = QWidget()
        scroll_content.setObjectName("settingsScrollContent")
        scroll_content.setStyleSheet("QWidget#settingsScrollContent { background-color: transparent; }")

        self.content_layout = QVBoxLayout(scroll_content)
        self.content_layout.setContentsMargins(0, 10, 10, 0)
        self.content_layout.setSpacing(10)
        self.content_layout.setAlignment(Qt.AlignTop)

        self._add_section_header(self.tr("Eliminación de Fondo (Rembg)"))
        for family_name, models in REMBG_MODEL_FAMILIES.items():
            self._add_family_header(family_name)
            for model_name, model_info in models.items():
                self._add_rembg_row(model_name, model_info)

        self.content_layout.addSpacing(8)
        self._add_section_header(self.tr("Motores de Reescalado (Upscaling)"))
        for engine_key, tool_info in UPSCALING_TOOLS.items():
            self._add_upscaling_row(engine_key, tool_info)

        scroll_area.setWidget(scroll_content)
        self.main_layout.addWidget(scroll_area)

    def _add_section_header(self, text: str):
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #EEEEEE; font-size: 14px; font-weight: bold; margin-top: 4px;")
        self.content_layout.addWidget(lbl)

    def _add_family_header(self, text: str):
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #B9E640; font-size: 12px; font-weight: bold; margin-top: 6px;")
        self.content_layout.addWidget(lbl)

    def _is_gated(self, model_info: dict) -> bool:
        # Los modelos con URL a una página (no a un archivo directo) necesitan
        # descarga manual con cuenta -- por ahora se muestran bloqueados sin acción.
        return is_rembg_model_gated(model_info)

    def _add_rembg_row(self, model_name: str, model_info: dict):
        row_id = f"rembg::{model_info['folder']}::{model_info['file']}"
        path = os.path.join(get_models_dir(), model_info["folder"], model_info["file"])
        gated = self._is_gated(model_info)
        row = ModelRow(row_id, model_name, path, gated=gated)
        row.download_requested.connect(self._on_download_requested)
        if not gated:
            row.btn_delete.clicked.connect(lambda: self._on_delete_rembg(row_id, model_name))
        self.rows[row_id] = row
        self.row_info[row_id] = model_info
        self.row_kind[row_id] = "rembg"
        self.content_layout.addWidget(row)

    def _add_upscaling_row(self, engine_key: str, tool_info: dict):
        row_id = f"upscaling::{engine_key}"
        path = os.path.join(get_models_dir(), tool_info["folder"])
        row = ModelRow(row_id, tool_info["name"], path, gated=False)
        row.download_requested.connect(self._on_download_requested)
        row.btn_delete.clicked.connect(lambda: self._on_delete_upscaling(row_id, tool_info["name"]))
        self.rows[row_id] = row
        self.row_info[row_id] = tool_info
        self.row_kind[row_id] = "upscaling"
        self.content_layout.addWidget(row)

    # ── Descarga ─────────────────────────────────────────────────────────────
    def _on_download_requested(self, row_id: str):
        row = self.rows[row_id]
        info = self.row_info[row_id]
        kind = self.row_kind[row_id]
        download_func = download_rembg_model if kind == "rembg" else download_upscaling_engine

        row.set_downloading(True)
        worker = ModelDownloadWorker(row_id, download_func, info, parent=self)
        worker.numeric_progress_signal.connect(self._on_progress)
        worker.finished_signal.connect(self._on_download_finished)
        self._workers[row_id] = worker
        worker.start()

    def _on_progress(self, pct: int, row_id: str):
        row = self.rows.get(row_id)
        if row:
            row.set_progress(pct)

    def _on_download_finished(self, success: bool, msg: str, row_id: str):
        row = self.rows.get(row_id)
        self._workers.pop(row_id, None)
        if row:
            row.set_downloading(False)
            row.refresh_status()
        if not success:
            QMessageBox.warning(self, self.tr("Error de Descarga"), msg)

    # ── Eliminar ─────────────────────────────────────────────────────────────
    def _on_delete_rembg(self, row_id: str, display_name: str):
        if QMessageBox.question(
            self, self.tr("Eliminar modelo"),
            self.tr("¿Eliminar '{0}' del disco?").format(display_name)
        ) != QMessageBox.Yes:
            return
        if delete_rembg_model(self.row_info[row_id]):
            self.rows[row_id].refresh_status()

    def _on_delete_upscaling(self, row_id: str, display_name: str):
        if QMessageBox.question(
            self, self.tr("Eliminar motor"),
            self.tr("¿Eliminar '{0}' (motor completo) del disco?").format(display_name)
        ) != QMessageBox.Yes:
            return
        if delete_upscaling_engine(self.row_info[row_id]):
            self.rows[row_id].refresh_status()
