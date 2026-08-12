# src/gui/tabs/quick_mode/quick_mode_view.py
import os
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon

from gui.styles import get_theme_token, apply_cut_button_style
from gui.tabs.advanced_process.output_options import OutputOptionsWidget
from gui.tabs.advanced_process.video_details_components import RichComboBox, RichTextDelegate
from gui.widgets.animated_button import AnimatedButton

from gui.tabs.quick_mode.activity_panel import ActivityPanel
from gui.tabs.quick_mode.download_controller import QuickDownloadController
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
from core.logger.logger_manager import logger
from core.tabs.quick_mode.quick_mode_logic import reveal_in_file_manager


class QuickModeTab(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()
        
        # Inicializar el controlador
        self.controller = QuickDownloadController(self)
        
        # Conectar señales del controlador
        self.controller.busy_state_changed.connect(self._set_busy)
        self.controller.controls_state_changed.connect(self._set_controls_enabled)
        self.controller.download_text_changed.connect(self._set_download_text)
        self.controller.progress_updated.connect(self.output_options.set_progress)

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(15, 10, 15, 10)
        self.main_layout.setSpacing(8)

        self.url_panel = self._build_url_panel()
        self.options_panel = self._build_options_panel()
        
        # Instanciar el nuevo panel de actividad refactorizado
        self.activity_panel = ActivityPanel(self)
        self.activity_panel.row_close_requested.connect(self._on_row_close_requested)
        self.activity_panel.row_reveal_requested.connect(self._on_row_reveal_requested)
        self.activity_panel.cancel_all_requested.connect(self._on_cancel_all_clicked)
        self.activity_panel.clear_all_requested.connect(self._on_clear_all_clicked)

        self.output_options = OutputOptionsWidget()

        self.main_layout.addWidget(self.url_panel)
        self.main_layout.addWidget(self.options_panel)
        self.main_layout.addWidget(self.activity_panel, 1)
        self.main_layout.addWidget(self.output_options)

        self.options_panel.setAttribute(Qt.WA_StyledBackground, True)
        
        borde_color = get_theme_token('borde_normal', '#2d2d2d')
        fondo_color = get_theme_token('fondo_secundario', '#1e1e1e')
        box_style = f"""
            QFrame#analysisOptionsBar {{
                background-color: {fondo_color};
                border: 1px solid {borde_color};
                border-radius: 12px;
            }}
        """
        self.options_panel.setStyleSheet(box_style)

        # En Modo Rápido el botón "Descargar" junto a la URL ya dispara la descarga:
        # el botón de descarga duplicado dentro de "Opciones de Salida" es innecesario aquí.
        self.output_options.btn_start_download.setVisible(False)

        self.output_options.btn_open_output_path.clicked.disconnect()
        self.output_options.btn_open_output_path.clicked.connect(self._on_open_output_path_clicked)

        self._on_mode_changed(self.mode_combo.currentIndex())

    def _build_url_panel(self):
        panel = QWidget()
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(self.tr("Pega una URL para descargar directamente"))
        self.url_input.returnPressed.connect(self._on_download_clicked)
        self.url_input.textEdited.connect(self._on_text_edited)

        # Registrar el campo de URL en el monitor de portapapeles
        from core.utils.clipboard_monitor import ClipboardURLMonitor
        monitor = ClipboardURLMonitor.instance()
        monitor.register(self.url_input)
        monitor.url_detected.connect(self._on_clipboard_url_detected)

        # Botón circular conmutable para activar el recorte de fragmentos
        self.btn_cut = QPushButton()
        self.btn_cut.setCheckable(True)
        self.btn_cut.setFixedSize(34, 34)
        self.btn_cut.setToolTip(self.tr("Activar recorte de fragmento"))
        
        self.btn_cut.setIconSize(QSize(18, 18))
        self.btn_cut.toggled.connect(self._on_cut_toggled)
        apply_cut_button_style(self.btn_cut, "normal", icon_size=18)

        self.btn_download = AnimatedButton(self.tr("Descargar"))
        self.btn_download.setObjectName("analyzeButton")
        self.btn_download.setFixedWidth(120)
        self.btn_download.clicked.connect(self._on_download_clicked)

        layout.addWidget(QLabel(self.tr("URL:")))
        layout.addWidget(self.url_input, 1)
        layout.addWidget(self.btn_cut)
        layout.addWidget(self.btn_download)
        return panel

    def _build_options_panel(self):
        panel = QFrame()
        panel.setObjectName("analysisOptionsBar")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(15, 6, 15, 6)
        layout.setSpacing(12)

        layout.addWidget(QLabel(self.tr("Modo:")))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem(self.tr("Video + Audio"), "video+audio")
        self.mode_combo.addItem(self.tr("Solo Audio"), "audio_only")
        self.mode_combo.addItem(self.tr("Solo Video"), "video_only")
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        layout.addWidget(self.mode_combo)

        layout.addWidget(QLabel(self.tr("Calidad:")))
        self.quality_combo = RichComboBox()
        self.quality_combo.setItemDelegate(RichTextDelegate())
        layout.addWidget(self.quality_combo)

        self.chk_playlist_selector = QCheckBox(self.tr("Seleccionar playlist"))
        self.chk_playlist_selector.toggled.connect(self._on_playlist_selector_toggled)
        layout.addWidget(self.chk_playlist_selector)

        self.chk_thumb_file = QCheckBox(self.tr("Guardar miniatura"))
        layout.addWidget(self.chk_thumb_file)

        self.chk_thumb_only = QCheckBox(self.tr("Solo miniatura"))
        self.chk_thumb_only.toggled.connect(self._on_thumbnail_only_toggled)
        layout.addWidget(self.chk_thumb_only)

        layout.addStretch(1)
        return panel

    def _on_mode_changed(self, index):
        mode = self.mode_combo.itemData(index) or "video+audio"
        current = self.quality_combo.currentData()
        self.quality_combo.clear()

        self.quality_combo.addItem(self.tr("Mejor compatible") + " ✨", "best_compatible")
        self.quality_combo.addItem(self.tr("Máxima calidad"), "best")
        if mode != "audio_only":
            self.quality_combo.addItem("4K (2160p)", "2160")
            self.quality_combo.addItem("2K (1440p)", "1440")
            self.quality_combo.addItem("1080p", "1080")
            self.quality_combo.addItem("720p", "720")
            self.quality_combo.addItem("480p", "480")
            self.quality_combo.addItem("360p", "360")
        else:
            self.quality_combo.addItem(self.tr("Alta"), "320")
            self.quality_combo.addItem(self.tr("Media"), "192")
            self.quality_combo.addItem(self.tr("Baja"), "128")

        if current:
            idx = self.quality_combo.findData(current)
            if idx >= 0:
                self.quality_combo.setCurrentIndex(idx)

    def _on_thumbnail_only_toggled(self, checked):
        self.mode_combo.setEnabled(not checked)
        self.quality_combo.setEnabled(not checked)
        self.chk_thumb_file.setEnabled(not checked)

    def _on_playlist_selector_toggled(self, checked):
        """Cuando playlist está activa, deshabilitar y desactivar el corte de fragmento."""
        if checked:
            self.btn_cut.setChecked(False)
            self.btn_cut.setEnabled(False)
        else:
            self.btn_cut.setEnabled(True)

    def _on_download_clicked(self):
        url = self.url_input.text().strip()
        if not url:
            return

        # Delegar la descarga al controlador
        self.controller.start_download_flow(
            url=url,
            mode=self.mode_combo.currentData() or "video+audio",
            quality=self.quality_combo.currentData() or "best_compatible",
            output_path=self.output_options.output_path_input.text(),
            speed_limit_val=self.output_options.speed_limit_input.value(),
            chk_thumb_file_checked=self.chk_thumb_file.isChecked(),
            chk_thumb_only_checked=self.chk_thumb_only.isChecked(),
            btn_cut_checked=self.btn_cut.isChecked(),
            chk_playlist_selector_checked=self.chk_playlist_selector.isChecked()
        )
        self.url_input.clear()

    def _on_open_output_path_clicked(self):
        path = self.output_options.output_path_input.text().strip()
        if not path:
            return
        if self.controller.last_downloaded_filepath and os.path.exists(self.controller.last_downloaded_filepath):
            reveal_in_file_manager(self.controller.last_downloaded_filepath)
            return

        if os.path.exists(path):
            if os.name == "nt":
                os.startfile(path if os.path.isdir(path) else os.path.dirname(path))
            else:
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl.fromLocalFile(path if os.path.isdir(path) else os.path.dirname(path)))

    def _on_row_close_requested(self, row):
        """Quitar un item de la lista. Si estaba descargándose activamente, cancela."""
        if row not in self.activity_panel.item_rows:
            return
            
        if row in self.controller.current_item_rows:
            idx = self.controller.current_item_rows.index(row)
            self.controller.current_item_rows.pop(idx)
            if idx < len(self.controller.current_item_keys):
                self.controller.current_item_keys.pop(idx)
                
            if self.controller.is_downloading and not self.controller.current_item_rows:
                self.controller.cancel_download()
                
        self.activity_panel.remove_row(row)

    def _on_row_reveal_requested(self, row):
        """Abrir el gestor de archivos y seleccionar el archivo descargado."""
        if row.downloaded_filepath and os.path.exists(row.downloaded_filepath):
            reveal_in_file_manager(row.downloaded_filepath)

    def _on_cancel_all_clicked(self):
        """Cancelar descargas activas en curso."""
        if self.controller.is_downloading:
            self.controller.cancel_download()

    def _on_clear_all_clicked(self):
        """Cancelar descargas activas y limpiar toda la lista."""
        if self.controller.is_downloading:
            self.controller.cancel_download()
        self.activity_panel.clear_activity_rows()

    def _set_busy(self, busy, message=None):
        self._set_controls_enabled(not busy)
        self._set_download_text(self.tr("Analizando...") if busy else self.tr("Descargar"))
        if message:
            self.output_options.set_progress(0, message, "running" if busy else "wait")

    def _set_controls_enabled(self, enabled):
        # El campo de URL y el botón de descarga siempre se mantienen habilitados para permitir encolar/añadir
        self.url_input.setEnabled(True)
        self.btn_download.setEnabled(enabled or self.controller.is_downloading)
        self.options_panel.setEnabled(enabled)
        self.output_options.output_path_input.setEnabled(enabled)
        self.output_options.btn_select_output_path.setEnabled(enabled)
        self.output_options.speed_limit_input.setEnabled(enabled)
        
        # btn_cut: solo habilitar si playlist_selector no está activo
        if enabled:
            self.btn_cut.setEnabled(not self.chk_playlist_selector.isChecked())
        else:
            self.btn_cut.setEnabled(False)

    def _set_download_text(self, text):
        self.btn_download.setText(text)

    def _on_clipboard_url_detected(self, url):
        """Llamado cuando el monitor de portapapeles pega una URL en nuestro campo."""
        if self.url_input.text().strip() != url:
            return
        if self.controller.is_downloading:
            return
        from core.utils.config_manager import get_config
        if get_config().get("auto_analyze", False):
            logger.info("QuickModeTab: Auto-inicio por pegado automático de URL")
            self._on_download_clicked()

    def _on_text_edited(self, text):
        """Llamado cuando el usuario edita el texto manualmente (incluyendo pegar)."""
        url = text.strip()
        if not url:
            return
        if self.controller.is_downloading:
            return
            
        from core.utils.config_manager import get_config
        if not get_config().get("auto_analyze", False):
            return
            
        if not url.startswith(("http://", "https://")):
            return
            
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        if clipboard:
            clip_text = clipboard.text().strip()
            if url == clip_text:
                logger.info("QuickModeTab: Detección de pegado manual. Iniciando descarga...")
                self._on_download_clicked()

    def _on_cut_toggled(self, checked: bool):
        status = "saved" if checked else "normal"
        apply_cut_button_style(self.btn_cut, status, icon_size=18)
