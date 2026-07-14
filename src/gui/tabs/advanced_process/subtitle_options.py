# src/gui/tabs/single_process/subtitle_options.py
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from gui.widgets.toggle_switch import ToggleSwitch


class PaddingDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(size.height() + 6)
        return size


class SubtitleOptionsWidget(QFrame):
    COMPACT_WIDTH = 350
    PANEL_HEIGHT = 210

    def __init__(self):
        super().__init__()
        self.setObjectName("additionalOptionsContainer")
        self.setFixedWidth(self.COMPACT_WIDTH)
        self.setFixedWidth(self.COMPACT_WIDTH)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(5)

        self.title_label = QLabel(self.tr("Subtítulos"))
        self.title_label.setObjectName("sectionTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title_label)

        self.language_container = QWidget()
        language_layout = QHBoxLayout(self.language_container)
        language_layout.setContentsMargins(0, 0, 0, 0)
        language_layout.setSpacing(8)

        self.lbl_subtitle_language = QLabel(self.tr("Idioma"))
        self.lbl_subtitle_language.setObjectName("menuLabel")
        self.lbl_subtitle_language.setFixedWidth(58)
        self.combo_subtitle_language = QComboBox()
        self.combo_subtitle_language.setItemDelegate(PaddingDelegate())
        self.combo_subtitle_language.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.combo_subtitle_language.addItem(self.tr("Seleccionar idioma..."))

        language_layout.addWidget(self.lbl_subtitle_language)
        language_layout.addWidget(self.combo_subtitle_language, 1)

        self.format_container = QWidget()
        format_layout = QHBoxLayout(self.format_container)
        format_layout.setContentsMargins(0, 0, 0, 0)
        format_layout.setSpacing(8)

        self.lbl_subtitle_format = QLabel(self.tr("Formato"))
        self.lbl_subtitle_format.setObjectName("menuLabel")
        self.lbl_subtitle_format.setFixedWidth(58)
        self.combo_subtitle_format = QComboBox()
        self.combo_subtitle_format.setItemDelegate(PaddingDelegate())
        self.combo_subtitle_format.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.combo_subtitle_format.addItem("-")
        self.combo_subtitle_format.setEnabled(False)

        format_layout.addWidget(self.lbl_subtitle_format)
        format_layout.addWidget(self.combo_subtitle_format, 1)

        self.combo_subtitle_format.currentTextChanged.connect(self.update_standardize_visibility)

        self.btn_download_subtitles = QPushButton(self.tr("Descargar Subtítulos"))
        self.btn_download_subtitles.setObjectName("secondaryButton")
        self.btn_download_subtitles.setEnabled(False)

        self.chk_download_with_media = self._build_switch_row(self.tr("Descargar con el medio"))
        self.chk_standardize_srt = self._build_switch_row(self.tr("Convertir y estandarizar a SRT"))
        self.chk_cut_to_fragment = self._build_switch_row(self.tr("Recortar subtítulo al fragmento"))
        
        # Deshabilitados por defecto hasta que se seleccione un subtítulo válido
        self.chk_download_with_media["container"].setEnabled(False)
        self.chk_standardize_srt["container"].setEnabled(False)
        self.chk_cut_to_fragment["container"].setEnabled(False)
        
        # Añadir tooltip informativo
        tooltip_text = self.tr("Al recortar, el subtítulo se convertirá automáticamente a SRT para garantizar la compatibilidad y precisión del corte.")
        self.chk_cut_to_fragment["container"].setToolTip(tooltip_text)
        self.chk_cut_to_fragment["switch"].setToolTip(tooltip_text)
        self.chk_cut_to_fragment["label"].setToolTip(tooltip_text)
        
        layout.addWidget(self.language_container)
        layout.addWidget(self.format_container)
        layout.addWidget(self.btn_download_subtitles)
        layout.addWidget(self.chk_download_with_media["container"])
        layout.addWidget(self.chk_standardize_srt["container"])
        layout.addWidget(self.chk_cut_to_fragment["container"])
        
        layout.addStretch(1)

    def _build_switch_row(self, text):
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        switch = ToggleSwitch()
        label = QLabel(text)
        label.setObjectName("switchLabel")

        layout.addWidget(switch)
        layout.addWidget(label)
        layout.addStretch()

        return {"container": container, "switch": switch, "label": label}

    def update_standardize_visibility(self):
        """Deshabilita o habilita la opción de estandarizar según el formato seleccionado."""
        # Se permite estandarizar para todos los formatos (incluyendo .srt y default '-')
        # para que el usuario pueda limpiar líneas duplicadas y traslapes en el archivo final.
        self.chk_standardize_srt["container"].setEnabled(True)
