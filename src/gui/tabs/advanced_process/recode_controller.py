# src/gui/tabs/advanced_process/recode_controller.py
from PySide6.QtCore import QObject


class RecodeController(QObject):
    """
    Contraparte de SubtitleController para la tarjeta "Recodificar": no descarga ni
    ejecuta nada por sí mismo, solo traduce entre los widgets de recode_options.py y las
    3 claves que viajan en request_data (descarga individual) o job.config (playlist, ver
    advanced_process_view.py::_save_current_job_options) - "recode_enabled",
    "recode_preset_name", "recode_keep_original". La ejecución real (encolar el job
    RECODE, cuarentena/backup) vive en download_controller.py.
    """
    def __init__(self, tab):
        super().__init__()
        self.tab = tab

    def collect_recode_data(self) -> dict:
        widget = self.tab.recode_options
        enabled = widget.switch_recode.isChecked()
        return {
            "recode_enabled": enabled,
            "recode_preset_name": widget.preset_bar.active_preset_name() if enabled else None,
            "recode_keep_original": widget.chk_keep_original.isChecked(),
            "recode_filename_prefix": widget.txt_prefix.text().strip(),
            "recode_filename_suffix": widget.txt_suffix.text().strip(),
        }

    def restore_recode_to_ui(self, data: dict):
        widget = self.tab.recode_options
        widget.switch_recode.blockSignals(True)
        widget.switch_recode.setChecked(bool(data.get("recode_enabled", False)))
        widget.switch_recode.blockSignals(False)
        widget._on_switch_toggled(widget.switch_recode.isChecked())

        preset_name = data.get("recode_preset_name")
        if preset_name:
            widget.preset_bar.refresh(select_name=preset_name)
        else:
            widget.preset_bar.clear_selection()

        widget.chk_keep_original.setChecked(bool(data.get("recode_keep_original", True)))
        widget.txt_prefix.setText(data.get("recode_filename_prefix", "") or "")
        if "recode_filename_suffix" in data:
            widget.txt_suffix.setText(data.get("recode_filename_suffix") if data.get("recode_filename_suffix") is not None else "_recoded")
        else:
            widget.txt_suffix.setText("_recoded")

    def reset_to_defaults(self):
        self.restore_recode_to_ui({
            "recode_enabled": False,
            "recode_preset_name": None,
            "recode_keep_original": True,
            "recode_filename_prefix": "",
            "recode_filename_suffix": "_recoded",
        })
