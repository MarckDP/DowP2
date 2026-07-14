# src/gui/tabs/video_tools/video_tools_view.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QFrame, QComboBox, QSizePolicy
from PySide6.QtCore import Qt

class AspectRatioFrame(QFrame):
    """Contenedor que mantiene una relación de aspecto 16:9 forzada."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def resizeEvent(self, event):
        # Forzar la altura a ser 9/16 del ancho actual
        new_width = event.size().width()
        new_height = int(new_width * 9 / 16)
        self.setFixedHeight(new_height)
        super().resizeEvent(event)

class VideoToolsTab(QWidget):
    def __init__(self):
        super().__init__()
        self._is_wide_mode = None
        self.init_ui()

    def init_ui(self):
        # Layout Principal
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(15, 10, 15, 10)
        self.main_layout.setSpacing(10)

        # --- PANEL IZQUIERDO: Lista de Archivos ---
        self.left_container = QFrame()
        self.left_container.setObjectName("videoContainer")
        self.left_container.setMinimumWidth(250)
        self.left_container.setMaximumWidth(400)
        self.left_layout = QVBoxLayout(self.left_container)
        
        self.lbl_files = QLabel(self.tr("Lista de Archivos"))
        self.lbl_files.setObjectName("sectionTitle")
        self.file_list = QListWidget()
        self.file_list.setObjectName("videoList")
        self.left_layout.addWidget(self.lbl_files)
        self.left_layout.addWidget(self.file_list)
        
        # --- PANEL DERECHO: Workspace ---
        # Usaremos un contenedor intermedio para poder reordenar el layout
        self.workspace_container = QWidget()
        self.workspace_layout = None 
        
        # --- CREACIÓN DE COMPONENTES ---
        self._setup_components()

        # Añadir al Layout Principal
        self.main_layout.addWidget(self.left_container, 1)
        self.main_layout.addWidget(self.workspace_container, 4)

        # Inicializar orientación
        self.update_layout_orientation(False)

    def _setup_components(self):
        # 1. Área de Previsualización (Video + Onda)
        self.preview_container = QFrame()
        self.preview_container.setObjectName("additionalOptionsContainer")
        self.preview_layout = QVBoxLayout(self.preview_container)
        self.preview_layout.setContentsMargins(10, 10, 10, 10)
        
        self.video_container = AspectRatioFrame()
        self.video_container.setObjectName("fragmentVideoContainer")
        self.video_container.setStyleSheet("border-radius: 0px;")
        self.video_container.setMinimumWidth(400)
        self.video_container.setMaximumWidth(1600)
        self.video_container_layout = QVBoxLayout(self.video_container)
        self.video_container_layout.setContentsMargins(0, 0, 0, 0)
        
        self.lbl_video = QLabel(self.tr("Vista Previa (16:9)"))
        self.lbl_video.setAlignment(Qt.AlignCenter)
        self.lbl_video.setObjectName("panelPlaceholder")
        self.video_container_layout.addWidget(self.lbl_video)
        
        # Audio Section
        self.audio_section_layout = QHBoxLayout()
        self.track_selector_layout = QVBoxLayout()
        self.lbl_tracks = QLabel(self.tr("Pistas"))
        self.lbl_tracks.setObjectName("sectionStatus")
        self.combo_audio_tracks = QComboBox()
        self.combo_audio_tracks.setFixedWidth(70)
        self.combo_audio_tracks.addItem("A1")
        self.track_selector_layout.addWidget(self.lbl_tracks)
        self.track_selector_layout.addWidget(self.combo_audio_tracks)
        
        self.audio_waveform = QFrame()
        self.audio_waveform.setObjectName("consoleContent")
        self.audio_waveform.setFixedHeight(70)
        self.audio_waveform.setStyleSheet("border-radius: 0px;")
        self.audio_waveform_layout = QVBoxLayout(self.audio_waveform)
        self.lbl_audio = QLabel(self.tr("Onda de Audio"))
        self.lbl_audio.setAlignment(Qt.AlignCenter)
        self.lbl_audio.setObjectName("panelPlaceholder")
        self.audio_waveform_layout.addWidget(self.lbl_audio)
        
        self.audio_section_layout.addLayout(self.track_selector_layout)
        self.audio_section_layout.addWidget(self.audio_waveform, 1)
        
        self.preview_layout.addWidget(self.video_container)
        self.preview_layout.addLayout(self.audio_section_layout)

        # 2. Área de Controles
        self.options_container = QFrame()
        self.options_container.setObjectName("additionalOptionsContainer")
        self.options_layout = QVBoxLayout(self.options_container)
        self.lbl_options = QLabel(self.tr("Opciones de Herramientas"))
        self.lbl_options.setObjectName("sectionTitle")
        self.options_layout.addWidget(self.lbl_options)
        self.options_layout.addStretch()
        
        self.info_container = QFrame()
        self.info_container.setObjectName("outputOptionsContainer")
        self.info_container.setMinimumWidth(280)
        self.info_layout = QVBoxLayout(self.info_container)
        self.lbl_info = QLabel(self.tr("Detalles del Archivo"))
        self.lbl_info.setObjectName("sectionTitle")
        self.info_layout.addWidget(self.lbl_info)
        self.info_layout.addStretch()

    def update_layout_orientation(self, is_wide):
        """Reorganiza los widgets según el espacio disponible."""
        if self.workspace_layout:
            # Desvincular widgets para que no se destruyan al limpiar el layout
            self.preview_container.setParent(None)
            self.options_container.setParent(None)
            self.info_container.setParent(None)
            
            # En PySide6, para cambiar el layout de un widget, movemos el viejo a un dummy
            # Esto libera al workspace_container para recibir un nuevo layout
            QWidget().setLayout(self.workspace_container.layout())

        if is_wide:
            # MODO PANORÁMICO: Previsualización a la izquierda, Controles a la derecha
            self.workspace_layout = QHBoxLayout(self.workspace_container)
            self.workspace_layout.setContentsMargins(0, 0, 0, 0)
            self.workspace_layout.setSpacing(10)
            
            # Sub-layout para controles verticales
            right_controls = QVBoxLayout()
            right_controls.setSpacing(10)
            right_controls.addWidget(self.options_container, 1)
            right_controls.addWidget(self.info_container, 0)
            
            self.workspace_layout.addWidget(self.preview_container, 2)
            self.workspace_layout.addLayout(right_controls, 1)
        else:
            # MODO ESTÁNDAR: Previsualización arriba, Controles abajo
            self.workspace_layout = QVBoxLayout(self.workspace_container)
            self.workspace_layout.setContentsMargins(0, 0, 0, 0)
            self.workspace_layout.setSpacing(10)
            
            # Sub-layout para controles horizontales
            bottom_controls = QHBoxLayout()
            bottom_controls.setSpacing(10)
            bottom_controls.addWidget(self.options_container, 2)
            bottom_controls.addWidget(self.info_container, 1)
            
            self.workspace_layout.addWidget(self.preview_container, 1)
            self.workspace_layout.addLayout(bottom_controls, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Umbral para cambiar a modo panorámico (aprox cuando se maximiza o estira mucho)
        threshold = 1350 
        is_wide = self.window().width() > threshold
        
        if is_wide != self._is_wide_mode:
            self._is_wide_mode = is_wide
            self.update_layout_orientation(is_wide)
