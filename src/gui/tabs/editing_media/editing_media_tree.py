# src/gui/tabs/editing_media/editing_media_tree.py
import os
from PySide6.QtCore import Qt, QSize, QRectF
from PySide6.QtGui import QIcon, QColor, QFont, QPixmap, QPainter
from PySide6.QtWidgets import (
    QTreeWidgetItem,
    QListWidgetItem,
    QFileDialog,
    QMessageBox,
    QInputDialog,
    QMenu
)
from gui.styles import get_theme_token
from core.logger.logger_manager import logger
from gui.tabs.editing_media.editing_media_icons import (
    get_colored_svg_icon,
    get_colored_folder_icon,
    get_svg_icon,
    get_contrast_svg_icon,
    get_folder_icon,
    get_placeholder_thumbnail_icon
)

from core.tabs.editing_media.folder_color_manager import get_item_color, set_item_color, get_random_label_color
from core.tabs.editing_media.editing_media_logic import VALID_EXTS
from core.tabs.editing_media.thumbnail_cache_manager import ThumbnailCacheManager



class TreeListMixin:
    """Mixin que maneja el árbol de carpetas, lista de medios y menús contextuales."""

    # ── Población y Control de Vistas del Árbol ──────────────────────────────
    # ── Población y Control de Vistas del Árbol ──────────────────────────────
    def _update_tree_view(self):
        """Reconstruye el árbol de carpetas lógicas y físicas de forma jerárquica con Lazy Loading."""
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
            self._populate_folder_children(item, folder)

        # 3. Nodo Raíz de Colecciones Virtuales
        self.virtual_root = QTreeWidgetItem(self.tree_folders, [self.tr("Colecciones")])
        self.virtual_root.setIcon(0, get_svg_icon("star.svg"))
        self.virtual_root.setData(0, Qt.UserRole, {"tipo": "root_virtual"})
        self.virtual_root.setExpanded(True)

        for col_name in self.controller.collections.keys():
            item = QTreeWidgetItem(self.virtual_root, [col_name])
            color = get_item_color(f"col:{col_name}")
            if col_name == "Descargados":
                accent_color = get_theme_token("acento_primario", "#B9E640")
                item.setIcon(0, get_colored_svg_icon("download.svg", color or accent_color))
            elif color:
                item.setIcon(0, get_colored_svg_icon("star.svg", color))
            else:
                item.setIcon(0, get_svg_icon("star.svg"))
            item.setData(0, Qt.UserRole, {"tipo": "collection", "nombre": col_name})


        # Restaurar selección anterior guardada en sesión o seleccionar Directorios por defecto (primera vez)
        saved_target = getattr(self.controller, "last_selected_tree_node", None)
        target = selected_data or saved_target
        restored = False
        if target:
            restored = self._restore_tree_selection(self.tree_folders.invisibleRootItem(), target)

        if not restored:
            self.tree_folders.setCurrentItem(self.physical_root)

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

    def _on_tree_item_expanded(self, item):
        """Carga bajo demanda (Lazy Loading) las subcarpetas del nodo expandido."""
        data = item.data(0, Qt.UserRole)
        if not data or data.get("tipo") not in ["folder", "subfolder"]:
            return

        # Si el primer hijo es un placeholder/dummy, poblar subcarpetas reales
        if item.childCount() == 1 and item.child(0).data(0, Qt.UserRole) == {"tipo": "dummy"}:
            item.removeChild(item.child(0))
            folder_path = data.get("ruta")
            self._populate_folder_children(item, folder_path)

    def _populate_folder_children(self, parent_item, folder_path):
        """Puebla solo las subcarpetas directas (1 nivel) de forma eficiente."""
        try:
            if not (os.path.exists(folder_path) and os.path.isdir(folder_path)):
                return

            subdirs = []
            with os.scandir(folder_path) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        subdirs.append((entry.name, entry.path.replace("\\", "/")))

            subdirs.sort(key=lambda x: x[0].lower())

            for name, normalized_path in subdirs:
                child = QTreeWidgetItem(parent_item, [name])
                color = get_item_color(f"folder:{normalized_path}")
                if color:
                    child.setIcon(0, get_colored_folder_icon(color))
                else:
                    child.setIcon(0, get_folder_icon())
                child.setData(0, Qt.UserRole, {"tipo": "subfolder", "ruta": normalized_path})
                
                # Si esta subcarpeta tiene a su vez subcarpetas, añadir placeholder para expandir
                if self._has_subdirs(normalized_path):
                    dummy = QTreeWidgetItem(child, ["..."])
                    dummy.setData(0, Qt.UserRole, {"tipo": "dummy"})
        except Exception as e:
            logger.debug(f"EditingMediaTab: Error al buscar subcarpetas en {folder_path}: {e}")

    def _has_subdirs(self, folder_path: str) -> bool:
        """Comprueba rápidamente (O(1)) si una carpeta contiene al menos una subcarpeta."""
        try:
            with os.scandir(folder_path) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        return True
        except Exception:
            pass
        return False

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
        if hasattr(self, "license_container"):
            self.license_container.setVisible(is_online)
            
        # Ocultar columnas innecesarias para medios locales y actualizar headers
        if hasattr(self, "media_model"):
            self.media_model.set_online_mode(is_online)
        if hasattr(self, "media_table"):
            self.media_table.setColumnHidden(2, False) # Tamaño (Local) / Descripción (Web)
            self.media_table.setColumnHidden(3, False) # Tipo (Local) / Licencia (Web)
            self.media_table.setColumnHidden(4, False) # Modificado (Local) / Duración (Web)
            self.media_table.setColumnHidden(5, False) # Ruta (Local) / Origen (Web)
            self.media_table.setColumnHidden(6, not is_online) # Tipo de Archivo (Web)
            self.media_table.setColumnHidden(7, not is_online) # Detalles (Web)
            
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
        """Refresca la lista central de medios inyectando datos filtrados en el Modelo MVC."""
        # Limpiar la selección anterior si es posible
        target_path = getattr(self, "current_playing_path", None)
        if not target_path:
            target_path = getattr(self, "last_selected_media_path", None)

        def restore_selection():
            restored = False
            if target_path:
                idx = self.media_model.find_item_index_by_path(target_path)
                if idx.isValid():
                    from PySide6.QtCore import QItemSelectionModel
                    # Esta reselección es solo un efecto del refresco de la lista (p.ej. tras
                    # completar una descarga en segundo plano), no una nueva elección del usuario:
                    # evitar que reinicie la reproducción/waveform del ítem ya activo.
                    self._suppress_next_media_click_reset = True
                    # media_table y media_list COMPARTEN el mismo selectionModel (ver
                    # editing_media_view.py: media_list.setSelectionModel(media_table.selectionModel())).
                    # Llamar a .select()/.setCurrentIndex() en ambas vistas por separado dispara
                    # selectionChanged DOS veces sobre el mismo modelo: la primera consumía la
                    # bandera de supresión de arriba, y la segunda emisión (redundante) caía en el
                    # camino de "selección nueva" y reiniciaba la reproducción. Basta con
                    # seleccionar una sola vez; ambas vistas reflejan el resaltado igualmente
                    # porque están conectadas al mismo modelo compartido.
                    selection_model = self.media_table.selectionModel() if hasattr(self, "media_table") else None
                    if selection_model:
                        selection_model.select(idx, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
                        # NoUpdate: solo mover el índice "actual" (para que ambas vistas hagan
                        # scroll-to-visible vía su propio slot currentChanged), sin volver a
                        # tocar la selección, que .select() ya dejó correcta arriba.
                        selection_model.setCurrentIndex(idx, QItemSelectionModel.NoUpdate)
                    restored = True

            # Terminó el refresco (reset del modelo). Si no había nada que restaurar (p.ej.
            # cambiamos de carpeta/colección y el ítem activo ya no existe aquí), aplicar ahora
            # el detener/limpiar que se suprimió mientras el modelo estaba en reset transitorio.
            self._refreshing_media_list = False
            if not restored:
                self._clear_metadata()
                self._stop_audio_playback()

            # Restaurar la posición de scroll previa al refresco (p.ej. "Cargar más" o el scroll
            # infinito de Freesound), en vez de dejar que Qt salte a donde quedó reubicado el
            # ítem reseleccionado.
            pending_scroll = getattr(self, "_pending_scroll_restore", None)
            if pending_scroll is not None:
                self._pending_scroll_restore = None
                scroll_widget = self.media_table if getattr(self, "view_mode", "grid") == "list" and hasattr(self, "media_table") else self.media_list
                if scroll_widget:
                    scroll_widget.verticalScrollBar().setValue(pending_scroll)

        # Detener temporizador de búsqueda anterior si lo hubiera
        if hasattr(self, "_batch_timer") and self._batch_timer and self._batch_timer.isActive():
            self._batch_timer.stop()

        try:
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
            elif tipo == "root_physical":
                media_items = self.controller.get_all_media_files()
            elif tipo == "root_virtual":
                media_items = []
            elif tipo == "root_online":
                # Renderizar resultados de Freesound
                if not self.controller.is_freesound_authenticated:
                    msg = self.tr("Inicia sesión con Freesound para buscar sonidos 🔑")
                    self.media_model.set_data([{"nombre": msg, "tipo": "empty"}])
                    return

                if not self.online_results:
                    is_searching = self.online_search_thread and self.online_search_thread.isRunning()
                    msg = self.tr("Buscando en Freesound...") if is_searching else self.tr("No se encontraron resultados o la búsqueda falló. Intente de nuevo.")
                    self.media_model.set_data([{"nombre": msg, "tipo": "empty"}])
                    return

                downloaded_list = self.controller.collections.get("Descargados", [])
                from core.utils.config_manager import get_config
                config = get_config()
                custom_dl_dir = config.get("default_web_download_dir")
                user_dl_dir = custom_dl_dir if custom_dl_dir and os.path.isdir(custom_dl_dir) else os.path.expanduser("~/Downloads")
                labels = config.get("labels", [])

                for item in self.online_results:
                    file_name = item.get("nombre", "").strip()
                    is_downloaded = False
                    found_path = None

                    for d_path in downloaded_list:
                        if os.path.basename(d_path).strip().lower() == file_name.lower() and os.path.exists(d_path):
                            is_downloaded = True
                            found_path = d_path
                            break

                    if not is_downloaded:
                        target = os.path.join(user_dl_dir, file_name)
                        if os.path.exists(target):
                            is_downloaded = True
                            found_path = target

                    if not is_downloaded:
                        for lbl in labels:
                            lbl_p = lbl.get("path")
                            if lbl_p and os.path.exists(lbl_p):
                                target = os.path.join(lbl_p, file_name)
                                if os.path.exists(target):
                                    is_downloaded = True
                                    found_path = target
                                    break

                    if is_downloaded and found_path:
                        item["dest_path"] = found_path

                if getattr(self, "_pending_scroll_restore", None) is None:
                    scroll_widget = self.media_table if getattr(self, "view_mode", "grid") == "list" and hasattr(self, "media_table") else self.media_list
                    if scroll_widget and hasattr(scroll_widget, "verticalScrollBar"):
                        val = scroll_widget.verticalScrollBar().value()
                        if val > 0:
                            self._pending_scroll_restore = val

                self._refreshing_media_list = True
                self.media_model.set_data(self.online_results)
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, restore_selection)
                return

            else:
                media_items = self.controller.get_all_media_files()

            # 1. Pre-filtrado rápido en RAM (0ms)
            active_filter = getattr(self, "active_filter", "Todos")
            search_query = self.search_input.text().lower().strip() if hasattr(self, "search_input") else ""

            filtered_items = []
            for item in media_items:
                item_type = item.get("tipo", "")
                item_name = item.get("nombre", "").lower()

                if active_filter == "Imágenes" and item_type != "imagen":
                    continue
                if active_filter == "Videos" and item_type != "video":
                    continue
                if active_filter == "Audios" and item_type != "audio":
                    continue

                if search_query and search_query not in item_name:
                    continue

                filtered_items.append(item)

            # Si no hay ítems filtrados, mostrar mensaje
            if not filtered_items:
                msg = ""
                if tipo == "collection":
                    nombre = data.get("nombre", "") if data else ""
                    if nombre == "Favoritos":
                        msg = self.tr("Aquí puedes guardar tus medios locales o web para acceder más rápido a ellos ⭐")
                    else:
                        msg = self.tr(f"La colección '{nombre}' está vacía.\nAñade elementos haciendo clic derecho sobre cualquier medio.")
                elif tipo in ["folder", "subfolder"]:
                    msg = self.tr("Esta carpeta no contiene archivos multimedia.")
                elif tipo == "root_virtual":
                    msg = self.tr("Selecciona o crea una colección a la izquierda para ver sus archivos.")
                elif search_query:
                    msg = self.tr(f"No se encontraron medios que coincidan con '{search_query}'.")
                elif active_filter != "Todos":
                    msg = self.tr(f"No hay elementos de tipo '{active_filter}' en esta sección.")
                else:
                    msg = self.tr("No hay archivos multimedia para mostrar.")
                
                self.media_model.set_data([{"nombre": msg, "tipo": "empty"}])
                return

            # 2. Pre-ordenación ultrarrápida en RAM (0ms)
            sort_by = getattr(self, "sort_by", "nombre")
            sort_asc = getattr(self, "sort_ascending", True)

            def sort_key(item):
                if sort_by == "nombre":
                    return item.get("nombre", "").lower()
                elif sort_by in ["mtime", "ctime"]:
                    return item.get(sort_by, 0.0)
                elif sort_by == "size":
                    return item.get("size_bytes", 0)
                elif sort_by == "tipo":
                    ext = os.path.splitext(item.get("nombre", ""))[1].lower()
                    if not ext:
                        ext = str(item.get("file_type", item.get("tipo", ""))).lower()
                    return ext
                elif sort_by == "ruta":
                    return item.get("ruta", "").lower()
                elif sort_by == "license":
                    return str(item.get("license", "")).lower()
                elif sort_by == "duration":
                    d = item.get("duration", 0)
                    if isinstance(d, (int, float)): return float(d)
                    if "duración" in item:
                        dur_str = str(item["duración"])
                        if ":" in dur_str:
                            parts = dur_str.split(":")
                            if len(parts) == 2:
                                try: return float(parts[0])*60 + float(parts[1])
                                except: return 0.0
                    return 0.0
                return item.get("nombre", "").lower()

            filtered_items.sort(key=sort_key, reverse=not sort_asc)

            # 3. Pasar los datos filtrados y ordenados al modelo MVC
            # Opcional: Límite de vista para evitar exceso de RAM
            max_count = getattr(self, "_max_display_count", 999999) # O lo que prefieras
            if len(filtered_items) > max_count:
                display_items = filtered_items[:max_count]
                # Agregamos el item de "Mostrar todo" si cortamos la lista
                display_items.append({"nombre": "Cargar más", "tipo": "load_more"})
            else:
                display_items = filtered_items

            if getattr(self, "_pending_scroll_restore", None) is None:
                scroll_widget = self.media_table if getattr(self, "view_mode", "grid") == "list" and hasattr(self, "media_table") else self.media_list
                if scroll_widget and hasattr(scroll_widget, "verticalScrollBar"):
                    val = scroll_widget.verticalScrollBar().value()
                    if val > 0:
                        self._pending_scroll_restore = val

            self._refreshing_media_list = True
            self.media_model.set_data(display_items)

            # Re-seleccionar si es necesario
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, restore_selection)

        except Exception as e:
            logger.error(f"EditingMediaTab: Error al actualizar lista de medios: {e}", exc_info=True)

    def _on_disk_changed(self):
        """Callback del watchdog cuando hay cambios en las carpetas vigiladas (con debounce de 500ms)."""
        if not hasattr(self, "_disk_change_timer") or self._disk_change_timer is None:
            from PySide6.QtCore import QTimer
            self._disk_change_timer = QTimer(self)
            self._disk_change_timer.setSingleShot(True)
            self._disk_change_timer.setInterval(500)
            self._disk_change_timer.timeout.connect(self._do_disk_changed_refresh)
        
        self._disk_change_timer.start()

    def _do_disk_changed_refresh(self):
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
        if current and current != previous:
            try:
                self._on_tree_item_clicked(current, 0)
            except RuntimeError:
                pass

    def _on_current_item_changed(self, current, previous):
        if current:
            try:
                self._on_media_clicked(current)
            except RuntimeError:
                pass

    def _on_tree_item_clicked(self, item, column):
        self._update_button_states()
        
        try:
            data = item.data(0, Qt.UserRole) if item else None

            # Evitar re-ejecución duplicada si ya es el nodo seleccionado y renderizado.
            # Se compara solo por datos lógicos (tipo/ruta/nombre): el árbol se reconstruye
            # por completo en cada refresco (_update_tree_view crea QTreeWidgetItem nuevos),
            # así que comparar por identidad de objeto siempre fallaría aunque el nodo
            # seleccionado no haya cambiado realmente.
            if data is not None and getattr(self, "_active_tree_data", None) == data:
                self._active_tree_item = item
                return
        except RuntimeError:
            self._active_tree_item = None
            self._active_tree_data = None
            if not item:
                return
            try:
                data = item.data(0, Qt.UserRole)
            except RuntimeError:
                return

        self._active_tree_item = item
        self._active_tree_data = data
        self._max_display_count = 500



        # Limpiar selección previa del reproductor al cambiar de carpeta en el árbol
        self.current_playing_path = None
        
        if data:
            self.controller.last_selected_tree_node = data
            self.controller.save_data()

        if data and data.get("tipo") == "root_online":
            self.current_page = 1
            if not self.online_results:
                self._exec_online_search()
                
        self._update_media_list()

    def _sort_media_list_items(self):
        """Reordena los ítems actualizando los datos del modelo MVC."""
        self._update_media_list()

    def _apply_active_filters_fast(self):
        """Aplica filtros de tipo, ordenación y búsqueda en RAM (0ms)."""
        self._update_media_list()

    def _on_filter_button_clicked(self):
        """Maneja el cambio de filtro y deselecciona los otros botones."""
        sender = self.sender()
        self.active_filter = sender.text()
        self._max_display_count = 500  # Resetear paginación al cambiar de filtro
        
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

        self._update_media_list()

    def _refresh_current_view(self):
        """Refresca la vista actual (limpia cachés de medios/metadatos y re-escanea o re-ejecuta búsquedas)."""
        if hasattr(self.controller, "_media_cache"):
            self.controller._media_cache = {}
        if hasattr(self, "_metadata_cache"):
            self._metadata_cache = {}

        selected = self.tree_folders.currentItem()
        if selected:
            try:
                data = selected.data(0, Qt.UserRole)
                if data and data.get("tipo") == "root_online":
                    self.current_page = 1
                    self.online_results = []
                    self._exec_online_search()
                    return
            except RuntimeError:
                pass

        self._update_media_list()

    def _show_tree_context_menu(self, position):
        item = self.tree_folders.itemAt(position)
        menu = QMenu(self)

        act_refresh = menu.addAction(get_contrast_svg_icon("refresh.svg"), self.tr("Actualizar"))

        act_refresh.triggered.connect(self._refresh_current_view)
        menu.addSeparator()

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
        is_list_view = getattr(self, "view_mode", "grid") == "list" and hasattr(self, "media_table")
        view_widget = self.media_table if is_list_view else self.media_list
        index = view_widget.indexAt(position)
        
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

        # 1. Acciones específicas si se hace clic sobre uno o varios archivos
        selected_indexes = getattr(self, "_selected_indexes", [])
        if index.isValid() and index not in selected_indexes:
            selected_indexes = [index] # Si el click derecho fue fuera de la selección, solo usamos el item clickeado
            
        if selected_indexes:
            file_paths = []
            for idx in selected_indexes:
                item_data = self.media_model.get_item(idx)
                if item_data and "ruta" in item_data:
                    file_paths.append(item_data["ruta"])

            if file_paths:
                # Determinar si estamos visualizando una colección virtual
                tree_item = self.tree_folders.currentItem()
                is_viewing_collection = False
                current_col_name = ""
                if tree_item:
                    tree_data = tree_item.data(0, Qt.UserRole)
                    if tree_data and tree_data.get("tipo") == "collection":
                        is_viewing_collection = True
                        current_col_name = tree_data.get("nombre")
                        
                count_str = f" ({len(file_paths)})" if len(file_paths) > 1 else ""

                if is_viewing_collection:
                    act_remove = menu.addAction(self.tr(f"Quitar de esta Colección{count_str}"))
                    act_remove.triggered.connect(lambda: [self._remove_file_from_collection(current_col_name, fp) for fp in file_paths])
                else:
                    submenu = menu.addMenu(self.tr(f"Añadir a Colección{count_str}"))
                    collections_list = [c for c in self.controller.collections.keys() if c != "Descargados"]
                    if collections_list:
                        for col_name in collections_list:
                            act_col = submenu.addAction(col_name)
                            act_col.triggered.connect(lambda checked=False, cn=col_name, paths=file_paths: [self._add_file_to_collection(cn, fp) for fp in paths])
                    else:
                        act_none = submenu.addAction(self.tr("(Sin colecciones)"))
                        act_none.setEnabled(False)

                if len(file_paths) == 1:
                    is_remote = file_paths[0].startswith("http://") or file_paths[0].startswith("https://")
                    if is_remote:
                        act_download = menu.addAction(get_svg_icon("download.svg"), self.tr("Descargar Medio"))
                        act_download.triggered.connect(self._on_download_clicked)
                    else:
                        act_reveal = menu.addAction(get_svg_icon("folder_open.svg"), self.tr("Abrir en Explorador"))
                        act_reveal.triggered.connect(self._on_reveal_clicked)
                
                from core.services.editor_integration_manager import EditorIntegrationManager
                editor_mgr = EditorIntegrationManager.get_instance()
                if editor_mgr and editor_mgr.active_editor:
                    active = editor_mgr.active_editor
                    if active == "premiere":
                        e_icon = get_svg_icon("premiere pro.svg")
                        e_name = "Premiere Pro"
                    elif active == "aftereffects":
                        e_icon = get_svg_icon("after effects.svg")
                        e_name = "After Effects"
                    elif active == "davinci":
                        e_icon = get_svg_icon("davinci resolve.svg")
                        e_name = "DaVinci Resolve"
                    else:
                        e_icon = QIcon()
                        e_name = "Editor"
                        
                    count = len(file_paths)
                    if count > 1:
                        act_send = menu.addAction(e_icon, self.tr(f"Enviar ({count}) medios a {e_name}"))
                    else:
                        act_send = menu.addAction(e_icon, self.tr(f"Enviar medio a {e_name}"))
                        
                    act_send.triggered.connect(self._on_send_editor_clicked)

                menu.addSeparator()

        # 2. Acciones Generales (Actualizar, Ordenar por, Vista)
        act_refresh = menu.addAction(get_contrast_svg_icon("refresh.svg"), self.tr("Actualizar Lista"))
        act_refresh.triggered.connect(self._refresh_current_view)
        menu.addSeparator()

        # Detectar si estamos navegando en modo online (Freesound)
        selected_tree = self.tree_folders.currentItem()
        is_online_mode = False
        if selected_tree:
            t_data = selected_tree.data(0, Qt.UserRole)
            if t_data and t_data.get("tipo") == "root_online":
                is_online_mode = True

        sort_sub = menu.addMenu(self.tr("Ordenar por"))

        if is_online_mode:
            options = [
                ("nombre", self.tr("Nombre")),
                ("duration", self.tr("Duración")),
                ("license", self.tr("Licencia")),
            ]
        else:
            options = [
                ("nombre", self.tr("Nombre")),
                ("size", self.tr("Tamaño")),
                ("tipo", self.tr("Tipo de Archivo")),
                ("mtime", self.tr("Fecha de Modificación")),
                ("ruta", self.tr("Ruta Completa")),
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
        act_asc = sort_sub.addAction(self.tr("Ascendente (A-Z, Menor a Mayor)"))
        act_asc.setCheckable(True)
        act_asc.setChecked(getattr(self, "sort_ascending", True))
        act_asc.triggered.connect(lambda: self._set_sort_direction(True))

        act_desc = sort_sub.addAction(self.tr("Descendente (Z-A, Mayor a Menor)"))
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

        menu.exec(view_widget.mapToGlobal(position))


    def _add_file_to_collection(self, col_name, file_path):
        success = self.controller.add_to_collection(col_name, file_path)
        if success:
            logger.info(f"EditingMediaTab: Archivo {os.path.basename(file_path)} añadido a colección {col_name}")
        else:
            logger.info(f"EditingMediaTab: El archivo ya se encuentra en la colección {col_name}")

    def _remove_file_from_collection(self, col_name, file_path):
        self.controller.remove_from_collection(col_name, file_path)
        self._update_media_list()

    def _on_sort_option_selected(self, key: str, label: str):
        self.sort_by = key
        if hasattr(self, "_update_media_list"):
            self._update_media_list()

    def _set_sort_direction(self, asc: bool):
        self.sort_ascending = asc
        if hasattr(self, "btn_sort_dir"):
            if asc:
                self.btn_sort_dir.setIcon(get_colored_svg_icon("arrow_upward_alt.svg", "#FFFFFF", size=16))
                self.btn_sort_dir.setIconSize(QSize(16, 16))
                self.btn_sort_dir.setToolTip(self.tr("Orden Ascendente (A-Z, Antiguos primero)"))
            else:
                self.btn_sort_dir.setIcon(get_colored_svg_icon("arrow_downward_alt.svg", "#FFFFFF", size=16))
                self.btn_sort_dir.setIconSize(QSize(16, 16))
                self.btn_sort_dir.setToolTip(self.tr("Orden Descendente (Z-A, Recientes primero)"))
        self._apply_active_filters_fast()
        self.preview_box.show_default_state()
        self._clear_metadata()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and event.source() is None:
            event.acceptProposedAction()
            from gui.styles import get_theme_token
            color = self._get_border_accent_color()
            fondo_secundario = get_theme_token('fondo_secundario', '#1e1e1e')
            if hasattr(self, "col2_container"):
                self.col2_container.setStyleSheet(f"""
                    QFrame#mediaListFrame {{
                        background-color: {fondo_secundario};
                        border: 2px dashed {color};
                        border-radius: 12px;
                    }}
                """)

    def _get_border_accent_color(self):
        # Usar getter para evitar imports circulares de estilos si es posible
        from gui.styles import get_theme_token
        return get_theme_token('acento_primario', '#B9E640')

    def dragLeaveEvent(self, event):
        self.setStyleSheet("")
        self._apply_custom_styles()

    def dropEvent(self, event):
        self.setStyleSheet("")
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
