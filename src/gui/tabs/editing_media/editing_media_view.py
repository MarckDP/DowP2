# src/gui/tabs/editing_media/editing_media_view.py
import os
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QLabel,
    QTreeWidget,
    QListWidget,
    QFrame,
    QLineEdit,
    QPushButton,
    QSlider,
    QScrollArea,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon

# Importar QtMultimedia de forma segura para reproducción de audio
try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    MULTIMEDIA_AVAILABLE = True
except ImportError:
    MULTIMEDIA_AVAILABLE = False

from core.logger.logger_manager import logger
from gui.styles import get_theme_token
from gui.widgets.animated_button import AnimatedButton
from core.tabs.editing_media.editing_media_logic import EditingMediaController

# Importar los widgets que fueron extraídos a sus propios archivos
from gui.tabs.editing_media.waveform_widget import AudioWaveformWidget
from gui.tabs.editing_media.preview_panel import PreviewContainerWidget
from gui.tabs.editing_media.editing_media_icons import (
    get_colored_svg_icon,
    get_colored_folder_icon,
    get_svg_icon,
    get_folder_icon,
)

# Importar Mixins que dividen la lógica
from gui.tabs.editing_media.editing_media_tree import TreeListMixin
from gui.tabs.editing_media.editing_media_playback import PlaybackMixin
from gui.tabs.editing_media.editing_media_freesound import FreesoundMixin
from core.tabs.editing_media.thumbnail_cache_manager import ThumbnailCacheManager

class EditingMediaTab(FreesoundMixin, PlaybackMixin, TreeListMixin, QWidget):
    """Pestaña 'Medios de Edición' con una distribución visual de tres paneles de 20/40/40."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        
        # Inicializar el controlador
        self.controller = EditingMediaController(self)
        
        self.selected_tree_item_data = None
        self.active_filter = "Todos"
        self.view_mode = "grid"
        self._metadata_cache = {}
        self.waveform_thread = None
        self._icon_cache = {}
        
        # Conectar señal del cargador de miniaturas en segundo plano
        ThumbnailCacheManager.get_instance().thumbnail_loaded.connect(self._on_thumbnail_loaded)
        
        # Inicializar cliente de Freesound y timer para debouncing de búsqueda
        from core.tabs.editing_media.freesound_client import FreesoundClient
        from PySide6.QtCore import QTimer
        self.freesound_client = FreesoundClient()
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._exec_online_search)
        self.online_search_thread = None
        self.online_results = []
        self.current_page = 1
        self.loading_next_page = False
        
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
        
        # Conectar señales del reproductor de video de la vista previa al waveform central
        if MULTIMEDIA_AVAILABLE and hasattr(self, "preview_box") and self.preview_box.media_player:
            self.preview_box.media_player.positionChanged.connect(self._on_video_position_changed)
        
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
        # Detener servidor de callback de OAuth si estuviera corriendo
        if hasattr(self, "_oauth_handler") and self._oauth_handler:
            self._oauth_handler.cancel()

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
        self.tree_folders.currentItemChanged.connect(self._on_tree_current_item_changed)
        self.tree_folders.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_folders.customContextMenuRequested.connect(self._show_tree_context_menu)
        layout.addWidget(self.tree_folders, 1)

        # Botón para Indexar Carpeta (único botón físico)
        self.btn_add_folder = AnimatedButton(self.tr("Indexar Carpeta"))
        self.btn_add_folder.setObjectName("analyzeButton")
        self.btn_add_folder.setFixedHeight(32)
        self.btn_add_folder.clicked.connect(self._on_add_folder_clicked)
        layout.addWidget(self.btn_add_folder)

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
        search_layout = QHBoxLayout()
        search_layout.setSpacing(6)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self.tr("Buscar medios..."))
        self.search_input.textChanged.connect(self._update_media_input_changed)
        search_layout.addWidget(self.search_input)

        self.btn_freesound_login = QPushButton()
        self.btn_freesound_login.setFixedSize(26, 26)
        self.btn_freesound_login.setStyleSheet(f"""
            QPushButton {{
                background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')};
            }}
        """)
        self.btn_freesound_login.clicked.connect(self._on_freesound_login_clicked)
        self.btn_freesound_login.setVisible(False)
        self._update_freesound_login_button()
        search_layout.addWidget(self.btn_freesound_login)

        layout.addLayout(search_layout)

        # Botones de filtro rápido + Selector de vista
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

        btn_bar.addStretch(1)

        # Botones de Modo de Vista (Lista / Cuadrícula)
        btn_mode_style = f"""
            QPushButton {{
                background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')};
            }}
            QPushButton:checked {{
                background-color: {get_theme_token('acento_primario', '#B9E640')};
                border-color: {get_theme_token('acento_primario', '#B9E640')};
            }}
        """

        self.btn_view_list = QPushButton()
        self.btn_view_list.setFixedSize(26, 26)
        self.btn_view_list.setCheckable(True)
        self.btn_view_list.setToolTip(self.tr("Vista de Lista"))
        list_icon = get_svg_icon("list_alt.svg")
        if list_icon.isNull():
            list_icon = get_svg_icon("view_list.svg")
        self.btn_view_list.setIcon(list_icon)
        self.btn_view_list.setIconSize(QSize(14, 14))
        self.btn_view_list.setStyleSheet(btn_mode_style)
        self.btn_view_list.clicked.connect(lambda: self.set_view_mode("list"))
        btn_bar.addWidget(self.btn_view_list)

        self.btn_view_grid = QPushButton()
        self.btn_view_grid.setFixedSize(26, 26)
        self.btn_view_grid.setCheckable(True)
        self.btn_view_grid.setToolTip(self.tr("Vista de Cuadrícula"))
        self.btn_view_grid.setIcon(get_svg_icon("grid_view.svg"))
        self.btn_view_grid.setIconSize(QSize(14, 14))
        self.btn_view_grid.setStyleSheet(btn_mode_style)
        self.btn_view_grid.clicked.connect(lambda: self.set_view_mode("grid"))
        btn_bar.addWidget(self.btn_view_grid)

        # Slider para ajustar el tamaño de iconos/miniaturas
        self.icon_size_slider = QSlider(Qt.Horizontal)
        self.icon_size_slider.setRange(48, 200)
        self.icon_size_slider.setValue(112)
        self.icon_size_slider.setFixedWidth(80)
        self.icon_size_slider.setToolTip(self.tr("Tamaño de Miniaturas"))
        self.icon_size_slider.valueChanged.connect(self._on_icon_size_changed)
        btn_bar.addWidget(self.icon_size_slider)

        layout.addLayout(btn_bar)

        # Lista de archivos multimedia
        self.media_list = QListWidget()
        self.media_list.setObjectName("mediaListWidget")
        self.media_list.setSpacing(0)
        self.media_list.setIconSize(QSize(16, 16))
        self.media_list.itemClicked.connect(self._on_media_clicked)
        self.media_list.currentItemChanged.connect(self._on_current_item_changed)
        
        # Activar menú contextual e infinite scroll
        self.media_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.media_list.customContextMenuRequested.connect(self._show_media_context_menu)
        self.media_list.verticalScrollBar().valueChanged.connect(self._on_list_scroll)
        
        layout.addWidget(self.media_list, 1)

        # Aplicar modo de vista por defecto (cuadrícula)
        self.set_view_mode("grid")

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

        # Controles inferiores (Play/Pausa, Volumen, Tiempo) — agrupados para poder ocultarlos en videos
        self.audio_controls_widget = QWidget()
        controls_layout = QHBoxLayout(self.audio_controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(8)

        self.btn_play = QPushButton()
        self.btn_play.setIcon(get_svg_icon("play_arrow.svg"))
        self.btn_play.setIconSize(QSize(14, 14))
        self.btn_play.setFixedSize(26, 26)
        self.btn_play.setStyleSheet(f"""
            QPushButton {{
                background-color: {get_theme_token('acento_secundario', '#1DC038')};
                border: none;
                border-radius: 13px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('acento_primario', '#B9E640')};
            }}
        """)
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

        audio_layout.addWidget(self.audio_controls_widget)

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

        # El panel de audio/forma de onda
        layout.addWidget(self.audio_panel)

        # Panel de Licencia Online
        self.license_panel = QFrame()
        self.license_panel.setObjectName("licensePanel")
        self.license_panel.setVisible(False)
        self.license_panel.setStyleSheet(f"""
            QFrame#licensePanel {{
                background-color: {get_theme_token('fondo_elemento', '#1e1e1e')};
                border: 1px solid {get_theme_token('acento_primario', '#B9E640')};
                border-radius: 8px;
            }}
        """)
        license_layout = QHBoxLayout(self.license_panel)
        license_layout.setContentsMargins(8, 4, 8, 4)

        self.lbl_license_icon = QLabel()
        copyright_icon = get_colored_svg_icon("copyright.svg", get_theme_token("acento_primario", "#B9E640"))
        self.lbl_license_icon.setPixmap(copyright_icon.pixmap(16, 16))
        license_layout.addWidget(self.lbl_license_icon)

        self.lbl_license_text = QLabel()
        self.lbl_license_text.setStyleSheet("font-size: 11px; font-weight: bold; color: #f5c2e7;")
        self.lbl_license_text.setWordWrap(True)
        self.lbl_license_text.setOpenExternalLinks(True)
        license_layout.addWidget(self.lbl_license_text, 1)

        layout.addWidget(self.license_panel)

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
        
        self.metadata_header_labels = {}
        for key, label_text in fields:
            row = QHBoxLayout()
            row.setSpacing(6)
            
            lbl_key = QLabel(label_text)
            lbl_key.setFixedWidth(90)
            lbl_key.setStyleSheet("color: #89b4fa; font-size: 11px; font-weight: bold;")
            self.metadata_header_labels[key] = lbl_key
            
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

        # Botones inferiores del panel de metadatos
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(8)

        # Botón para revelar en el explorador de archivos
        self.btn_reveal = AnimatedButton(self.tr("Revelar en Explorador"))
        self.btn_reveal.setEnabled(False)
        self.btn_reveal.clicked.connect(self._on_reveal_clicked)
        buttons_layout.addWidget(self.btn_reveal, 1)

        # Botón para descargar archivo de Freesound
        self.btn_download = AnimatedButton(self.tr("Descargar Audio"))
        self.btn_download.setEnabled(False)
        self.btn_download.setVisible(False)
        self.btn_download.clicked.connect(self._on_download_clicked)
        buttons_layout.addWidget(self.btn_download, 1)

        info_layout.addLayout(buttons_layout)

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
                padding: 4px;
                margin: 2px;
                border-radius: 8px;
                color: {get_theme_token('texto_principal', '#cdd6f4')};
                background-color: {get_theme_token('fondo_elemento', '#1c1c1e')};
                border: 1px solid transparent;
            }}
            QListWidget::item:hover {{
                background-color: {get_theme_token('seleccion_fondo', '#2d2d2d')};
                border-color: {get_theme_token('borde_normal', '#3d3d3d')};
            }}
            QListWidget::item:selected {{
                background-color: {get_theme_token('seleccion_fondo', '#2d2d2d')};
                border: 1.5px solid {get_theme_token('acento_primario', '#B9E640')};
                color: {get_theme_token('acento_primario', '#B9E640')};
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

    def set_view_mode(self, mode: str):
        """Alterna entre vista de lista y vista de cuadrícula/miniaturas."""
        self.view_mode = mode
        if mode == "grid":
            self.btn_view_grid.setChecked(True)
            self.btn_view_list.setChecked(False)
            self.icon_size_slider.setVisible(True)
            self.media_list.setViewMode(QListWidget.IconMode)
            self.media_list.setResizeMode(QListWidget.Adjust)
            self.media_list.setMovement(QListWidget.Static)
            self.media_list.setWordWrap(True)
            self.media_list.setSpacing(8)
            self._apply_icon_size(self.icon_size_slider.value())
        else:
            self.btn_view_list.setChecked(True)
            self.btn_view_grid.setChecked(False)
            self.icon_size_slider.setVisible(False)
            self.media_list.setViewMode(QListWidget.ListMode)
            self.media_list.setWordWrap(False)
            self.media_list.setSpacing(2)
            self.media_list.setGridSize(QSize())
            self.media_list.setIconSize(QSize(24, 24))

    def _on_icon_size_changed(self, val: int):
        if self.view_mode == "grid":
            self._apply_icon_size(val)

    def _apply_icon_size(self, size: int):
        self.media_list.setIconSize(QSize(size, size))
        self.media_list.setGridSize(QSize(size + 24, size + 46))

    def _on_thumbnail_loaded(self, file_path: str, thumb_path: str):
        """Callback asíncrono cuando una miniatura en segundo plano finaliza su generación."""
        icon = QIcon(thumb_path)
        for i in range(self.media_list.count()):
            item = self.media_list.item(i)
            data = item.data(Qt.UserRole)
            if isinstance(data, dict) and data.get("ruta") == file_path:
                item.setIcon(icon)
                break
