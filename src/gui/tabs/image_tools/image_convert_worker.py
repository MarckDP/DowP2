# src/gui/tabs/image_tools/image_convert_worker.py
import os
import threading

from PySide6.QtCore import QThread, Signal

from core.logger.logger_manager import logger
from core.tabs.image_tools.image_converter import ImageConverter
from core.utils.file_conflict_manager import resolve_conflict, commit_backup, rollback_backup

# Extensión de salida por formato -- "No Convertir" no está acá a propósito, se
# resuelve en _desired_output_path() mirando la extensión de cada archivo de origen.
_EXT_BY_FORMAT = {
    "PNG": ".png", "JPG": ".jpg", "WEBP": ".webp", "AVIF": ".avif",
    "PDF": ".pdf", "TIFF": ".tiff", "ICO": ".ico", "BMP": ".bmp",
}
_PASSTHROUGH_KEEP_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp"}


class ImageConvertWorker(QThread):
    """Convierte un lote de imágenes con las mismas opciones -- mismo patrón que
    ModelDownloadWorker (gui/tabs/settings/pages/models_page.py) pero iterando N
    archivos en vez de un solo item. El destino (carpeta + qué hacer si el archivo
    ya existe) se resuelve con core/utils/file_conflict_manager.resolve_conflict,
    la misma utilidad que ya usa el resto de la app (descargas) -- mismo respaldo
    reversible si la política es "sobrescribir": se confirma (se borra el .dbak) si
    la conversión de ESE archivo salió bien, o se revierte si falló/se canceló."""

    file_progress = Signal(str, int)          # filepath, %
    file_status_changed = Signal(str, str)    # filepath, texto de estado
    file_completed = Signal(str, str)         # input_path, output_path -- solo en éxito
    finished_signal = Signal(int, int)        # completados, total

    def __init__(self, filepaths: list[str], options: dict, parent=None):
        super().__init__(parent)
        self.filepaths = list(filepaths)
        self.options = options
        self.cancellation_event = threading.Event()
        self._converter = ImageConverter()

    def cancel(self):
        self.cancellation_event.set()

    def _desired_output_path(self, input_path: str) -> str:
        fmt = self.options.get("format", "No Convertir")
        input_ext = os.path.splitext(input_path)[1].lower()
        if fmt == "No Convertir":
            ext = input_ext if input_ext in _PASSTHROUGH_KEEP_EXTS else ".png"
        else:
            ext = _EXT_BY_FORMAT.get(fmt, ".png")

        filename = os.path.splitext(os.path.basename(input_path))[0] + ext
        output_folder = (self.options.get("output_folder") or "").strip()
        if output_folder and os.path.isdir(output_folder):
            return os.path.join(output_folder, filename)
        return os.path.join(os.path.dirname(input_path), filename)

    def run(self):
        total = len(self.filepaths)
        completed = 0
        policy = self.options.get("conflict_policy", "conservar")

        for filepath in self.filepaths:
            if self.cancellation_event.is_set():
                self.file_status_changed.emit(filepath, self.tr("Cancelado"))
                continue

            desired_path = self._desired_output_path(filepath)
            try:
                output_path, backup_path = resolve_conflict(desired_path, policy)
            except Exception as e:
                logger.error(f"ImageConvertWorker: fallo resolviendo destino de {filepath}: {e}")
                self.file_status_changed.emit(filepath, self.tr("Error: {0}").format(e))
                continue

            if output_path is None:
                # "omitir" con conflicto -- no es un error, el usuario eligió esto.
                self.file_status_changed.emit(filepath, self.tr("Omitido (ya existe)"))
                continue

            self.file_status_changed.emit(filepath, self.tr("Procesando..."))

            # Caso "sobrescribir" cuando la salida cae justo en el mismo path que el
            # ORIGEN (ej. "No Convertir" con destino = misma carpeta y mismo formato):
            # resolve_conflict() ya renombró ese archivo a backup_path antes de que
            # lleguemos acá -- filepath ya no existe en ese momento, así que hay que
            # leer desde el backup en vez de desde filepath.
            read_path = filepath
            if backup_path and os.path.normpath(desired_path) == os.path.normpath(filepath):
                read_path = backup_path

            def progress_cb(pct, _filepath=filepath):
                self.file_progress.emit(_filepath, pct)

            try:
                success, message = self._converter.convert_file(
                    read_path, output_path, self.options,
                    progress_callback=progress_cb,
                    cancellation_event=self.cancellation_event,
                )
            except Exception as e:
                logger.error(f"ImageConvertWorker: fallo inesperado con {filepath}: {e}")
                success, message = False, str(e)

            if success:
                commit_backup(backup_path)
                completed += 1
                self.file_status_changed.emit(filepath, self.tr("Completado"))
                self.file_completed.emit(filepath, output_path)
            else:
                rollback_backup(backup_path)
                self.file_status_changed.emit(filepath, self.tr("Error: {0}").format(message))

        self.finished_signal.emit(completed, total)
