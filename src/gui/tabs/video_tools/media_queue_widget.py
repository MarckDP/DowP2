# src/gui/tabs/video_tools/media_queue_widget.py
import os
import mimetypes
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
    QLabel,
    QFrame,
    QAbstractItemView,
    QMenu,
    QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QSize, QUrl
from PySide6.QtGui import QIcon, QDragEnterEvent, QDropEvent

from gui.styles import get_theme_token
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
from core.tabs.editing_media.thumbnail_cache_manager import ThumbnailCacheManager
from core.tabs.editing_media.waveform_cache_manager import WaveformCacheManager
from core.logger.logger_manager import logger


def _accent_rgba(alpha: int) -> str:
    """Convierte el color de acento del tema a 'rgba(r,g,b,a)', igual que en el Gestor de
    Medios (editing_media_view.py), para fondos de hover/selección con buen contraste."""
    from PySide6.QtGui import QColor
    color = QColor(get_theme_token('acento_primario', '#B9E640'))
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a", ".opus", ".wma"}
SUPPORTED_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

# Mismos colores que usa el Gestor de Medios (media_model.py) para estos íconos.
_VIDEO_ICON_COLOR = "#9b59b6"
_AUDIO_ICON_COLOR = "#3498db"
_ROW_THUMB_SIZE = 18  # px, cuadrado (miniatura de video)
_ROW_WAVEFORM_SIZE = QSize(32, 18)  # icono de waveform rápida (audio)

class MediaQueueWidget(QFrame):
    """
    Widget de la cola de archivos multimedia (Columna Izquierda / Master).
    Permite importar archivos por Drag and Drop o explorador, mostrando
    metadatos detallados y sincronizando la seleccion con la vista previa.
    """
    file_selected = Signal(str)  # Emite la ruta del archivo seleccionado
    queue_updated = Signal(int) # Emite la cantidad de archivos en cola

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mediaQueueWidget")
        self.setAcceptDrops(True)
        self.files_list = []
        self._items_by_path = {}
        self._icon_cache = {}
        self._init_ui()

        ThumbnailCacheManager.get_instance().thumbnail_loaded.connect(self._on_thumbnail_loaded)
        WaveformCacheManager.get_instance().waveform_loaded.connect(self._on_waveform_icon_loaded)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Estilo del contenedor
        bg_color = get_theme_token('fondo_secundario', '#1e1e1e')
        border_color = get_theme_token('borde_normal', '#2d2d2d')
        self.setStyleSheet(f"""
            QFrame#mediaQueueWidget {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 8px;
            }}
        """)

        # Cabecera de la Cola
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(4, 2, 4, 2)
        
        self.lbl_title = QLabel(self.tr("Cola de Archivos Multimedia"))
        self.lbl_title.setStyleSheet("font-weight: bold; font-size: 13px;")
        
        self.lbl_count = QLabel(self.tr("0 archivos"))
        self.lbl_count.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#888888')}; font-size: 11px;")
        
        header_layout.addWidget(self.lbl_title)
        header_layout.addStretch()
        header_layout.addWidget(self.lbl_count)
        layout.addLayout(header_layout)

        # Barra de Botones de Importación
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        self.btn_add_files = QPushButton(self.tr("Agregar Archivos"))
        self.btn_add_files.setCursor(Qt.PointingHandCursor)
        self.btn_add_files.clicked.connect(self._on_add_files_clicked)

        self.btn_add_folder = QPushButton(self.tr("Agregar Carpeta"))
        self.btn_add_folder.setCursor(Qt.PointingHandCursor)
        self.btn_add_folder.clicked.connect(self._on_add_folder_clicked)

        self.btn_clear = QPushButton(self.tr("Limpiar Todo"))
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.clicked.connect(self.clear_queue)

        btn_layout.addWidget(self.btn_add_files)
        btn_layout.addWidget(self.btn_add_folder)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_clear)
        layout.addLayout(btn_layout)

        # Árbol de Archivos (QTreeWidget) — mismo estilo visual que la lista de medios en
        # "modo lista" del Gestor de Medios (QTreeView#mediaTableWidget en editing_media_view.py).
        self.tree = QTreeWidget()
        self.tree.setObjectName("mediaQueueTree")
        self.tree.setHeaderLabels([
            self.tr("Nombre"),
            self.tr("Tipo"),
            self.tr("Tamaño"),
            self.tr("Estado")
        ])
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setAlternatingRowColors(True)
        self.tree.setIconSize(QSize(32, 18))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)

        self.tree.setStyleSheet(f"""
            QTreeWidget#mediaQueueTree {{
                background-color: {get_theme_token('fondo_principal', '#0a0a0a')};
                border: 1px solid {border_color};
                padding: 0px;
                color: {get_theme_token('texto_principal', '#cdd6f4')};
                font-size: 12px;
                alternate-background-color: {get_theme_token('fondo_secundario', '#121212')};
                outline: none;
            }}
            QTreeWidget#mediaQueueTree::item {{
                padding: 4px 8px;
                border-bottom: 1px solid {get_theme_token('borde_normal', '#1f1f23')};
                color: {get_theme_token('texto_principal', '#cdd6f4')};
            }}
            QTreeWidget#mediaQueueTree::item:hover {{
                background-color: {_accent_rgba(22)};
            }}
            QTreeWidget#mediaQueueTree::item:selected {{
                background-color: {_accent_rgba(60)};
                border-top: 1px solid {get_theme_token('acento_primario', '#B9E640')};
                border-bottom: 1px solid {get_theme_token('acento_primario', '#B9E640')};
                color: {get_theme_token('acento_primario', '#B9E640')};
                font-weight: bold;
            }}
            QHeaderView::section {{
                background-color: {get_theme_token('fondo_elemento', '#1c1c1e')};
                color: {get_theme_token('texto_secundario', '#a6adc8')};
                padding: 6px 8px;
                border: none;
                border-right: 1px solid {border_color};
                border-bottom: 1px solid {get_theme_token('acento_primario', '#B9E640')};
                font-weight: bold;
                font-size: 11px;
                text-transform: uppercase;
            }}
            QHeaderView::section:hover {{
                background-color: {get_theme_token('seleccion_fondo', '#2d2d2d')};
                color: {get_theme_token('acento_primario', '#B9E640')};
            }}
        """)

        # Configurar cabeceras
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)

        layout.addWidget(self.tree, 1)

        # Mensaje de arrastre (Drop zone visual)
        self.lbl_drop_hint = QLabel(self.tr("Arrastra archivos de vídeo o audio aquí"))
        self.lbl_drop_hint.setAlignment(Qt.AlignCenter)
        self.lbl_drop_hint.setStyleSheet(f"""
            color: {get_theme_token('texto_secundario', '#888888')};
            border: 1px dashed {border_color};
            border-radius: 6px;
            padding: 8px;
            font-size: 11px;
        """)
        layout.addWidget(self.lbl_drop_hint)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        paths = [url.toLocalFile() for url in urls if url.isLocalFile()]
        valid_paths = []
        for p in paths:
            if os.path.isdir(p):
                for root, _, files in os.walk(p):
                    for f in files:
                        ext = os.path.splitext(f)[1].lower()
                        if ext in SUPPORTED_EXTENSIONS:
                            valid_paths.append(os.path.join(root, f))
            else:
                ext = os.path.splitext(p)[1].lower()
                if ext in SUPPORTED_EXTENSIONS:
                    valid_paths.append(p)

        if valid_paths:
            self.add_files(valid_paths)
            event.acceptProposedAction()

    def _on_add_files_clicked(self):
        from PySide6.QtWidgets import QFileDialog
        filter_str = "Archivos Multimedia (*.mp4 *.mkv *.mov *.avi *.webm *.mp3 *.wav *.aac *.flac *.ogg);;Todos los archivos (*.*)"
        files, _ = QFileDialog.getOpenFileNames(self, self.tr("Seleccionar Archivos Multimedia"), "", filter_str)
        if files:
            self.add_files(files)

    def _on_add_folder_clicked(self):
        from PySide6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self, self.tr("Seleccionar Carpeta con Medios"))
        if folder:
            valid_paths = []
            for root, _, files in os.walk(folder):
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        valid_paths.append(os.path.join(root, f))
            if valid_paths:
                self.add_files(valid_paths)

    def add_files(self, paths):
        for p in paths:
            if p in self.files_list:
                continue
            self.files_list.append(p)

            filename = os.path.basename(p)
            ext_lower = os.path.splitext(p)[1].lower()
            ext = ext_lower.upper().replace(".", "")
            media_type = "audio" if ext_lower in AUDIO_EXTENSIONS else "video"

            try:
                size_mb = os.path.getsize(p) / (1024 * 1024)
                size_str = f"{size_mb:.1f} MB"
            except Exception:
                size_str = "N/A"

            item = QTreeWidgetItem(self.tree)
            item.setText(0, filename)
            item.setText(1, ext)
            item.setText(2, size_str)
            item.setText(3, self.tr("Pendiente"))
            item.setData(0, Qt.UserRole, p)
            item.setIcon(0, self._get_icon_for_file(p, media_type))

            self._items_by_path[p] = item

        self._update_counter()
        if self.tree.topLevelItemCount() > 0 and not self.tree.selectedItems():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def clear_queue(self):
        self.files_list.clear()
        self.tree.clear()
        self._items_by_path.clear()
        self._update_counter()
        self.file_selected.emit("")

    def remove_selected(self):
        selected = self.tree.selectedItems()
        for item in selected:
            path = item.data(0, Qt.UserRole)
            if path in self.files_list:
                self.files_list.remove(path)
            self._items_by_path.pop(path, None)
            index = self.tree.indexOfTopLevelItem(item)
            self.tree.takeTopLevelItem(index)
        self._update_counter()

    def _fallback_icon(self, svg_name: str, color: str, size: int = 18):
        key = (svg_name, color, size)
        if key not in self._icon_cache:
            self._icon_cache[key] = get_colored_svg_icon(svg_name, color, size=size)
        return self._icon_cache[key]

    def _get_icon_for_file(self, path: str, media_type: str):
        """Ícono por defecto de la fila: nota musical (audio) / claqueta (video) como
        placeholder inmediato, sustituido por una miniatura real o una waveform rápida en
        cuanto termina de generarse en segundo plano (igual que en el Gestor de Medios)."""
        if media_type == "audio":
            wf_mgr = WaveformCacheManager.get_instance()
            cached = wf_mgr.get_cached_qicon(path, _ROW_WAVEFORM_SIZE)
            if cached is not None:
                return cached
            wf_mgr.request_waveform(path, size=_ROW_WAVEFORM_SIZE)
            return self._fallback_icon("music_note.svg", _AUDIO_ICON_COLOR)

        thumb_mgr = ThumbnailCacheManager.get_instance()
        cached = thumb_mgr.get_cached_qicon(path, _ROW_THUMB_SIZE)
        if cached is not None:
            return cached
        thumb_mgr.request_thumbnail(path, "video", _ROW_THUMB_SIZE)
        return self._fallback_icon("movie.svg", _VIDEO_ICON_COLOR)

    def _on_thumbnail_loaded(self, file_path: str, thumbnail_path: str):
        item = self._items_by_path.get(file_path)
        if item is None:
            return
        icon = ThumbnailCacheManager.get_instance().get_cached_qicon(file_path, _ROW_THUMB_SIZE)
        if icon is not None:
            item.setIcon(0, icon)

    def _on_waveform_icon_loaded(self, file_path: str, peaks: list):
        item = self._items_by_path.get(file_path)
        if item is None:
            return
        icon = WaveformCacheManager.get_instance().get_cached_qicon(file_path, _ROW_WAVEFORM_SIZE)
        if icon is not None:
            item.setIcon(0, icon)

    def get_all_filepaths(self):
        return list(self.files_list)

    def _update_counter(self):
        count = len(self.files_list)
        self.lbl_count.setText(f"{count} {self.tr('archivos')}")
        self.queue_updated.emit(count)
        self.lbl_drop_hint.setVisible(count == 0)

    def _on_selection_changed(self):
        selected = self.tree.selectedItems()
        if selected:
            filepath = selected[0].data(0, Qt.UserRole)
            self.file_selected.emit(filepath)
        else:
            self.file_selected.emit("")

    def _show_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        action_remove = menu.addAction(self.tr("Eliminar de la cola"))
        action_open_loc = menu.addAction(self.tr("Abrir ubicación del archivo"))
        
        action = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if action == action_remove:
            self.remove_selected()
        elif action == action_open_loc:
            path = item.data(0, Qt.UserRole)
            if path and os.path.exists(path):
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
