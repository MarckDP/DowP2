# src/gui/tabs/image_tools/convert_panel.py
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QComboBox, QCheckBox,
    QSlider, QScrollArea, QSizePolicy, QStackedWidget, QLineEdit, QPushButton,
    QFileDialog,
)
from PySide6.QtCore import Signal, Qt, QUrl
from PySide6.QtGui import QDesktopServices

from gui.styles import get_theme_token, apply_folder_browse_button_style, apply_folder_open_button_style
from gui.widgets.combo_box import CheckmarkComboDelegate, AutoPopupComboBox
from core.tabs.image_tools.convert_options import (
    OUTPUT_FORMATS, JPG_SUBSAMPLING_OPTIONS, TIFF_COMPRESSION_OPTIONS,
    ICO_SIZES, ICO_DEFAULT_SIZES, default_options_for_format,
)

_MAX_VISIBLE_COMBO_ITEMS = 12
_TOOL_BUTTON_SIZE = 32


class ConvertPanel(QWidget):
    """Panel "Convertir" del Editor de Imagen -- formato de salida + sus opciones +
    carpeta de destino, aplicado a TODO el lote de la cola (mismo criterio que
    DowP1: un único set de opciones global, no por archivo). Redimensionar vive
    aparte, en su propio botón/popover de la franja superior (ver
    resize_popover.py) -- acá solo queda lo específico de "a qué formato/archivo
    convertir", no el tamaño. Mismo contrato público que
    gui/tabs/video_tools/convert_panel.py::ConvertPanel (get_settings/is_valid/
    validity_changed), sin el selector Rápido/Manual -- acá no hay equivalente a
    "auto-decidir copy vs recode", el usuario siempre elige formato + sus opciones
    directo, como hacía DowP1 con su único panel de formato."""

    validity_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ico_checkboxes = {}
        self._init_ui()
        self._on_format_changed()

    # ─── UI ──────────────────────────────────────────────────────

    def _init_ui(self):
        self.setObjectName("convertPanel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setObjectName("convertScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        self.setStyleSheet("""
            QWidget#convertPanel { background: transparent; }
            QScrollArea#convertScroll { background: transparent; }
            QWidget#convertContent { background: transparent; }
        """)

        content = QWidget(scroll)
        content.setObjectName("convertContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        frame_format, fv = self._card_frame(self.tr("Formato de salida"), content)
        self.combo_format = AutoPopupComboBox(frame_format)
        self._setup_fixed_combo(self.combo_format)
        for fmt in OUTPUT_FORMATS:
            self.combo_format.addItem(fmt, fmt)
        self.combo_format.currentIndexChanged.connect(self._on_format_changed)
        fv.addWidget(self.combo_format)
        layout.addWidget(frame_format)

        layout.addWidget(self._build_output_card(content))

        self.format_stack = QStackedWidget(content)
        self._build_format_pages(content)
        layout.addWidget(self.format_stack)

        layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _card_frame(self, title: str | None, parent=None) -> tuple[QFrame, QVBoxLayout]:
        """Mismo criterio visual que gui/tabs/video_tools/convert_panel.py::_card_frame
        (duplicado a propósito -- no hay un helper compartido factorizado en el resto
        de la app, cada panel de opciones trae el suyo)."""
        frame = QFrame(parent or self)
        frame.setObjectName("advancedCard")
        border_color = get_theme_token('borde_sutil', '#2d2d2d')
        frame.setStyleSheet(f"""
            QFrame#advancedCard {{
                background-color: transparent;
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
        """)
        frame.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        v = QVBoxLayout(frame)
        v.setContentsMargins(12, 10, 12, 12)
        v.setSpacing(8)
        if title:
            lbl = QLabel(title, frame)
            lbl.setObjectName("sectionTitle")
            lbl.setAlignment(Qt.AlignCenter)
            v.addWidget(lbl)
        return frame, v

    def _setup_fixed_combo(self, combo: QComboBox):
        combo.setMaxVisibleItems(_MAX_VISIBLE_COMBO_ITEMS)
        combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(1)
        combo.setItemDelegate(CheckmarkComboDelegate(combo))
        combo.setCursor(Qt.PointingHandCursor)

    def _build_output_card(self, parent) -> QFrame:
        """Carpeta de destino + qué hacer si el archivo de salida ya existe --
        mismo criterio y mismos 3 valores (Sobrescribir/Conservar/Omitir) que
        gui/tabs/advanced_process/output_options.py::OutputOptionsWidget, resuelto
        con la misma utilidad compartida (core/utils/file_conflict_manager.
        resolve_conflict, ver image_convert_worker.py) para que el comportamiento
        sea consistente con el resto de la app."""
        frame, v = self._card_frame(self.tr("Destino"), parent)

        path_row = QHBoxLayout()
        self.entry_output_folder = QLineEdit(frame)
        self.entry_output_folder.setPlaceholderText(self.tr("Misma carpeta que cada archivo"))
        path_row.addWidget(self.entry_output_folder, 1)

        self.btn_browse_output_folder = QPushButton(frame)
        self.btn_browse_output_folder.setFixedSize(_TOOL_BUTTON_SIZE, _TOOL_BUTTON_SIZE)
        apply_folder_browse_button_style(self.btn_browse_output_folder, self.tr("Elegir carpeta de destino"))
        self.btn_browse_output_folder.clicked.connect(self._on_browse_output_folder)
        path_row.addWidget(self.btn_browse_output_folder)

        self.btn_open_output_folder = QPushButton(frame)
        self.btn_open_output_folder.setFixedSize(_TOOL_BUTTON_SIZE, _TOOL_BUTTON_SIZE)
        apply_folder_open_button_style(self.btn_open_output_folder, self.tr("Abrir carpeta de destino"))
        self.btn_open_output_folder.clicked.connect(self._on_open_output_folder)
        path_row.addWidget(self.btn_open_output_folder)
        v.addLayout(path_row)

        lbl_conflict = QLabel(self.tr("Si el archivo ya existe:"), frame)
        lbl_conflict.setObjectName("menuLabel")
        v.addWidget(lbl_conflict)
        self.combo_conflict_policy = AutoPopupComboBox(frame)
        self._setup_fixed_combo(self.combo_conflict_policy)
        self.combo_conflict_policy.addItem(self.tr("Sobrescribir"), "sobrescribir")
        self.combo_conflict_policy.addItem(self.tr("Conservar (renombrar)"), "conservar")
        self.combo_conflict_policy.addItem(self.tr("Omitir"), "omitir")
        self.combo_conflict_policy.setCurrentIndex(1)  # "Conservar" por defecto, igual que Descargas.
        self.combo_conflict_policy.setToolTip(self.tr(
            "• Sobrescribir: reemplaza el archivo existente (con respaldo reversible).\n"
            "• Conservar: guarda el nuevo archivo como 'nombre (1).ext'.\n"
            "• Omitir: no convierte ese archivo."
        ))
        v.addWidget(self.combo_conflict_policy)

        return frame

    def _on_browse_output_folder(self):
        current = self.entry_output_folder.text().strip()
        start = current if os.path.isdir(current) else os.path.expanduser("~")
        selected = QFileDialog.getExistingDirectory(self, self.tr("Elegir carpeta de destino"), start)
        if selected:
            self.entry_output_folder.setText(selected)

    def _on_open_output_folder(self):
        path = self.entry_output_folder.text().strip()
        if path and os.path.isdir(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ─── Páginas de opciones por formato ────────────────────────

    def _build_format_pages(self, parent):
        pages = {
            "No Convertir": self._build_passthrough_page(parent),
            "PNG": self._build_png_page(parent),
            "JPG": self._build_jpg_page(parent),
            "WEBP": self._build_webp_page(parent),
            "AVIF": self._build_avif_page(parent),
            "PDF": QWidget(parent),  # sin opciones propias
            "TIFF": self._build_tiff_page(parent),
            "ICO": self._build_ico_page(parent),
            "BMP": self._build_bmp_page(parent),
        }
        self._format_page_index = {}
        for fmt in OUTPUT_FORMATS:
            self._format_page_index[fmt] = self.format_stack.count()
            self.format_stack.addWidget(pages[fmt])

    def _build_passthrough_page(self, parent) -> QWidget:
        page = QWidget(parent)
        v = QVBoxLayout(page)
        lbl = QLabel(
            self.tr("Mantiene el formato original de cada archivo -- útil si solo "
                     "querés aplicar Redimensionar (franja superior) sin cambiar de formato."),
            page,
        )
        lbl.setWordWrap(True)
        lbl.setObjectName("mutedLabel")
        v.addWidget(lbl)
        return page

    def _build_png_page(self, parent) -> QWidget:
        page = QWidget(parent)
        v = QVBoxLayout(page)
        self.chk_png_transparency = QCheckBox(self.tr("Mantener transparencia"), page)
        self.chk_png_transparency.setChecked(True)
        v.addWidget(self.chk_png_transparency)
        v.addWidget(QLabel(self.tr("Compresión:"), page))
        self.slider_png_compression = QSlider(Qt.Horizontal, page)
        self.slider_png_compression.setRange(0, 9)
        self.slider_png_compression.setValue(6)
        v.addWidget(self.slider_png_compression)
        return page

    def _build_jpg_page(self, parent) -> QWidget:
        page = QWidget(parent)
        v = QVBoxLayout(page)
        v.addWidget(QLabel(self.tr("Calidad:"), page))
        self.slider_jpg_quality = QSlider(Qt.Horizontal, page)
        self.slider_jpg_quality.setRange(1, 100)
        self.slider_jpg_quality.setValue(90)
        v.addWidget(self.slider_jpg_quality)
        v.addWidget(QLabel(self.tr("Submuestreo de color:"), page))
        self.combo_jpg_subsampling = AutoPopupComboBox(page)
        self._setup_fixed_combo(self.combo_jpg_subsampling)
        for opt in JPG_SUBSAMPLING_OPTIONS:
            self.combo_jpg_subsampling.addItem(opt, opt)
        v.addWidget(self.combo_jpg_subsampling)
        self.chk_jpg_progressive = QCheckBox(self.tr("Escaneo progresivo (web)"), page)
        v.addWidget(self.chk_jpg_progressive)
        return page

    def _build_webp_page(self, parent) -> QWidget:
        page = QWidget(parent)
        v = QVBoxLayout(page)
        self.chk_webp_lossless = QCheckBox(self.tr("Sin pérdida"), page)
        self.chk_webp_lossless.toggled.connect(self._on_webp_lossless_toggled)
        v.addWidget(self.chk_webp_lossless)
        self.lbl_webp_quality = QLabel(self.tr("Calidad:"), page)
        v.addWidget(self.lbl_webp_quality)
        self.slider_webp_quality = QSlider(Qt.Horizontal, page)
        self.slider_webp_quality.setRange(1, 100)
        self.slider_webp_quality.setValue(90)
        v.addWidget(self.slider_webp_quality)
        self.chk_webp_transparency = QCheckBox(self.tr("Mantener transparencia"), page)
        self.chk_webp_transparency.setChecked(True)
        v.addWidget(self.chk_webp_transparency)
        self.chk_webp_metadata = QCheckBox(self.tr("Guardar metadatos EXIF"), page)
        v.addWidget(self.chk_webp_metadata)
        return page

    def _on_webp_lossless_toggled(self, checked: bool):
        self.lbl_webp_quality.setVisible(not checked)
        self.slider_webp_quality.setVisible(not checked)

    def _build_avif_page(self, parent) -> QWidget:
        page = QWidget(parent)
        v = QVBoxLayout(page)
        v.addWidget(QLabel(self.tr("Calidad:"), page))
        self.slider_avif_quality = QSlider(Qt.Horizontal, page)
        self.slider_avif_quality.setRange(1, 100)
        self.slider_avif_quality.setValue(80)
        v.addWidget(self.slider_avif_quality)
        return page

    def _build_tiff_page(self, parent) -> QWidget:
        page = QWidget(parent)
        v = QVBoxLayout(page)
        v.addWidget(QLabel(self.tr("Compresión:"), page))
        self.combo_tiff_compression = AutoPopupComboBox(page)
        self._setup_fixed_combo(self.combo_tiff_compression)
        for opt in TIFF_COMPRESSION_OPTIONS:
            self.combo_tiff_compression.addItem(opt, opt)
        self.combo_tiff_compression.setCurrentIndex(1)  # LZW (Recomendada)
        v.addWidget(self.combo_tiff_compression)
        self.chk_tiff_transparency = QCheckBox(self.tr("Mantener transparencia"), page)
        self.chk_tiff_transparency.setChecked(True)
        v.addWidget(self.chk_tiff_transparency)
        return page

    def _build_ico_page(self, parent) -> QWidget:
        page = QWidget(parent)
        v = QVBoxLayout(page)
        v.addWidget(QLabel(self.tr("Tamaños a incluir:"), page))
        for size in ICO_SIZES:
            chk = QCheckBox(f"{size}×{size}", page)
            chk.setChecked(size in ICO_DEFAULT_SIZES)
            chk.toggled.connect(self._emit_validity)
            v.addWidget(chk)
            self._ico_checkboxes[size] = chk
        return page

    def _build_bmp_page(self, parent) -> QWidget:
        page = QWidget(parent)
        v = QVBoxLayout(page)
        self.chk_bmp_rle = QCheckBox(self.tr("Comprimir (RLE)"), page)
        v.addWidget(self.chk_bmp_rle)
        return page

    def _on_format_changed(self, *_args):
        fmt = self.combo_format.currentData() or "No Convertir"
        self.format_stack.setCurrentIndex(self._format_page_index.get(fmt, 0))
        self._emit_validity()

    def _emit_validity(self, *_args):
        self.validity_changed.emit(self.is_valid())

    # ─── API pública ─────────────────────────────────────────────

    def is_valid(self) -> bool:
        if self.combo_format.currentData() == "ICO":
            return any(chk.isChecked() for chk in self._ico_checkboxes.values())
        return True

    def get_status(self) -> tuple[bool, str]:
        if self.is_valid():
            return True, self.tr("Convertir")
        return False, self.tr("Elegí al menos un tamaño de ícono.")

    def get_settings(self) -> dict:
        """No incluye resize_*/interpolation_method -- eso lo aporta
        ResizePopoverContent.get_settings() (ver resize_popover.py); quien dispare
        la conversión combina ambos dicts (ver ImageToolsTab._on_convert_clicked)."""
        fmt = self.combo_format.currentData() or "No Convertir"
        settings = {"format": fmt}
        settings.update(default_options_for_format(fmt))

        settings["output_folder"] = self.entry_output_folder.text().strip()
        settings["conflict_policy"] = self.combo_conflict_policy.currentData() or "conservar"

        if fmt == "PNG":
            settings["png_transparency"] = self.chk_png_transparency.isChecked()
            settings["png_compression"] = self.slider_png_compression.value()
        elif fmt == "JPG":
            settings["jpg_quality"] = self.slider_jpg_quality.value()
            settings["jpg_subsampling"] = self.combo_jpg_subsampling.currentData()
            settings["jpg_progressive"] = self.chk_jpg_progressive.isChecked()
        elif fmt == "WEBP":
            settings["webp_lossless"] = self.chk_webp_lossless.isChecked()
            settings["webp_quality"] = self.slider_webp_quality.value()
            settings["webp_transparency"] = self.chk_webp_transparency.isChecked()
            settings["webp_metadata"] = self.chk_webp_metadata.isChecked()
        elif fmt == "AVIF":
            settings["avif_quality"] = self.slider_avif_quality.value()
        elif fmt == "TIFF":
            settings["tiff_compression"] = self.combo_tiff_compression.currentData()
            settings["tiff_transparency"] = self.chk_tiff_transparency.isChecked()
        elif fmt == "ICO":
            settings["ico_sizes"] = {size: chk.isChecked() for size, chk in self._ico_checkboxes.items()}
        elif fmt == "BMP":
            settings["bmp_rle"] = self.chk_bmp_rle.isChecked()

        return settings
