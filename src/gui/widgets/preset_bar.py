# src/gui/widgets/preset_bar.py
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QFileDialog,
    QMessageBox,
)

from gui.widgets.combo_box import AutoPopupComboBox
from core.logger.logger_manager import logger
from core.utils.preset_manager import get_preset_manager


class PresetBar(QWidget):
    """
    Barra reutilizable de presets: combobox editable + botones Exportar/Importar/Eliminar.

    - Seleccionar un preset existente lo aplica llamando a `set_settings`.
    - Escribir un nombre nuevo y presionar Enter guarda los ajustes actuales
      (obtenidos vía `get_settings`) bajo ese nombre.
    - Exportar/Importar mueven presets individuales como archivos JSON.

    No sabe nada del contenido de los ajustes: cualquier panel que exponga
    `get_settings() -> dict` y `set_settings(dict)` puede usarla, solo cambia
    el namespace (ej. "video_tools/comprimir").
    """
    preset_applied = Signal(str)

    def __init__(self, namespace: str, get_settings, set_settings, parent=None):
        super().__init__(parent)
        self.namespace = namespace
        self._get_settings = get_settings
        self._set_settings = set_settings

        self._init_ui()
        self.refresh()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.combo = AutoPopupComboBox(self)
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(AutoPopupComboBox.NoInsert)
        self.combo.lineEdit().setPlaceholderText(
            self.tr("Escribe un nombre y presiona Enter para guardar...")
        )
        self.combo.activated.connect(self._on_preset_selected)
        self.combo.lineEdit().returnPressed.connect(self._on_save_requested)
        layout.addWidget(self.combo)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self.btn_export = QPushButton(self.tr("Exportar"))
        self.btn_export.setObjectName("secondaryButton")
        self.btn_export.setCursor(Qt.PointingHandCursor)
        self.btn_export.clicked.connect(self._on_export_clicked)
        btn_row.addWidget(self.btn_export)

        self.btn_import = QPushButton(self.tr("Importar"))
        self.btn_import.setObjectName("secondaryButton")
        self.btn_import.setCursor(Qt.PointingHandCursor)
        self.btn_import.clicked.connect(self._on_import_clicked)
        btn_row.addWidget(self.btn_import)

        self.btn_delete = QPushButton(self.tr("Eliminar"))
        self.btn_delete.setObjectName("redButton")
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.clicked.connect(self._on_delete_clicked)
        btn_row.addWidget(self.btn_delete)

        layout.addLayout(btn_row)

    def refresh(self, select_name: str = ""):
        """Recarga la lista de presets desde el manager, conservando el texto escrito."""
        current_text = self.combo.currentText()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(get_preset_manager().list_names(self.namespace))
        self.combo.blockSignals(False)
        target = select_name or current_text
        if target:
            idx = self.combo.findText(target)
            if idx >= 0:
                self.combo.setCurrentIndex(idx)
            else:
                self.combo.setCurrentIndex(-1)
                self.combo.setCurrentText(target)
        else:
            self.combo.setCurrentIndex(-1)

    def _selected_preset_name(self) -> str:
        """Retorna el nombre del preset seleccionado solo si existe de verdad."""
        text = self.combo.currentText().strip()
        return text if text in get_preset_manager().list_names(self.namespace) else ""

    def _on_preset_selected(self, index: int):
        name = self.combo.itemText(index)
        settings = get_preset_manager().get_settings(self.namespace, name)
        if not settings:
            return
        self._set_settings(settings)
        logger.info(f"PresetBar [{self.namespace}]: Preset '{name}' aplicado.")
        self.preset_applied.emit(name)

    def _on_save_requested(self):
        name = self.combo.currentText().strip()
        if not name:
            return
        manager = get_preset_manager()
        if name in manager.list_names(self.namespace):
            resp = QMessageBox.question(
                self,
                self.tr("Sobrescribir preset"),
                self.tr("El preset '{0}' ya existe. ¿Sobrescribirlo?").format(name),
            )
            if resp != QMessageBox.Yes:
                return
        manager.save_preset(self.namespace, name, self._get_settings())
        self.refresh(select_name=name)

    def _on_export_clicked(self):
        name = self._selected_preset_name()
        if not name:
            QMessageBox.information(
                self, self.tr("Sin preset"), self.tr("Selecciona un preset de la lista para exportarlo.")
            )
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, self.tr("Exportar Preset"), f"{name}.json", self.tr("Preset JSON (*.json)")
        )
        if file_path:
            get_preset_manager().export_preset(self.namespace, name, file_path)

    def _on_import_clicked(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Importar Preset"), "", self.tr("Preset JSON (*.json)")
        )
        if not file_path:
            return
        name = get_preset_manager().import_preset(self.namespace, file_path)
        if name:
            self.refresh(select_name=name)
        else:
            QMessageBox.warning(
                self, self.tr("Error"), self.tr("No se pudo importar el preset desde el archivo seleccionado.")
            )

    def _on_delete_clicked(self):
        name = self._selected_preset_name()
        if not name:
            QMessageBox.information(
                self, self.tr("Sin preset"), self.tr("Selecciona un preset de la lista para eliminarlo.")
            )
            return
        resp = QMessageBox.question(
            self,
            self.tr("Eliminar preset"),
            self.tr("¿Eliminar el preset '{0}'?").format(name),
        )
        if resp == QMessageBox.Yes:
            get_preset_manager().delete_preset(self.namespace, name)
            self.refresh()
