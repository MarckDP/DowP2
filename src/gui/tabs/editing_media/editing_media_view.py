# src/gui/tabs/editing_media/editing_media_view.py
import os
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QListWidget,
    QListWidgetItem,
    QFrame,
    QLineEdit,
    QPushButton,
    QSlider,
    QSizePolicy,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QMenu,
    QScrollArea,
)
from PySide6.QtCore import Qt, QSize, Signal, QUrl
from PySide6.QtGui import QIcon, QPixmap, QCursor

# Importar QtMultimedia de forma segura para reproducción de audio
try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    MULTIMEDIA_AVAILABLE = True
except ImportError:
    MULTIMEDIA_AVAILABLE = False

from core.logger.logger_manager import logger
from gui.styles import get_theme_token
from gui.widgets.animated_button import AnimatedButton
from core.tabs.editing_media.editing_media_logic import (
    EditingMediaController,
    WaveformExtractorThread,
    VALID_IMAGE_EXTS,
    VALID_VIDEO_EXTS,
    VALID_AUDIO_EXTS,
)

# Importar los widgets que fueron extraídos a sus propios archivos
from gui.tabs.editing_media.waveform_widget import AudioWaveformWidget
from gui.tabs.editing_media.preview_panel import PreviewContainerWidget


class EditingMediaTab(QWidget):
    """Pestaña 'Medios de Edición' con una distribución visual de tres paneles de 20/40/40."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        
        # Inicializar el controlador
        self.controller = EditingMediaController(self)
        
        self.selected_tree_item_data = None
        self.active_filter = "Todos"
        self._metadata_cache = {}
        self.waveform_thread = None
        
        # Inicializar reproductor de audio central para el espectro
        self.audio_player = None
        self.audio_output = None
        if MULTIMEDIA_AVAILABLE:
            try:
                self.audio_player = QMediaPlayer(self)
                self.audio_output = QAudioOutput(self)
                self.audio_player.setAudioOutput(self.audio_output)
                self.audio_output.setVolume(0.7)  # Volumen por defecto al 70%
                
                # Conectar señales del reproductor
                self.audio_player.positionChanged.connect(self._on_audio_position_changed)
                self.audio_player.durationChanged.connect(self._on_audio_duration_changed)
            except Exception as e:
                logger.error(f"EditingMediaTab: Error inicializando reproductor de audio: {e}")

        self.init_ui()
        
        # Conectar señales del controlador
        self.controller.disk_changed.connect(self._on_disk_changed)
        self.controller.collections_changed.connect(self._on_collections_changed)
        
        # Detener el Watchdog y la música cuando se destruya el widget
        self.destroyed.connect(self._cleanup)

        # Cargar los datos en el árbol por primera vez
        self._update_tree_view()
        self._update_media_list()  # Cargar lista inicial (mostrará todo al no haber selección)

    def init_ui(self):
        # Layout principal
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(15, 15, 15, 15)
        self.main_layout.setSpacing(8)

        # ── Splitter Horizontal Principal ─────────────────────────────────────
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(8)
        self.main_layout.addWidget(self.splitter, 1)

        # 1. Columna Izquierda (20%): Carpetas Indexadas (Acordeón)
        self.col1_container = self._build_left_column()
        self.splitter.addWidget(self.col1_container)

        # 2. Columna Central (40%): Lista de Medios e Instrumento de Audio
        self.col2_container = self._build_center_column()
        self.splitter.addWidget(self.col2_container)

        # 3. Columna Derecha (40%): Vista Previa e Info Técnica
        self.col3_container = self._build_right_column()
        self.splitter.addWidget(self.col3_container)

        # Proporción inicial 20% - 40% - 40%
        self.splitter.setSizes([240, 480, 480])

        # Asegurar anchos mínimos
        self.col1_container.setMinimumWidth(200)
        self.col2_container.setMinimumWidth(300)
        self.col3_container.setMinimumWidth(300)

        # Aplicar hojas de estilo para contenedores y listas
        self._apply_custom_styles()

    def _cleanup(self):
        """Detiene el watchdog y cualquier reproducción activa al cerrar."""
        self.controller.stop_watcher()
        self._stop_audio_playback()
        self.preview_box.stop_media()
        if hasattr(self, "waveform_thread") and self.waveform_thread and self.waveform_thread.isRunning():
            self.waveform_thread.terminate()
            self.waveform_thread.wait()

    def _build_left_column(self) -> QFrame:
        col = QFrame()
        col.setObjectName("sidebarFrame")
        layout = QVBoxLayout(col)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        lbl_section = QLabel(self.tr("Carpetas & Colecciones"))
        lbl_section.setStyleSheet("font-weight: bold; font-size: 14px; color: white;")
        layout.addWidget(lbl_section)

        # QTreeWidget en modo acordeón/árbol de carpetas
        self.tree_folders = QTreeWidget()
        self.tree_folders.setHeaderHidden(True)
        self.tree_folders.setObjectName("accordionTree")
        self.tree_folders.setAnimated(True)
        self.tree_folders.setIndentation(14)
        self.tree_folders.itemClicked.connect(self._on_tree_item_clicked)
        layout.addWidget(self.tree_folders, 1)

        # ── PANEL DE BOTONES (4 acciones: 2 para Carpetas, 2 para Colecciones) ──
        buttons_layout = QVBoxLayout()
        buttons_layout.setSpacing(5)

        # Fila 1: Carpetas Físicas
        row_folders = QHBoxLayout()
        row_folders.setSpacing(6)
        
        self.btn_add_folder = AnimatedButton(self.tr("Indexar Carpeta"))
        self.btn_add_folder.setObjectName("analyzeButton")
        self.btn_add_folder.setFixedHeight(30)
        self.btn_add_folder.clicked.connect(self._on_add_folder_clicked)
        
        self.btn_remove_folder = QPushButton(self.tr("Desvincular"))
        self.btn_remove_folder.setFixedHeight(30)
        self.btn_remove_folder.setEnabled(False)
        self.btn_remove_folder.clicked.connect(self._on_remove_folder_clicked)
        
        row_folders.addWidget(self.btn_add_folder, 1)
        row_folders.addWidget(self.btn_remove_folder, 1)
        buttons_layout.addLayout(row_folders)

        # Fila 2: Colecciones Virtuales
        row_collections = QHBoxLayout()
        row_collections.setSpacing(6)
        
        self.btn_add_col = QPushButton(self.tr("Nueva Col."))
        self.btn_add_col.setFixedHeight(30)
        self.btn_add_col.clicked.connect(self._on_add_collection_clicked)
        
        self.btn_remove_col = QPushButton(self.tr("Borrar Col."))
        self.btn_remove_col.setFixedHeight(30)
        self.btn_remove_col.setEnabled(False)
        self.btn_remove_col.clicked.connect(self._on_remove_collection_clicked)
        
        row_collections.addWidget(self.btn_add_col, 1)
        row_collections.addWidget(self.btn_remove_col, 1)
        buttons_layout.addLayout(row_collections)

        layout.addLayout(buttons_layout)

        # Estilo común para botones secundarios de la barra lateral
        secundary_btn_style = f"""
            QPushButton {{
                background-color: {get_theme_token('boton_secundario_fondo', '#2d2d2d')};
                color: {get_theme_token('boton_secundario_texto', '#cdd6f4')};
                border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-radius: 8px;
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('boton_secundario_hover', '#3a3a3a')};
            }}
            QPushButton:disabled {{
                background-color: #1e1e1e;
                color: #555555;
                border-color: #2d2d2d;
            }}
        """
        self.btn_remove_folder.setStyleSheet(secundary_btn_style)
        self.btn_add_col.setStyleSheet(secundary_btn_style)
        self.btn_remove_col.setStyleSheet(secundary_btn_style)

        return col

    def _build_center_column(self) -> QFrame:
        col = QFrame()
        col.setObjectName("mediaListFrame")
        layout = QVBoxLayout(col)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Título
        lbl_section = QLabel(self.tr("Lista de Medios"))
        lbl_section.setStyleSheet("font-weight: bold; font-size: 14px; color: white;")
        layout.addWidget(lbl_section)

        # Buscador
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self.tr("Buscar medios..."))
        self.search_input.textChanged.connect(self._update_media_list)
        layout.addWidget(self.search_input)

        # Botones de filtro rápido
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(4)
        self.filter_buttons = []
        for text in ["Todos", "Imágenes", "Videos", "Audios"]:
            btn = QPushButton(self.tr(text))
            btn.setCheckable(True)
            if text == "Todos":
                btn.setChecked(True)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                    border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                    padding: 4px 8px;
                    font-size: 11px;
                    border-radius: 6px;
                }}
                QPushButton:checked {{
                    background-color: {get_theme_token('acento_primario', '#B9E640')};
                    color: {get_theme_token('fondo_principal', '#0a0a0a')};
                    font-weight: bold;
                }}
            """)
            btn.clicked.connect(self._on_filter_button_clicked)
            btn_bar.addWidget(btn)
            self.filter_buttons.append(btn)
        layout.addLayout(btn_bar)

        # Lista de archivos multimedia
        self.media_list = QListWidget()
        self.media_list.setObjectName("mediaListWidget")
        self.media_list.setSpacing(0)
        self.media_list.itemClicked.connect(self._on_media_clicked)
        
        # Activar menú contextual
        self.media_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.media_list.customContextMenuRequested.connect(self._show_media_context_menu)
        
        layout.addWidget(self.media_list, 1)

        # ── ESPECTRO DE AUDIO INTEGRADO (A pie de columna, oculto por defecto) ──
        self.audio_panel = QFrame()
        self.audio_panel.setObjectName("audioSpectrumPanel")
        self.audio_panel.setVisible(False)
        audio_layout = QVBoxLayout(self.audio_panel)
        audio_layout.setContentsMargins(8, 8, 8, 8)
        audio_layout.setSpacing(6)

        # Título interno
        lbl_audio_title = QLabel(self.tr("Visualizador de Espectro"))
        lbl_audio_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #f5c2e7;")
        audio_layout.addWidget(lbl_audio_title)

        # El widget gráfico del espectro
        self.waveform_widget = AudioWaveformWidget()
        self.waveform_widget.seek_requested.connect(self._on_waveform_seek_requested)
        audio_layout.addWidget(self.waveform_widget)

        # Controles inferiores (Play/Pausa, Volumen, Tiempo)
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(8)

        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedSize(26, 26)
        self.btn_play.setStyleSheet(f"border-radius: 13px; background-color: {get_theme_token('acento_primario', '#B9E640')}; color: black; font-weight: bold;")
        self.btn_play.clicked.connect(self._on_play_clicked)
        controls_layout.addWidget(self.btn_play)

        self.lbl_time = QLabel("00:00 / 00:00")
        self.lbl_time.setStyleSheet("font-size: 11px; color: #a6adc8;")
        controls_layout.addWidget(self.lbl_time)

        controls_layout.addStretch(1)

        lbl_vol = QLabel("Vol:")
        lbl_vol.setStyleSheet("font-size: 11px; color: #a6adc8;")
        controls_layout.addWidget(lbl_vol)

        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setFixedWidth(80)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(70)
        self.vol_slider.valueChanged.connect(self._on_volume_changed)
        controls_layout.addWidget(self.vol_slider)

        audio_layout.addLayout(controls_layout)
        layout.addWidget(self.audio_panel)

        return col

    def _build_right_column(self) -> QFrame:
        col = QFrame()
        col.setObjectName("previewFrame")
        layout = QVBoxLayout(col)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        lbl_section = QLabel(self.tr("Vista Previa & Detalles"))
        lbl_section.setStyleSheet("font-weight: bold; font-size: 14px; color: white;")
        layout.addWidget(lbl_section)

        # Contenedor de Vista Previa Cuadrado
        self.preview_box = PreviewContainerWidget()
        layout.addWidget(self.preview_box)

        # Contenedor de Información Técnica (Metadatos)
        self.info_box = QFrame()
        self.info_box.setObjectName("infoBoxFrame")
        info_layout = QVBoxLayout(self.info_box)
        info_layout.setContentsMargins(10, 10, 10, 10)
        info_layout.setSpacing(6)

        lbl_info_title = QLabel(self.tr("Información Técnica"))
        lbl_info_title.setStyleSheet("font-weight: bold; font-size: 12px; color: #a6adc8;")
        info_layout.addWidget(lbl_info_title)

        # Crear QScrollArea para los metadatos
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)
        scroll_area.setStyleSheet("background: transparent; border: none;")
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Estilizar el scrollbar de manera elegante
        scroll_area.verticalScrollBar().setStyleSheet("""
            QScrollBar:vertical {
                border: none;
                background: #111;
                width: 6px;
                margin: 0px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: #333;
                min-height: 20px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: #1DC038;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
                height: 0px;
            }
        """)

        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 8, 0)
        scroll_layout.setSpacing(6)

        # Grid de metadatos ampliado
        self.metadata_labels = {}
        fields = [
            ("nombre", self.tr("Nombre:")),
            ("ruta", self.tr("Ruta:")),
            ("tipo", self.tr("Tipo:")),
            ("tamaño", self.tr("Tamaño:")),
            ("creado", self.tr("Creado:")),
            ("modificado", self.tr("Modificado:")),
            ("duración", self.tr("Duración:")),
            ("resolución", self.tr("Resolución:")),
            ("video_codec", self.tr("Códec Video:")),
            ("video_profile", self.tr("Perfil Video:")),
            ("fps", self.tr("FPS:")),
            ("aspecto", self.tr("Rel. Aspecto:")),
            ("bitrate_video", self.tr("Bitrate Video:")),
            ("color", self.tr("Espacio Color:")),
            ("audio_codec", self.tr("Códec Audio:")),
            ("samplerate", self.tr("Muestreo:")),
            ("canales", self.tr("Canales:")),
            ("bitrate_audio", self.tr("Bitrate Audio:")),
        ]
        
        for key, label_text in fields:
            row = QHBoxLayout()
            row.setSpacing(6)
            
            lbl_key = QLabel(label_text)
            lbl_key.setFixedWidth(90)
            lbl_key.setStyleSheet("color: #89b4fa; font-size: 11px; font-weight: bold;")
            
            lbl_val = QLabel("-")
            lbl_val.setStyleSheet("color: #cdd6f4; font-size: 11px;")
            lbl_val.setWordWrap(True)
            self.metadata_labels[key] = lbl_val
            
            row.addWidget(lbl_key)
            row.addWidget(lbl_val, 1)
            scroll_layout.addLayout(row)

        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_content)
        info_layout.addWidget(scroll_area, 1)

        # Botón para revelar en el explorador de archivos
        self.btn_reveal = AnimatedButton(self.tr("Revelar en Explorador"))
        self.btn_reveal.setEnabled(False)
        self.btn_reveal.clicked.connect(self._on_reveal_clicked)
        info_layout.addWidget(self.btn_reveal)

        layout.addWidget(self.info_box, 1)

        return col

    def _apply_custom_styles(self):
        """Aplica colores y bordes usando el sistema de tokens de temas."""
        fondo_secundario = get_theme_token('fondo_secundario', '#1e1e1e')
        borde_color = get_theme_token('borde_normal', '#2d2d2d')

        box_style = f"""
            QFrame {{
                background-color: {fondo_secundario};
                border: 1px solid {borde_color};
                border-radius: 12px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """
        
        self.col1_container.setStyleSheet(box_style)
        self.col2_container.setStyleSheet(box_style)
        self.col3_container.setStyleSheet(box_style)

        # Estilo para el splitter horizontal (manejador transparente con línea vertical delgada en el centro)
        self.splitter.setStyleSheet(f"""
            QSplitter::handle:horizontal {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 transparent,
                    stop:0.45 transparent,
                    stop:0.5 {borde_color},
                    stop:0.55 transparent,
                    stop:1 transparent);
                width: 8px;
            }}
        """)

        # Estilo para el panel de audio
        self.audio_panel.setStyleSheet(f"""
            QFrame#audioSpectrumPanel {{
                background-color: {get_theme_token('fondo_principal', '#0a0a0a')};
                border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-radius: 8px;
            }}
        """)

        # Estilo para la lista de medios (Columna Central)
        list_style = f"""
            QListWidget {{
                background-color: {get_theme_token('fondo_principal', '#0a0a0a')};
                border: 1px solid {borde_color};
                padding: 5px;
            }}
            QListWidget::item {{
                padding: 2px 6px;
                margin: 0px;
                border-radius: 4px;
                color: {get_theme_token('texto_principal', '#cdd6f4')};
            }}
            QListWidget::item:hover {{
                background-color: {get_theme_token('seleccion_fondo', '#2d2d2d')};
            }}
            QListWidget::item:selected {{
                background-color: {get_theme_token('acento_primario', '#B9E640')};
                color: {get_theme_token('fondo_principal', '#0a0a0a')};
                font-weight: bold;
            }}
        """
        self.media_list.setStyleSheet(list_style)

        # Obtener rutas absolutas para las imágenes del árbol
        src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        closed_arrow = os.path.join(src_dir, "assets", "icons", "svg", "tree_closed.svg").replace("\\", "/")
        open_arrow = os.path.join(src_dir, "assets", "icons", "svg", "tree_open.svg").replace("\\", "/")

        # Estilo para el árbol de carpetas (Columna Izquierda)
        tree_style = f"""
            QTreeWidget {{
                background-color: {get_theme_token('fondo_principal', '#0a0a0a')};
                border: 1px solid {borde_color};
                padding: 5px;
                font-size: 11px;
            }}
            QTreeWidget::item {{
                padding: 4px 5px;
                border-radius: 4px;
                color: {get_theme_token('texto_principal', '#cdd6f4')};
            }}
            QTreeWidget::item:hover {{
                background-color: {get_theme_token('seleccion_fondo', '#2d2d2d')};
            }}
            QTreeWidget::item:selected {{
                background-color: {get_theme_token('seleccion_fondo', '#2d2d2d')};
                color: {get_theme_token('acento_primario', '#B9E640')};
                font-weight: bold;
            }}
            QTreeView::branch:has-children:closed:adjoins-item {{
                image: url("{closed_arrow}");
            }}
            QTreeView::branch:has-children:open:adjoins-item {{
                image: url("{open_arrow}");
            }}
            QTreeView::branch:selected {{
                background-color: {get_theme_token('seleccion_fondo', '#2d2d2d')};
            }}
            QTreeView::branch:hover {{
                background-color: {get_theme_token('seleccion_fondo', '#2d2d2d')};
            }}
        """
        self.tree_folders.setStyleSheet(tree_style)

    # ── Población y Control de Vistas del Árbol ──────────────────────────────
    def _update_tree_view(self):
        """Reconstruye el árbol de carpetas lógicas y físicas de forma jerárquica."""
        selected = self.tree_folders.currentItem()
        selected_data = None
        if selected:
            selected_data = selected.data(0, Qt.UserRole)

        self.tree_folders.clear()

        # 1. Nodo Raíz de Directorios Físicos
        self.physical_root = QTreeWidgetItem(self.tree_folders, [self.tr("📁 Directorios Físicos")])
        self.physical_root.setData(0, Qt.UserRole, {"tipo": "root_physical"})
        self.physical_root.setExpanded(True)

        for folder in self.controller.indexed_folders:
            folder_name = os.path.basename(folder) or folder
            item = QTreeWidgetItem(self.physical_root, [folder_name])
            item.setData(0, Qt.UserRole, {"tipo": "folder", "ruta": folder})
            item.setExpanded(True)
            self._add_folder_subdirs(item, folder)

        # 2. Nodo Raíz de Colecciones Virtuales
        self.virtual_root = QTreeWidgetItem(self.tree_folders, [self.tr("🌟 Colecciones Virtuales")])
        self.virtual_root.setData(0, Qt.UserRole, {"tipo": "root_virtual"})
        self.virtual_root.setExpanded(True)

        for col_name in self.controller.collections.keys():
            item = QTreeWidgetItem(self.virtual_root, [col_name])
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
                    elif tipo in ["root_physical", "root_virtual"]:
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
                    child = QTreeWidgetItem(parent_item, [name])
                    child.setData(0, Qt.UserRole, {"tipo": "subfolder", "ruta": subpath.replace("\\", "/")})
                    self._add_folder_subdirs(child, subpath)
        except Exception as e:
            logger.debug(f"EditingMediaTab: Error al buscar subcarpetas en {folder_path}: {e}")

    def _update_button_states(self):
        """Habilita o deshabilita botones según el ítem seleccionado en el árbol."""
        selected = self.tree_folders.currentItem()
        if not selected:
            self.btn_remove_folder.setEnabled(False)
            self.btn_remove_col.setEnabled(False)
            return

        data = selected.data(0, Qt.UserRole)
        if not data:
            self.btn_remove_folder.setEnabled(False)
            self.btn_remove_col.setEnabled(False)
            return

        tipo = data.get("tipo")
        
        # Desvincular carpeta solo activo en raíces físicas añadidas manualmente
        self.btn_remove_folder.setEnabled(tipo == "folder")
        
        # Eliminar colección solo activo para colecciones virtuales creadas
        self.btn_remove_col.setEnabled(tipo == "collection")

    # ── Población y Control de la Lista de Medios ──────────────────────────
    def _update_media_list(self):
        """Refresca la lista central de medios según el ítem activo del árbol y los filtros."""
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
        else:
            # Si no hay selección (o se seleccionó la raíz de carpetas/colecciones), mostrar TODOS los archivos indexados
            media_items = self.controller.get_all_media_files()

        # Aplicar filtros (búsqueda de texto y tipo de medio)
        search_query = self.search_input.text().lower().strip()

        for item in media_items:
            # 1. Filtro de búsqueda
            if search_query and search_query not in item["nombre"].lower():
                continue

            # 2. Filtro de categoría
            item_type = item["tipo"]
            if self.active_filter == "Imágenes" and item_type != "imagen":
                continue
            elif self.active_filter == "Videos" and item_type != "video":
                continue
            elif self.active_filter == "Audios" and item_type != "audio":
                continue

            # Construir visual del item
            icon_str = "🎥 " if item_type == "video" else ("🖼️ " if item_type == "imagen" else "🎵 ")
            list_item = QListWidgetItem(icon_str + item["nombre"])
            list_item.setData(Qt.UserRole, item)
            self.media_list.addItem(list_item)

    # ── Gestión de Señales y Eventos del Controlador ────────────────────────
    def _on_disk_changed(self):
        """Callback del watchdog cuando hay cambios en las carpetas vigiladas."""
        self._update_tree_view()
        self._update_media_list()

    def _on_collections_changed(self):
        """Callback cuando se modifican las colecciones virtuales."""
        self._update_tree_view()
        self._update_media_list()

    # ── Eventos de Botones de Gestión (Sidebar) ──────────────────────────────
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

    # ── Eventos de interacción de selección en las Vistas ────────────────────
    def _on_tree_item_clicked(self, item, column):
        self._update_button_states()
        self._update_media_list()

    def _on_media_clicked(self, list_item):
        item_data = list_item.data(Qt.UserRole)
        if not item_data:
            return

        name = item_data["nombre"]
        tipo = item_data["tipo"]
        path = item_data["ruta"]

        # Detener cualquier audio previo al cambiar de archivo
        self._stop_audio_playback()

        # 1. Controlar la visualización del espectro de audio
        if tipo == "audio":
            self.audio_panel.setVisible(True)
            self.waveform_widget.set_audio_path(path)
            self.waveform_widget.set_playback_ratio(0.0)
            
            # Detener hilo de extracción previo si estuviera corriendo
            if hasattr(self, "waveform_thread") and self.waveform_thread and self.waveform_thread.isRunning():
                self.waveform_thread.terminate()
                self.waveform_thread.wait()
                
            # Calcular cantidad ideal de picos basándose en el ancho actual del widget
            w_width = self.waveform_widget.width()
            num_peaks = max(50, min((w_width - 24) // 5, 180)) if w_width > 50 else 80
            
            # Iniciar extracción asíncrona de amplitudes reales
            self.waveform_thread = WaveformExtractorThread(path, num_peaks, self)
            self.waveform_thread.finished_extraction.connect(self.waveform_widget.set_peaks)
            self.waveform_thread.start()

            if self.audio_player:
                try:
                    self.audio_player.setSource(QUrl.fromLocalFile(path))
                    self.lbl_time.setText("00:00 / " + item_data["duración"])
                except Exception as e:
                    logger.error(f"EditingMediaTab: Error cargando fuente de audio: {e}")
        else:
            self.audio_panel.setVisible(False)

        # 2. Actualizar Vista Previa (Columna Derecha - Superior) con reproducción real
        if tipo == "imagen":
            self.preview_box.show_image_preview(path)
        elif tipo == "video":
            self.preview_box.show_video_preview(path)
        elif tipo == "audio":
            self.preview_box.show_audio_preview(path)

        # 3. Actualizar Detalles e Info Técnica (Columna Derecha - Inferior)
        self.metadata_labels["nombre"].setText(name)
        self.metadata_labels["ruta"].setText(path)
        self.metadata_labels["tipo"].setText(tipo.upper())
        self.metadata_labels["tamaño"].setText(item_data["tamaño"])
        
        # Obtener metadatos ricos de la cache o extraerlos
        if path not in self._metadata_cache:
            self._metadata_cache[path] = self._extract_rich_metadata(path, tipo)
            
        rich_meta = self._metadata_cache[path]
        
        # Llenar todos los campos en la UI
        self.metadata_labels["creado"].setText(rich_meta.get("creado", "-"))
        self.metadata_labels["modificado"].setText(rich_meta.get("modificado", "-"))
        self.metadata_labels["duración"].setText(rich_meta.get("duración", "-"))
        self.metadata_labels["resolución"].setText(rich_meta.get("resolución", "-"))
        self.metadata_labels["video_codec"].setText(rich_meta.get("video_codec", "-"))
        self.metadata_labels["video_profile"].setText(rich_meta.get("video_profile", "-"))
        self.metadata_labels["fps"].setText(rich_meta.get("fps", "-"))
        self.metadata_labels["aspecto"].setText(rich_meta.get("aspecto", "-"))
        self.metadata_labels["bitrate_video"].setText(rich_meta.get("bitrate_video", "-"))
        self.metadata_labels["color"].setText(rich_meta.get("color", "-"))
        self.metadata_labels["audio_codec"].setText(rich_meta.get("audio_codec", "-"))
        self.metadata_labels["samplerate"].setText(rich_meta.get("samplerate", "-"))
        self.metadata_labels["canales"].setText(rich_meta.get("canales", "-"))
        self.metadata_labels["bitrate_audio"].setText(rich_meta.get("bitrate_audio", "-"))

        self.btn_reveal.setEnabled(True)

    def _extract_rich_metadata(self, path: str, tipo: str) -> dict:
        import datetime
        import re
        import subprocess
        
        meta = {
            "creado": "-",
            "modificado": "-",
            "duración": "-",
            "resolución": "-",
            "video_codec": "-",
            "video_profile": "-",
            "fps": "-",
            "aspecto": "-",
            "bitrate_video": "-",
            "color": "-",
            "audio_codec": "-",
            "samplerate": "-",
            "canales": "-",
            "bitrate_audio": "-"
        }
        
        if not os.path.exists(path):
            return meta
            
        # 1. Fechas físicas del archivo
        try:
            stat_info = os.stat(path)
            # Fecha de modificación
            mtime = datetime.datetime.fromtimestamp(stat_info.st_mtime)
            meta["modificado"] = mtime.strftime("%Y-%m-%d %H:%M:%S")
            
            # Fecha de creación (Windows st_ctime es creación; Unix es metadatos)
            ctime = datetime.datetime.fromtimestamp(stat_info.st_ctime)
            meta["creado"] = ctime.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            logger.error(f"EditingMediaTab: Error al obtener fechas del archivo: {e}")
            
        # 2. Detalles específicos según tipo
        if tipo == "imagen":
            try:
                from PySide6.QtGui import QImageReader, QImage
                reader = QImageReader(path)
                if reader.canRead():
                    size = reader.size()
                    meta["resolución"] = f"{size.width()}x{size.height()}"
                    fmt = reader.format().data().decode('utf-8', errors='ignore').upper()
                    meta["video_codec"] = fmt
                    
                    img = QImage(path)
                    if not img.isNull():
                        fmt_name = str(img.format()).split('.')[-1]
                        meta["color"] = fmt_name
            except Exception as e:
                logger.error(f"EditingMediaTab: Error al extraer metadatos de imagen: {e}")
                
        elif tipo in ("video", "audio"):
            from core.setup.ffmpeg_setup import get_ffmpeg_dir, get_platform_info, check_ffmpeg
            if check_ffmpeg():
                try:
                    info = get_platform_info()
                    ffmpeg_exe = os.path.join(get_ffmpeg_dir(), info["binary_name"])
                    cmd = [ffmpeg_exe, "-hide_banner", "-i", path]
                    
                    startupinfo = None
                    if os.name == 'nt':
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        
                    process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        startupinfo=startupinfo,
                        text=True,
                        encoding='utf-8',
                        errors='ignore'
                    )
                    _, stderr = process.communicate(timeout=5)
                    
                    # Parsear duración
                    dur_match = re.search(r"Duration:\s*(\d{2}:\d{2}:\d{2}(?:\.\d+)?)", stderr)
                    if dur_match:
                        dur = dur_match.group(1)
                        if '.' in dur:
                            dur = dur.split('.')[0]
                        meta["duración"] = dur
                        
                    # Parsear Video Stream
                    video_match = re.search(r"Stream #\d+:\d+.*Video:\s*([^\n]+)", stderr)
                    if video_match:
                        video_info = video_match.group(1)
                        parts = [p.strip() for p in video_info.split(',')]
                        
                        codec_part = parts[0]
                        profile_m = re.search(r"\(([^)]+)\)", codec_part)
                        if profile_m:
                            meta["video_profile"] = profile_m.group(1)
                        codec_clean = re.sub(r"\s*\([^)]*\)", "", codec_part)
                        meta["video_codec"] = codec_clean.upper()
                        
                        for part in parts:
                            res_m = re.search(r"\b(\d{2,5})x(\d{2,5})\b", part)
                            if res_m:
                                meta["resolución"] = res_m.group(0)
                            if "DAR" in part or "SAR" in part:
                                meta["aspecto"] = part
                                
                        for part in parts:
                            if "fps" in part:
                                meta["fps"] = part
                            if "kb/s" in part:
                                meta["bitrate_video"] = part
                                
                        for part in parts:
                            if any(x in part.lower() for x in ["yuv", "rgb", "bgr", "gray", "nv12", "nv21", "p010"]):
                                meta["color"] = part
                                
                    # Parsear Audio Stream
                    audio_match = re.search(r"Stream #\d+:\d+.*Audio:\s*([^\n]+)", stderr)
                    if audio_match:
                        audio_info = audio_match.group(1)
                        parts = [p.strip() for p in audio_info.split(',')]
                        
                        codec_part = parts[0]
                        codec_clean = re.sub(r"\s*\([^)]*\)", "", codec_part)
                        meta["audio_codec"] = codec_clean.upper()
                        
                        if len(parts) > 1:
                            meta["samplerate"] = parts[1]
                        if len(parts) > 2:
                            meta["canales"] = parts[2]
                        for part in parts:
                            if "kb/s" in part:
                                meta["bitrate_audio"] = part
                                
                except Exception as e:
                    logger.error(f"EditingMediaTab: Error al extraer metadatos vía ffmpeg: {e}")
                    
        return meta

    # ── Métodos de Control para el Reproductor de Audio Central ─────────────
    def _on_play_clicked(self):
        if not self.audio_player:
            return
        
        state = self.audio_player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.audio_player.pause()
            self.btn_play.setText("▶")
        else:
            self.audio_player.play()
            self.btn_play.setText("⏸")

    def _on_volume_changed(self, value):
        if self.audio_output:
            self.audio_output.setVolume(value / 100.0)

    def _on_waveform_seek_requested(self, ratio):
        if self.audio_player and self.audio_player.duration() > 0:
            pos = int(self.audio_player.duration() * ratio)
            self.audio_player.setPosition(pos)

    def _on_audio_position_changed(self, position):
        if not self.audio_player:
            return
        duration = self.audio_player.duration()
        if duration > 0:
            ratio = position / duration
            self.waveform_widget.set_playback_ratio(ratio)
            
            # Formatear tiempos transcurridos
            pos_sec = position // 1000
            dur_sec = duration // 1000
            
            pos_min = pos_sec // 60
            pos_sec = pos_sec % 60
            dur_min = dur_sec // 60
            dur_sec = dur_sec % 60
            
            self.lbl_time.setText(f"{pos_min:02d}:{pos_sec:02d} / {dur_min:02d}:{dur_sec:02d}")

    def _on_audio_duration_changed(self, duration):
        if duration > 0:
            dur_sec = duration // 1000
            dur_min = dur_sec // 60
            dur_sec = dur_sec % 60
            self.lbl_time.setText(f"00:00 / {dur_min:02d}:{dur_sec:02d}")

    def _stop_audio_playback(self):
        if self.audio_player:
            try:
                self.audio_player.stop()
                self.btn_play.setText("▶")
            except Exception:
                pass

    def _clear_metadata(self):
        for lbl in self.metadata_labels.values():
            lbl.setText("-")
        self.btn_reveal.setEnabled(False)

    def _on_reveal_clicked(self):
        selected = self.media_list.currentItem()
        if not selected:
            return
        item_data = selected.data(Qt.UserRole)
        if item_data:
            path = item_data["ruta"]
            if os.path.exists(path):
                if os.name == "nt":
                    os.startfile(os.path.dirname(path))
                else:
                    from PySide6.QtGui import QDesktopServices
                    from PySide6.QtCore import QUrl
                    QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    def _on_filter_button_clicked(self):
        """Maneja el cambio de filtro y deselecciona los otros botones."""
        sender = self.sender()
        self.active_filter = sender.text()
        
        for btn in self.filter_buttons:
            if btn != sender:
                btn.setChecked(False)
        
        # Si se desmarca a sí mismo, por defecto vuelve a "Todos"
        if not sender.isChecked():
            self.filter_buttons[0].setChecked(True)
            self.active_filter = "Todos"
            
        self._update_media_list()

    # ── Menú Contextual (Click derecho sobre la lista central) ───────────────
    def _show_media_context_menu(self, position):
        item = self.media_list.itemAt(position)
        if not item:
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

        menu.addSeparator()
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
        self.preview_box.show_default_state()
        self._clear_metadata()

    # ── Soporte Drag and Drop Físico (Indexador Rápido) ─────────────────────
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(f"border: 2px dashed {get_theme_token('acento_primario', '#B9E640')};")

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
