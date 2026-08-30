# src/gui/tabs/video_tools/convert_panel.py
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QLabel,
    QComboBox,
    QRadioButton,
    QButtonGroup,
    QStackedWidget,
    QSpinBox,
    QDoubleSpinBox,
    QSizePolicy,
    QScrollArea,
)
from PySide6.QtCore import Signal, Qt

from gui.styles import get_theme_token
from gui.widgets.mode_selector import ModeSelector
from gui.widgets.engine_badge import EngineBadge
from gui.widgets.combo_box import CheckmarkComboDelegate, AutoPopupComboBox
from core.utils.recode_guard import (
    resolve_encoder, get_video_codecs, get_audio_codecs, get_compatible_containers,
    has_hardware_encoder, software_encoder, is_stream_copy_compatible, container_supports_video,
    CONTAINER_LABELS,
)
from core.tabs.video_tools.codec_profiles import build_custom_quality_args, build_custom_bitrate_args, build_custom_audio_bitrate_args
from core.tabs.video_tools.size_estimator import parse_duration_to_seconds
import core.tabs.video_tools.convert_advisor as advisor

_MAX_VISIBLE_COMBO_ITEMS = 12

# Mismo criterio que Comprimir: solo familias de video/audio orientadas a
# distribucion (ProRes/DNxHR/GIF/lossless quedan exclusivos de Avanzado).
_VIDEO_CODEC_IDS = ["h264", "hevc", "av1", "vp9"]
_AUDIO_CODEC_IDS = ["aac", "opus", "mp3"]

_QUALITY_MODE_CQ = "cq"
_QUALITY_MODE_BITRATE = "bitrate"
_QUALITY_MODE_TARGET_SIZE = "target_size"


class ConvertPanel(QWidget):
    """
    Pestaña "Convertir": selector Rápido/Manual.

    A diferencia de Comprimir (siempre recodifica, el eje es tamaño/calidad), acá el
    objetivo es cambiar de contenedor preservando calidad y velocidad - si el códec de
    origen ya es compatible con el contenedor destino (confirmado por el matrix, ver
    core/tabs/video_tools/convert_advisor.py), la conversión es un remux (-c copy,
    instantáneo, sin pérdida), decidido automáticamente por-archivo. Manual permite
    forzar recodificar (o forzar "Copiar" aunque no sea compatible, con la validación
    correspondiente) y elegir códec/calidad cuando sí hace falta recodificar.
    """

    validity_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._building = False
        self._last_valid = True
        self._invalid_reason = ""
        self._source_meta = None
        self._source_filepath = None
        self._queue_entries: list[tuple[str, dict]] = []
        self._force_cpu_manual = False
        self._init_ui()
        self._reload_manual_video_codecs()
        self._refresh_quick_status()

    # ─── UI ──────────────────────────────────────────────────────

    def _init_ui(self):
        self.setObjectName("convertPanel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setObjectName("convertScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        self.setStyleSheet("""
            QWidget#convertPanel { background: transparent; }
            QScrollArea#convertScroll { background: transparent; }
            QWidget#convertContent { background: transparent; }
        """)

        content = QWidget(scroll)
        content.setObjectName("convertContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.mode_selector = ModeSelector(content, labels=[self.tr("Rápido"), self.tr("Manual")])
        self.mode_selector.mode_changed.connect(self._on_top_mode_changed)
        layout.addWidget(self.mode_selector)

        self.stack = QStackedWidget(content)
        self.page_quick = self._build_quick_page(self.stack)
        self.page_manual = self._build_manual_page(self.stack)
        self.stack.addWidget(self.page_quick)
        self.stack.addWidget(self.page_manual)
        layout.addWidget(self.stack)

        layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _card_frame(self, title: str | None = None, parent=None) -> tuple[QFrame, QVBoxLayout]:
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
            lbl.setAlignment(Qt.AlignCenter)
            v.addWidget(lbl)
        return frame, v

    def _setup_fixed_combo(self, combo: QComboBox):
        combo.setMaxVisibleItems(_MAX_VISIBLE_COMBO_ITEMS)
        combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(1)
        combo.setItemDelegate(CheckmarkComboDelegate(combo))
        combo.setCursor(Qt.PointingHandCursor)

    def _populate_container_combo(self, combo: QComboBox):
        """Lista COMPLETA de contenedores del matrix (a diferencia de Comprimir, acá no
        se filtra por códec de origen: el usuario elige destino libremente, la app decide
        después si hace falta recodificar - ver convert_advisor.plan_conversion), agrupada
        en Video / Solo Audio según lo que el matrix confirma que cada contenedor acepta
        (recode_guard.container_supports_video) - no una lista adivinada a mano, para que
        sea obvio de entrada qué contenedores implican descartar el video."""
        all_ids = get_compatible_containers([])
        video_ids = [c for c in all_ids if container_supports_video(c)]
        audio_ids = [c for c in all_ids if not container_supports_video(c)]
        model = combo.model()

        def add_group(title: str, container_ids: list[str]):
            if not container_ids:
                return
            combo.addItem(f"─── {title} ───")
            item = model.item(combo.count() - 1)
            item.setEnabled(False)
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            item.setTextAlignment(Qt.AlignCenter)
            for container_id in container_ids:
                label = CONTAINER_LABELS.get(container_id, container_id.upper())
                combo.addItem(f"  {label}", container_id)

        add_group(self.tr("VIDEO"), video_ids)
        add_group(self.tr("SOLO AUDIO"), audio_ids)

        idx = combo.findData("mp4")
        if idx >= 0:
            combo.setCurrentIndex(idx)

    # ─── Página Rápido ───────────────────────────────────────────

    def _build_quick_page(self, parent) -> QWidget:
        page = QWidget(parent)
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        lbl_container = QLabel(self.tr("Convertir a:"), page)
        lbl_container.setObjectName("menuLabel")
        v.addWidget(lbl_container)

        self.combo_quick_container = AutoPopupComboBox(page)
        self._setup_fixed_combo(self.combo_quick_container)
        self._populate_container_combo(self.combo_quick_container)
        self.combo_quick_container.currentIndexChanged.connect(self._on_quick_container_changed)
        v.addWidget(self.combo_quick_container)

        status_frame, status_layout = self._card_frame(self.tr("Este archivo"), page)
        self.lbl_quick_video_status = QLabel("", status_frame)
        self.lbl_quick_video_status.setWordWrap(True)
        status_layout.addWidget(self.lbl_quick_video_status)
        self.lbl_quick_audio_status = QLabel("", status_frame)
        self.lbl_quick_audio_status.setWordWrap(True)
        status_layout.addWidget(self.lbl_quick_audio_status)
        v.addWidget(status_frame)

        self.lbl_queue_summary = QLabel("", page)
        self.lbl_queue_summary.setObjectName("mutedLabel")
        self.lbl_queue_summary.setWordWrap(True)
        v.addWidget(self.lbl_queue_summary)

        v.addStretch(1)
        return page

    def _on_quick_container_changed(self, *_args):
        self._refresh_quick_status()

    def _current_quick_container(self) -> str:
        return self.combo_quick_container.currentData() or "mp4"

    def _stream_status_text(self, label: str, plan_value: str | None, codec_source: str | None) -> str:
        if plan_value is None:
            return self.tr("{0}: no tiene esta pista.").format(label)
        if plan_value == "copy":
            return self.tr("{0}: se copia tal cual ({1}) — sin recodificar, sin pérdida de calidad.").format(label, (codec_source or "").upper())
        container_label = CONTAINER_LABELS.get(self._current_quick_container(), self._current_quick_container().upper())
        return self.tr("{0}: se recodifica — {1} no es compatible con {2}.").format(label, (codec_source or "?").upper(), container_label)

    def _refresh_quick_status(self):
        if not hasattr(self, "lbl_quick_video_status"):
            return
        if not self._source_meta:
            self.lbl_quick_video_status.setText(self.tr("Selecciona un archivo en la cola para ver el detalle."))
            self.lbl_quick_audio_status.setText("")
        else:
            plan = advisor.plan_conversion(self._source_meta, self._current_quick_container())
            if plan["video_dropped_audio_only_container"]:
                self.lbl_quick_video_status.setText(self.tr("Video: se descarta — este contenedor es solo de audio."))
            else:
                self.lbl_quick_video_status.setText(self._stream_status_text(self.tr("Video"), plan["video"], plan["video_codec_source"]))
            self.lbl_quick_audio_status.setText(self._stream_status_text(self.tr("Audio"), plan["audio"], plan["audio_codec_source"]))

        self._refresh_queue_summary()

    def _refresh_queue_summary(self):
        if not hasattr(self, "lbl_queue_summary"):
            return
        if not self._queue_entries:
            self.lbl_queue_summary.setText("")
            return
        summary = advisor.summarize_queue(self._queue_entries, self._current_quick_container())
        if summary["total"] == 0:
            self.lbl_queue_summary.setText("")
            return
        if summary["needs_recode_names"]:
            names = ", ".join(summary["needs_recode_names"][:5])
            if len(summary["needs_recode_names"]) > 5:
                names += self.tr(" y {0} más").format(len(summary["needs_recode_names"]) - 5)
            self.lbl_queue_summary.setText(
                self.tr("{0} de {1} archivos se copian sin recodificar. {2} necesitan recodificar: {3}").format(
                    summary["full_copy"], summary["total"], len(summary["needs_recode_names"]), names
                )
            )
        else:
            self.lbl_queue_summary.setText(
                self.tr("Los {0} archivos de la cola se copian sin recodificar — conversión instantánea.").format(summary["total"])
            )

    # ─── Página Manual ───────────────────────────────────────────

    def _build_manual_page(self, parent) -> QWidget:
        page = QWidget(parent)
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        # Contenedor
        frame_container, cv = self._card_frame(self.tr("Contenedor de salida"), page)
        self.combo_manual_container = AutoPopupComboBox(frame_container)
        self._setup_fixed_combo(self.combo_manual_container)
        self._populate_container_combo(self.combo_manual_container)
        self.combo_manual_container.currentIndexChanged.connect(self._on_manual_container_changed)
        cv.addWidget(self.combo_manual_container)
        v.addWidget(frame_container)

        # Video
        frame_video, vv = self._card_frame(self.tr("Video"), page)
        self.frame_video = frame_video
        codec_header_row = QHBoxLayout()
        lbl_vcodec = QLabel(self.tr("Códec:"), frame_video)
        lbl_vcodec.setObjectName("menuLabel")
        codec_header_row.addWidget(lbl_vcodec, 1)
        self.badge_manual_video_engine = EngineBadge(frame_video)
        self.badge_manual_video_engine.toggled_force_cpu.connect(self._on_manual_force_cpu_toggled)
        codec_header_row.addWidget(self.badge_manual_video_engine)
        vv.addLayout(codec_header_row)

        self.combo_manual_video_codec = AutoPopupComboBox(frame_video)
        self._setup_fixed_combo(self.combo_manual_video_codec)
        self.combo_manual_video_codec.currentIndexChanged.connect(self._on_manual_video_codec_changed)
        vv.addWidget(self.combo_manual_video_codec)

        lbl_quality_mode = QLabel(self.tr("Modo de calidad (si se recodifica):"), frame_video)
        lbl_quality_mode.setObjectName("menuLabel")
        vv.addWidget(lbl_quality_mode)

        self.quality_mode_group = QButtonGroup(frame_video)
        self.rb_quality_cq = QRadioButton(self.tr("Calidad constante (CRF)"), frame_video)
        self.rb_quality_bitrate = QRadioButton(self.tr("Bitrate de video (kbps)"), frame_video)
        self.rb_quality_target = QRadioButton(self.tr("Tamaño objetivo (MB)"), frame_video)
        self.rb_quality_cq.setChecked(True)
        for rb in (self.rb_quality_cq, self.rb_quality_bitrate, self.rb_quality_target):
            rb.setCursor(Qt.PointingHandCursor)
            self.quality_mode_group.addButton(rb)
            rb.toggled.connect(self._on_quality_mode_toggled)
            vv.addWidget(rb)

        self.spin_manual_cq = QSpinBox(frame_video)
        self.spin_manual_cq.setRange(0, 51)
        self.spin_manual_cq.setValue(18)  # Convertir prioriza fidelidad: default mas alto que Comprimir.
        self.spin_manual_cq.setSuffix(self.tr(" (CRF/CQ — más bajo = más calidad y más peso)"))
        self.spin_manual_cq.valueChanged.connect(self._on_manual_changed)
        vv.addWidget(self.spin_manual_cq)

        self.spin_manual_bitrate = QSpinBox(frame_video)
        self.spin_manual_bitrate.setRange(100, 500000)
        self.spin_manual_bitrate.setSingleStep(500)
        self.spin_manual_bitrate.setValue(8000)
        self.spin_manual_bitrate.setSuffix(" kbps")
        self.spin_manual_bitrate.valueChanged.connect(self._on_manual_changed)
        self.spin_manual_bitrate.setVisible(False)
        vv.addWidget(self.spin_manual_bitrate)

        self.spin_manual_target_mb = QDoubleSpinBox(frame_video)
        self.spin_manual_target_mb.setRange(1.0, 100000.0)
        self.spin_manual_target_mb.setDecimals(1)
        self.spin_manual_target_mb.setValue(25.0)
        self.spin_manual_target_mb.setSuffix(" MB")
        self.spin_manual_target_mb.valueChanged.connect(self._on_manual_changed)
        self.spin_manual_target_mb.setVisible(False)
        vv.addWidget(self.spin_manual_target_mb)

        v.addWidget(frame_video)

        # Audio
        frame_audio, av = self._card_frame(self.tr("Audio"), page)
        lbl_acodec = QLabel(self.tr("Códec:"), frame_audio)
        lbl_acodec.setObjectName("menuLabel")
        av.addWidget(lbl_acodec)
        self.combo_manual_audio_codec = AutoPopupComboBox(frame_audio)
        self._setup_fixed_combo(self.combo_manual_audio_codec)
        self.combo_manual_audio_codec.currentIndexChanged.connect(self._on_manual_changed)
        av.addWidget(self.combo_manual_audio_codec)

        self.spin_manual_audio_bitrate = QSpinBox(frame_audio)
        self.spin_manual_audio_bitrate.setRange(32, 320)
        self.spin_manual_audio_bitrate.setSingleStep(32)
        self.spin_manual_audio_bitrate.setValue(256)  # idem CRF: default de fidelidad, no de ahorro.
        self.spin_manual_audio_bitrate.setSuffix(" kbps")
        self.spin_manual_audio_bitrate.valueChanged.connect(self._on_manual_changed)
        av.addWidget(self.spin_manual_audio_bitrate)
        v.addWidget(frame_audio)

        self.lbl_manual_status = QLabel("", page)
        self.lbl_manual_status.setObjectName("mutedLabel")
        self.lbl_manual_status.setWordWrap(True)
        v.addWidget(self.lbl_manual_status)

        v.addStretch(1)

        self._reload_manual_audio_codecs()
        return page

    def _reload_manual_video_codecs(self):
        self._building = True
        try:
            self.combo_manual_video_codec.clear()
            self.combo_manual_video_codec.addItem(self.tr("Copiar (si es compatible)"), "copy")
            for codec in get_video_codecs(only_verified=False):
                if codec["codec_id"] in _VIDEO_CODEC_IDS:
                    self.combo_manual_video_codec.addItem(codec["display_name"], codec["codec_id"])
        finally:
            self._building = False
        self._on_manual_video_codec_changed()

    def _reload_manual_audio_codecs(self):
        self._building = True
        try:
            self.combo_manual_audio_codec.clear()
            self.combo_manual_audio_codec.addItem(self.tr("Copiar (si es compatible)"), "copy")
            for codec in get_audio_codecs(only_verified=False):
                if codec["codec_id"] in _AUDIO_CODEC_IDS:
                    self.combo_manual_audio_codec.addItem(codec["display_name"], codec["codec_id"])
        finally:
            self._building = False

    def _current_manual_video_choice(self) -> str:
        return self.combo_manual_video_codec.currentData() or "copy"

    def _current_manual_audio_choice(self) -> str:
        return self.combo_manual_audio_codec.currentData() or "copy"

    def _current_manual_video_encoder(self, codec_id: str) -> str:
        if self._force_cpu_manual:
            return software_encoder(codec_id) or resolve_encoder(codec_id) or "libx264"
        return resolve_encoder(codec_id) or "libx264"

    def _on_manual_video_codec_changed(self, *_args):
        if self._building:
            return
        choice = self._current_manual_video_choice()
        is_copy = (choice == "copy")
        self.rb_quality_cq.setEnabled(not is_copy)
        self.rb_quality_bitrate.setEnabled(not is_copy)
        self.rb_quality_target.setEnabled(not is_copy)
        self.spin_manual_cq.setEnabled(not is_copy)
        self.spin_manual_bitrate.setEnabled(not is_copy)
        self.spin_manual_target_mb.setEnabled(not is_copy)
        if is_copy:
            self.badge_manual_video_engine.set_state(False, False)
            self.badge_manual_video_engine.setVisible(False)
        else:
            self.badge_manual_video_engine.setVisible(True)
            self.badge_manual_video_engine.set_state(has_hardware_encoder(choice), self._force_cpu_manual)
        self._on_manual_changed()

    def _on_manual_force_cpu_toggled(self, force_cpu: bool):
        self._force_cpu_manual = force_cpu
        choice = self._current_manual_video_choice()
        if choice != "copy":
            self.badge_manual_video_engine.set_state(has_hardware_encoder(choice), self._force_cpu_manual)
        self._on_manual_changed()

    def _on_quality_mode_toggled(self, *_args):
        is_cq = self.rb_quality_cq.isChecked()
        is_bitrate = self.rb_quality_bitrate.isChecked()
        is_target = self.rb_quality_target.isChecked()
        self.spin_manual_cq.setVisible(is_cq)
        self.spin_manual_bitrate.setVisible(is_bitrate)
        self.spin_manual_target_mb.setVisible(is_target)
        self._on_manual_changed()

    def _current_quality_mode(self) -> str:
        if self.rb_quality_bitrate.isChecked():
            return _QUALITY_MODE_BITRATE
        if self.rb_quality_target.isChecked():
            return _QUALITY_MODE_TARGET_SIZE
        return _QUALITY_MODE_CQ

    def _manual_video_kbps_for_duration(self, duration_sec: float | None) -> float | None:
        mode = self._current_quality_mode()
        if mode == _QUALITY_MODE_BITRATE:
            return float(self.spin_manual_bitrate.value())
        if mode == _QUALITY_MODE_TARGET_SIZE:
            if not duration_sec or duration_sec <= 0:
                return None
            target_mb = self.spin_manual_target_mb.value()
            audio_kbps = float(self.spin_manual_audio_bitrate.value())
            total_kbps = (target_mb * 8 * 1024) / duration_sec
            return max(100.0, total_kbps - audio_kbps)
        return None  # CRF: sin bitrate fijo.

    def _build_manual_video_args(self, codec_id: str, duration_sec: float | None) -> list[str]:
        encoder = self._current_manual_video_encoder(codec_id)
        mode = self._current_quality_mode()
        if mode == _QUALITY_MODE_CQ:
            return build_custom_quality_args(encoder, self.spin_manual_cq.value())
        kbps = self._manual_video_kbps_for_duration(duration_sec)
        if kbps is None:
            kbps = 8000.0
        return build_custom_bitrate_args(encoder, "vbr", round(kbps))

    def _on_manual_container_changed(self, *_args):
        if self._building:
            return
        # Si el matrix confirma que este contenedor no acepta NINGÚN códec de video
        # (recode_guard.container_supports_video), no tiene sentido mostrar la tarjeta de
        # Video ni dejar que el usuario elija un códec que va a fallar seguro al muxear.
        container_id = self.combo_manual_container.currentData() or "mp4"
        self.frame_video.setVisible(container_supports_video(container_id))
        self._on_manual_changed()

    def _on_manual_changed(self, *_args):
        if self._building:
            return
        self._revalidate_manual()

    def _revalidate_manual(self):
        if not hasattr(self, "lbl_manual_status"):
            return
        if not self._source_meta:
            self._set_valid(True, "")
            self.lbl_manual_status.setText(self.tr("Selecciona un archivo en la cola para validar la configuración."))
            return

        container_id = self.combo_manual_container.currentData() or "mp4"
        plan = advisor.plan_conversion(self._source_meta, container_id)
        container_label = CONTAINER_LABELS.get(container_id, container_id.upper())

        # plan["video"] es None cuando no hay pista de video en el origen O cuando el
        # contenedor es de audio puro (ver plan_conversion) - en ambos casos no hay nada
        # que validar del lado del video, la tarjeta ya está oculta para el segundo caso.
        if plan["video"] is not None:
            video_choice = self._current_manual_video_choice()
            if video_choice == "copy" and plan["video"] == "recode":
                reason = self.tr("El video de origen ({0}) no es compatible con {1} — elegí recodificar o cambiá el contenedor.").format(
                    (plan["video_codec_source"] or "?").upper(), container_label
                )
                self._set_valid(False, reason)
                self.lbl_manual_status.setText(reason)
                return
            if video_choice != "copy" and not is_stream_copy_compatible(video_choice, container_id):
                reason = self.tr("{0} no es un códec de video válido para {1} — elegí otro.").format(
                    video_choice.upper(), container_label
                )
                self._set_valid(False, reason)
                self.lbl_manual_status.setText(reason)
                return

        if plan["audio"] is not None:
            audio_choice = self._current_manual_audio_choice()
            if audio_choice == "copy" and plan["audio"] == "recode":
                reason = self.tr("El audio de origen ({0}) no es compatible con {1} — elegí recodificar o cambiá el contenedor.").format(
                    (plan["audio_codec_source"] or "?").upper(), container_label
                )
                self._set_valid(False, reason)
                self.lbl_manual_status.setText(reason)
                return
            if audio_choice != "copy" and not is_stream_copy_compatible(audio_choice, container_id):
                reason = self.tr("{0} no es un códec de audio válido para {1} — elegí otro.").format(
                    audio_choice.upper(), container_label
                )
                self._set_valid(False, reason)
                self.lbl_manual_status.setText(reason)
                return

        self._set_valid(True, "")
        self.lbl_manual_status.setText(self.tr("Configuración válida para este archivo."))

    def _set_valid(self, valid: bool, reason: str):
        self._invalid_reason = reason
        changed = valid != self._last_valid
        self._last_valid = valid
        if changed:
            self.validity_changed.emit(valid)

    # ─── Modo superior (Rápido/Manual) ──────────────────────────

    def _on_top_mode_changed(self, mode_text: str):
        self.stack.setCurrentIndex(0 if mode_text == self.tr("Rápido") else 1)
        self._revalidate_manual()
        self.validity_changed.emit(self.is_valid())

    # ─── API pública ─────────────────────────────────────────────

    def is_valid(self) -> bool:
        if self.mode_selector.current_mode() == self.tr("Rápido"):
            return True
        return self._last_valid

    def get_status(self) -> tuple[bool, str]:
        if self.is_valid():
            return True, self.tr("Iniciar Recodificación")
        return False, self._invalid_reason or self.tr("Configuración no válida")

    def set_source_media(self, meta: dict, filepath: str):
        self._source_meta = meta or None
        self._source_filepath = filepath
        self._refresh_quick_status()
        self._revalidate_manual()

    def set_queue_entries(self, entries: list[tuple[str, dict]]):
        self._queue_entries = entries or []
        self._refresh_queue_summary()

    def get_settings(self, meta_override: dict | None = None, filepath_override: str | None = None) -> dict:
        is_quick = self.mode_selector.current_mode() == self.tr("Rápido")
        meta = meta_override if meta_override is not None else (self._source_meta or {})

        if is_quick:
            container_id = self._current_quick_container()
            return advisor.build_settings(meta, container_id)

        container_id = self.combo_manual_container.currentData() or "mp4"
        plan = advisor.plan_conversion(meta, container_id)
        duration_sec = parse_duration_to_seconds(meta.get("duración", "0")) if meta else None

        stream_mode = "video+audio"
        if plan["video"] is None and plan["audio"] is not None:
            stream_mode = "audio_only"
        elif plan["audio"] is None and plan["video"] is not None:
            stream_mode = "video_only"

        settings = {"container": container_id, "stream_mode": stream_mode}

        if plan["video"] is not None:
            video_choice = self._current_manual_video_choice()
            if video_choice == "copy":
                settings["video_mode"] = "copy"
                settings["video_codec"] = plan["video_codec_source"]
                settings["video_args"] = []
            else:
                settings["video_mode"] = "recode"
                settings["video_codec"] = video_choice
                settings["video_args"] = self._build_manual_video_args(video_choice, duration_sec)

        if plan["audio"] is not None:
            audio_choice = self._current_manual_audio_choice()
            if audio_choice == "copy":
                settings["audio_mode"] = "copy"
                settings["audio_codec"] = plan["audio_codec_source"]
                settings["audio_args"] = []
            else:
                audio_encoder = resolve_encoder(audio_choice) or "aac"
                settings["audio_mode"] = "recode"
                settings["audio_codec"] = audio_choice
                settings["audio_args"] = build_custom_audio_bitrate_args(audio_encoder, self.spin_manual_audio_bitrate.value())

        return settings
