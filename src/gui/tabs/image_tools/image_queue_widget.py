# src/gui/tabs/image_tools/image_queue_widget.py
import os
from PySide6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
    QLabel,
    QFrame,
    QAbstractItemView,
    QMenu,
)
from PySide6.QtCore import Qt, Signal, QSize, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent

from gui.styles import get_theme_token, create_colored_circle_icon
from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
from core.tabs.editing_media.thumbnail_cache_manager import ThumbnailCacheManager
from core.tabs.editing_media.editing_media_logic import VALID_IMAGE_EXTS, VALID_VECTOR_EXTS
from core.logger.logger_manager import logger

# Copia adaptada de gui/tabs/video_tools/media_queue_widget.py::MediaQueueWidget (misma
# estructura/estilo tal cual pidió el usuario) -- sin lo específico de video/audio
# (waveforms, distinción video/audio) y con el set de extensiones de imagen que ya
# soporta el Gestor de Medios (raster + RAW + vectoriales, ver editing_media_logic.py).

_STATUS_COLOR_MAP = {
    "completado (": "estado_aviso",
    "pendiente": "estado_espera",
    "en cola": "estado_espera",
    "procesando": "estado_aviso",
    "completado": "estado_exito",
    "finalizado": "estado_exito",
    "error": "estado_error",
    "cancelado": "estado_espera",
}

def _get_status_icon(status_text: str):
    clean = (status_text or "").lower().strip()
    token_key = "estado_espera"
    for key, token in _STATUS_COLOR_MAP.items():
        if key in clean:
            token_key = token
            break
    color = get_theme_token(token_key, "#888888")
    return create_colored_circle_icon(color, size=10)


def _accent_rgba(alpha: int) -> str:
    from PySide6.QtGui import QColor
    color = QColor(get_theme_token('acento_primario', '#B9E640'))
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"

SUPPORTED_EXTENSIONS = VALID_IMAGE_EXTS | VALID_VECTOR_EXTS

# Mismo color que usa el Gestor de Medios (media_model.py) para el ícono de "imagen".
_IMAGE_ICON_COLOR = "#2ecc71"
_ROW_THUMB_SIZE = 18  # px, cuadrado

class ImageQueueWidget(QFrame):
    """
    Cola de archivos de imagen (panel izquierdo del Editor de Imagen). Permite
    importar por Drag and Drop o explorador, sincronizando la selección con la
    vista previa. Misma estructura visual que MediaQueueWidget (Herramientas de
    Video), adaptada a imágenes.
    """
    file_selected = Signal(str)  # Emite la ruta del archivo seleccionado
    queue_updated = Signal(int)  # Emite la cantidad de archivos en cola

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("imageQueueWidget")
        self.setAcceptDrops(True)
        self.files_list = []
        self._items_by_path = {}
        self._icon_cache = {}
        self._init_ui()

        ThumbnailCacheManager.get_instance().thumbnail_loaded.connect(self._on_thumbnail_loaded)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        bg_color = get_theme_token('fondo_secundario', '#1e1e1e')
        border_color = get_theme_token('borde_normal', '#2d2d2d')
        self.setStyleSheet(f"""
            QFrame#imageQueueWidget {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
        """)

        header_grid = QGridLayout()
        header_grid.setContentsMargins(4, 2, 4, 2)

        self.lbl_title = QLabel(self.tr("Lista de Imágenes"), self)
        self.lbl_title.setObjectName("sectionTitle")
        self.lbl_title.setAlignment(Qt.AlignCenter)

        self.lbl_count = QLabel(self.tr("0 archivos"), self)
        self.lbl_count.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#888888')}; font-size: 11px;")
        self.lbl_count.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        header_grid.addWidget(self.lbl_title, 0, 0, 1, 3, Qt.AlignCenter)
        header_grid.addWidget(self.lbl_count, 0, 2, Qt.AlignRight | Qt.AlignVCenter)
        layout.addLayout(header_grid)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)

        # Etiquetas cortas a propósito: este panel es angosto (~380px, ancho fijo del
        # panel izquierdo colapsable) -- con el texto largo original ("Agregar
        # Archivos"/"Agregar Carpeta"/"Limpiar Todo") la fila de botones sola pedía
        # ~588px de ancho mínimo, más que el panel entero, disparando un scroll
        # horizontal en todo el panel (QScrollArea de CollapsiblePanel). El texto
        # completo queda en el tooltip.
        self.btn_add_files = QPushButton(self.tr("Archivos"))
        self.btn_add_files.setProperty("variant", "secondary")
        self.btn_add_files.setCursor(Qt.PointingHandCursor)
        self.btn_add_files.setToolTip(self.tr("Agregar archivos de imagen"))
        self.btn_add_files.clicked.connect(self._on_add_files_clicked)

        self.btn_add_folder = QPushButton(self.tr("Carpeta"))
        self.btn_add_folder.setProperty("variant", "secondary")
        self.btn_add_folder.setCursor(Qt.PointingHandCursor)
        self.btn_add_folder.setToolTip(self.tr("Agregar todas las imágenes de una carpeta"))
        self.btn_add_folder.clicked.connect(self._on_add_folder_clicked)

        self.btn_clear = QPushButton(self.tr("Limpiar"))
        self.btn_clear.setProperty("variant", "danger")
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.setToolTip(self.tr("Limpiar toda la lista"))
        self.btn_clear.clicked.connect(self.clear_queue)

        btn_layout.addWidget(self.btn_add_files)
        btn_layout.addWidget(self.btn_add_folder)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_clear)
        layout.addLayout(btn_layout)

        self.tree = QTreeWidget()
        self.tree.setObjectName("imageQueueTree")
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setHeaderLabels([
            self.tr("Nombre"),
            self.tr("Tipo"),
            self.tr("Tamaño"),
            self.tr("Estado")
        ])
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setAlternatingRowColors(True)
        self.tree.setIconSize(QSize(18, 18))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)

        self.tree.setStyleSheet(f"""
            QTreeWidget#imageQueueTree {{
                background-color: {get_theme_token('fondo_principal', '#0a0a0a')};
                border: 1px solid {border_color};
                padding: 0px;
                color: {get_theme_token('texto_principal', '#cdd6f4')};
                font-size: 12px;
                alternate-background-color: {get_theme_token('fondo_secundario', '#121212')};
                outline: none;
            }}
            QTreeWidget#imageQueueTree::branch {{
                background: transparent;
            }}
            QTreeWidget#imageQueueTree::item {{
                padding: 4px 8px;
                border-bottom: 1px solid {get_theme_token('borde_normal', '#1f1f23')};
                color: {get_theme_token('texto_principal', '#cdd6f4')};
            }}
            QTreeWidget#imageQueueTree::item:hover {{
                background-color: {_accent_rgba(22)};
            }}
            QTreeWidget#imageQueueTree::item:selected {{
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

        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        # Anchos por defecto más chicos que MediaQueueWidget (que asumía un panel más
        # ancho): acá el panel es angosto (~380px) -- estos igual son interactivos,
        # el usuario los puede agrandar a mano si hace falta.
        self.tree.setColumnWidth(0, 140)
        self.tree.setColumnWidth(1, 45)
        self.tree.setColumnWidth(2, 65)
        self.tree.setColumnWidth(3, 90)

        layout.addWidget(self.tree, 1)

        self.lbl_drop_hint = QLabel(self.tr("Arrastra archivos de imagen aquí"))
        self.lbl_drop_hint.setAlignment(Qt.AlignCenter)
        # Sin wrap, este texto en una sola línea pedía 370px de ancho mínimo -- más
        # que el panel angosto (~380px con margen incluido, ver comentario de los
        # botones más arriba).
        self.lbl_drop_hint.setWordWrap(True)
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
        exts_pattern = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTENSIONS))
        filter_str = f"Archivos de Imagen ({exts_pattern});;Todos los archivos (*.*)"
        files, _ = QFileDialog.getOpenFileNames(self, self.tr("Seleccionar Archivos de Imagen"), "", filter_str)
        if files:
            self.add_files(files)

    def _on_add_folder_clicked(self):
        from PySide6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self, self.tr("Seleccionar Carpeta con Imágenes"))
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
            ext = os.path.splitext(p)[1].upper().replace(".", "")

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
            item.setIcon(3, _get_status_icon("pendiente"))
            item.setData(0, Qt.UserRole, p)
            item.setIcon(0, self._get_icon_for_file(p))

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

    def _get_icon_for_file(self, path: str):
        """Ícono por defecto de la fila (placeholder inmediato), sustituido por una
        miniatura real en cuanto termina de generarse en segundo plano (igual que en
        el Gestor de Medios)."""
        thumb_mgr = ThumbnailCacheManager.get_instance()
        cached = thumb_mgr.get_cached_qicon(path, _ROW_THUMB_SIZE)
        if cached is not None:
            return cached
        thumb_mgr.request_thumbnail(path, "imagen", _ROW_THUMB_SIZE)
        return self._fallback_icon("image.svg", _IMAGE_ICON_COLOR)

    def _on_thumbnail_loaded(self, file_path: str, thumbnail_path: str):
        item = self._items_by_path.get(file_path)
        if item is None:
            return
        icon = ThumbnailCacheManager.get_instance().get_cached_qicon(file_path, _ROW_THUMB_SIZE)
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

    def update_file_status(self, filepath: str, status_text: str):
        item = self._items_by_path.get(filepath)
        if item:
            item.setText(3, status_text)
            item.setIcon(3, _get_status_icon(status_text))
