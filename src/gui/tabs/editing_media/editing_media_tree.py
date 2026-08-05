# src/gui/tabs/editing_media/editing_media_tree.py
import os
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QTreeWidgetItem,
    QListWidgetItem,
    QFileDialog,
    QMessageBox,
    QInputDialog,
    QMenu
)
from core.logger.logger_manager import logger
from gui.tabs.editing_media.editing_media_icons import (
    get_colored_svg_icon,
    get_colored_folder_icon,
    get_svg_icon,
    get_folder_icon,
    get_placeholder_thumbnail_icon
)
from core.tabs.editing_media.thumbnail_cache_manager import ThumbnailCacheManager

class MediaListWidgetItem(QListWidgetItem):
    """QListWidgetItem personalizado con comparación nativa C++ ultra rápida para sortItems()."""
    def __lt__(self, other):
        if isinstance(other, QListWidgetItem):
            v1 = self.data(Qt.UserRole + 1)
            v2 = other.data(Qt.UserRole + 1)
            if v1 is not None and v2 is not None:
                try:
                    return v1 < v2
                except Exception:
                    return str(v1) < str(v2)
        return super().__lt__(other)

class TreeListMixin:
    """Mixin que maneja el árbol de carpetas, lista de medios y menús contextuales."""

    # ── Población y Control de Vistas del Árbol ──────────────────────────────
    def _update_tree_view(self):
        """Reconstruye el árbol de carpetas lógicas y físicas de forma jerárquica."""
        selected = self.tree_folders.currentItem()
        selected_data = None
        if selected:
            selected_data = selected.data(0, Qt.UserRole)

        self.tree_folders.clear()
        
        # 1. Nodo Raíz de Freesound (Online)
        self.online_root = QTreeWidgetItem(self.tree_folders, [self.tr("Freesound")])
        self.online_root.setIcon(0, get_svg_icon("travel_explore.svg"))
        self.online_root.setData(0, Qt.UserRole, {"tipo": "root_online"})
        self.online_root.setExpanded(True)

        # 2. Nodo Raíz de Directorios Físicos
        self.physical_root = QTreeWidgetItem(self.tree_folders, [self.tr("Directorios")])
        self.physical_root.setIcon(0, get_folder_icon())
        self.physical_root.setData(0, Qt.UserRole, {"tipo": "root_physical"})
        self.physical_root.setExpanded(True)

        for folder in self.controller.indexed_folders:
            folder_name = os.path.basename(folder) or folder
            item = QTreeWidgetItem(self.physical_root, [folder_name])
            color = get_item_color(f"folder:{folder}")
            if color:
                item.setIcon(0, get_colored_folder_icon(color))
            else:
                item.setIcon(0, get_folder_icon())
            item.setData(0, Qt.UserRole, {"tipo": "folder", "ruta": folder})
            item.setExpanded(True)
            self._add_folder_subdirs(item, folder)

        # 3. Nodo Raíz de Colecciones Virtuales
        self.virtual_root = QTreeWidgetItem(self.tree_folders, [self.tr("Colecciones")])
        self.virtual_root.setIcon(0, get_svg_icon("star.svg"))
        self.virtual_root.setData(0, Qt.UserRole, {"tipo": "root_virtual"})
        self.virtual_root.setExpanded(True)

        for col_name in self.controller.collections.keys():
            item = QTreeWidgetItem(self.virtual_root, [col_name])
            color = get_item_color(f"col:{col_name}")
            if color:
                item.setIcon(0, get_colored_svg_icon("star.svg", color))
            else:
                item.setIcon(0, get_svg_icon("star.svg"))
            item.setData(0, Qt.UserRole, {"tipo": "collection", "nombre": col_name})

        # Restaurar selección anterior
        if selected_data:
            self._restore_tree_selection(self.tree_folders.invisibleRootItem(), selected_data)

        # Restaurar estado de botones
        self._update_button_states()

    def _restore_tree_selection(self, parent_item, target_data):
        """Busca y restaura recursivamente la selección del árbol tras un refresco."""
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            child_data = child.data(0, Qt.UserRole)
            if child_data:
                match = False
                tipo = child_data.get("tipo")
                target_tipo = target_data.get("tipo")
                
                if tipo == target_tipo:
                    if tipo in ["folder", "subfolder"] and child_data.get("ruta") == target_data.get("ruta"):
                        match = True
                    elif tipo == "collection" and child_data.get("nombre") == target_data.get("nombre"):
                        match = True
                    elif tipo in ["root_physical", "root_virtual", "root_online"]:
                        match = True
                
                if match:
                    self.tree_folders.setCurrentItem(child)
                    return True
            
            # Buscar recursivamente en hijos
            if self._restore_tree_selection(child, target_data):
                return True
        return False

    def _add_folder_subdirs(self, parent_item, folder_path):
        """Busca y añade recursivamente subcarpetas al árbol."""
        try:
            if not os.path.exists(folder_path):
                return
            for name in sorted(os.listdir(folder_path)):
                subpath = os.path.join(folder_path, name)
                if os.path.isdir(subpath):
                    normalized_path = subpath.replace("\\", "/")
                    child = QTreeWidgetItem(parent_item, [name])
                    color = get_item_color(f"folder:{normalized_path}")
                    if color:
                        child.setIcon(0, get_colored_folder_icon(color))
                    else:
                        child.setIcon(0, get_folder_icon())
                    child.setData(0, Qt.UserRole, {"tipo": "subfolder", "ruta": normalized_path})
                    self._add_folder_subdirs(child, subpath)
        except Exception as e:
            logger.debug(f"EditingMediaTab: Error al buscar subcarpetas en {folder_path}: {e}")

    def _update_button_states(self):
        selected = self.tree_folders.currentItem()
        is_online = False
        if selected:
            data = selected.data(0, Qt.UserRole)
            if data:
                tipo = data.get("tipo")
                if tipo == "root_online":
                    is_online = True
        
        # Deshabilitar botón de indexar carpeta en modo online
        if hasattr(self, "btn_add_folder"):
            self.btn_add_folder.setEnabled(not is_online)
        
        # Mostrar engranaje de configuración en modo online
        if hasattr(self, "btn_freesound_login"):
            self.btn_freesound_login.setVisible(is_online)
            
        # Si es online, forzar el filtro "Audios" y deshabilitar los otros
        if is_online:
            for btn in self.filter_buttons:
                if btn.text() == self.tr("Audios"):
                    btn.setChecked(True)
                    btn.setEnabled(True)
                    self.active_filter = "Audios"
                else:
                    btn.setChecked(False)
                    btn.setEnabled(False)
        else:
            for btn in self.filter_buttons:
                btn.setEnabled(True)

    def _get_cached_media_icon(self, icon_name: str, color: str) -> QIcon:
        """Obtiene un icono coloreado desde la cache o lo crea si no existe."""
        cache_key = f"{icon_name}:{color}"
        # Se asume la existencia de self._icon_cache en la clase principal
        if cache_key not in self._icon_cache:
            self._icon_cache[cache_key] = get_colored_svg_icon(icon_name, color)
        return self._icon_cache[cache_key]

    def _update_media_list(self):
        """Refresca la lista central de medios según el ítem activo del árbol y los filtros."""
        self.media_list.setUpdatesEnabled(False)
        try:
            self.media_list.clear()
            
            selected = self.tree_folders.currentItem()
            tipo = None
            data = None
            if selected:
                data = selected.data(0, Qt.UserRole)
                if data:
                    tipo = data.get("tipo")

            media_items = []

            if tipo in ["folder", "subfolder"]:
                ruta = data.get("ruta")
                media_items = self.controller.get_media_files_in_folder(ruta)
            elif tipo == "collection":
                nombre = data.get("nombre")
                media_items = self.controller.get_media_files_in_collection(nombre)
            elif tipo == "root_online":
                # Renderizar resultados de Freesound
                icon_cloud_list = self._get_cached_media_icon("travel_explore.svg", "#3498db")
                icon_cloud_grid = get_placeholder_thumbnail_icon("travel_explore.svg", "#3498db")
                is_grid = getattr(self, "view_mode", "grid") == "grid"

                if not self.controller.is_freesound_authenticated:
                    list_item = QListWidgetItem(self.tr("Inicia sesión con Freesound para buscar sonidos 🔑"))
                    self.media_list.addItem(list_item)
                    return

                if not self.online_results:
                    is_searching = self.online_search_thread and self.online_search_thread.isRunning()
                    if is_searching:
                        list_item = QListWidgetItem(self.tr("Buscando en Freesound..."))
                    else:
                        list_item = QListWidgetItem(self.tr("No se encontraron resultados o la búsqueda falló. Intente de nuevo."))
                    self.media_list.addItem(list_item)
                    return

                for item in self.online_results:
                    list_item = QListWidgetItem(item["nombre"])
                    if is_grid:
                        list_item.setIcon(icon_cloud_grid)
                    else:
                        list_item.setIcon(icon_cloud_list)
                    list_item.setData(Qt.UserRole, item)
                    self.media_list.addItem(list_item)
                return
            else:
                media_items = self.controller.get_all_media_files()

            # Obtener iconos cacheados una sola vez
            icon_video_list = self._get_cached_media_icon("movie.svg", "#9b59b6")
            icon_image_list = self._get_cached_media_icon("image.svg", "#2ecc71")
            icon_audio_list = self._get_cached_media_icon("music_note.svg", "#3498db")

            icon_video_grid = get_placeholder_thumbnail_icon("movie.svg", "#9b59b6")
            icon_image_grid = get_placeholder_thumbnail_icon("image.svg", "#2ecc71")
            icon_audio_grid = get_placeholder_thumbnail_icon("music_note.svg", "#3498db")

            thumb_mgr = ThumbnailCacheManager.get_instance()
            is_grid = getattr(self, "view_mode", "grid") == "grid"

            for item in media_items:
                list_item = MediaListWidgetItem(item["nombre"])
                item_type = item["tipo"]
                file_path = item.get("ruta", "")

                cached_icon = thumb_mgr.get_cached_qicon(file_path) if file_path else None
                if cached_icon:
                    list_item.setIcon(cached_icon)
                else:
                    if is_grid:
                        if item_type == "video":
                            list_item.setIcon(icon_video_grid)
                        elif item_type == "imagen":
                            list_item.setIcon(icon_image_grid)
                        elif item_type == "audio":
                            list_item.setIcon(icon_audio_grid)
                    else:
                        if item_type == "video":
                            list_item.setIcon(icon_video_list)
                        elif item_type == "imagen":
                            list_item.setIcon(icon_image_list)
                        elif item_type == "audio":
                            list_item.setIcon(icon_audio_list)

                    if file_path:
                        thumb_mgr.request_thumbnail(file_path, item_type)

                list_item.setData(Qt.UserRole, item)
                self.media_list.addItem(list_item)

            # Aplicar filtro activo y texto de búsqueda sin destruir la lista
            self._apply_active_filters_fast()
        finally:
            self.media_list.setUpdatesEnabled(True)

    def _on_disk_changed(self):
        """Callback del watchdog cuando hay cambios en las carpetas vigiladas."""
        self._update_tree_view()
        self._update_media_list()

    def _on_collections_changed(self):
        """Callback cuando se modifican las colecciones virtuales."""
        self._update_tree_view()
        self._update_media_list()

    def _on_add_folder_clicked(self):
        """Abre un selector de carpetas e indexa la seleccionada."""
        folder = QFileDialog.getExistingDirectory(self, self.tr("Seleccionar carpeta para indexar"))
        if folder:
            success = self.controller.add_folder(folder)
            if success:
                self._update_tree_view()
                # Seleccionar la nueva carpeta indexada automáticamente
                for i in range(self.physical_root.childCount()):
                    child = self.physical_root.child(i)
                    child_data = child.data(0, Qt.UserRole)
                    if child_data and child_data.get("ruta") == folder.replace("\\", "/"):
                        self.tree_folders.setCurrentItem(child)
                        self._update_media_list()
                        break
            else:
                QMessageBox.information(self, self.tr("Indexador"), self.tr("Esta carpeta ya se encuentra indexada."))

    def _on_remove_folder_clicked(self):
        """Remueve la carpeta indexada seleccionada."""
        selected = self.tree_folders.currentItem()
        if not selected:
            return
        
        data = selected.data(0, Qt.UserRole)
        if data and data.get("tipo") == "folder":
            ruta = data.get("ruta")
            # Confirmar desvinculación
            reply = QMessageBox.question(
                self, 
                self.tr("Desvincular Carpeta"),
                self.tr(f"¿Estás seguro de que deseas desvincular '{os.path.basename(ruta)}'?\n(No se eliminarán los archivos del disco)."),
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.controller.remove_folder(ruta)
                self.preview_box.show_default_state()
                self._clear_metadata()

    def _on_add_collection_clicked(self):
        """Crea una nueva colección virtual solicitando el nombre al usuario."""
        name, ok = QInputDialog.getText(
            self, 
            self.tr("Nueva Colección"), 
            self.tr("Nombre de la colección virtual:")
        )
        if ok and name.strip():
            name = name.strip()
            success = self.controller.add_collection(name)
            if not success:
                QMessageBox.warning(self, self.tr("Nueva Colección"), self.tr("El nombre ingresado está vacío o ya existe."))

    def _on_remove_collection_clicked(self):
        """Elimina una colección virtual."""
        selected = self.tree_folders.currentItem()
        if not selected:
            return
        
        data = selected.data(0, Qt.UserRole)
        if data and data.get("tipo") == "collection":
            name = data.get("nombre")
            reply = QMessageBox.question(
                self, 
                self.tr("Eliminar Colección"),
                self.tr(f"¿Estás seguro de que deseas eliminar la colección '{name}'?"),
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.controller.remove_collection(name)
                self.preview_box.show_default_state()
                self._clear_metadata()

    def _on_tree_current_item_changed(self, current, previous):
        if current:
            self._on_tree_item_clicked(current, 0)

    def _on_current_item_changed(self, current, previous):
        if current:
            self._on_media_clicked(current)

    def _on_tree_item_clicked(self, item, column):
        self._update_button_states()
        
        data = item.data(0, Qt.UserRole)
        if data and data.get("tipo") == "root_online":
            self.current_page = 1
            if not self.online_results:
                self._exec_online_search()
                
        self._update_media_list()

    def _sort_media_list_items(self):
        """Reordena los ítems de self.media_list utilizando sortItems() nativo de Qt en C++ (0 ms)."""
        sort_by = getattr(self, "sort_by", "nombre")
        sort_asc = getattr(self, "sort_ascending", True)

        self.media_list.setUpdatesEnabled(False)
        try:
            for i in range(self.media_list.count()):
                item = self.media_list.item(i)
                data = item.data(Qt.UserRole)
                if isinstance(data, dict):
                    if sort_by == "nombre":
                        val = data.get("nombre", "").lower()
                    elif sort_by == "mtime":
                        val = data.get("mtime", 0.0)
                    elif sort_by == "ctime":
                        val = data.get("ctime", 0.0)
                    elif sort_by == "size":
                        val = data.get("size_bytes", 0)
                    elif sort_by == "tipo":
                        val = data.get("tipo", "")
                    else:
                        val = data.get("nombre", "").lower()
                    item.setData(Qt.UserRole + 1, val)

            order = Qt.AscendingOrder if sort_asc else Qt.DescendingOrder
            self.media_list.sortItems(order)
        finally:
            self.media_list.setUpdatesEnabled(True)

    def _apply_active_filters_fast(self):
        """Aplica filtros de tipo, ordenación y búsqueda en 0ms ocultando/mostrando/reordenando ítems."""
        selected = self.tree_folders.currentItem()
        data = selected.data(0, Qt.UserRole) if selected else None
        if data and data.get("tipo") == "root_online":
            self._update_media_list()
            return

        active_filter = self.active_filter
        search_query = self.search_input.text().lower().strip()

        # Re-ordenar ítems en RAM primero
        self._sort_media_list_items()

        self.media_list.setUpdatesEnabled(False)
        try:
            for i in range(self.media_list.count()):
                item = self.media_list.item(i)
                item_data = item.data(Qt.UserRole)
                if not isinstance(item_data, dict):
                    continue

                item_type = item_data.get("tipo", "")
                item_name = item_data.get("nombre", "").lower()

                type_match = True
                if active_filter == "Imágenes" and item_type != "imagen":
                    type_match = False
                elif active_filter == "Videos" and item_type != "video":
                    type_match = False
                elif active_filter == "Audios" and item_type != "audio":
                    type_match = False

                search_match = True
                if search_query and search_query not in item_name:
                    search_match = False

                item.setHidden(not (type_match and search_match))
        finally:
            self.media_list.setUpdatesEnabled(True)

    def _on_filter_button_clicked(self):
        """Maneja el cambio de filtro y deselecciona los otros botones."""
        sender = self.sender()
        self.active_filter = sender.text()
        
        # Si filtramos por categoría específica y el modo actual de ordenación es "tipo", revertir a "nombre"
        if self.active_filter != "Todos" and getattr(self, "sort_by", "nombre") == "tipo":
            self.sort_by = "nombre"
            if hasattr(self, "btn_sort_by"):
                self.btn_sort_by.setText("Nombre")

        for btn in self.filter_buttons:
            if btn != sender:
                btn.setChecked(False)
        sender.setChecked(True)
        
        if hasattr(self, "_build_sort_menu"):
            self._build_sort_menu()

        self._apply_active_filters_fast()

    def _show_tree_context_menu(self, position):
        item = self.tree_folders.itemAt(position)
        menu = QMenu(self)
        
        if not item:
            # Click derecho en zona vacía: ofrecer crear colección virtual
            act_new_col = menu.addAction(self.tr("Nueva Colección Virtual"))
            act_new_col.triggered.connect(self._on_add_collection_clicked)
            menu.exec(self.tree_folders.mapToGlobal(position))
            return
            
        data = item.data(0, Qt.UserRole)
        if not data:
            return
            
        tipo = data.get("tipo")
        if tipo == "folder":
            act_remove = menu.addAction(self.tr("Desvincular Carpeta Física"))
            act_remove.triggered.connect(self._on_remove_folder_clicked)
            
            # Opciones de coloreado
            menu.addSeparator()
            act_color = menu.addAction(self.tr("Color Aleatorio"))
            act_color.triggered.connect(lambda: self._set_random_color_for_item(item))
            
            act_choose = menu.addAction(self.tr("Elegir Color..."))
            act_choose.triggered.connect(lambda: self._choose_color_for_item(item))
            
            current_color = get_item_color(f"folder:{data.get('ruta')}")
            if current_color:
                act_reset_color = menu.addAction(self.tr("Restablecer Color"))
                act_reset_color.triggered.connect(lambda: self._reset_color_for_item(item))
                
            menu.exec(self.tree_folders.mapToGlobal(position))
        elif tipo == "subfolder":
            # Para subcarpetas físicas, no hay acción de desvincular, pero sí de colorear
            act_color = menu.addAction(self.tr("Color Aleatorio"))
            act_color.triggered.connect(lambda: self._set_random_color_for_item(item))
            
            act_choose = menu.addAction(self.tr("Elegir Color..."))
            act_choose.triggered.connect(lambda: self._choose_color_for_item(item))
            
            current_color = get_item_color(f"folder:{data.get('ruta')}")
            if current_color:
                act_reset_color = menu.addAction(self.tr("Restablecer Color"))
                act_reset_color.triggered.connect(lambda: self._reset_color_for_item(item))
                
            menu.exec(self.tree_folders.mapToGlobal(position))
        elif tipo == "collection":
            act_remove = menu.addAction(self.tr("Eliminar Colección Virtual"))
            act_remove.triggered.connect(self._on_remove_collection_clicked)
            
            # Opciones de coloreado
            menu.addSeparator()
            act_color = menu.addAction(self.tr("Color Aleatorio"))
            act_color.triggered.connect(lambda: self._set_random_color_for_item(item))
            
            act_choose = menu.addAction(self.tr("Elegir Color..."))
            act_choose.triggered.connect(lambda: self._choose_color_for_item(item))
            
            current_color = get_item_color(f"col:{data.get('nombre')}")
            if current_color:
                act_reset_color = menu.addAction(self.tr("Restablecer Color"))
                act_reset_color.triggered.connect(lambda: self._reset_color_for_item(item))
                
            menu.exec(self.tree_folders.mapToGlobal(position))
        elif tipo == "root_virtual":
            act_new_col = menu.addAction(self.tr("Nueva Colección Virtual"))
            act_new_col.triggered.connect(self._on_add_collection_clicked)
            menu.exec(self.tree_folders.mapToGlobal(position))

    def _set_random_color_for_item(self, item):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        tipo = data.get("tipo")
        
        # Obtener el color actual para excluirlo y garantizar el cambio de color
        current_color = None
        if tipo in ["folder", "subfolder"]:
            ruta = data.get("ruta")
            current_color = get_item_color(f"folder:{ruta}")
        elif tipo == "collection":
            nombre = data.get("nombre")
            current_color = get_item_color(f"col:{nombre}")
            
        color = get_random_label_color(exclude_color=current_color)
        
        if tipo in ["folder", "subfolder"]:
            ruta = data.get("ruta")
            set_item_color(f"folder:{ruta}", color)
        elif tipo == "collection":
            nombre = data.get("nombre")
            set_item_color(f"col:{nombre}", color)
            
        self._update_tree_view()

    def _choose_color_for_item(self, item):
        from gui.dialogs.dialogs import AdobeColorPickerDialog
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        tipo = data.get("tipo")
        
        # Obtener el color actual para inicializar el picker
        current_color = None
        if tipo in ["folder", "subfolder"]:
            ruta = data.get("ruta")
            current_color = get_item_color(f"folder:{ruta}")
        elif tipo == "collection":
            nombre = data.get("nombre")
            current_color = get_item_color(f"col:{nombre}")
            
        initial_color = current_color if current_color else "#B9E640"
        
        dialog = AdobeColorPickerDialog(initial_color, self)
        if dialog.exec():
            color = dialog.get_color()
            if tipo in ["folder", "subfolder"]:
                ruta = data.get("ruta")
                set_item_color(f"folder:{ruta}", color)
            elif tipo == "collection":
                nombre = data.get("nombre")
                set_item_color(f"col:{nombre}", color)
                
            self._update_tree_view()

    def _reset_color_for_item(self, item):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        tipo = data.get("tipo")
        
        if tipo in ["folder", "subfolder"]:
            ruta = data.get("ruta")
            set_item_color(f"folder:{ruta}", None)
        elif tipo == "collection":
            nombre = data.get("nombre")
            set_item_color(f"col:{nombre}", None)
            
        self._update_tree_view()

    def _show_media_context_menu(self, position):
        item = self.media_list.itemAt(position)
        if not item:
            menu = QMenu(self)
            menu.setStyleSheet(f"""
                QMenu {{
                    background-color: {get_theme_token('fondo_elemento', '#1e1e1e')};
                    border: 1px solid {get_theme_token('borde_normal', '#3d3d3d')};
                    padding: 4px;
                    border-radius: 6px;
                }}
                QMenu::item {{
                    padding: 6px 20px 6px 20px;
                    border-radius: 4px;
                    color: {get_theme_token('texto_principal', '#cdd6f4')};
                    font-size: 11px;
                }}
                QMenu::item:selected {{
                    background-color: {get_theme_token('acento_primario', '#B9E640')};
                    color: {get_theme_token('fondo_principal', '#0a0a0a')};
                    font-weight: bold;
                }}
                QMenu::item:disabled {{
                    color: #555555;
                }}
            """)
            sort_sub = menu.addMenu(self.tr("Ordenar por"))
            options = [
                ("nombre", self.tr("Nombre")),
                ("mtime", self.tr("Fecha de Modificación")),
                ("ctime", self.tr("Fecha de Creación")),
                ("size", self.tr("Tamaño")),
                ("tipo", self.tr("Tipo de Medio")),
            ]
            curr_sort = getattr(self, "sort_by", "nombre")
            active_filter = getattr(self, "active_filter", "Todos")

            for key, label in options:
                act = sort_sub.addAction(label)
                act.setCheckable(True)
                if key == curr_sort:
                    act.setChecked(True)
                if key == "tipo" and active_filter != "Todos":
                    act.setEnabled(False)
                act.triggered.connect(lambda checked, k=key, l=label: self._on_sort_option_selected(k, l))

            sort_sub.addSeparator()
            act_asc = sort_sub.addAction(self.tr("Ascendente (A-Z, Antiguos)"))
            act_asc.setCheckable(True)
            act_asc.setChecked(getattr(self, "sort_ascending", True))
            act_asc.triggered.connect(lambda: self._set_sort_direction(True))

            act_desc = sort_sub.addAction(self.tr("Descendente (Z-A, Recientes)"))
            act_desc.setCheckable(True)
            act_desc.setChecked(not getattr(self, "sort_ascending", True))
            act_desc.triggered.connect(lambda: self._set_sort_direction(False))

            view_sub = menu.addMenu(self.tr("Vista"))
            act_grid = view_sub.addAction(self.tr("Cuadrícula"))
            act_grid.setCheckable(True)
            act_grid.setChecked(getattr(self, "view_mode", "grid") == "grid")
            act_grid.triggered.connect(lambda: self.set_view_mode("grid"))

            act_list = view_sub.addAction(self.tr("Lista"))
            act_list.setCheckable(True)
            act_list.setChecked(getattr(self, "view_mode", "grid") == "list")
            act_list.triggered.connect(lambda: self.set_view_mode("list"))

            menu.exec(self.media_list.mapToGlobal(position))
            return

        item_data = item.data(Qt.UserRole)
        if not item_data:
            return

        file_path = item_data["ruta"]
        menu = QMenu(self)

        # Determinar si estamos visualizando una colección virtual
        tree_item = self.tree_folders.currentItem()
        is_viewing_collection = False
        current_col_name = ""
        
        if tree_item:
            tree_data = tree_item.data(0, Qt.UserRole)
            if tree_data and tree_data.get("tipo") == "collection":
                is_viewing_collection = True
                current_col_name = tree_data.get("nombre")

        if is_viewing_collection:
            # Opción para quitar de la colección actual
            act_remove = menu.addAction(self.tr("Quitar de esta Colección"))
            act_remove.triggered.connect(lambda: self._remove_file_from_collection(current_col_name, file_path))
        else:
            # Opción para añadir a una colección
            submenu = menu.addMenu(self.tr("Añadir a Colección"))
            
            # Cargar colecciones dinámicamente
            collections_list = list(self.controller.collections.keys())
            if collections_list:
                for col_name in collections_list:
                    act_col = submenu.addAction(col_name)
                    # Usar captura de variable por scope en lambda
                    act_col.triggered.connect(lambda checked=False, cn=col_name: self._add_file_to_collection(cn, file_path))
            else:
                act_none = submenu.addAction(self.tr("(Sin colecciones)"))
                act_none.setEnabled(False)

        is_remote = file_path.startswith("http://") or file_path.startswith("https://")
        menu.addSeparator()
        if is_remote:
            act_download = menu.addAction(self.tr("Descargar Audio"))
            act_download.triggered.connect(self._on_download_clicked)
        else:
            act_reveal = menu.addAction(self.tr("Revelar en Explorador"))
            act_reveal.triggered.connect(self._on_reveal_clicked)

        menu.exec(self.media_list.mapToGlobal(position))

    def _add_file_to_collection(self, col_name, file_path):
        success = self.controller.add_to_collection(col_name, file_path)
        if success:
            logger.info(f"EditingMediaTab: Archivo {os.path.basename(file_path)} añadido a colección {col_name}")
        else:
            logger.info(f"EditingMediaTab: El archivo ya se encuentra en la colección {col_name}")

    def _remove_file_from_collection(self, col_name, file_path):
        self.controller.remove_from_collection(col_name, file_path)
        self._update_media_list()

    def _set_sort_direction(self, asc: bool):
        self.sort_ascending = asc
        if hasattr(self, "btn_sort_dir"):
            if asc:
                self.btn_sort_dir.setIcon(get_colored_svg_icon("arrow_upward_alt.svg", "#FFFFFF", size=16))
                self.btn_sort_dir.setIconSize(QSize(16, 16))
                self.btn_sort_dir.setToolTip(self.tr("Orden Ascendente (A-Z, Antiguos primero)"))
            else:
                self.btn_sort_dir.setIcon(get_colored_svg_icon("arrow_circle_down.svg", "#FFFFFF", size=16))
                self.btn_sort_dir.setIconSize(QSize(16, 16))
                self.btn_sort_dir.setToolTip(self.tr("Orden Descendente (Z-A, Recientes primero)"))
        self._apply_active_filters_fast()
        self.preview_box.show_default_state()
        self._clear_metadata()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(f"border: 2px dashed {self._get_border_accent_color()};")

    def _get_border_accent_color(self):
        # Usar getter para evitar imports circulares de estilos si es posible
        from gui.styles import get_theme_token
        return get_theme_token('acento_primario', '#B9E640')

    def dragLeaveEvent(self, event):
        self._apply_custom_styles()

    def dropEvent(self, event):
        self._apply_custom_styles()
        urls = event.mimeData().urls()
        
        has_new_folders = False
        has_new_files = False
        first_added_path = None
        
        for url in urls:
            local_path = url.toLocalFile()
            logger.info(f"EditingMediaTab: Elemento arrastrado y soltado: {local_path}")
            
            if os.path.isdir(local_path):
                self.controller.add_folder(local_path)
                has_new_folders = True
                if not first_added_path:
                    first_added_path = local_path.replace("\\", "/")
            elif os.path.isfile(local_path):
                ext = os.path.splitext(local_path)[1].lower()
                if ext in VALID_EXTS:
                    col_name = "Favoritos"
                    if "Favoritos" not in self.controller.collections:
                        cols = list(self.controller.collections.keys())
                        if cols:
                            col_name = cols[0]
                        else:
                            self.controller.add_collection("Favoritos")
                    
                    self.controller.add_to_collection(col_name, local_path)
                    has_new_files = True

        if has_new_folders:
            self._update_tree_view()
            if first_added_path:
                for i in range(self.physical_root.childCount()):
                    child = self.physical_root.child(i)
                    child_data = child.data(0, Qt.UserRole)
                    if child_data and child_data.get("ruta") == first_added_path:
                        self.tree_folders.setCurrentItem(child)
                        self._update_media_list()
                        break
        elif has_new_files:
            self._update_tree_view()
            for i in range(self.virtual_root.childCount()):
                child = self.virtual_root.child(i)
                child_data = child.data(0, Qt.UserRole)
                if child_data and child_data.get("nombre") == "Favoritos":
                    self.tree_folders.setCurrentItem(child)
                    self._update_media_list()
                    break
