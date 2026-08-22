# src/gui/tabs/single_process/output_options.py
import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QDoubleSpinBox,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtCore import Qt, QUrl, QSize, QPropertyAnimation, QParallelAnimationGroup, QEasingCurve
from gui.widgets.animated_button import AnimatedButton
from gui.styles import apply_folder_browse_button_style, apply_folder_open_button_style


_SPINBOX_SYMBOLS = getattr(QAbstractSpinBox, "ButtonSymbols", QAbstractSpinBox)
PLUS_MINUS_BUTTONS = getattr(
    _SPINBOX_SYMBOLS,
    "PlusMinus",
    getattr(_SPINBOX_SYMBOLS, "UpDownArrows"),
)


class OutputOptionsWidget(QFrame):
    TOOL_BUTTON_SIZE = 32
    PANEL_HEIGHT = 210

    def __init__(self):
        super().__init__()
        self.setObjectName("outputOptionsContainer")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        self.output_title_label = QLabel(self.tr("Opciones de salida"))
        self.output_title_label.setObjectName("sectionTitle")
        self.output_title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.output_title_label)

        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(10)

        # --- CONFLICT POLICY SECTION (a la izquierda de la ruta) ---
        # Visible siempre en Modo Rápido; en Proceso Avanzado solo en modo LOTES
        # (ver advanced_process_view.py::_on_solo_toggled, que llama
        # set_conflict_policy_visible()).
        self.conflict_policy_container = QWidget()
        conflict_policy_layout = QHBoxLayout(self.conflict_policy_container)
        conflict_policy_layout.setContentsMargins(0, 0, 0, 0)
        conflict_policy_layout.setSpacing(6)

        self.lbl_conflict_policy = QLabel(self.tr("Si existe:"))
        self.lbl_conflict_policy.setObjectName("menuLabel")

        self.conflict_policy_combo = QComboBox()
        self.conflict_policy_combo.addItem(self.tr("Sobrescribir"), "sobrescribir")
        self.conflict_policy_combo.addItem(self.tr("Conservar"), "conservar")
        self.conflict_policy_combo.addItem(self.tr("Omitir"), "omitir")
        self.conflict_policy_combo.setCurrentIndex(1)  # "Conservar" por defecto
        self.conflict_policy_combo.setToolTip(self.tr(
            "Determina qué hacer si un archivo con el mismo nombre ya existe:\n"
            "• Sobrescribir: reemplaza el archivo antiguo (con respaldo reversible).\n"
            "• Conservar: guarda el nuevo archivo como 'nombre (1).ext'.\n"
            "• Omitir: no descarga ese archivo."
        ))

        conflict_policy_layout.addWidget(self.lbl_conflict_policy)
        conflict_policy_layout.addWidget(self.conflict_policy_combo)

        controls_layout.addWidget(self.conflict_policy_container)
        controls_layout.addSpacing(10)

        # --- PATH SECTION ---
        from core.tabs.advanced_process.output_logic import get_default_download_path
        default_path = get_default_download_path()

        self.lbl_path = QLabel(self.tr("Ruta:"))
        self.lbl_path.setObjectName("menuLabel")

        self.output_path_input = QLineEdit()
        self.output_path_input.setPlaceholderText(self.tr("Ruta de salida"))
        self.output_path_input.setText(default_path)
        
        self.btn_select_output_path = QPushButton()
        self.btn_select_output_path.setFixedSize(self.TOOL_BUTTON_SIZE, self.TOOL_BUTTON_SIZE)
        apply_folder_browse_button_style(self.btn_select_output_path, self.tr("Seleccionar carpeta de salida"), icon_size=20)

        self.btn_open_output_path = QPushButton()
        self.btn_open_output_path.setFixedSize(self.TOOL_BUTTON_SIZE, self.TOOL_BUTTON_SIZE)
        apply_folder_open_button_style(self.btn_open_output_path, self.tr("Abrir carpeta de salida"), icon_size=20)

        self.btn_select_output_path.clicked.connect(self.select_output_path)
        self.btn_open_output_path.clicked.connect(self.open_output_path)

        controls_layout.addWidget(self.lbl_path)
        controls_layout.addWidget(self.output_path_input, 1) # Stretch 1
        controls_layout.addWidget(self.btn_select_output_path)
        controls_layout.addWidget(self.btn_open_output_path)

        # Spacing before speed limit
        controls_layout.addSpacing(10)

        # --- SPEED LIMIT SECTION ---
        self.speed_limit_label = QLabel(self.tr("Límite de velocidad:"))
        self.speed_limit_label.setObjectName("menuLabel")
        self.speed_limit_input = QDoubleSpinBox()
        self.speed_limit_input.setRange(0.0, 999.0)
        self.speed_limit_input.setDecimals(1)
        self.speed_limit_input.setSingleStep(0.5)
        self.speed_limit_input.setSuffix(self.tr(" MB/s"))
        self.speed_limit_input.setSpecialValueText(self.tr("Sin límite"))
        self.speed_limit_input.setFixedWidth(140)
        self.speed_limit_input.setButtonSymbols(PLUS_MINUS_BUTTONS)
        self.speed_limit_input.setStyleSheet("""
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                font-size: 9px;
                padding: 0px;
            }
        """)

        controls_layout.addWidget(self.speed_limit_label)
        controls_layout.addWidget(self.speed_limit_input)

        # Spacing before download button
        controls_layout.addSpacing(10)

        # --- DOWNLOAD BUTTON ---
        self.btn_start_download = AnimatedButton(self.tr("Iniciar descarga"))
        self.btn_start_download.setObjectName("downloadButton")
        self.btn_start_download.setFixedWidth(160)
        self.btn_start_download.setFixedHeight(32)
        self.btn_start_download.setEnabled(False)

        controls_layout.addWidget(self.btn_start_download)

        layout.addLayout(controls_layout)

        # --- PROGRESS BAR ---
        from gui.widgets.bouncing_progress_bar import BouncingProgressBar
        self.progress_bar = BouncingProgressBar()
        self.progress_bar.setObjectName("downloadProgressBar")
        self.progress_bar.setProperty("status", "wait")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(self.tr("En espera"))
        self.progress_bar.setTextVisible(True)

        layout.addWidget(self.progress_bar)

    def set_download_state(self, state, text=None):
        state_names = {
            "idle": self.tr("Iniciar descarga"),
            "running": self.tr("Descargando..."),
            "paused": self.tr("Reanudar descarga"),
            "done": self.tr("Descarga completada"),
            "error": self.tr("Reintentar descarga"),
        }

        self.btn_start_download.setProperty("state", state)
        self.btn_start_download.setText(text or state_names.get(state, state_names["idle"]))
        self._refresh_style(self.btn_start_download)

    def set_progress(self, value, message=None, status="wait"):
        """
        Estados:
          - 'running'      → barrita rebotando (modo indeterminado custom)
          - 'downloading'  → barra real 0-100% con info de descarga
          - 'done'         → barra al 100%
          - 'wait'         → barra vacía
          - 'error'        → barra vacía con error
        """
        if status == "running":
            self.progress_bar.setBouncing(True)
        else:
            self.progress_bar.setBouncing(False)
            self.progress_bar.setValue(value)

        self.progress_bar.setProperty("status", status)

        if message:
            self.progress_bar.setFormat(message)
        elif status == "wait":
            self.progress_bar.setFormat(self.tr("En espera"))
        else:
            self.progress_bar.setFormat(f"{value}%")

        self._refresh_style(self.progress_bar)

    def select_output_path(self):
        current_path = self.output_path_input.text().strip()
        start_path = current_path if os.path.isdir(current_path) else os.path.expanduser("~")
        selected_path = QFileDialog.getExistingDirectory(
            self,
            self.tr("Seleccionar carpeta de salida"),
            start_path,
        )
        if selected_path:
            self.output_path_input.setText(selected_path)

    def open_output_path(self):
        path = self.output_path_input.text().strip()
        if not path:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def set_conflict_policy_visible(self, visible: bool, animated: bool = True):
        """
        Muestra/oculta el combo de política de conflicto. Usado por Proceso Avanzado
        para ocultarlo en modo SOLO (donde en su lugar se pregunta con un diálogo
        modal por archivo) y mostrarlo en modo LOTES. Modo Rápido nunca llama a este
        método: el combo queda siempre visible ahí.

        Anima minimumWidth/maximumWidth del contenedor a 0 <-> ancho natural, mismo
        patrón que advanced_process_view.py usa para queue_trigger/queue_panel al
        alternar SOLO/LOTES.
        """
        target_width = self.conflict_policy_container.sizeHint().width() if visible else 0

        if hasattr(self, "_conflict_anim_group") and self._conflict_anim_group.state() == QParallelAnimationGroup.State.Running:
            self._conflict_anim_group.stop()

        if not animated:
            self.conflict_policy_container.setMinimumWidth(target_width)
            self.conflict_policy_container.setMaximumWidth(target_width if visible else 0)
            self.conflict_policy_container.setVisible(visible)
            return

        if visible:
            self.conflict_policy_container.setVisible(True)

        self._conflict_anim_group = QParallelAnimationGroup(self)
        current_width = self.conflict_policy_container.width()

        anim_min = QPropertyAnimation(self.conflict_policy_container, b"minimumWidth")
        anim_min.setDuration(220)
        anim_min.setStartValue(current_width)
        anim_min.setEndValue(target_width)
        anim_min.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._conflict_anim_group.addAnimation(anim_min)

        anim_max = QPropertyAnimation(self.conflict_policy_container, b"maximumWidth")
        anim_max.setDuration(220)
        anim_max.setStartValue(current_width)
        anim_max.setEndValue(target_width)
        anim_max.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._conflict_anim_group.addAnimation(anim_max)

        def on_finished():
            self.conflict_policy_container.setMaximumWidth(16777215)
            if not visible:
                self.conflict_policy_container.setVisible(False)

        self._conflict_anim_group.finished.connect(on_finished)
        self._conflict_anim_group.start()

    def _refresh_style(self, widget):
        from gui.widgets.bouncing_progress_bar import BouncingProgressBar
        if isinstance(widget, BouncingProgressBar):
            widget.refresh_theme_colors()
            
        widget.style().unpolish(widget)
        widget.style().polish(widget)
