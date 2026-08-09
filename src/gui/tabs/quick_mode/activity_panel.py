# src/gui/tabs/quick_mode/activity_panel.py
import os
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QPushButton,
)
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QIcon

from gui.styles import get_theme_token
from gui.tabs.quick_mode.download_row import QuickDownloadRow


class ActivityPanel(QFrame):
    """Panel de Actividad de Descargas con barra de scroll y lista de tarjetas."""
    row_close_requested = Signal(object)      # Emitido cuando una fila de descarga solicita cerrarse
    row_reveal_requested = Signal(object)     # Emitido cuando una fila solicita abrir carpeta
    clear_all_requested = Signal()            # Emitido cuando se hace clic en limpiar todo

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("activityPanel")
        self.item_rows = []
        self.item_keys = []
        self.current_item_pos = 0
        self.completed_items = 0
        self.init_ui()

    def init_ui(self):
        # Aplicar el estilo de caja redondeada
        self.setAttribute(Qt.WA_StyledBackground, True)
        borde_color = get_theme_token('borde_normal', '#2d2d2d')
        fondo_color = get_theme_token('fondo_secundario', '#1e1e1e')
        self.setStyleSheet(f"""
            QFrame#activityPanel {{
                background-color: {fondo_color};
                border: 1px solid {borde_color};
                border-radius: 12px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # Barra de encabezado con título y botón "Limpiar todo"
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)
        
        self.lbl_title = QLabel(self.tr("Lista de descargas") if hasattr(self, "tr") else "Lista de descargas")
        self.lbl_title.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#888888')}; font-size: 11px; font-weight: bold;")
        header_layout.addWidget(self.lbl_title)
        
        header_layout.addStretch(1)

        icon_dir = os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "assets", "icons", "svg"
        ))
        self.btn_clear_all = QPushButton(self.tr("Limpiar") if hasattr(self, "tr") else "Limpiar")
        self.btn_clear_all.setFixedHeight(22)
        self.btn_clear_all.setToolTip(self.tr("Cancelar descargas activas y limpiar la lista") if hasattr(self, "tr") else "Cancelar descargas y limpiar")
        _delete_icon = os.path.join(icon_dir, "delete.svg")
        if os.path.exists(_delete_icon):
            self.btn_clear_all.setIcon(QIcon(_delete_icon))
            self.btn_clear_all.setIconSize(QSize(14, 14))
        self.btn_clear_all.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {get_theme_token('texto_secundario', '#888888')};
                border: 1px solid {get_theme_token('borde', '#2d2d2d')};
                border-radius: 6px;
                padding: 2px 10px;
                font-size: 10px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('fondo_hover', '#2a2a2a')};
                color: #ff6b6b;
                border-color: #ff6b6b;
            }}
        """)
        self.btn_clear_all.clicked.connect(self.clear_all_requested.emit)
        # El botón siempre estará visible a petición del usuario
        header_layout.addWidget(self.btn_clear_all)
        layout.addLayout(header_layout)
        
        # Línea separadora sutil
        self.header_line = QFrame()
        self.header_line.setFrameShape(QFrame.HLine)
        self.header_line.setFrameShadow(QFrame.Sunken)
        self.header_line.setStyleSheet(f"background-color: {get_theme_token('borde_normal', '#2d2d2d')};")
        self.header_line.setFixedHeight(1)
        layout.addWidget(self.header_line)

        # ScrollArea
        self.activity_scroll = QScrollArea()
        self.activity_scroll.setWidgetResizable(True)
        self.activity_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.activity_scroll.setStyleSheet("border: none; background: transparent;")

        self.activity_container = QWidget()
        self.activity_layout = QVBoxLayout(self.activity_container)
        self.activity_layout.setContentsMargins(0, 0, 0, 0)
        self.activity_layout.setSpacing(8)
        
        # Etiqueta de placeholder cuando no hay descargas
        self.empty_lbl = QLabel(self.tr("Aquí aparecerán tus descargas") if hasattr(self, "tr") else "Aquí aparecerán tus descargas")
        self.empty_lbl.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#888888')}; font-size: 11px;")
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        self.activity_layout.addWidget(self.empty_lbl)
        
        self.activity_layout.addStretch(1)
        self.activity_scroll.setWidget(self.activity_container)
        layout.addWidget(self.activity_scroll, 1)

    def add_activity_rows(self, entries, selected_indices):
        self.empty_lbl.hide()
        self.btn_clear_all.show()
        
        new_rows = []
        new_keys = []

        for idx, entry in enumerate(entries):
            title = entry.get("title") or entry.get("id") or entry.get("url") or (self.tr(f"Item {idx + 1}") if hasattr(self, "tr") else f"Item {idx + 1}")
            playlist_idx = entry.get("playlist_index") or (selected_indices[idx] + 1 if idx < len(selected_indices) else idx + 1)
            new_keys.append(playlist_idx)
            
            row = QuickDownloadRow(str(title), self.activity_container)
            row.update_metadata_from_dict(entry)
            row.close_requested.connect(self.row_close_requested.emit)
            row.reveal_requested.connect(self.row_reveal_requested.emit)
            
            self.activity_layout.insertWidget(self.activity_layout.count() - 1, row)
            self.item_rows.append(row)
            new_rows.append(row)

        if new_rows:
            new_rows[0].update_progress(0, status=self.tr("Preparando") if hasattr(self, "tr") else "Preparando")
            
        return new_rows, new_keys

    def clear_activity_rows(self):
        for row in self.item_rows:
            if hasattr(row, "destroy_row"):
                row.destroy_row()
            self.activity_layout.removeWidget(row)
            row.deleteLater()
        self.item_rows = []
        self.item_keys = []
        self.current_item_pos = 0
        self.completed_items = 0
        self.empty_lbl.show()
        self.btn_clear_all.hide()

    def remove_row(self, row):
        if row not in self.item_rows:
            return
        idx = self.item_rows.index(row)
        self.item_rows.pop(idx)
        row.destroy_row()
        self.activity_layout.removeWidget(row)
        row.deleteLater()
        
        if not self.item_rows:
            self.empty_lbl.show()
