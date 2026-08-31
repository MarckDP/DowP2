# src/gui/tabs/video_tools/presets_panel.py
import os

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QFileDialog
from PySide6.QtCore import Qt

from gui.styles import get_theme_token
from gui.widgets.preset_bar import PresetBar
from gui.tabs.video_tools.advanced_recode_panel import _PRESET_NAMESPACE
from core.utils.watermark_builder import check_watermark_file
from core.utils.recode_guard import normalize_container


class PresetsPanel(QWidget):
    """
    Pestaña 'Preajustes' de Herramientas Multimedia.

    Acá el usuario ELIGE qué preset usar para el próximo trabajo, sin pasar
    por la pestaña que lo creó (ej. guardaste "422 Proxy" en Avanzado una vez;
    de ahí en más solo entrás acá, lo elegís, y mandás "Iniciar
    Recodificación" directo). Por eso expone get_settings()/is_valid() con la
    misma forma que AdvancedRecodePanel - EncodingOptionsWidget los trata
    igual sea cual sea la pestaña activa.

    Namespace: por ahora apunta al mismo que usa AdvancedRecodePanel, porque
    es la única pestaña que hoy guarda ajustes reales. Cuando Comprimir/
    Convertir/Proxies tengan lógica propia, esto va a necesitar mostrar
    varios namespaces a la vez (agrupados o con un filtro), no solo uno.

    Cada preajuste puede pedir container="same" (ver core.utils.default_presets, ej.
    los de normalizar audio: no tiene sentido forzar un contenedor fijo si solo se está
    tocando el audio) - se resuelve acá por archivo, igual que ya hacía
    compress_panel.py en Manual ("Mismo que el original"), porque get_settings() recibe
    meta_override/filepath_override por archivo cuando video_tools_view.py arma el lote
    (ver needs_per_file_recompute).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings_override = {}
        self._source_meta = None
        self._source_filepath = None
        self._warning_text = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Un solo combo, agrupado por función adentro (ver PresetBar.refresh) - nada de
        # un filtro aparte más el picker (ver conversación).
        self.preset_bar = PresetBar(
            _PRESET_NAMESPACE, get_settings=None, parent=self,
            show_picker=True, show_save_button=False,
        )
        layout.addWidget(self.preset_bar)

        # Aviso "la marca de agua de este preajuste ya no existe" + reparación puntual
        # (ver conversación): solo corrige la corrida actual, no reescribe el preajuste
        # guardado en disco.
        self.warning_container = QWidget(self)
        warn_layout = QVBoxLayout(self.warning_container)
        warn_layout.setContentsMargins(0, 0, 0, 0)
        warn_layout.setSpacing(6)
        self.lbl_watermark_warning = QLabel("", self.warning_container)
        self.lbl_watermark_warning.setWordWrap(True)
        warning_color = get_theme_token("estado_error", "#e06c75")
        self.lbl_watermark_warning.setStyleSheet(f"color: {warning_color}; font-weight: bold;")
        warn_layout.addWidget(self.lbl_watermark_warning)
        self.btn_fix_watermark = QPushButton(self.tr("Seleccionar otra imagen…"), self.warning_container)
        self.btn_fix_watermark.setObjectName("secondaryButton")
        self.btn_fix_watermark.setCursor(Qt.PointingHandCursor)
        self.btn_fix_watermark.clicked.connect(self._on_fix_watermark_clicked)
        warn_layout.addWidget(self.btn_fix_watermark)
        self.warning_container.setVisible(False)
        layout.addWidget(self.warning_container)

        layout.addStretch(1)

        self.preset_bar.preset_applied.connect(self._on_preset_applied)

    def _on_preset_applied(self, _name: str):
        self._settings_override = {}
        self._refresh_watermark_warning()

    def _refresh_watermark_warning(self):
        merged = dict(self.preset_bar.current_preset_settings() or {})
        merged.update(self._settings_override)
        self._warning_text = check_watermark_file(merged)
        if self._warning_text:
            self.lbl_watermark_warning.setText(f"⚠ {self._warning_text}")
        self.warning_container.setVisible(bool(self._warning_text))

    def _on_fix_watermark_clicked(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Seleccionar imagen de marca de agua"), "",
            self.tr("Imágenes (*.png *.jpg *.jpeg *.webp *.bmp);;Todos los archivos (*.*)"),
        )
        if not file_path:
            return
        # Solo corrige la corrida actual — el preajuste guardado en disco no se toca.
        self._settings_override["watermark_image_path"] = file_path
        self._refresh_watermark_warning()
        # Reutiliza la señal que EncodingOptionsWidget ya escucha para refrescar el botón
        # "Iniciar" — ver preset_bar.py / encoding_options_widget.py.
        self.preset_bar.preset_applied.emit(self.preset_bar.active_preset_name() or "")

    def set_source_media(self, meta: dict, filepath: str):
        self._source_meta = meta or None
        self._source_filepath = filepath

    def get_settings(self, meta_override: dict | None = None, filepath_override: str | None = None) -> dict:
        settings = dict(self.preset_bar.current_preset_settings() or {})
        settings.update(self._settings_override)
        if settings.get("container") == "same":
            filepath = filepath_override if filepath_override is not None else self._source_filepath
            resolved = None
            if filepath:
                ext = os.path.splitext(filepath)[1]
                resolved = normalize_container(ext) if ext else None
            settings["container"] = resolved or ("m4a" if settings.get("stream_mode") == "audio_only" else "mp4")
        return settings

    def is_valid(self) -> bool:
        return self.get_status()[0]

    def get_status(self) -> tuple[bool, str]:
        if self.preset_bar.active_preset_name() is None:
            return False, self.tr("Selecciona un preajuste")
        if self._warning_text:
            return False, self.tr("Resuelve el aviso de la marca de agua")
        return True, self.tr("Iniciar Recodificación")
