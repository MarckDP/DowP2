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
from gui.dialogs.dialogs import SavePresetDialog
from core.logger.logger_manager import logger
from core.utils.preset_manager import get_preset_manager

_NO_PRESET_DATA = None  # dato del item "Sin preset" (siempre el primero del combo)


class PresetBar(QWidget):
    """
    Barra reutilizable de presets, en dos modos según quién la use (se pueden
    combinar los dos flags, pero en la práctica cada pestaña usa uno u otro):

    - `show_save_button=True, show_picker=False` (ej. AdvancedRecodePanel): la
      pestaña donde el usuario ARMA la configuración a mano. Solo aparece el
      botón "Guardar como preajuste", que abre un diálogo para nombrarlo y lo
      guarda vía `get_settings()`. No hay combo acá - esta pestaña nunca
      "aplica" un preset a sus propios controles.

    - `show_picker=True, show_save_button=False` (ej. PresetsPanel, la pestaña
      central "Preajustes"): la pestaña donde el usuario ELIGE qué preset usar
      para el próximo trabajo, sin pasar por la pestaña que lo creó. Acá
      aparecen el combo (solo selección, no editable) + Exportar/Importar/
      Eliminar, pero no "Guardar" (esta pestaña no arma configuraciones
      propias, solo administra las que otras pestañas ya guardaron).

    Elegir un preset del combo NO modifica ningún otro control de la app: el
    panel host debe consultar `current_preset_settings()` al armar su trabajo
    real y usar ese diccionario tal cual si no es None.

    No sabe nada del contenido de los ajustes: cualquier panel que exponga
    `get_settings() -> dict` puede usarla para guardar, solo cambia el
    namespace (ej. "video_tools/avanzado").
    """
    preset_applied = Signal(str)  # nombre del preset activo, o "" si se deseleccionó

    def __init__(self, namespace: str, get_settings=None, parent=None,
                 show_picker: bool = True, show_save_button: bool = True):
        super().__init__(parent)
        self.namespace = namespace
        self._get_settings = get_settings
        self._active_name = None
        self._is_picker = show_picker  # NO usar combo.isVisible(): una pestaña
        # inactiva del QTabWidget reporta isVisible()==False aunque este
        # configurada para mostrar el combo, y eso rompería el auto-refresh.

        self._init_ui(show_picker, show_save_button)
        if show_picker:
            self.refresh()
        get_preset_manager().presets_changed.connect(self._on_presets_changed)

    def _init_ui(self, show_picker: bool, show_save_button: bool):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.combo = AutoPopupComboBox(self)
        self.combo.currentIndexChanged.connect(self._on_combo_changed)
        self.combo.setVisible(show_picker)
        layout.addWidget(self.combo)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self.btn_save = QPushButton(self.tr("Guardar como preajuste"))
        self.btn_save.setObjectName("secondaryButton")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.clicked.connect(self._on_save_clicked)
        self.btn_save.setVisible(show_save_button)
        btn_row.addWidget(self.btn_save)

        self.btn_export = QPushButton(self.tr("Exportar"))
        self.btn_export.setObjectName("secondaryButton")
        self.btn_export.setCursor(Qt.PointingHandCursor)
        self.btn_export.clicked.connect(self._on_export_clicked)
        self.btn_export.setVisible(show_picker)
        btn_row.addWidget(self.btn_export)

        self.btn_import = QPushButton(self.tr("Importar"))
        self.btn_import.setObjectName("secondaryButton")
        self.btn_import.setCursor(Qt.PointingHandCursor)
        self.btn_import.clicked.connect(self._on_import_clicked)
        self.btn_import.setVisible(show_picker)
        btn_row.addWidget(self.btn_import)

        self.btn_delete = QPushButton(self.tr("Eliminar"))
        self.btn_delete.setObjectName("redButton")
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.clicked.connect(self._on_delete_clicked)
        self.btn_delete.setVisible(show_picker)
        btn_row.addWidget(self.btn_delete)

        layout.addLayout(btn_row)

    # ─── Estado / API pública ────────────────────────────────────

    def current_preset_settings(self):
        """Ajustes del preset activo, o None si no hay ninguno seleccionado
        ("Sin preset"). El panel host debe preferir esto sobre leer sus
        propios widgets al armar un trabajo real."""
        if not self._active_name:
            return None
        return get_preset_manager().get_settings(self.namespace, self._active_name)

    def active_preset_name(self):
        return self._active_name

    def clear_selection(self):
        """Vuelve a 'Sin preset' sin disparar guardado ni nada."""
        if self.combo.currentIndex() == 0:
            return
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(0)
        self.combo.blockSignals(False)
        self._active_name = None

    # ─── Internos ────────────────────────────────────────────────

    def refresh(self, select_name: str = ""):
        """Recarga la lista de presets desde el manager."""
        target = select_name or self._active_name
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(self.tr("Sin preset"), _NO_PRESET_DATA)
        for name in get_preset_manager().list_names(self.namespace):
            self.combo.addItem(name, name)
        if target:
            idx = self.combo.findData(target)
            self.combo.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            self.combo.setCurrentIndex(0)
        self._active_name = self.combo.currentData()
        self.combo.blockSignals(False)

    def _on_presets_changed(self, namespace: str):
        if namespace == self.namespace and self._is_picker:
            self.refresh()

    def _on_combo_changed(self, index: int):
        self._active_name = self.combo.itemData(index)
        if self._active_name:
            logger.info(f"PresetBar [{self.namespace}]: Preset '{self._active_name}' seleccionado.")
        self.preset_applied.emit(self._active_name or "")

    def _on_save_clicked(self):
        manager = get_preset_manager()
        existing = manager.list_names(self.namespace)
        dialog = SavePresetDialog(self, existing_names=existing)
        if not dialog.exec() or not dialog.result_name:
            return
        name = dialog.result_name
        manager.save_preset(self.namespace, name, self._get_settings())

    def _on_export_clicked(self):
        if not self._active_name:
            QMessageBox.information(
                self, self.tr("Sin preset"), self.tr("Selecciona un preset de la lista para exportarlo.")
            )
            return
        name = self._active_name
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
        if not self._active_name:
            QMessageBox.information(
                self, self.tr("Sin preset"), self.tr("Selecciona un preset de la lista para eliminarlo.")
            )
            return
        name = self._active_name
        resp = QMessageBox.question(
            self,
            self.tr("Eliminar preset"),
            self.tr("¿Eliminar el preset '{0}'?").format(name),
        )
        if resp == QMessageBox.Yes:
            get_preset_manager().delete_preset(self.namespace, name)
