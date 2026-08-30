# src/gui/tabs/advanced_process/subtitle_options.py
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.widgets.toggle_switch import ToggleSwitch
from gui.widgets.combo_box import AutoPopupComboBox
from gui.styles import get_theme_token


class SubtitleOptionsWidget(QFrame):
    COMPACT_WIDTH = 350
    COLLAPSED_HEIGHT = 38
    EXPANDED_HEIGHT = 230
    toggled_collapse = Signal(bool)

    def __init__(self, start_expanded: bool = False):
        super().__init__()
        self.setObjectName("additionalOptionsContainer")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(self.COMPACT_WIDTH)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        
        self._is_expanded = start_expanded
        self._anim_group = None

        self.init_ui()
        self.set_expanded(self._is_expanded, animate=False)

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 8, 12, 8)
        self.main_layout.setSpacing(4)

        # ── 1. Cabecera Clicable (Delgada y Centrada) ───────────────────────
        self.header_widget = QWidget()
        self.header_widget.setObjectName("subtitleHeaderWidget")
        self.header_widget.setCursor(Qt.PointingHandCursor)
        self.header_widget.setFixedHeight(22)
        header_layout = QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(4, 0, 4, 0)
        header_layout.setSpacing(0)

        self.title_label = QLabel(self.tr("Subtítulos"))
        self.title_label.setObjectName("sectionTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("font-weight: bold; font-size: 13px;")

        header_layout.addWidget(self.title_label)

        self.header_widget.mousePressEvent = self._on_header_clicked
        self.main_layout.addWidget(self.header_widget)

        # ── 2. Contenedor de Opciones Desplegable ───────────────────────────
        self.body_container = QWidget()
        body_layout = QVBoxLayout(self.body_container)
        body_layout.setContentsMargins(0, 4, 0, 0)
        body_layout.setSpacing(6)

        # Idioma
        self.language_container = QWidget()
        language_layout = QHBoxLayout(self.language_container)
        language_layout.setContentsMargins(0, 0, 0, 0)
        language_layout.setSpacing(8)

        self.lbl_subtitle_language = QLabel(self.tr("Idioma"))
        self.lbl_subtitle_language.setObjectName("menuLabel")
        self.lbl_subtitle_language.setFixedWidth(58)
        self.combo_subtitle_language = AutoPopupComboBox()
        self.combo_subtitle_language.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.combo_subtitle_language.addItem(self.tr("Seleccionar idioma..."))

        language_layout.addWidget(self.lbl_subtitle_language)
        language_layout.addWidget(self.combo_subtitle_language, 1)

        # Formato
        self.format_container = QWidget()
        format_layout = QHBoxLayout(self.format_container)
        format_layout.setContentsMargins(0, 0, 0, 0)
        format_layout.setSpacing(8)

        self.lbl_subtitle_format = QLabel(self.tr("Formato"))
        self.lbl_subtitle_format.setObjectName("menuLabel")
        self.lbl_subtitle_format.setFixedWidth(58)
        self.combo_subtitle_format = AutoPopupComboBox()
        self.combo_subtitle_format.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.combo_subtitle_format.addItem("-")
        self.combo_subtitle_format.setEnabled(False)

        format_layout.addWidget(self.lbl_subtitle_format)
        format_layout.addWidget(self.combo_subtitle_format, 1)

        self.combo_subtitle_format.currentTextChanged.connect(self.update_standardize_visibility)

        # Botón Descargar Subtítulos
        self.btn_download_subtitles = QPushButton(self.tr("Descargar Subtítulos"))
        self.btn_download_subtitles.setObjectName("secondaryButton")
        self.btn_download_subtitles.setEnabled(False)

        # Switches
        self.chk_download_with_media = self._build_switch_row(self.tr("Descargar con el medio"))
        self.chk_standardize_srt = self._build_switch_row(self.tr("Convertir y estandarizar a SRT"))
        self.chk_cut_to_fragment = self._build_switch_row(self.tr("Recortar subtítulo al fragmento"))
        
        # Deshabilitados por defecto hasta que se seleccione un subtítulo válido
        self.chk_download_with_media["container"].setEnabled(False)
        self.chk_standardize_srt["container"].setEnabled(False)
        self.chk_cut_to_fragment["container"].setEnabled(False)
        
        # Tooltips
        tooltip_text = self.tr("Al recortar, el subtítulo se convertirá automáticamente a SRT para garantizar la compatibilidad y precisión del corte.")
        self.chk_cut_to_fragment["container"].setToolTip(tooltip_text)
        self.chk_cut_to_fragment["switch"].setToolTip(tooltip_text)
        self.chk_cut_to_fragment["label"].setToolTip(tooltip_text)
        
        body_layout.addWidget(self.language_container)
        body_layout.addWidget(self.format_container)
        body_layout.addWidget(self.btn_download_subtitles)
        body_layout.addWidget(self.chk_download_with_media["container"])
        body_layout.addWidget(self.chk_standardize_srt["container"])
        body_layout.addWidget(self.chk_cut_to_fragment["container"])

        self.main_layout.addWidget(self.body_container)

    def _on_header_clicked(self, event):
        self.toggle_collapse()

    def toggle_collapse(self):
        self.set_expanded(not self._is_expanded, animate=True)

    def set_expanded(self, expanded: bool, animate: bool = True):
        self._is_expanded = expanded
        
        start_h = self.height() if self.height() > 0 else (self.EXPANDED_HEIGHT if not expanded else self.COLLAPSED_HEIGHT)
        target_h = self.EXPANDED_HEIGHT if expanded else self.COLLAPSED_HEIGHT

        if not animate:
            if self._anim_group and self._anim_group.state() == QPropertyAnimation.Running:
                self._anim_group.stop()
            self.body_container.setVisible(expanded)
            self.setFixedHeight(target_h)
            self.toggled_collapse.emit(expanded)
            return

        if self._anim_group and self._anim_group.state() == QPropertyAnimation.Running:
            self._anim_group.stop()

        if expanded:
            self.body_container.show()

        anim_max = QPropertyAnimation(self, b"maximumHeight")
        anim_max.setDuration(220)
        anim_max.setStartValue(start_h)
        anim_max.setEndValue(target_h)
        anim_max.setEasingCurve(QEasingCurve.Type.OutCubic)

        anim_min = QPropertyAnimation(self, b"minimumHeight")
        anim_min.setDuration(220)
        anim_min.setStartValue(start_h)
        anim_min.setEndValue(target_h)
        anim_min.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._anim_group = QParallelAnimationGroup(self)
        self._anim_group.addAnimation(anim_max)
        self._anim_group.addAnimation(anim_min)

        def on_finished():
            if not self._is_expanded:
                self.body_container.hide()
            self.setFixedHeight(target_h)
            self.toggled_collapse.emit(self._is_expanded)

        self._anim_group.finished.connect(on_finished)
        self._anim_group.start()

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
        """Habilita 'Convertir y estandarizar a SRT' solo cuando hay un subtítulo seleccionado
        cuyo formato de origen no sea ya SRT."""
        fmt_data = self.combo_subtitle_format.currentData()
        ext = (fmt_data.get("ext") or "").lower() if fmt_data else ""
        should_enable = bool(fmt_data) and ext != "" and ext != "srt"
        self.chk_standardize_srt["container"].setEnabled(should_enable)
        if not should_enable:
            self.chk_standardize_srt["switch"].setChecked(False)
