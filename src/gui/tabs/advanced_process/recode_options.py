# src/gui/tabs/advanced_process/recode_options.py
import sys
import os

if __name__ == "__main__":
    src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.widgets.preset_bar import PresetBar

_PRESET_NAMESPACE = "video_tools/avanzado"


class RecodeOptionsWidget(QFrame):
    """
    Tarjeta "Recodificar" de Proceso Avanzado: switch para recodificar el medio al
    terminar la descarga (eligiendo un preajuste ya armado en Herramientas Multimedia >
    Avanzado, vía PresetBar en modo picker) + checkbox "Mantener medios originales".

    Mismo molde visual que SubtitleOptionsWidget (misma pestaña, tarjeta hermana a su
    izquierda): QFrame de ancho fijo, header colapsable, cuerpo animado. No sabe nada de
    cómo se ejecuta la recodificación — eso lo maneja recode_controller.py.
    """
    COMPACT_WIDTH = 350
    COLLAPSED_HEIGHT = 38
    toggled_collapse = Signal(bool)

    def __init__(self, start_expanded: bool = False):
        super().__init__()
        self.setObjectName("additionalOptionsContainer")
        self.setAttribute(Qt.WA_StyledBackground, True)
        # Ver mismo comentario en subtitle_options.py: sin ancho fijo NI mínimo propio,
        # para que se achique junto con la ventana (texto recortado y todo) en vez de
        # desbordar al llegar a un piso que video_details no tiene.
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._is_expanded = start_expanded
        self._anim_group = None

        self.init_ui()
        self.set_expanded(self._is_expanded, animate=False)

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 8, 12, 8)
        self.main_layout.setSpacing(4)

        # ── 1. Cabecera Clicable ─────────────────────────────────
        self.header_widget = QWidget()
        self.header_widget.setObjectName("recodeHeaderWidget")
        self.header_widget.setCursor(Qt.PointingHandCursor)
        self.header_widget.setFixedHeight(22)
        header_layout = QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(4, 0, 4, 0)
        header_layout.setSpacing(0)

        self.title_label = QLabel(self.tr("Recodificar"))
        self.title_label.setObjectName("sectionTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        header_layout.addWidget(self.title_label)

        self.header_widget.mousePressEvent = self._on_header_clicked
        self.main_layout.addWidget(self.header_widget)

        # ── 2. Cuerpo Desplegable ────────────────────────────────
        self.body_container = QWidget()
        body_layout = QVBoxLayout(self.body_container)
        body_layout.setContentsMargins(0, 4, 0, 0)
        body_layout.setSpacing(6)

        # Texto propio del checkbox (no un QLabel aparte, ver conversación): el tema ya
        # define QCheckBox { spacing: 8px } para el hueco entre el indicador y su
        # texto - con un QLabel aparte más spacing de layout encima (arrastre de cuando
        # esto era un ToggleSwitch mucho más ancho), quedaban dos huecos sumados.
        switch_row = QHBoxLayout()
        switch_row.setContentsMargins(0, 0, 0, 0)
        self.switch_recode = QCheckBox(self.tr("Recodificar al finalizar"))
        self.switch_recode.setCursor(Qt.PointingHandCursor)
        switch_row.addWidget(self.switch_recode)
        switch_row.addStretch()
        body_layout.addLayout(switch_row)

        self.chk_keep_original = QCheckBox(self.tr("Mantener medios originales"))
        self.chk_keep_original.setCursor(Qt.PointingHandCursor)
        self.chk_keep_original.setChecked(True)
        self.chk_keep_original.setEnabled(False)
        self.chk_keep_original.setToolTip(self.tr(
            "Activado (por defecto): conserva el archivo descargado además del "
            "recodificado. Desactivado: al terminar con éxito la recodificación, se "
            "borra el original."
        ))
        body_layout.addWidget(self.chk_keep_original)

        self.preset_bar = PresetBar(
            _PRESET_NAMESPACE, get_settings=None, parent=self.body_container,
            show_picker=True, show_save_button=False,
        )
        self.preset_bar.setEnabled(False)
        body_layout.addWidget(self.preset_bar)

        # Prefijo/Sufijo del archivo recodificado - vacíos por defecto (la app igual
        # evita colisiones sola, ver preset_manager.build_recode_output_path, si el
        # contenedor elegido no cambia la extensión del original), pero permiten
        # elegir un nombre propio en vez del automático "(recodificado)".
        naming_row = QHBoxLayout()
        naming_row.setContentsMargins(0, 0, 0, 0)
        naming_row.setSpacing(6)

        prefix_col = QVBoxLayout()
        prefix_col.setSpacing(2)
        self.lbl_prefix = QLabel(self.tr("Prefijo"))
        self.lbl_prefix.setObjectName("menuLabel")
        self.txt_prefix = QLineEdit()
        self.txt_prefix.setPlaceholderText(self.tr("(ninguno)"))
        self.txt_prefix.setEnabled(False)
        prefix_col.addWidget(self.lbl_prefix)
        prefix_col.addWidget(self.txt_prefix)
        naming_row.addLayout(prefix_col)

        suffix_col = QVBoxLayout()
        suffix_col.setSpacing(2)
        self.lbl_suffix = QLabel(self.tr("Sufijo"))
        self.lbl_suffix.setObjectName("menuLabel")
        self.txt_suffix = QLineEdit("_recoded")
        self.txt_suffix.setPlaceholderText(self.tr("(ninguno)"))
        self.txt_suffix.setEnabled(False)
        suffix_col.addWidget(self.lbl_suffix)
        suffix_col.addWidget(self.txt_suffix)
        naming_row.addLayout(suffix_col)

        body_layout.addLayout(naming_row)

        # Red de seguridad: _expanded_height() ya calcula el alto exacto del contenido
        # (ver conversación - antes esto era necesario porque EXPANDED_HEIGHT era un
        # número fijo con hueco de sobra, y sin stretch Qt centraba el contenido en vez
        # de pegarlo arriba), pero se deja igual por si algún redondeo/timing de
        # animación deja un resto de un par de píxeles.
        body_layout.addStretch(1)

        self.main_layout.addWidget(self.body_container)

        self.switch_recode.toggled.connect(self._on_switch_toggled)

    def _on_switch_toggled(self, checked: bool):
        self.preset_bar.setEnabled(checked)
        self.chk_keep_original.setEnabled(checked)
        self.txt_prefix.setEnabled(checked)
        self.txt_suffix.setEnabled(checked)

    def _on_header_clicked(self, event):
        self.toggle_collapse()

    def toggle_collapse(self):
        self.set_expanded(not self._is_expanded, animate=True)

    def _expanded_height(self) -> int:
        """Ver mismo método en subtitle_options.py: alto calculado en vivo en vez de
        un número fijo, para que no se desalinee cada vez que cambia el contenido del
        cuerpo (prefijo/sufijo, switches->checkboxes, etc.)."""
        margins = self.main_layout.contentsMargins()
        return (
            self.header_widget.height() + self.main_layout.spacing()
            + self.body_container.sizeHint().height()
            + margins.top() + margins.bottom()
        )

    def set_expanded(self, expanded: bool, animate: bool = True):
        self._is_expanded = expanded

        expanded_h = self._expanded_height()
        start_h = self.height() if self.height() > 0 else (expanded_h if not expanded else self.COLLAPSED_HEIGHT)
        target_h = expanded_h if expanded else self.COLLAPSED_HEIGHT

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


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    from gui.styles import load_stylesheet
    app = QApplication(sys.argv)
    load_stylesheet(app, "dark")
    w = RecodeOptionsWidget(start_expanded=True)
    w.resize(350, 250)
    w.show()
    sys.exit(app.exec())
