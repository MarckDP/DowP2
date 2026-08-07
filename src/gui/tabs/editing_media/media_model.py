import os
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, Signal, QSize
from PySide6.QtGui import QIcon, QColor, QFont
from core.tabs.editing_media.thumbnail_cache_manager import ThumbnailCacheManager
from gui.tabs.editing_media.editing_media_icons import (
    get_placeholder_thumbnail_icon,
    get_colored_svg_icon
)
from gui.styles import get_theme_token

class MediaTableModel(QAbstractTableModel):
    """
    Modelo de datos para la lista de medios.
    Soporta visualización tanto en QListView (IconMode) como en QTreeView (Tabla).
    """
    global_sort_requested = Signal(int, bool) # column, is_ascending

    def __init__(self, parent=None):
        super().__init__(parent)
        self._media_items = []
        self._view_mode = "grid"
        self._grid_size_hint = QSize(150, 150)
        
        # Conectar señal de miniaturas al modelo
        thumb_mgr = ThumbnailCacheManager.get_instance()
        thumb_mgr.thumbnail_loaded.connect(self._on_thumbnail_loaded)
        
        # Para caché rápido de íconos base y colores
        self._icon_cache = {}
        
        self.headers = [
            "Estado",
            "Nombre de Archivo",
            "Descripción",
            "Licencia",
            "Duración",
            "Origen",
            "Tipo de Archivo",
            "Sample Rate"
        ]

    def set_view_mode(self, mode: str, grid_size_hint: QSize = None):
        """Actualiza el modo de vista y el tamaño de la cuadrícula si aplica."""
        self._view_mode = mode
        if grid_size_hint:
            self._grid_size_hint = grid_size_hint
        
    def get_cached_icon(self, icon_name: str, color: str, size: int = None) -> QIcon:
        key = f"{icon_name}_{color}_{size}"
        if key not in self._icon_cache:
            if "placeholder" in key:
                 self._icon_cache[key] = get_placeholder_thumbnail_icon(icon_name.replace("_placeholder", ""), color)
            else:
                 self._icon_cache[key] = get_colored_svg_icon(icon_name, color, size=size if size else 18)
        return self._icon_cache[key]

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._media_items)

    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self.headers)
        
    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.headers[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()
        item = self._media_items[row]
        
        # Rol para obtener el diccionario completo
        if role == Qt.UserRole:
            return item

        tipo = item.get("tipo", "")
        file_path = item.get("ruta", "")
        is_web = item.get("es_remoto", False) or file_path.startswith("http")
        
        if role == Qt.DisplayRole:
            if self._view_mode == "grid":
                if col == 0:
                    # En modo Grid, la ListView asume que la columna 0 provee el texto y el ícono
                    if tipo == "load_more":
                        return item.get("nombre", "Mostrar todo")
                    return item.get("nombre", "")
                return None
            else:
                # Modo Tabla
                if tipo == "load_more":
                    if col == 1:
                        return item.get("nombre", "Mostrar todo")
                    return ""
                
                if col == 0: return "" # Ícono
                elif col == 1: return item.get("nombre", "")
                elif col == 2: 
                    desc = str(item.get("description", item.get("desc", "-"))).strip()
                    return desc[:117] + "..." if len(desc) > 120 else (desc if desc else "-")
                elif col == 3: return str(item.get("license", "Local")).strip() or "Local"
                elif col == 4: return str(item.get("duración", item.get("duration_str", "-"))).strip() or "-"
                elif col == 5: return str(item.get("library", "Freesound" if is_web else "Local")).strip()
                elif col == 6: 
                    file_type = item.get("file_type") or item.get("type", "")
                    if not file_type and "." in item.get("nombre", ""):
                        ext = item.get("nombre", "").split(".")[-1].upper()
                        if len(ext) <= 5: file_type = ext
                    return str(file_type).upper() if file_type else str(tipo).upper()
                elif col == 7: return str(item.get("sample_rate", item.get("samplerate", "-")))
        
        elif role == Qt.DecorationRole and col == 0:
            accent_green = get_theme_token("acento_primario", "#B9E640")
            
            if tipo == "load_more":
                if self._view_mode == "grid":
                    return None # En grid podríamos usar un ítem personalizado o fallback
                else:
                    return self.get_cached_icon("arrow_circle_down.svg", accent_green, size=18)

            # Verificar si está descargado
            is_downloaded = False
            if is_web and "dest_path" in item:
                is_downloaded = True

            if is_web and is_downloaded:
                return self.get_cached_icon("music_note.svg", accent_green, size=32 if self._view_mode=="grid" else 18)
            elif is_web:
                if self._view_mode == "grid":
                    return self.get_cached_icon("travel_explore.svg_placeholder", "#3498db")
                else:
                    return self.get_cached_icon("travel_explore.svg", "#3498db", size=18)

            # Si es local, cargar miniatura
            thumb_mgr = ThumbnailCacheManager.get_instance()
            cached_icon = thumb_mgr.get_cached_qicon(file_path)
            
            if cached_icon:
                return cached_icon
            else:
                # Solicitar la miniatura de forma asíncrona
                thumb_mgr.request_thumbnail(file_path, tipo)
                
                # Devolver ícono por defecto mientras carga
                if self._view_mode == "grid":
                    if tipo == "video": return self.get_cached_icon("movie.svg_placeholder", "#9b59b6")
                    elif tipo == "imagen": return self.get_cached_icon("image.svg_placeholder", "#2ecc71")
                    elif tipo == "audio": return self.get_cached_icon("music_note.svg_placeholder", "#3498db")
                else:
                    if tipo == "video": return self.get_cached_icon("movie.svg", "#9b59b6", size=18)
                    elif tipo == "imagen": return self.get_cached_icon("image.svg", "#2ecc71", size=18)
                    elif tipo == "audio": return self.get_cached_icon("music_note.svg", "#3498db", size=18)

        elif role == Qt.SizeHintRole and self._view_mode == "grid" and col == 0:
            return self._grid_size_hint

        elif role == Qt.ForegroundRole:
            if tipo == "load_more":
                return QColor(get_theme_token("acento_primario", "#B9E640"))
            if col == 1 and tipo == "load_more":
                return QColor(get_theme_token("acento_primario", "#B9E640"))
            
        elif role == Qt.FontRole:
            if tipo == "load_more":
                f = QFont()
                f.setBold(True)
                return f
        
        elif role == Qt.TextAlignmentRole:
            if tipo == "empty":
                return Qt.AlignCenter
            if tipo == "load_more" and self._view_mode == "grid":
                return Qt.AlignCenter
                
        return None
        
    def _on_thumbnail_loaded(self, file_path: str, thumb_path: str):
        """Al terminar de generar una miniatura, notificar a la vista para que se actualice."""
        if not hasattr(self, "_path_to_row"):
            return
            
        if file_path in self._path_to_row:
            row = self._path_to_row[file_path]
            idx_start = self.index(row, 0)
            idx_end = self.index(row, self.columnCount() - 1)
            self.dataChanged.emit(idx_start, idx_end, [Qt.DecorationRole])

    def set_data(self, media_items):
        """Reemplaza los datos del modelo."""
        self.beginResetModel()
        self._media_items = media_items
        self._path_to_row = {}
        for idx, item in enumerate(self._media_items):
            if "ruta" in item:
                self._path_to_row[item["ruta"]] = idx
        self.endResetModel()

    def get_item(self, index: QModelIndex):
        if index.isValid() and 0 <= index.row() < len(self._media_items):
            return self._media_items[index.row()]
        return None

    def get_item_by_row(self, row: int):
        if 0 <= row < len(self._media_items):
            return self._media_items[row]
        return None

    def find_item_index_by_path(self, path: str):
        if hasattr(self, "_path_to_row") and path in self._path_to_row:
            return self.index(self._path_to_row[path], 0)
        return QModelIndex()

    def sort(self, column: int, order=Qt.AscendingOrder):
        """Implementación nativa de ordenamiento para soportar clics en las cabeceras de QTreeView."""
        is_remote = False
        if len(self._media_items) > 0:
            for item in self._media_items:
                if item.get("tipo") not in ("empty", "load_more"):
                    is_remote = item.get("es_remoto", False) or item.get("ruta", "").startswith("http")
                    break
                    
        if not is_remote:
            self.global_sort_requested.emit(column, order == Qt.AscendingOrder)
            return

        self.layoutAboutToBeChanged.emit()
        
        reverse = (order == Qt.DescendingOrder)
        
        def safe_float(val):
            try: return float(val)
            except: return 0.0

        if column == 1: # Nombre de Archivo
            key_func = lambda item: item.get("nombre", "").lower()
        elif column == 2: # Descripción
            key_func = lambda item: item.get("description", "").lower()
        elif column == 3: # Licencia
            key_func = lambda item: item.get("license", "").lower()
        elif column == 4: # Duración
            def dur_key(item):
                if "duration" in item:
                    return safe_float(item["duration"])
                if "duración" in item:
                    dur_str = str(item["duración"])
                    if ":" in dur_str:
                        parts = dur_str.split(":")
                        if len(parts) == 2:
                            return safe_float(parts[0])*60 + safe_float(parts[1])
                return 0.0
            key_func = dur_key
        elif column == 5: # Origen
            key_func = lambda item: item.get("library", "Local").lower()
        elif column == 6: # Tipo de Archivo
            key_func = lambda item: item.get("file_type", "").lower()
        elif column == 7: # Sample Rate
            key_func = lambda item: str(item.get("sample_rate", "")).lower()
        else: # Estado o fallback (columna 0)
            key_func = lambda item: str(item.get("estado", "")).lower()

        # Separar los ítems normales de los ítems de estado (load_more, empty)
        normal_items = []
        special_items = []
        for item in self._media_items:
            if item.get("tipo") in ("load_more", "empty"):
                special_items.append(item)
            else:
                normal_items.append(item)
                
        # Ordenar sólo los ítems normales
        normal_items.sort(key=key_func, reverse=reverse)
        
        # Volver a unirlos manteniendo siempre los especiales al final
        self._media_items = normal_items + special_items
        
        # Re-construir índices
        self._path_to_row = {}
        for idx, item in enumerate(self._media_items):
            if "ruta" in item:
                self._path_to_row[item["ruta"]] = idx
                
        self.layoutChanged.emit()
