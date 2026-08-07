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
from PySide6.QtCore import Qt, QSize, QEvent, QPoint
from PySide6.QtGui import QIcon

# Importar QtMultimedia de forma segura para reproducción de audio
try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    MULTIMEDIA_AVAILABLE = True
except ImportError:
    MULTIMEDIA_AVAILABLE = False

from core.logger.logger_manager import logger
from gui.styles import get_theme_token, apply_player_play_button_style, apply_player_loop_button_style
from gui.widgets.animated_button import AnimatedButton
from core.tabs.editing_media.editing_media_logic import EditingMediaController

# Importar los widgets que fueron extraídos a sus propios archivos
from gui.tabs.editing_media.waveform_widget import AudioWaveformWidget
from gui.tabs.editing_media.preview_panel import PreviewContainerWidget
from gui.widgets.volume_control import VolumeControlWidget
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
from gui.tabs.editing_media.editing_media_icons import LoadingSpinnerWidget
from core.tabs.editing_media.thumbnail_cache_manager import ThumbnailCacheManager
from core.utils.config_manager import get_config, save_config

class EditingMediaTab(FreesoundMixin, PlaybackMixin, TreeListMixin, QWidget):
    """Pestaña 'Medios de Edición' con una distribución visual de tres paneles de 20/40/40."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        
        # Inicializar el controlador
        self.controller = EditingMediaController(self)
        
        self.selected_tree_item_data = None
        self.active_filter = "Todos"
        
        # Restaurar preferencias persistentes de vista
        cfg = get_config()
        self.view_mode = cfg.get("editing_media_view_mode", "grid")
        self._saved_icon_size = cfg.get("editing_media_icon_size", 112)
        
        self.sort_by = "nombre"
        self.sort_ascending = True
        self._metadata_cache = {}
        self.waveform_thread = None
        self._icon_cache = {}
        
        # Conectar señal del cargador de miniaturas y metadatos en segundo plano
        ThumbnailCacheManager.get_instance().thumbnail_loaded.connect(self._on_thumbnail_loaded)
        from core.tabs.editing_media.ffprobe_metadata_manager import FFprobeMetadataManager
        FFprobeMetadataManager.get_instance().metadata_ready.connect(self._on_async_metadata_ready)
        
        # Temporizador de retardo (debounce) para búsquedas locales (250ms)
        from PySide6.QtCore import QTimer
        self.local_search_timer = QTimer(self)
        self.local_search_timer.setSingleShot(True)
        self.local_search_timer.setInterval(250)
        self.local_search_timer.timeout.connect(self._on_local_search_timer_timeout)

        # Temporizador de retardo (debounce) para persistir tamaño de cuadrícula (500ms)
        self._icon_size_save_timer = QTimer(self)
        self._icon_size_save_timer.setSingleShot(True)
        self._icon_size_save_timer.setInterval(500)
        self._icon_size_save_timer.timeout.connect(self._save_icon_size_to_config)

        # Temporizador de retardo (debounce) para persistir tamaños del splitter (500ms)
        self._splitter_save_timer = QTimer(self)
        self._splitter_save_timer.setSingleShot(True)
        self._splitter_save_timer.setInterval(500)
        self._splitter_save_timer.timeout.connect(self._save_splitter_sizes_to_config)

        # Inicializar cliente de Freesound y timer para debouncing de búsqueda
        from core.tabs.editing_media.freesound_client import FreesoundClient
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
                self.audio_player.setLoops(QMediaPlayer.Infinite)  # Bucle por defecto
                
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
        from PySide6.QtCore import QTimer
        QTimer.singleShot(150, self._update_media_list)

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

        # Restaurar tamaños del splitter desde la configuración guardada
        cfg = get_config()
        saved_sizes = cfg.get("editing_media_splitter_sizes", [240, 480, 480])
        self.splitter.setSizes(saved_sizes)

        # Conectar señal para persistir cambios de tamaño del splitter
        self.splitter.splitterMoved.connect(self._on_splitter_moved)

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
        self.tree_folders.itemExpanded.connect(self._on_tree_item_expanded)
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
        self.search_input.setStyleSheet("QLineEdit { padding-right: 28px; }")

        # Integrar spinner de carga animado a la derecha de search_input
        self.search_spinner = LoadingSpinnerWidget(self.search_input, size=16, color=get_theme_token('acento_primario', '#B9E640'))
        spin_layout = QHBoxLayout(self.search_input)
        spin_layout.setContentsMargins(0, 0, 8, 0)
        spin_layout.addStretch()
        spin_layout.addWidget(self.search_spinner)

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
        self.btn_view_list.setIcon(get_colored_svg_icon("view_list.svg", "#FFFFFF", size=14))
        self.btn_view_list.setIconSize(QSize(14, 14))
        self.btn_view_list.setStyleSheet(btn_mode_style)
        self.btn_view_list.clicked.connect(lambda: self.set_view_mode("list"))
        btn_bar.addWidget(self.btn_view_list)

        self.btn_view_grid = QPushButton()
        self.btn_view_grid.setFixedSize(26, 26)
        self.btn_view_grid.setCheckable(True)
        self.btn_view_grid.setToolTip(self.tr("Vista de Cuadrícula"))
        self.btn_view_grid.setIcon(get_colored_svg_icon("grid_view.svg", "#000000", size=14))
        self.btn_view_grid.setIconSize(QSize(14, 14))
        self.btn_view_grid.setStyleSheet(btn_mode_style)
        self.btn_view_grid.clicked.connect(lambda: self.set_view_mode("grid"))
        self.btn_view_grid.installEventFilter(self)
        btn_bar.addWidget(self.btn_view_grid)

        # Temporizador para ocultar popup al perder hover (puente extendido de 400ms)
        from PySide6.QtCore import QTimer
        self.hide_popup_timer = QTimer(self)
        self.hide_popup_timer.setSingleShot(True)
        self.hide_popup_timer.setInterval(400)
        self.hide_popup_timer.timeout.connect(self._hide_grid_scale_popup)

        # Popup emergente flotante (usamos Tool para no robar foco modalmente)
        self.grid_scale_popup = QFrame(self, Qt.Tool | Qt.FramelessWindowHint)
        self.grid_scale_popup.setObjectName("gridScalePopup")
        self.grid_scale_popup.installEventFilter(self)
        self.grid_scale_popup.setAttribute(Qt.WA_TranslucentBackground)
        self.grid_scale_popup.setFixedWidth(100)
        self.grid_scale_popup.setStyleSheet(f"""
            QFrame#gridScalePopup {{
                background-color: {get_theme_token('panel_fondo', '#181818')};
                border: 1px solid {get_theme_token('borde_sutil', '#333333')};
                border-radius: 10px;
            }}
        """)
        popup_layout = QHBoxLayout(self.grid_scale_popup)
        popup_layout.setContentsMargins(6, 4, 6, 4)
        popup_layout.setSpacing(0)

        self.icon_size_slider = QSlider(Qt.Horizontal)
        self.icon_size_slider.setRange(48, 200)
        self.icon_size_slider.setValue(self._saved_icon_size)
        self.icon_size_slider.setFixedWidth(75)
        self.icon_size_slider.setToolTip(self.tr("Tamaño de cuadrícula"))
        self.icon_size_slider.valueChanged.connect(self._on_icon_size_changed)

        accent_sec = get_theme_token('acento_secundario', '#1DC038')
        accent_pri = get_theme_token('acento_primario', '#B9E640')
        border_color = get_theme_token('borde_normal', '#444444')
        self.icon_size_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                border-radius: 2px;
                height: 4px;
                background: {border_color};
            }}
            QSlider::sub-page:horizontal {{
                background: {accent_sec};
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: #ffffff;
                width: 10px;
                margin-top: -3px;
                margin-bottom: -3px;
                border-radius: 5px;
            }}
            QSlider::handle:horizontal:hover {{
                background: {accent_pri};
            }}
        """)
        popup_layout.addWidget(self.icon_size_slider)

        # Botón de Ordenar Por
        self.btn_sort_by = QPushButton(self.tr("Nombre"))
        self.btn_sort_by.setFixedHeight(26)
        self.btn_sort_by.setStyleSheet(f"""
            QPushButton {{
                background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-radius: 6px;
                padding: 2px 8px;
                font-size: 11px;
                color: {get_theme_token('texto_principal', '#cdd6f4')};
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')};
            }}
        """)
        self._build_sort_menu()
        btn_bar.addWidget(self.btn_sort_by)

        # Botón conmutador de Dirección de Orden (Ascendente / Descendente)
        self.btn_sort_dir = QPushButton()
        self.btn_sort_dir.setFixedSize(26, 26)
        self.btn_sort_dir.setIcon(get_colored_svg_icon("arrow_upward_alt.svg", "#FFFFFF", size=16))
        self.btn_sort_dir.setIconSize(QSize(16, 16))
        self.btn_sort_dir.setToolTip(self.tr("Orden Ascendente (A-Z, Antiguos primero)"))
        self.btn_sort_dir.setStyleSheet(btn_mode_style)
        self.btn_sort_dir.clicked.connect(self._toggle_sort_direction)
        btn_bar.addWidget(self.btn_sort_dir)

        layout.addLayout(btn_bar)

        # Lista de archivos multimedia
        self.media_list = QListWidget()
        self.media_list.setObjectName("mediaListWidget")
        self.media_list.setSpacing(0)
        self.media_list.setIconSize(QSize(16, 16))
        self.media_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.media_list.verticalScrollBar().setSingleStep(30)
        self.media_list.itemClicked.connect(self._on_media_clicked)
        self.media_list.currentItemChanged.connect(self._on_current_item_changed)
        
        # Activar menú contextual e infinite scroll
        self.media_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.media_list.customContextMenuRequested.connect(self._show_media_context_menu)
        self.media_list.verticalScrollBar().valueChanged.connect(self._on_list_scroll)
        self.media_list.viewport().installEventFilter(self)
        
        layout.addWidget(self.media_list, 1)

        # Aplicar modo de vista guardado
        self.set_view_mode(self.view_mode)

        # ── ESPECTRO DE AUDIO INTEGRADO (A pie de columna, oculto por defecto) ──
        self.audio_panel = QFrame()
        self.audio_panel.setObjectName("audioSpectrumPanel")
        self.audio_panel.setVisible(False)
        audio_layout = QVBoxLayout(self.audio_panel)
        audio_layout.setContentsMargins(10, 10, 10, 10)
        audio_layout.setSpacing(6)

        # Header superior con Carátula e información de título para archivos de audio
        self.audio_header_widget = QWidget()
        header_layout = QHBoxLayout(self.audio_header_widget)
        header_layout.setContentsMargins(0, 0, 0, 4)
        header_layout.setSpacing(12)

        self.lbl_cover_art = QLabel()
        self.lbl_cover_art.setFixedSize(64, 64)
        self.lbl_cover_art.setStyleSheet(f"""
            QLabel {{
                background-color: {get_theme_token('fondo_elemento', '#1c1c1e')};
                border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-radius: 8px;
            }}
        """)
        self.lbl_cover_art.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(self.lbl_cover_art)

        header_info_v = QVBoxLayout()
        header_info_v.setSpacing(2)
        header_info_v.addStretch()

        self.lbl_audio_name = QLabel()
        self.lbl_audio_name.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {get_theme_token('acento_primario', '#B9E640')};")
        self.lbl_audio_name.setWordWrap(True)
        header_info_v.addWidget(self.lbl_audio_name)

        self.lbl_audio_sub = QLabel()
        self.lbl_audio_sub.setStyleSheet("font-size: 11px; color: #a6adc8;")
        header_info_v.addWidget(self.lbl_audio_sub)
        header_info_v.addStretch()

        header_layout.addLayout(header_info_v, 1)
        audio_layout.addWidget(self.audio_header_widget)

        # Título interno
        self.lbl_audio_title = QLabel(self.tr("Visualizador de Espectro"))
        self.lbl_audio_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #f5c2e7;")
        audio_layout.addWidget(self.lbl_audio_title)

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
        self.btn_play.setIconSize(QSize(14, 14))
        self.btn_play.setFixedSize(26, 26)
        apply_player_play_button_style(self.btn_play, is_playing=False, icon_size=14)
        self.btn_play.clicked.connect(self._on_play_clicked)
        controls_layout.addWidget(self.btn_play)

        # Botón Loop/Repetir para audio
        self._audio_loop_active = True  # Por defecto EN loop
        self.btn_loop_audio = QPushButton()
        self.btn_loop_audio.setIconSize(QSize(14, 14))
        self.btn_loop_audio.setFixedSize(26, 26)
        apply_player_loop_button_style(self.btn_loop_audio, is_active=True, icon_size=14)
        self.btn_loop_audio.clicked.connect(self._on_toggle_audio_loop)
        controls_layout.addWidget(self.btn_loop_audio)

        self.lbl_time = QLabel("00:00:00.000 / 00:00:00.000")
        self.lbl_time.setStyleSheet("font-size: 11px; color: #a6adc8;")
        controls_layout.addWidget(self.lbl_time)

        controls_layout.addStretch(1)

        # Control de Volumen Unificado
        self.volume_control = VolumeControlWidget(initial_volume=70, slider_width=80)
        self.volume_control.volume_changed.connect(self._on_volume_changed)
        controls_layout.addWidget(self.volume_control)

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
                color: {get_theme_token('texto_principal', '#cdd6f4')};
            }}
            QListWidget::item {{
                padding: 4px;
                margin: 2px;
                border-radius: 8px;
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
        self.media_list.setUpdatesEnabled(False)
        try:
            if mode == "grid":
                self.btn_view_grid.setChecked(True)
                self.btn_view_list.setChecked(False)
                self.btn_view_grid.setIcon(get_colored_svg_icon("grid_view.svg", "#000000", size=14))
                self.btn_view_list.setIcon(get_colored_svg_icon("view_list.svg", "#FFFFFF", size=14))
                self.media_list.setViewMode(QListWidget.IconMode)
                self.media_list.setResizeMode(QListWidget.Adjust)
                self.media_list.setMovement(QListWidget.Static)
                self.media_list.setWordWrap(True)
                self.media_list.setSpacing(8)
                self.media_list.setUniformItemSizes(True)
                self.media_list.setBatchSize(50)
                self.media_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
                self._apply_icon_size(self.icon_size_slider.value())
            else:
                self.btn_view_list.setChecked(True)
                self.btn_view_grid.setChecked(False)
                self.btn_view_list.setIcon(get_colored_svg_icon("view_list.svg", "#000000", size=14))
                self.btn_view_grid.setIcon(get_colored_svg_icon("grid_view.svg", "#FFFFFF", size=14))
                if hasattr(self, "grid_scale_popup"):
                    self.grid_scale_popup.hide()
                self.media_list.setViewMode(QListWidget.ListMode)
                self.media_list.setWordWrap(False)
                self.media_list.setSpacing(2)
                self.media_list.setGridSize(QSize())
                self.media_list.setIconSize(QSize(24, 24))
                self.media_list.setUniformItemSizes(True)
                self.media_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

            self._update_media_list()
            self.media_list.doItemsLayout()
            self.media_list.update()
        finally:
            self.media_list.setUpdatesEnabled(True)
        
        # Persistir la preferencia de modo de vista
        cfg = get_config()
        cfg["editing_media_view_mode"] = mode
        save_config(cfg)

    def _hide_grid_scale_popup(self):
        if hasattr(self, "grid_scale_popup"):
            self.grid_scale_popup.hide()

    def eventFilter(self, obj, event):
        if hasattr(self, "btn_view_grid") and obj == self.btn_view_grid:
            if event.type() == QEvent.Enter:
                if getattr(self, "view_mode", "grid") == "grid":
                    if hasattr(self, "hide_popup_timer"):
                        self.hide_popup_timer.stop()
                    self._show_grid_scale_popup()
            elif event.type() == QEvent.Leave:
                if hasattr(self, "hide_popup_timer"):
                    self.hide_popup_timer.start()
        elif hasattr(self, "grid_scale_popup") and obj == self.grid_scale_popup:
            if event.type() == QEvent.Enter:
                if hasattr(self, "hide_popup_timer"):
                    self.hide_popup_timer.stop()
            elif event.type() == QEvent.Leave:
                if hasattr(self, "hide_popup_timer"):
                    self.hide_popup_timer.start()
        elif hasattr(self, "media_list") and self.media_list and obj == self.media_list.viewport():
            if event.type() == QEvent.Resize:
                if getattr(self, "view_mode", "grid") == "grid":
                    self._recalculate_grid_spacing()
        return super().eventFilter(obj, event)

    def _recalculate_grid_spacing(self):
        """Calcula el ancho fluido adaptable de las tarjetas para rellenar el 100% del contenedor sin espacio muerto a la derecha."""
        if getattr(self, "view_mode", "list") != "grid":
            return
        if getattr(self, "_is_recalculating_grid", False):
            return
        self._is_recalculating_grid = True

        try:
            viewport_w = self.media_list.viewport().width()
            if viewport_w <= 50:
                return
            
            icon_size = self.icon_size_slider.value() if hasattr(self, "icon_size_slider") else 112
            base_cell_w = icon_size + 32
            cell_h = icon_size + 46
            
            spacing = 4
            # Ancho efectivo reservado para columnas (considerando márgenes laterales)
            avail_w = max(10, viewport_w - (spacing * 2))
            
            # Número exacto de columnas que caben confortablemente
            num_cols = max(1, avail_w // base_cell_w)
            
            # Ancho fluido exacto por celda
            fluid_cell_w = avail_w // num_cols
            
            # Ajuste de espaciado para absorber residuos de división entera
            leftover = avail_w - (fluid_cell_w * num_cols)
            final_spacing = spacing + (leftover // (num_cols + 1))
            
            self.media_list.setSpacing(max(1, final_spacing))
            self.media_list.setGridSize(QSize(fluid_cell_w, cell_h))
            
            hint = QSize(fluid_cell_w, cell_h)
            for i in range(self.media_list.count()):
                self.media_list.item(i).setSizeHint(hint)
            
            self.media_list.doItemsLayout()
        finally:
            self._is_recalculating_grid = False

    def _show_grid_scale_popup(self):
        if hasattr(self, "grid_scale_popup") and hasattr(self, "btn_view_grid"):
            self.grid_scale_popup.adjustSize()
            popup_w = self.grid_scale_popup.width() if self.grid_scale_popup.width() > 0 else 90
            
            btn_global_pos = self.btn_view_grid.mapToGlobal(QPoint(0, 0))
            btn_w = self.btn_view_grid.width()
            btn_h = self.btn_view_grid.height()
            
            center_x = btn_global_pos.x() + (btn_w // 2)
            popup_x = center_x - (popup_w // 2)
            # Solapar ligeramente el popup sobre el botón (-2 px) para asegurar hitbox continuo
            popup_y = btn_global_pos.y() + btn_h - 2
            
            self.grid_scale_popup.move(QPoint(popup_x, popup_y))
            self.grid_scale_popup.show()
            self.grid_scale_popup.raise_()

    def _on_icon_size_changed(self, val: int):
        if self.view_mode == "grid":
            self.media_list.setUpdatesEnabled(False)
            try:
                self._apply_icon_size(val)
                self.media_list.doItemsLayout()
            finally:
                self.media_list.setUpdatesEnabled(True)
        
        # Reiniciar el temporizador de debounce para persistir el tamaño
        self._icon_size_save_timer.start()

    def _save_icon_size_to_config(self):
        """Persiste el tamaño de cuadrícula al archivo de configuración (llamado con debounce)."""
        val = self.icon_size_slider.value()
        cfg = get_config()
        cfg["editing_media_icon_size"] = val
        save_config(cfg)

    def _on_splitter_moved(self, pos, index):
        """Reinicia el temporizador de debounce al mover el splitter."""
        self._splitter_save_timer.start()

    def _save_splitter_sizes_to_config(self):
        """Persiste los tamaños del splitter al archivo de configuración (llamado con debounce)."""
        cfg = get_config()
        cfg["editing_media_splitter_sizes"] = self.splitter.sizes()
        save_config(cfg)

    def _apply_icon_size(self, size: int):
        self.media_list.setIconSize(QSize(size, size))
        cell_w = size + 32
        cell_h = size + 46
        self.media_list.setGridSize(QSize(cell_w, cell_h))
        # Forzar sizeHint en cada ítem existente para que Qt no recorte
        hint = QSize(cell_w, cell_h)
        for i in range(self.media_list.count()):
            self.media_list.item(i).setSizeHint(hint)
        self._recalculate_grid_spacing()

    def _on_thumbnail_loaded(self, file_path: str, thumb_path: str):
        """Callback asíncrono cuando una miniatura en segundo plano finaliza su generación."""
        if not thumb_path or not os.path.exists(thumb_path):
            return
        icon = ThumbnailCacheManager.get_instance().get_cached_qicon(file_path)
        if not icon:
            icon = QIcon(thumb_path)
        for i in range(self.media_list.count()):
            item = self.media_list.item(i)
            data = item.data(Qt.UserRole)
            if isinstance(data, dict) and data.get("ruta") == file_path:
                item.setIcon(icon)
                break

        # Actualizar carátula en el panel de audio si el archivo coincide
        if hasattr(self, "current_playing_path") and self.current_playing_path == file_path:
            if hasattr(self, "lbl_cover_art") and hasattr(self, "current_playing_type") and self.current_playing_type == "audio":
                pix = QPixmap(thumb_path).scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.lbl_cover_art.setPixmap(pix)

    def _build_sort_menu(self):
        """Construye el menú desplegable de opciones de ordenación."""
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QActionGroup
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

        group = QActionGroup(menu)
        options = [
            ("nombre", self.tr("Nombre (Alfabético)")),
            ("mtime", self.tr("Fecha de Modificación")),
            ("ctime", self.tr("Fecha de Creación")),
            ("size", self.tr("Tamaño de Archivo")),
            ("tipo", self.tr("Tipo de Medio")),
        ]

        curr_sort = getattr(self, "sort_by", "nombre")
        active_filter = getattr(self, "active_filter", "Todos")

        for key, label in options:
            action = menu.addAction(label)
            action.setCheckable(True)
            if key == curr_sort:
                action.setChecked(True)
            # Deshabilitar "Tipo de Medio" si se está filtrando por una categoría específica
            if key == "tipo" and active_filter != "Todos":
                action.setEnabled(False)
            action.setActionGroup(group)
            action.triggered.connect(lambda checked, k=key, l=label: self._on_sort_option_selected(k, l))

        self.btn_sort_by.setMenu(menu)

    def _on_sort_option_selected(self, key: str, label: str):
        self.sort_by = key
        short_label = label.split("(")[0].strip()
        self.btn_sort_by.setText(short_label)
        self._apply_active_filters_fast()

    def _toggle_sort_direction(self):
        self._set_sort_direction(not getattr(self, "sort_ascending", True))

    def _on_local_search_timer_timeout(self):
        """Callback cuando vence el timer de retardo (250ms) para búsquedas locales."""
        try:
            self._apply_active_filters_fast()
        finally:
            if hasattr(self, "search_spinner"):
                self.search_spinner.stop()
