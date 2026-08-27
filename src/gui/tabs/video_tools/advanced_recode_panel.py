# src/gui/tabs/video_tools/advanced_recode_panel.py
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QFrame,
    QLabel,
    QComboBox,
    QRadioButton,
    QButtonGroup,
    QScrollArea,
    QSpinBox,
    QCheckBox,
    QSizePolicy,
    QPushButton,
    QStyledItemDelegate,
)
from PySide6.QtCore import Signal, Qt
import math

from gui.styles import get_theme_token
from gui.widgets.mode_selector import ModeSelector
from gui.widgets.preset_bar import PresetBar
from gui.widgets.combo_box import CheckmarkComboDelegate, AutoPopupComboBox
from core.logger.logger_manager import logger
from core.utils.recode_guard import evaluate_recode, get_video_codecs, get_audio_codecs, get_compatible_containers, resolve_encoder, get_channel_support, get_dimension_alignment
from core.utils.hardware_detector import detect_hardware
from core.tabs.video_tools.codec_profiles import (
    get_profiles, build_custom_bitrate_args, extract_bitrate_kbps,
    recommend_audio_codec, supports_two_pass, encoder_is_two_pass_capable, build_pass_args, ENCODER_VARIANTS,
)
from core.tabs.video_tools.size_estimator import (
    parse_duration_to_seconds, parse_kbps_from_label, estimate_size_mb, source_codec_id,
)

# Con listas de ~25-30 codecs, el popup del combo se cae a scroll para no tapar la pantalla
_MAX_VISIBLE_COMBO_ITEMS = 12

_PRESET_NAMESPACE = "video_tools/avanzado"

# Contenedores de stream elemental que NUNCA pueden llevar más de una pista de audio,
# sin importar el códec (a diferencia del resto, que son contenedores de multiplexado
# reales y sí pueden). Lista acotada a mano por ahora, igual que hacía DowP Lite -
# pendiente de reemplazar por un dato verificado empíricamente contra el ffmpeg
# empaquetado cuando se amplíe tools/codec_matrix con soporte multi-pista (ver charla).
_SINGLE_AUDIO_STREAM_CONTAINERS = {"mp3", "wav", "flac"}

_SEVERITY_LABELS = {
    "ok": "Compatible",
    "warning": "Advertencia",
    "unverified": "No verificado",
    "blocked": "No compatible",
}
_SEVERITY_TOKENS = {
    "ok": "estado_exito",
    "warning": "estado_aviso",
    "unverified": "estado_espera",
    "blocked": "estado_error",
}

_ENGINE_LABELS = {
    "h264_nvenc": "NVIDIA NVENC", "hevc_nvenc": "NVIDIA NVENC", "av1_nvenc": "NVIDIA NVENC",
    "h264_videotoolbox": "Apple VideoToolbox", "hevc_videotoolbox": "Apple VideoToolbox",
    "h264_qsv": "Intel QuickSync", "hevc_qsv": "Intel QuickSync", "av1_qsv": "Intel QuickSync",
    "h264_amf": "AMD AMF", "hevc_amf": "AMD AMF", "av1_amf": "AMD AMF",
    "h264_vaapi": "VA-API", "hevc_vaapi": "VA-API", "av1_vaapi": "VA-API", "vp9_vaapi": "VA-API",
}

_CONTAINER_LABELS = {
    "qtff": "MOV",
    "mov": "MOV",
    "mp4": "MP4",
    "mkv": "MKV",
    "avi": "AVI",
    "asf": "WMV",
    "ps": "MPEG-PS",
    "ts": "MPEG-TS",
    "webm": "WEBM",
    "mxf": "MXF",
    "3gp": "3GP",
    "3g2": "3G2",
    "mp3": "MP3",
    "m4a": "M4A",
    "ogg": "OGG",
    "wav": "WAV",
    "flac": "FLAC",
    "flv": "FLV",
    "apng": "APNG",
    "webp": "WEBP",
    "gif": "GIF",
    "opus": "OPUS",
}

# Presets de resolución: escalan el LADO LARGO del video preservando el aspecto real del fuente
# (modelo "conservar aspecto" — nunca recortan ni deforman por sí solos). El valor es el tamaño
# objetivo en píxeles del lado más largo; la expresión ffmpeg que lo usa decide en tiempo de
# ejecución (con iw/ih) si ese lado es el ancho o el alto, sin que DowP necesite saber la
# orientación del fuente de antemano.
_RESOLUTION_PRESETS = [
    ("original", "Original", None),
    ("4k", "4K (2160p)", 3840),
    ("2k", "2K (1440p)", 2560),
    ("1080p", "1080p (Full HD)", 1920),
    ("720p", "720p (HD)", 1280),
    ("480p", "480p (SD)", 854),
    ("custom", "Personalizado", None),
]

# Framerates estándar de broadcast/cine para forzar CFR.
_CFR_FPS_OPTIONS = [23.976, 24, 25, 29.97, 30, 50, 59.94, 60]

_FIT_MODE_LABELS = {
    "deformar": "Deformar",
    "ajustar": "Ajustar",
    "crop": "Recortar",
}
_FIT_MODE_TOOLTIPS = {
    "deformar": "Estira la imagen al tamaño exacto elegido, sin respetar su relación de aspecto original.",
    "ajustar": "Encoge la imagen para que quepa entera en el tamaño elegido y rellena el sobrante con barras negras.",
    "crop": "Agranda la imagen para cubrir todo el tamaño elegido y recorta lo que sobre por los bordes.",
}

_PREFERRED_CONTAINER_BY_CODEC = {
    # Video profesional / edición -> qtff (MOV)
    "prores": "qtff",
    "dnxhd": "qtff",
    "dnxhr": "qtff",
    "cfhd": "qtff",
    "qtrle": "qtff",
    "hap": "qtff",
    # Animaciones
    "gif": "gif",
    "apng": "apng",
    # Web / Abiertos
    "theora": "ogg",
    "vp8": "webm",
    "vp9": "webm",
    "h264": "mp4",
    "hevc": "mp4",
    "av1": "mp4",
    "vvc": "mp4",
    # Audio
    "mp3": "mp3",
    "aac": "m4a",
    "flac": "flac",
    "alac": "m4a",
    "opus": "opus",
    "vorbis": "ogg",
    "pcm_s16le": "wav",
    "pcm_s24le": "wav",
    "pcm_s32le": "wav",
    "pcm_f32le": "wav",
}


class AdvancedRecodePanel(QWidget):
    """
    Pestaña "Avanzado": eleccion libre de codec de video/audio (o copiar el stream
    original) y contenedor, validada en vivo contra recode_guard (ffmpeg_codec_matrix.json
    + hardware_detector) antes de permitir iniciar el proceso.
    """
    validity_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._building = False
        self._last_valid = True
        self._force_cpu_engine = False
        self._last_profile_codec = {"video": None, "audio": None}
        self._source_meta = None
        self._source_filepath = None
        self._init_ui()
        self._reload_codec_lists()
        initial_video_codec = self._current_video_codec()
        if initial_video_codec:
            self._apply_audio_recommendation(initial_video_codec)
        self._on_selection_changed()

    def _init_ui(self):
        self.setObjectName("advancedTabPanel")
        self.setStyleSheet("""
            QWidget#advancedTabPanel { background: transparent; }
            QScrollArea#advancedScroll { background: transparent; }
            QWidget#advancedContent { background: transparent; }
        """)
        
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setObjectName("advancedScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)

        content = QWidget(scroll)
        content.setObjectName("advancedContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 0. Selector de Modo (Video + Audio / Solo Audio / Solo Video)
        self.mode_selector = ModeSelector(content)
        self.mode_selector.mode_changed.connect(self._on_mode_changed)
        layout.addWidget(self.mode_selector)

        # 1. Tarjeta de Estado de Compatibilidad
        layout.addWidget(self._build_messages_section(content))

        # 2. Cuadrícula dinámica de Tarjetas (2 columnas adaptables)
        self.cards_grid = QGridLayout()
        self.cards_grid.setSpacing(10)
        self.cards_grid.setColumnStretch(0, 1)
        self.cards_grid.setColumnStretch(1, 1)

        self._build_stream_section(self.tr("Video"), "video", is_video=True, parent=content)
        self._build_stream_section(self.tr("Audio"), "audio", is_video=False, parent=content)
        self._build_transform_section(content)
        self._build_container_section(content)
        self._build_size_estimate_section(content)

        layout.addLayout(self.cards_grid)

        # Preajustes: va debajo de todo el panel (no es una tarjeta más de la
        # cuadrícula) - ver conversación sobre el sistema de presets.
        preset_card, preset_card_layout = self._card_frame(self.tr("Preajustes"), parent=content)
        self.preset_bar = PresetBar(
            _PRESET_NAMESPACE, self.get_settings, preset_card,
            show_picker=False, show_save_button=True,
        )
        preset_card_layout.addWidget(self.preset_bar)
        layout.addWidget(preset_card)

        layout.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _card_frame(self, title: str | None = None, parent=None) -> tuple[QFrame, QVBoxLayout]:
        """Crea una tarjeta con fondo transparente y borde sutil mediante ID selector para no afectar popups."""
        frame = QFrame(parent or self)
        frame.setObjectName("advancedCard")
        border_color = get_theme_token('borde_sutil', '#2d2d2d')
        frame.setStyleSheet(f"""
            QFrame#advancedCard {{
                background-color: transparent;
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
        """)
        frame.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        v = QVBoxLayout(frame)
        v.setContentsMargins(12, 10, 12, 12)
        v.setSpacing(8)
        if title:
            lbl = QLabel(title, frame)
            lbl.setObjectName("sectionTitle")
            v.addWidget(lbl)
        return frame, v

    def _setup_fixed_combo(self, combo: QComboBox):
        """Configura el combo para que nunca empuje el ancho de columna aunque el texto sea largo."""
        combo.setMaxVisibleItems(_MAX_VISIBLE_COMBO_ITEMS)
        combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(1)
        combo.setItemDelegate(CheckmarkComboDelegate(combo))
        # El filtro global de cursor (HandCursorInstaller, main.py) escucha ChildAdded, pero acá
        # todos los combos se construyen pasando el parent directo al constructor
        # (AutoPopupComboBox(frame)) en vez de agregarlos después vía layout.addWidget() — con eso
        # el evento ChildAdded nunca llega a dispararse (verificado), así que el filtro global no
        # los alcanza nunca. Se fija a mano acá, mismo patrón que ya usan los QRadioButton/
        # QCheckBox de este archivo.
        combo.setCursor(Qt.PointingHandCursor)

    def _build_stream_section(self, title: str, prefix: str, is_video: bool, parent=None) -> QFrame:
        frame, v = self._card_frame(parent=parent)

        # Cabecera de la columna (Título + Badge CPU/GPU si es video)
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 2)
        header_row.setSpacing(8)

        lbl_title = QLabel(title, frame)
        lbl_title.setObjectName("sectionTitle")
        header_row.addWidget(lbl_title)
        header_row.addStretch(1)

        engine_badge = QPushButton("", frame)
        engine_badge.setObjectName(f"{prefix}EngineBadge")
        engine_badge.setCursor(Qt.PointingHandCursor)
        engine_badge.setVisible(False)
        header_row.addWidget(engine_badge)
        v.addLayout(header_row)

        # Selector de Modo (Recodificar / Copiar original)
        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 2, 0, 4)
        mode_row.setSpacing(14)

        rb_recode = QRadioButton(self.tr("Recodificar"), frame)
        rb_copy = QRadioButton(self.tr("Copiar original"), frame)
        rb_recode.setChecked(True)
        rb_recode.setCursor(Qt.PointingHandCursor)
        rb_copy.setCursor(Qt.PointingHandCursor)

        group = QButtonGroup(frame)
        group.addButton(rb_recode)
        group.addButton(rb_copy)
        mode_row.addWidget(rb_recode)
        mode_row.addWidget(rb_copy)
        mode_row.addStretch(1)
        v.addLayout(mode_row)

        # Códec
        lbl_codec = QLabel(self.tr("Códec:"), frame)
        lbl_codec.setObjectName("menuLabel")
        v.addWidget(lbl_codec)

        codec_combo = AutoPopupComboBox(frame)
        self._setup_fixed_combo(codec_combo)
        v.addWidget(codec_combo)

        # Variante / Motor (Opcional)
        lbl_variant = QLabel(self.tr("Motor / Variante:"), frame)
        lbl_variant.setObjectName("menuLabel")
        v.addWidget(lbl_variant)
        lbl_variant.setVisible(False)

        variant_combo = AutoPopupComboBox(frame)
        self._setup_fixed_combo(variant_combo)
        v.addWidget(variant_combo)
        variant_combo.setVisible(False)

        # Perfil de Calidad
        lbl_profile = QLabel(self.tr("Perfil de calidad:"), frame)
        lbl_profile.setObjectName("menuLabel")
        v.addWidget(lbl_profile)

        profile_combo = AutoPopupComboBox(frame)
        self._setup_fixed_combo(profile_combo)
        v.addWidget(profile_combo)

        # Valor Personalizado (Bitrate o CQ)
        custom_container = QWidget(frame)
        custom_layout = QVBoxLayout(custom_container)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setSpacing(4)

        lbl_custom = QLabel(self.tr("Valor:"), custom_container)
        lbl_custom.setObjectName("menuLabel")
        custom_layout.addWidget(lbl_custom)

        bitrate_spin = QSpinBox(custom_container)
        if is_video:
            bitrate_spin.setRange(64, 500000)
            bitrate_spin.setSingleStep(500)
            bitrate_spin.setValue(8000)
        else:
            bitrate_spin.setRange(16, 640)
            bitrate_spin.setSingleStep(32)
            bitrate_spin.setValue(192)
        bitrate_spin.setSuffix(" kbps")
        bitrate_spin.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        custom_layout.addWidget(bitrate_spin)

        cq_spin = QSpinBox(custom_container)
        cq_spin.setRange(0, 63)
        cq_spin.setSingleStep(1)
        cq_spin.setValue(23)
        cq_spin.setSuffix(" (CRF/CQ)")
        cq_spin.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        custom_layout.addWidget(cq_spin)

        if is_video:
            gif_container = QWidget(custom_container)
            gif_layout = QVBoxLayout(gif_container)
            gif_layout.setContentsMargins(0, 0, 0, 0)
            gif_layout.setSpacing(4)

            lbl_dither = QLabel(self.tr("Difuminado (Dither):"), gif_container)
            lbl_dither.setObjectName("menuLabel")
            gif_layout.addWidget(lbl_dither)

            combo_dither = AutoPopupComboBox(gif_container)
            self._setup_fixed_combo(combo_dither)
            combo_dither.addItem(self.tr("Floyd-Steinberg (Suave, estándar)"), "floyd_steinberg")
            combo_dither.addItem(self.tr("Bayer (Geométrico, liviano)"), "bayer")
            combo_dither.addItem(self.tr("Sierra2_4a (Equilibrado)"), "sierra2_4a")
            combo_dither.addItem(self.tr("Sierra2"), "sierra2")
            combo_dither.addItem(self.tr("Sin Difuminado (Colores planos)"), "none")
            gif_layout.addWidget(combo_dither)

            lbl_stats = QLabel(self.tr("Generación de Paleta:"), gif_container)
            lbl_stats.setObjectName("menuLabel")
            gif_layout.addWidget(lbl_stats)

            combo_stats = AutoPopupComboBox(gif_container)
            self._setup_fixed_combo(combo_stats)
            combo_stats.addItem(self.tr("Global / Todo el clip (full)"), "full")
            combo_stats.addItem(self.tr("Zonas en movimiento (diff)"), "diff")
            combo_stats.addItem(self.tr("Por Fotograma (single)"), "single")
            gif_layout.addWidget(combo_stats)

            lbl_colors = QLabel(self.tr("Máximo de Colores:"), gif_container)
            lbl_colors.setObjectName("menuLabel")
            gif_layout.addWidget(lbl_colors)

            combo_colors = AutoPopupComboBox(gif_container)
            self._setup_fixed_combo(combo_colors)
            combo_colors.addItem(self.tr("256 colores (Máximo)"), 256)
            combo_colors.addItem(self.tr("128 colores"), 128)
            combo_colors.addItem(self.tr("64 colores"), 64)
            combo_colors.addItem(self.tr("32 colores"), 32)
            combo_colors.addItem(self.tr("16 colores"), 16)
            gif_layout.addWidget(combo_colors)

            lbl_fps = QLabel(self.tr("Cuadros por Segundo (FPS):"), gif_container)
            lbl_fps.setObjectName("menuLabel")
            gif_layout.addWidget(lbl_fps)

            combo_fps = AutoPopupComboBox(gif_container)
            self._setup_fixed_combo(combo_fps)
            combo_fps.addItem(self.tr("Original (Sin cambios)"), None)
            combo_fps.addItem(self.tr("30 FPS (Fluido)"), 30)
            combo_fps.addItem(self.tr("24 FPS (Cinemático)"), 24)
            combo_fps.addItem(self.tr("20 FPS"), 20)
            combo_fps.addItem(self.tr("15 FPS (Recomendado para GIF)"), 15)
            combo_fps.addItem(self.tr("12 FPS (Ligero)"), 12)
            combo_fps.addItem(self.tr("10 FPS (Máximo ahorro)"), 10)
            gif_layout.addWidget(combo_fps)

            custom_layout.addWidget(gif_container)
            gif_container.setVisible(False)
            self.widget_video_gif_custom = gif_container
            self.combo_video_gif_dither = combo_dither
            self.combo_video_gif_stats = combo_stats
            self.combo_video_gif_colors = combo_colors
            self.combo_video_gif_fps = combo_fps

            combo_dither.currentIndexChanged.connect(self._update_size_estimate)
            combo_stats.currentIndexChanged.connect(self._update_size_estimate)
            combo_colors.currentIndexChanged.connect(self._update_size_estimate)
            combo_fps.currentIndexChanged.connect(self._update_size_estimate)

        v.addWidget(custom_container)
        custom_container.setVisible(False)

        # Registro de atributos
        setattr(self, f"rb_{prefix}_recode", rb_recode)
        setattr(self, f"rb_{prefix}_copy", rb_copy)
        setattr(self, f"lbl_{prefix}_codec", lbl_codec)
        setattr(self, f"combo_{prefix}_codec", codec_combo)
        setattr(self, f"lbl_{prefix}_variant", lbl_variant)
        setattr(self, f"combo_{prefix}_variant", variant_combo)
        setattr(self, f"lbl_{prefix}_engine", engine_badge)
        setattr(self, f"lbl_{prefix}_profile", lbl_profile)
        setattr(self, f"combo_{prefix}_profile", profile_combo)
        setattr(self, f"widget_{prefix}_custom", custom_container)
        setattr(self, f"lbl_{prefix}_custom", lbl_custom)
        setattr(self, f"spin_{prefix}_bitrate", bitrate_spin)
        setattr(self, f"spin_{prefix}_cq", cq_spin)
        setattr(self, f"frame_{prefix}", frame)

        rb_recode.toggled.connect(self._on_selection_changed)
        if is_video:
            codec_combo.currentIndexChanged.connect(self._on_video_codec_changed)
        else:
            codec_combo.currentIndexChanged.connect(self._on_selection_changed)
        profile_combo.currentIndexChanged.connect(lambda *_: self._on_profile_changed(prefix))
        variant_combo.currentIndexChanged.connect(lambda *_: self._on_variant_changed(prefix))
        bitrate_spin.valueChanged.connect(self._update_size_estimate)
        cq_spin.valueChanged.connect(self._update_size_estimate)

        if is_video:
            engine_badge.clicked.connect(self._toggle_engine_mode)

        # Pasadas (Solo Video)
        if is_video:
            pass_container = QWidget(frame)
            pass_layout = QVBoxLayout(pass_container)
            pass_layout.setContentsMargins(0, 0, 0, 4)
            pass_layout.setSpacing(8)

            lbl_passes = QLabel(self.tr("Pasadas:"), pass_container)
            lbl_passes.setObjectName("menuLabel")
            pass_layout.addWidget(lbl_passes)

            pass_radios_row = QHBoxLayout()
            pass_radios_row.setContentsMargins(0, 0, 0, 0)
            pass_radios_row.setSpacing(16)

            rb_pass1 = QRadioButton(self.tr("1 pasada"), pass_container)
            rb_pass2 = QRadioButton(self.tr("2 pasadas"), pass_container)
            rb_pass1.setCursor(Qt.PointingHandCursor)
            rb_pass2.setCursor(Qt.PointingHandCursor)
            rb_pass2.setToolTip(self.tr("2 pasadas: más precisión de bitrate objetivo, tarda el doble."))
            rb_pass1.setChecked(True)

            pass_group = QButtonGroup(pass_container)
            pass_group.addButton(rb_pass1)
            pass_group.addButton(rb_pass2)
            pass_radios_row.addWidget(rb_pass1)
            pass_radios_row.addWidget(rb_pass2)
            pass_radios_row.addStretch(1)
            pass_layout.addLayout(pass_radios_row)

            v.addWidget(pass_container)
            self.widget_video_passes = pass_container
            self.lbl_video_passes = lbl_passes
            self.rb_video_pass1 = rb_pass1
            self.rb_video_pass2 = rb_pass2
            pass_container.setVisible(False)
            rb_pass1.toggled.connect(self._update_size_estimate)

        if not is_video:
            channels_container = QWidget(frame)
            channels_layout = QVBoxLayout(channels_container)
            channels_layout.setContentsMargins(0, 0, 0, 4)
            channels_layout.setSpacing(8)

            lbl_channels = QLabel(self.tr("Canales:"), channels_container)
            lbl_channels.setObjectName("menuLabel")
            channels_layout.addWidget(lbl_channels)

            channels_combo = AutoPopupComboBox(channels_container)
            self._setup_fixed_combo(channels_combo)
            channels_combo.addItem(self.tr("Igual al original"), "")
            channels_combo.addItem(self.tr("Mono (1 canal)"), "1")
            channels_combo.addItem(self.tr("Estéreo (2 canales)"), "2")
            channels_combo.addItem(self.tr("5.1 Surround"), "6")
            channels_layout.addWidget(channels_combo)

            v.addWidget(channels_container)
            self.widget_audio_channels = channels_container
            self.lbl_audio_channels = lbl_channels
            self.combo_audio_channels = channels_combo

            samplerate_container = QWidget(frame)
            samplerate_layout = QVBoxLayout(samplerate_container)
            samplerate_layout.setContentsMargins(0, 0, 0, 4)
            samplerate_layout.setSpacing(8)

            lbl_samplerate = QLabel(self.tr("Velocidad de muestreo:"), samplerate_container)
            lbl_samplerate.setObjectName("menuLabel")
            samplerate_layout.addWidget(lbl_samplerate)

            samplerate_combo = AutoPopupComboBox(samplerate_container)
            self._setup_fixed_combo(samplerate_combo)
            samplerate_combo.addItem(self.tr("Igual al original"), "")
            samplerate_combo.addItem("48000 Hz", "48000")
            samplerate_combo.addItem("44100 Hz", "44100")
            samplerate_combo.addItem("32000 Hz", "32000")
            samplerate_combo.addItem("24000 Hz", "24000")
            samplerate_combo.addItem("22050 Hz", "22050")
            samplerate_combo.addItem("16000 Hz", "16000")
            samplerate_layout.addWidget(samplerate_combo)

            v.addWidget(samplerate_container)
            self.widget_audio_samplerate = samplerate_container
            self.lbl_audio_samplerate = lbl_samplerate
            self.combo_audio_samplerate = samplerate_combo

        v.addStretch(1)
        return frame

    def _build_transform_section(self, parent=None) -> QFrame:
        frame, v = self._card_frame(self.tr("Transformación de video"), parent=parent)

        # ── CFR ──────────────────────────────────────────────
        cfr_row = QHBoxLayout()
        cfr_row.setSpacing(8)
        self.chk_cfr = QCheckBox(self.tr("CFR"), frame)
        self.chk_cfr.setCursor(Qt.PointingHandCursor)
        self.chk_cfr.setToolTip(self.tr(
            "Forzar FPS constante (Constant Frame Rate): reescribe el video a una tasa de "
            "fotogramas fija, en vez de conservar la original."
        ))
        cfr_row.addWidget(self.chk_cfr)

        self.combo_cfr_fps = AutoPopupComboBox(frame)
        self._setup_fixed_combo(self.combo_cfr_fps)
        self.combo_cfr_fps.setEditable(True)
        # _setup_fixed_combo deja el ancho "Ignored" + mínimo de 1 caracter (pensado para combos
        # de solo lectura en columnas angostas) — acá hace falta lugar real para escribir/leer un
        # valor como "29.97 fps" sin que la caja quede achicada a una estampilla.
        self.combo_cfr_fps.setMinimumWidth(100)
        self.combo_cfr_fps.setToolTip(self.tr("Elige un valor común o escribe el FPS que prefieras."))
        from PySide6.QtGui import QDoubleValidator
        fps_validator = QDoubleValidator(1.0, 300.0, 3, self.combo_cfr_fps)
        fps_validator.setNotation(QDoubleValidator.StandardNotation)
        self.combo_cfr_fps.lineEdit().setValidator(fps_validator)
        for fps in _CFR_FPS_OPTIONS:
            label = f"{fps:g} fps"
            self.combo_cfr_fps.addItem(label, fps)
        self.combo_cfr_fps.setCurrentIndex(_CFR_FPS_OPTIONS.index(30))
        self.combo_cfr_fps.setEnabled(False)
        cfr_row.addWidget(self.combo_cfr_fps, 1)
        v.addLayout(cfr_row)

        self.chk_cfr.toggled.connect(self._on_cfr_toggled)
        self.combo_cfr_fps.currentIndexChanged.connect(self._update_size_estimate)

        # ── Resolución ───────────────────────────────────────
        lbl_res = QLabel(self.tr("Resolución:"), frame)
        lbl_res.setObjectName("menuLabel")
        v.addWidget(lbl_res)

        self.combo_resolution = AutoPopupComboBox(frame)
        self._setup_fixed_combo(self.combo_resolution)
        for key, label, _target in _RESOLUTION_PRESETS:
            self.combo_resolution.addItem(self.tr(label), key)
        v.addWidget(self.combo_resolution)
        self.combo_resolution.currentIndexChanged.connect(self._on_resolution_changed)

        # ── Sub-panel Personalizado ───────────────────────────
        custom_container = QWidget(frame)
        custom_layout = QVBoxLayout(custom_container)
        custom_layout.setContentsMargins(0, 4, 0, 0)
        custom_layout.setSpacing(6)

        dims_row = QHBoxLayout()
        dims_row.setSpacing(8)

        w_col = QVBoxLayout()
        lbl_w = QLabel(self.tr("Ancho:"), custom_container)
        lbl_w.setObjectName("menuLabel")
        w_col.addWidget(lbl_w)
        self.spin_custom_width = QSpinBox(custom_container)
        self.spin_custom_width.setRange(2, 7680)
        self.spin_custom_width.setSingleStep(2)
        self.spin_custom_width.setValue(1920)
        # Sin esto, valueChanged (y con él el redondeo a par + recálculo del alto vinculado)
        # dispara en cada tecla que escribís, no solo al terminar — por eso "19" saltaba a "20"
        # a mitad de escritura en vez de esperar a que sueltes el campo.
        self.spin_custom_width.setKeyboardTracking(False)
        w_col.addWidget(self.spin_custom_width)
        dims_row.addLayout(w_col)

        h_col = QVBoxLayout()
        lbl_h = QLabel(self.tr("Alto:"), custom_container)
        lbl_h.setObjectName("menuLabel")
        h_col.addWidget(lbl_h)
        self.spin_custom_height = QSpinBox(custom_container)
        self.spin_custom_height.setRange(2, 7680)
        self.spin_custom_height.setSingleStep(2)
        self.spin_custom_height.setValue(1080)
        self.spin_custom_height.setKeyboardTracking(False)
        h_col.addWidget(self.spin_custom_height)
        dims_row.addLayout(h_col)

        custom_layout.addLayout(dims_row)

        self.chk_keep_aspect = QCheckBox(self.tr("Conservar relación de aspecto"), custom_container)
        self.chk_keep_aspect.setCursor(Qt.PointingHandCursor)
        self.chk_keep_aspect.setChecked(True)
        self.chk_keep_aspect.setToolTip(self.tr(
            "Al escribir un valor, el otro se recalcula solo para mantener la proporción real del "
            "archivo de origen."
        ))
        custom_layout.addWidget(self.chk_keep_aspect)

        self.lbl_source_aspect = QLabel(self.tr("Fuente: -"), custom_container)
        self.lbl_source_aspect.setObjectName("mutedLabel")
        custom_layout.addWidget(self.lbl_source_aspect)

        fit_row = QHBoxLayout()
        fit_row.setSpacing(14)
        self.fit_mode_group = QButtonGroup(custom_container)
        self.rb_fit_deformar = QRadioButton(self.tr(_FIT_MODE_LABELS["deformar"]), custom_container)
        self.rb_fit_ajustar = QRadioButton(self.tr(_FIT_MODE_LABELS["ajustar"]), custom_container)
        self.rb_fit_crop = QRadioButton(self.tr(_FIT_MODE_LABELS["crop"]), custom_container)
        self.rb_fit_deformar.setToolTip(self.tr(_FIT_MODE_TOOLTIPS["deformar"]))
        self.rb_fit_ajustar.setToolTip(self.tr(_FIT_MODE_TOOLTIPS["ajustar"]))
        self.rb_fit_crop.setToolTip(self.tr(_FIT_MODE_TOOLTIPS["crop"]))
        self.rb_fit_ajustar.setChecked(True)
        for rb in (self.rb_fit_deformar, self.rb_fit_ajustar, self.rb_fit_crop):
            rb.setCursor(Qt.PointingHandCursor)
            self.fit_mode_group.addButton(rb)
            fit_row.addWidget(rb)
        custom_layout.addLayout(fit_row)

        v.addWidget(custom_container)
        self.widget_custom_resolution = custom_container
        custom_container.setVisible(False)

        self.spin_custom_width.valueChanged.connect(lambda _v: self._on_custom_dim_changed("width"))
        self.spin_custom_height.valueChanged.connect(lambda _v: self._on_custom_dim_changed("height"))
        self.chk_keep_aspect.toggled.connect(self._on_keep_aspect_toggled)
        for rb in (self.rb_fit_deformar, self.rb_fit_ajustar, self.rb_fit_crop):
            rb.toggled.connect(self._update_size_estimate)

        self.frame_transform = frame
        return frame

    def _build_container_section(self, parent=None) -> QFrame:
        frame, v = self._card_frame(self.tr("Contenedor de salida"), parent=parent)

        self.combo_container = AutoPopupComboBox(frame)
        self._setup_fixed_combo(self.combo_container)
        v.addWidget(self.combo_container)

        lbl_hint = QLabel(self.tr("Se muestran únicamente los contenedores compatibles con los códecs seleccionados."), frame)
        lbl_hint.setObjectName("mutedLabel")
        lbl_hint.setWordWrap(True)
        v.addWidget(lbl_hint)

        self.combo_container.currentIndexChanged.connect(self._on_container_changed)
        self.frame_container = frame
        return frame

    def _build_size_estimate_section(self, parent=None) -> QFrame:
        frame, v = self._card_frame(self.tr("Peso final estimado"), parent=parent)

        self.lbl_source_info = QLabel(self.tr("Selecciona un archivo en la cola para estimar el peso."), frame)
        self.lbl_source_info.setObjectName("mutedLabel")
        self.lbl_source_info.setWordWrap(True)
        v.addWidget(self.lbl_source_info)

        self.lbl_size_estimate = QLabel("", frame)
        self.lbl_size_estimate.setWordWrap(True)
        self.lbl_size_estimate.setObjectName("sectionTitle")
        v.addWidget(self.lbl_size_estimate)

        self.frame_size = frame
        return frame

    def _build_messages_section(self, parent=None) -> QFrame:
        frame, v = self._card_frame(self.tr("Estado de compatibilidad"), parent=parent)
        self.messages_layout = QVBoxLayout()
        self.messages_layout.setContentsMargins(0, 2, 0, 2)
        self.messages_layout.setSpacing(6)
        v.addLayout(self.messages_layout)
        return frame

    # ─── Poblado de combos ──────────────────────────────────────

    def _reload_codec_lists(self):
        self._building = True
        try:
            for combo, codecs in (
                (self.combo_video_codec, get_video_codecs(only_verified=False)),
                (self.combo_audio_codec, get_audio_codecs(only_verified=False)),
            ):
                combo.clear()
                model = combo.model()
                current_cat = None
                
                for c in codecs:
                    cat = c.get("category", "Otros")
                    if cat != current_cat:
                        current_cat = cat
                        # Insert header
                        combo.addItem(f"─── {current_cat.upper()} ───")
                        
                        # Disable the header item
                        idx = combo.count() - 1
                        item = model.item(idx)
                        item.setEnabled(False)
                        
                        # Style it
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                        item.setTextAlignment(Qt.AlignCenter)
                        
                    label = c["display_name"] if c["verified"] else f"{c['display_name']} (sin verificar)"
                    combo.addItem(f"  {label}", c["codec_id"])
                    
                # Seleccionar el primer elemento que esté habilitado (saltando las cabeceras)
                for i in range(combo.count()):
                    if model.item(i).isEnabled():
                        combo.setCurrentIndex(i)
                        break
        finally:
            self._building = False

    # ─── Logica de cambio de seleccion ──────────────────────────

    def _current_stream_mode(self) -> str:
        """Devuelve 'video+audio', 'audio_only' o 'video_only'."""
        if not hasattr(self, "mode_selector"):
            return "video+audio"
        if self.mode_selector.btn_audio.isChecked():
            return "audio_only"
        if self.mode_selector.btn_video.isChecked():
            return "video_only"
        return "video+audio"

    def _on_mode_changed(self, _mode_text: str = ""):
        self._on_selection_changed()

    def _current_video_codec(self):
        if self._current_stream_mode() == "audio_only":
            return None
        if getattr(self, "frame_video", None) and not self.frame_video.isEnabled():
            return None
        if self.rb_video_copy.isChecked():
            return None
        return self.combo_video_codec.currentData()

    def _current_audio_codec(self):
        if self._current_stream_mode() == "video_only":
            return None
        if getattr(self, "frame_audio", None) and not self.frame_audio.isEnabled():
            return None
        if self.rb_audio_copy.isChecked():
            return None
        return self.combo_audio_codec.currentData()

    def _on_video_codec_changed(self, *_args):
        if self._building:
            return
        video_codec = self._current_video_codec()
        if video_codec and self.rb_audio_recode.isChecked():
            self._apply_audio_recommendation(video_codec)
        self._revalidate_custom_dimensions()
        self._on_selection_changed()

    def _apply_audio_recommendation(self, video_codec_id: str):
        """Autocompleta el codec de audio recomendado para agilizar el flujo."""
        recommended = recommend_audio_codec(video_codec_id)
        idx = self.combo_audio_codec.findData(recommended)
        if idx < 0 or idx == self.combo_audio_codec.currentIndex():
            return
        self._building = True
        try:
            self.combo_audio_codec.setCurrentIndex(idx)
        finally:
            self._building = False
        self._last_profile_codec["audio"] = None

    def _on_selection_changed(self, *_args):
        if self._building:
            return

        stream_mode = self._current_stream_mode()
        is_audio_only = (stream_mode == "audio_only")
        is_video_only = (stream_mode == "video_only")

        # Habilitar o deshabilitar columnas según el selector de modo
        if getattr(self, "frame_video", None):
            self.frame_video.setEnabled(not is_audio_only)

        is_gif = (self.combo_video_codec.currentData() == "gif" and self.rb_video_recode.isChecked() and not is_audio_only)
        if getattr(self, "frame_audio", None):
            self.frame_audio.setEnabled((not is_video_only) and (not is_gif))

        # Habilitar o deshabilitar campos según modo recodificar vs copiar
        video_recode = self.rb_video_recode.isChecked() and (not is_audio_only)
        audio_recode = self.rb_audio_recode.isChecked() and (not is_video_only)

        self.combo_video_codec.setEnabled(video_recode)
        self.combo_audio_codec.setEnabled(audio_recode)
        self.combo_video_profile.setEnabled(video_recode)
        self.combo_audio_profile.setEnabled(audio_recode)
        if hasattr(self, "combo_audio_channels"):
            self.combo_audio_channels.setEnabled(audio_recode)
        if hasattr(self, "combo_audio_samplerate"):
            self.combo_audio_samplerate.setEnabled(audio_recode)
        if getattr(self, "frame_transform", None):
            # Un filtro de video (-vf) o -r no puede aplicarse con -c:v copy.
            self.frame_transform.setEnabled(video_recode)
            self.frame_transform.setToolTip(
                "" if video_recode else self.tr("No disponible con Video en modo 'Copiar original'.")
            )

        self._relayout_cards()
        self._update_engine_label()
        self._refresh_variant_combo("video", self._current_video_codec())
        self._refresh_variant_combo("audio", self._current_audio_codec())
        self._refresh_profile_combo("video", self._current_video_codec())
        self._refresh_profile_combo("audio", self._current_audio_codec())
        self._update_two_pass_visibility()
        self._refresh_container_options()
        self._evaluate_and_render()
        self._update_size_estimate()

    def _relayout_cards(self):
        """Reorganiza dinámicamente las tarjetas en la cuadrícula de 2 columnas según el modo activo."""
        if not hasattr(self, "cards_grid") or not hasattr(self, "frame_container") or not hasattr(self, "frame_size"):
            return

        stream_mode = self._current_stream_mode()
        has_transform = getattr(self, "frame_transform", None) is not None

        if stream_mode == "audio_only":
            self.frame_video.hide()
            self.frame_audio.show()
            if has_transform:
                self.frame_transform.hide()
            visible_cards = [self.frame_audio, self.frame_container, self.frame_size]
        elif stream_mode == "video_only":
            self.frame_audio.hide()
            self.frame_video.show()
            visible_cards = [self.frame_video]
            if has_transform:
                self.frame_transform.show()
                visible_cards.append(self.frame_transform)
            visible_cards += [self.frame_container, self.frame_size]
        else: # video+audio
            self.frame_video.show()
            self.frame_audio.show()
            visible_cards = [self.frame_video, self.frame_audio]
            if has_transform:
                self.frame_transform.show()
                visible_cards.append(self.frame_transform)
            visible_cards += [self.frame_container, self.frame_size]

        while self.cards_grid.count():
            self.cards_grid.takeAt(0)

        for idx, card in enumerate(visible_cards):
            row = idx // 2
            col = idx % 2
            self.cards_grid.addWidget(card, row, col)
            card.show()

    def _refresh_variant_combo(self, prefix: str, codec_id):
        combo = getattr(self, f"combo_{prefix}_variant")
        lbl = getattr(self, f"lbl_{prefix}_variant")
        variants = ENCODER_VARIANTS.get(codec_id) if codec_id else None
        self._building = True
        try:
            combo.clear()
            if not variants:
                combo.setVisible(False)
                lbl.setVisible(False)
                return
            for encoder, label in variants:
                combo.addItem(label, encoder)
            combo.setVisible(True)
            lbl.setVisible(True)
        finally:
            self._building = False

    def _on_variant_changed(self, prefix: str):
        if self._building:
            return
        self._last_profile_codec[prefix] = None
        self._refresh_profile_combo(prefix, getattr(self, f"combo_{prefix}_codec").currentData())
        if prefix == "video":
            self._update_two_pass_visibility()
        self._evaluate_and_render()
        self._update_size_estimate()

    def _effective_encoder(self, prefix: str, codec_id):
        if not codec_id:
            return None
        variant_combo = getattr(self, f"combo_{prefix}_variant")
        if variant_combo.isVisible() and variant_combo.currentData():
            return variant_combo.currentData()
            
        if prefix == "video" and self._force_cpu_engine:
            from core.utils.recode_guard import _load_matrix
            matrix = _load_matrix()
            entry = matrix.get("codecs", {}).get(codec_id)
            return entry.get("encoder") if entry else resolve_encoder(codec_id)
            
        return resolve_encoder(codec_id)

    def _on_profile_changed(self, prefix: str):
        if self._building:
            return
        profile = getattr(self, f"combo_{prefix}_profile").currentData()
        custom_type = profile.get("custom") if profile else None
        
        custom_container = getattr(self, f"widget_{prefix}_custom")
        bitrate_spin = getattr(self, f"spin_{prefix}_bitrate")
        cq_spin = getattr(self, f"spin_{prefix}_cq")
        lbl_custom = getattr(self, f"lbl_{prefix}_custom")
        widget_gif_custom = getattr(self, "widget_video_gif_custom", None)

        is_gif_custom = (prefix == "video" and custom_type == "gif")
        custom_container.setVisible(bool(custom_type))

        if is_gif_custom:
            lbl_custom.setVisible(False)
            bitrate_spin.setVisible(False)
            cq_spin.setVisible(False)
            if widget_gif_custom:
                widget_gif_custom.setVisible(True)
        elif custom_type == "cq":
            lbl_custom.setVisible(True)
            lbl_custom.setText(self.tr("Nivel de calidad (CRF/CQ):"))
            bitrate_spin.setVisible(False)
            cq_spin.setVisible(True)
            if widget_gif_custom:
                widget_gif_custom.setVisible(False)
        elif custom_type in ("vbr", "cbr", "audio_bitrate"):
            lbl_custom.setVisible(True)
            lbl_custom.setText(self.tr("Bitrate objetivo:"))
            bitrate_spin.setVisible(True)
            cq_spin.setVisible(False)
            if widget_gif_custom:
                widget_gif_custom.setVisible(False)
        else:
            if widget_gif_custom:
                widget_gif_custom.setVisible(False)

        if prefix == "video":
            self._update_two_pass_visibility()
        self._update_size_estimate()

    def _update_two_pass_visibility(self):
        if not hasattr(self, "widget_video_passes"):
            return
        video_codec = self._current_video_codec()
        encoder = self._effective_encoder("video", video_codec)
        profile = self.combo_video_profile.currentData()

        show = encoder_is_two_pass_capable(encoder)
        can_use_2pass = supports_two_pass(encoder, profile)
        
        self.widget_video_passes.setVisible(show)
        self.rb_video_pass2.setEnabled(can_use_2pass)
        self.rb_video_pass2.setToolTip(
            self.tr("2 pasadas: más precisión de bitrate objetivo, tarda el doble.") if can_use_2pass
            else self.tr("Solo disponible con un perfil de bitrate objetivo (ej. 'Bitrate Personalizado'); no aplica a calidad constante (CRF/CQ).")
        )
        if not can_use_2pass:
            self.rb_video_pass1.setChecked(True)

    def _effective_args(self, prefix: str) -> list[str] | None:
        codec_id = self._current_video_codec() if prefix == "video" else self._current_audio_codec()
        if not codec_id:
            return None
        profile = getattr(self, f"combo_{prefix}_profile").currentData()
        if not profile:
            return None
            
        custom_type = profile.get("custom")
        args = []
        if custom_type:
            encoder = self._effective_encoder(prefix, codec_id)
            if custom_type == "gif":
                from core.tabs.video_tools.codec_profiles import build_custom_gif_args
                dither = self.combo_video_gif_dither.currentData() if hasattr(self, "combo_video_gif_dither") else "floyd_steinberg"
                stats = self.combo_video_gif_stats.currentData() if hasattr(self, "combo_video_gif_stats") else "full"
                colors = self.combo_video_gif_colors.currentData() if hasattr(self, "combo_video_gif_colors") else 256
                fps = self.combo_video_gif_fps.currentData() if hasattr(self, "combo_video_gif_fps") else None
                args = build_custom_gif_args(dither=dither or "floyd_steinberg", stats_mode=stats or "full", max_colors=colors or 256, fps=fps)
            elif custom_type == "cq":
                from core.tabs.video_tools.codec_profiles import build_custom_quality_args
                cq_val = getattr(self, f"spin_{prefix}_cq").value()
                args = build_custom_quality_args(encoder, cq_val)
            elif custom_type == "audio_bitrate":
                from core.tabs.video_tools.codec_profiles import build_custom_audio_bitrate_args
                bitrate = getattr(self, f"spin_{prefix}_bitrate").value()
                args = build_custom_audio_bitrate_args(encoder, bitrate)
            else:
                from core.tabs.video_tools.codec_profiles import build_custom_bitrate_args
                bitrate = getattr(self, f"spin_{prefix}_bitrate").value()
                args = build_custom_bitrate_args(encoder, custom_type, bitrate)
        else:
            args = list(profile["args"])
            
        if prefix == "audio":
            if hasattr(self, "combo_audio_channels"):
                channels = self.combo_audio_channels.currentData()
                if channels:
                    args.extend(["-ac", channels])
            if hasattr(self, "combo_audio_samplerate"):
                sr = self.combo_audio_samplerate.currentData()
                if sr:
                    args.extend(["-ar", sr])
                
        return args

    # ─── Datos del archivo fuente (cola de medios) ──────────────

    def set_source_media(self, meta: dict, filepath: str):
        self._source_meta = meta or None
        self._source_filepath = filepath
        self._update_source_info_label()
        self._update_source_aspect_label()
        self._evaluate_and_render()
        self._update_size_estimate()

    def _update_source_info_label(self):
        meta = self._source_meta
        if not meta:
            self.lbl_source_info.setText(self.tr("Selecciona un archivo en la cola para estimar el peso."))
            return
        dur = meta.get("duración", "-")
        vcod = meta.get("video_codec", "-")
        acod = meta.get("audio_codec", "-")
        self.lbl_source_info.setText(
            self.tr("Archivo de origen: duración {0} | video {1} | audio {2}").format(dur, vcod, acod)
        )

    def _source_codec(self, prefix: str):
        if not self._source_meta:
            return None
        key = "video_codec" if prefix == "video" else "audio_codec"
        return source_codec_id(self._source_meta.get(key))

    # ─── Transformación de video (CFR / Resolución / Aspecto) ───

    def _source_wh(self) -> tuple[int, int] | None:
        """Ancho/alto reales del archivo fuente, parseados de meta['resolución'] ('WxH')."""
        if not self._source_meta:
            return None
        raw = self._source_meta.get("resolución", "-")
        try:
            w_str, h_str = raw.lower().split("x")
            w, h = int(w_str), int(h_str)
            if w > 0 and h > 0:
                return w, h
        except (ValueError, AttributeError):
            pass
        return None

    def _update_source_aspect_label(self):
        if not hasattr(self, "lbl_source_aspect"):
            return
        wh = self._source_wh()
        if not wh:
            self.lbl_source_aspect.setText(self.tr("Fuente: -"))
            return
        w, h = wh
        divisor = math.gcd(w, h) or 1
        self.lbl_source_aspect.setText(
            self.tr("Fuente: {0}×{1} ({2}:{3})").format(w, h, w // divisor, h // divisor)
        )

    def _on_cfr_toggled(self, checked: bool):
        self.combo_cfr_fps.setEnabled(checked)
        self._update_size_estimate()

    def _on_resolution_changed(self, *_args):
        if self._building:
            return
        is_custom = self.combo_resolution.currentData() == "custom"
        self.widget_custom_resolution.setVisible(is_custom)
        if is_custom:
            self._update_source_aspect_label()
            self._update_fit_mode_enabled()
        self._update_size_estimate()

    def _round_to_even(self, value: int) -> int:
        return value if value % 2 == 0 else value + 1

    def _current_dimension_alignment(self) -> dict:
        """Requisito real de paridad ancho/alto para el códec de video elegido (ver
        core.utils.recode_guard.get_dimension_alignment, generado empíricamente contra el
        encoder — no todo códec 4:2:2/4:4:4 se comporta igual, ver notas del matrix)."""
        return get_dimension_alignment(self._current_video_codec())

    def _on_custom_dim_changed(self, which: str):
        if self._building:
            return
        alignment = self._current_dimension_alignment()

        spin = self.spin_custom_width if which == "width" else self.spin_custom_height
        needs_even = alignment["width_even_required" if which == "width" else "height_even_required"]
        if needs_even:
            rounded = self._round_to_even(spin.value())
            if rounded != spin.value():
                self._building = True
                try:
                    spin.setValue(rounded)
                finally:
                    self._building = False

        if self.chk_keep_aspect.isChecked():
            wh = self._source_wh()
            if wh:
                src_w, src_h = wh
                self._building = True
                try:
                    if which == "width":
                        new_h = round(self.spin_custom_width.value() * src_h / src_w)
                        if alignment["height_even_required"]:
                            new_h = self._round_to_even(new_h)
                        self.spin_custom_height.setValue(max(2, new_h))
                    else:
                        new_w = round(self.spin_custom_height.value() * src_w / src_h)
                        if alignment["width_even_required"]:
                            new_w = self._round_to_even(new_w)
                        self.spin_custom_width.setValue(max(2, new_w))
                finally:
                    self._building = False

        self._update_fit_mode_enabled()
        self._update_size_estimate()

    def _revalidate_custom_dimensions(self):
        """Vuelve a aplicar el redondeo de paridad a los campos Ancho/Alto ya cargados —
        se usa cuando cambia el códec de video, porque el requisito de paridad puede cambiar
        (ej. veniás de ProRes sin restricción y pasaste a H.264, que sí la exige)."""
        if not hasattr(self, "spin_custom_width"):
            return
        alignment = self._current_dimension_alignment()
        self._building = True
        try:
            if alignment["width_even_required"]:
                self.spin_custom_width.setValue(self._round_to_even(self.spin_custom_width.value()))
            if alignment["height_even_required"]:
                self.spin_custom_height.setValue(self._round_to_even(self.spin_custom_height.value()))
        finally:
            self._building = False
        self._update_fit_mode_enabled()

    def _on_keep_aspect_toggled(self, checked: bool):
        if checked:
            # Al reactivar el vínculo, recalcular el alto a partir del ancho actual para que
            # los dos campos vuelvan a quedar coherentes de inmediato.
            self._on_custom_dim_changed("width")
        self._update_fit_mode_enabled()

    def _update_fit_mode_enabled(self):
        """El selector Crop/Ajustar/Deformar solo importa cuando el aspecto conservado está
        desactivado y el W×H elegido no coincide con el aspecto real del fuente — en cualquier
        otro caso no hay nada que resolver."""
        mismatch = False
        if not self.chk_keep_aspect.isChecked():
            wh = self._source_wh()
            if wh:
                src_w, src_h = wh
                target_ratio = self.spin_custom_width.value() / self.spin_custom_height.value()
                source_ratio = src_w / src_h
                mismatch = abs(target_ratio - source_ratio) > 0.01
            else:
                # Sin metadata del fuente no se puede saber si coincide; se habilita por las dudas.
                mismatch = True
        enabled = (not self.chk_keep_aspect.isChecked()) and mismatch
        for rb in (self.rb_fit_deformar, self.rb_fit_ajustar, self.rb_fit_crop):
            rb.setEnabled(enabled)

    def _current_cfr_fps(self) -> float | None:
        """FPS elegido para CFR, parseado directo del texto mostrado en el combo (editable): sirve
        igual para un valor predefinido ("30 fps") que para uno escrito a mano ("48"), sin
        depender de si currentIndex/currentData quedaron sincronizados con lo que se ve en pantalla."""
        if not hasattr(self, "combo_cfr_fps"):
            return None
        text = self.combo_cfr_fps.currentText().strip().lower().replace("fps", "").replace(",", ".").strip()
        try:
            value = float(text)
            return value if value > 0 else None
        except ValueError:
            return None

    def _current_fit_mode(self) -> str:
        if self.rb_fit_crop.isChecked():
            return "crop"
        if self.rb_fit_deformar.isChecked():
            return "deformar"
        return "ajustar"

    def _build_vf_expression(self) -> str | None:
        preset = self.combo_resolution.currentData() if hasattr(self, "combo_resolution") else "original"
        if not preset or preset == "original":
            return None

        if preset == "custom":
            w = self.spin_custom_width.value()
            h = self.spin_custom_height.value()
            if self.chk_keep_aspect.isChecked():
                return f"scale={w}:{h}"
            fit_mode = self._current_fit_mode()
            if fit_mode == "deformar":
                return f"scale={w}:{h}"
            if fit_mode == "crop":
                return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
            return f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"

        target = next((t for key, _label, t in _RESOLUTION_PRESETS if key == preset), None)
        if not target:
            return None
        return f"scale='if(gt(iw,ih),{target},-2)':'if(gt(iw,ih),-2,{target})'"

    def _transform_args(self, video_args: list[str]) -> list[str]:
        """Fusiona el filtro de resolución/aspecto (si hay) y el -r de CFR (si está activo) con
        los args que ya trae el perfil de códec — reusando el -vf existente en vez de agregar uno
        segundo, para no romper perfiles que ya arman su propio filtro (ej. paleta de GIF)."""
        args = list(video_args) if video_args else []

        vf_expr = self._build_vf_expression()
        if vf_expr:
            if "-vf" in args:
                idx = args.index("-vf") + 1
                args[idx] = f"{args[idx]},{vf_expr}"
            else:
                args += ["-vf", vf_expr]

        if hasattr(self, "chk_cfr") and self.chk_cfr.isChecked():
            fps = self._current_cfr_fps()
            if fps:
                args += ["-r", f"{fps:g}"]

        return args

    def _guard_codec(self, prefix: str):
        stream_mode = self._current_stream_mode()
        if prefix == "video" and stream_mode == "audio_only":
            return None
        if prefix == "audio" and stream_mode == "video_only":
            return None

        frame = getattr(self, f"frame_{prefix}", None)
        if frame and not frame.isEnabled():
            return None
            
        is_copy = getattr(self, f"rb_{prefix}_copy").isChecked()
        if is_copy:
            return self._source_codec(prefix)
        return getattr(self, f"combo_{prefix}_codec").currentData()

    def _update_size_estimate(self, *_args):
        if self._building or not hasattr(self, "lbl_size_estimate"):
            return

        if not self._source_meta:
            self.lbl_size_estimate.setText("")
            return

        duration_sec = parse_duration_to_seconds(self._source_meta.get("duración", "0"))
        if duration_sec <= 0:
            self.lbl_size_estimate.setText(self.tr("Duración del archivo todavía no disponible."))
            return

        stream_mode = self._current_stream_mode()

        def stream_kbps(prefix, meta_key, arg_flag):
            if getattr(self, f"rb_{prefix}_copy").isChecked():
                return parse_kbps_from_label(self._source_meta.get(meta_key))
            args = self._effective_args(prefix)
            return extract_bitrate_kbps(args, arg_flag) if args else None

        video_kbps = stream_kbps("video", "bitrate_video", "-b:v") if stream_mode != "audio_only" else None
        audio_kbps = stream_kbps("audio", "bitrate_audio", "-b:a") if stream_mode != "video_only" else None
        size_mb = estimate_size_mb(video_kbps, audio_kbps, duration_sec)

        if size_mb is None:
            self.lbl_size_estimate.setText(self.tr(
                "No se puede estimar: ningún stream tiene un bitrate fijo conocido (perfiles de "
                "calidad constante como CRF/CQ no tienen un tamaño predecible de antemano)."
            ))
            return

        parts = []
        if stream_mode != "audio_only":
            parts.append(self.tr("video: {0:.0f} kbps").format(video_kbps) if video_kbps is not None
                          else self.tr("video: sin bitrate fijo, no incluido"))
        if stream_mode != "video_only":
            parts.append(self.tr("audio: {0:.0f} kbps").format(audio_kbps) if audio_kbps is not None
                          else self.tr("audio: sin bitrate fijo, no incluido"))

        self.lbl_size_estimate.setText(
            self.tr("~ {0:.1f} MB").format(size_mb) + "  (" + ", ".join(parts) + ")"
        )

    def _refresh_profile_combo(self, prefix: str, codec_id):
        if codec_id == self._last_profile_codec[prefix]:
            return
        self._last_profile_codec[prefix] = codec_id

        combo = getattr(self, f"combo_{prefix}_profile")
        lbl = getattr(self, f"lbl_{prefix}_profile")
        self._building = True
        try:
            combo.clear()
            if not codec_id:
                combo.setEnabled(False)
                lbl.setVisible(False)
                combo.setVisible(False)
                return
            encoder = self._effective_encoder(prefix, codec_id)
            profiles = get_profiles(prefix, encoder)
            for p in profiles:
                combo.addItem(p["label"], p)
            combo.setEnabled(bool(profiles))
            lbl.setVisible(True)
            combo.setVisible(True)
        finally:
            self._building = False
        self._on_profile_changed(prefix)

    def _on_container_changed(self, *_args):
        if self._building:
            return
        self._evaluate_and_render()

    def _toggle_engine_mode(self):
        self._force_cpu_engine = not self._force_cpu_engine
        self._on_video_codec_changed()

    def _update_engine_label(self):
        codec_id = self._current_video_codec()
        if not codec_id:
            self.lbl_video_engine.setVisible(False)
            return
        
        hw_info = detect_hardware()
        status = hw_info.get("codec_status", {}).get(codec_id)
        
        has_hw = bool(status and status.get("status") == "full")
        is_cpu_forced = self._force_cpu_engine

        if is_cpu_forced or not has_hw:
            self.lbl_video_engine.setText(self.tr("CPU"))
            self.lbl_video_engine.setStyleSheet("""
                QPushButton {
                    background-color: rgba(255, 255, 255, 0.08);
                    color: #aaaaaa;
                    border: 1px solid rgba(255, 255, 255, 0.15);
                    border-radius: 4px;
                    padding: 2px 8px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: rgba(255, 255, 255, 0.15); }
            """)
            if has_hw:
                self.lbl_video_engine.setToolTip(self.tr("Clic para usar aceleración por GPU"))
            else:
                self.lbl_video_engine.setToolTip("")
        else:
            self.lbl_video_engine.setText(self.tr("GPU Acelerado"))
            self.lbl_video_engine.setStyleSheet("""
                QPushButton {
                    background-color: rgba(185, 230, 64, 0.15);
                    color: #B9E640;
                    border: 1px solid rgba(185, 230, 64, 0.35);
                    border-radius: 4px;
                    padding: 2px 8px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: rgba(185, 230, 64, 0.25); }
            """)
            self.lbl_video_engine.setToolTip(self.tr("Clic para usar codificación por CPU"))

        self.lbl_video_engine.setVisible(True)
        self.lbl_video_engine.setEnabled(has_hw)

    def _refresh_container_options(self):
        self._building = True
        try:
            v_codec = self._guard_codec("video")
            a_codec = self._guard_codec("audio")
            codec_ids = [c for c in (v_codec, a_codec) if c]
            containers = get_compatible_containers(codec_ids) if codec_ids else []
            current = self.combo_container.currentData()
            self.combo_container.clear()
            for cont_id in containers:
                label = _CONTAINER_LABELS.get(cont_id, cont_id.upper())
                self.combo_container.addItem(label, cont_id)

            stream_mode = self._current_stream_mode()
            is_audio_only = (stream_mode == "audio_only")
            primary_codec = a_codec if is_audio_only else v_codec
            preferred = _PREFERRED_CONTAINER_BY_CODEC.get(primary_codec)

            # Auto-selección inteligente de contenedor:
            # 1. En modo Solo Audio: auto-seleccionar siempre de inmediato el contenedor nativo del códec de audio
            if is_audio_only and preferred in containers:
                target = preferred
            # 2. En video: Códecs con contenedor obligatorio / estándar de la industria (ProRes/DNxHD/etc -> MOV, GIF -> GIF):
            elif primary_codec in ("prores", "dnxhd", "dnxhr", "cfhd", "qtrle", "hap", "gif", "apng") and preferred in containers:
                target = preferred
            # 3. Si el contenedor actual sigue siendo compatible y válido en la lista, conservarlo
            elif current and self.combo_container.findData(current) >= 0:
                target = current
            # 4. Si el contenedor anterior no es compatible, usar el preferido del códec si está en la lista
            elif preferred and preferred in containers:
                target = preferred
            # 5. Homónimo directo (ej. webp, flac, mp3, wav)
            elif v_codec and v_codec in containers:
                target = v_codec
            elif a_codec and a_codec in containers:
                target = a_codec
            else:
                target = None

            if target:
                idx = self.combo_container.findData(target)
                if idx >= 0:
                    self.combo_container.setCurrentIndex(idx)
        finally:
            self._building = False

    # ─── Evaluacion contra el colchon ───────────────────────────

    def _clear_messages(self):
        while self.messages_layout.count():
            child = self.messages_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _add_message(self, severity: str, text: str, compact: bool = False):
        color = get_theme_token(_SEVERITY_TOKENS[severity], "#aaaaaa")
        label_text = f"● {text}" if compact else f"● {_SEVERITY_LABELS[severity]}: {text}"
        lbl = QLabel(label_text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {color}; font-size: {'13px' if compact else '12px'}; font-weight: {'bold' if compact else 'normal'};")
        self.messages_layout.addWidget(lbl)

    def _refresh_audio_channel_options(self, container_id: str | None):
        """Muestra/oculta y habilita/deshabilita las opciones del combo 'Canales' según lo
        que el codec de audio elegido soporta en el contenedor elegido (ver
        recode_guard.get_channel_support / ffmpeg_codec_matrix.json)."""
        if not hasattr(self, "combo_audio_channels"):
            return
        combo = self.combo_audio_channels
        audio_codec = self._current_audio_codec()
        support = get_channel_support(audio_codec, container_id) if (audio_codec and container_id) else {}

        self._building = True
        try:
            model = combo.model()
            view = combo.view()
            current_data = combo.currentData()
            reset_needed = False
            for i in range(combo.count()):
                data = combo.itemData(i)
                if not data:
                    continue  # "Igual al original": siempre disponible
                info = support.get(data)
                enabled = info["supported"] if info else True
                item = model.item(i)
                item.setEnabled(enabled)
                item.setToolTip((info or {}).get("reason") or "" if not enabled else "")
                view.setRowHidden(i, not enabled)
                if not enabled and data == current_data:
                    reset_needed = True
            if reset_needed:
                combo.setCurrentIndex(0)
        finally:
            self._building = False

    def _evaluate_and_render(self):
        self._clear_messages()
        container_id = self.combo_container.currentData()
        self._refresh_audio_channel_options(container_id)

        if not container_id:
            self._add_message("unverified", self.tr("No hay ningún contenedor compatible con la combinación de codecs elegida."))
            self._last_valid = False
            self._invalid_reason = self.tr("Sin contenedor compatible")
            self.validity_changed.emit(False)
            return

        result = evaluate_recode(self._guard_codec("video"), self._guard_codec("audio"), container_id)

        if not result["issues"]:
            self._add_message("ok", self.tr("Configuración compatible y lista para procesar."), compact=True)
        else:
            for issue in result["issues"]:
                if issue["check"] == "playback_risk":
                    message = self._format_playback_risk_message(issue["risk"])
                else:
                    message = issue["message"]
                self._add_message(issue["severity"], message)

        self._last_valid = result["verdict"] != "blocked"
        self._invalid_reason = self.tr("Combinación no compatible") if not self._last_valid else ""
        self.validity_changed.emit(self._last_valid)

    def _format_playback_risk_message(self, risk: dict) -> str:
        """Arma el texto final del warning de "riesgo de reproducción" (ver
        recode_guard._check_playback_risk, que solo devuelve datos estructurados).
        Vive acá y no en recode_guard.py porque necesita self.tr() para ser
        traducible — ese módulo es lógica pura, no un QObject.

        level="none"/"planned" es un caso distinto de los demás: ahí ffmpeg logró
        el mux pero el estándar del contenedor directamente NO contempla esta
        combinación (no es solo "no estándar" o "parcial"), así que se avisa con
        una frase separada en vez de reusar la plantilla genérica con una
        descripción de nivel que diría, de forma confusa, "no es estándar (sin
        soporte)"."""
        level = risk.get("level")

        if level in ("none", "planned"):
            msg = self.tr(
                "ffmpeg permite generar este archivo, pero el estándar del contenedor "
                "no contempla esta combinación de codec"
            )
        else:
            level_descriptions = {
                "partial": self.tr("soporte restringido a un perfil, versión o subformato específico"),
                "indirect": self.tr("soporte indirecto a través de un mecanismo externo, no nativo del contenedor"),
                "requires_external": self.tr("requiere un componente o codec adicional instalado aparte"),
                "private": self.tr("implementación privada o no estandarizada del contenedor"),
                "nonstandard": self.tr("reconocido por algunos reproductores/editores pero no forma parte del estándar"),
                "problematic": self.tr("técnicamente posible pero problemático o poco fiable en la práctica"),
                "beta": self.tr("soporte en fase beta, puede ser inestable"),
            }
            desc = level_descriptions.get(level, level)
            msg = self.tr("ffmpeg acepta este mux, pero no es un uso estándar del contenedor ({0})").format(desc)

        extra = None
        if risk.get("via"):
            via_labels = {
                "vcm": self.tr("Video Compression Manager (VCM)"),
                "acm": self.tr("Audio Compression Manager (ACM)"),
            }
            extra = self.tr("vía {0}").format(via_labels.get(risk["via"], risk["via"]))
        elif risk.get("requires"):
            extra = self.tr("requiere {0}").format(risk["requires"])
        elif risk.get("note"):
            extra = risk["note"]  # hecho técnico (nombre de perfil/formato), no se traduce a propósito

        if extra:
            msg += f" — {extra}"
        msg += ". " + self.tr("Podría no reproducirse en todos los reproductores/dispositivos.")
        return msg

    # ─── API publica ─────────────────────────────────────────────

    def is_valid(self) -> bool:
        return self._last_valid

    def get_status(self) -> tuple[bool, str]:
        if not self._last_valid:
            return False, self._invalid_reason or self.tr("Combinación no compatible")
        return True, self.tr("Iniciar Recodificación")

    def get_settings(self) -> dict:
        stream_mode = self._current_stream_mode()
        v_codec = self._current_video_codec()
        is_gif = (v_codec == "gif" and self.rb_video_recode.isChecked())
        video_recode_active = (stream_mode != "audio_only" and self.rb_video_recode.isChecked())
        video_args = self._effective_args("video") if video_recode_active else None
        if video_args is not None and video_recode_active:
            # Fusiona -vf (resolución/aspecto) y -r (CFR) con los args del perfil de códec ANTES
            # de dividir en pasadas, para que ambas pasadas de un 2-pass usen el mismo filtro.
            video_args = self._transform_args(video_args)
        passes = 2 if (video_args and self.rb_video_pass2.isChecked() and self.rb_video_pass2.isEnabled() and stream_mode != "audio_only" and not is_gif) else 1

        resolution_preset = self.combo_resolution.currentData() if hasattr(self, "combo_resolution") else "original"
        settings = {
            "stream_mode": stream_mode,
            "video_mode": "copy" if self.rb_video_copy.isChecked() else "recode",
            "video_codec": v_codec,
            "video_args": video_args,
            "video_passes": passes,
            "audio_mode": "copy" if self.rb_audio_copy.isChecked() else "recode",
            "audio_codec": self._current_audio_codec() if not is_gif else None,
            "audio_args": self._effective_args("audio") if (stream_mode != "video_only" and self.rb_audio_recode.isChecked() and not is_gif) else None,
            "container": self.combo_container.currentData(),
            "resolution_preset": resolution_preset,
            "custom_width": self.spin_custom_width.value() if (hasattr(self, "spin_custom_width") and resolution_preset == "custom") else None,
            "custom_height": self.spin_custom_height.value() if (hasattr(self, "spin_custom_height") and resolution_preset == "custom") else None,
            "keep_aspect_ratio": self.chk_keep_aspect.isChecked() if hasattr(self, "chk_keep_aspect") else True,
            "fit_mode": self._current_fit_mode() if hasattr(self, "rb_fit_ajustar") else "ajustar",
            "force_cfr": self.chk_cfr.isChecked() if hasattr(self, "chk_cfr") else False,
            "target_fps": self._current_cfr_fps() if (hasattr(self, "chk_cfr") and self.chk_cfr.isChecked()) else None,
        }
        if passes == 2:
            settings["video_args_pass1"] = build_pass_args(video_args, 1)
            settings["video_args_pass2"] = build_pass_args(video_args, 2)
        return settings
