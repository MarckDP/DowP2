# src/gui/dialogs/subclip_dialog.py
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QWidget,
    QSizePolicy, QLineEdit, QFrame, QToolButton, QMenu
)
from PySide6.QtCore import Qt, QSize, QTimer, Signal, QPoint
from PySide6.QtGui import QIcon, QPainter, QColor

from gui.styles import get_theme_token
from gui.widgets.send_state_button import SendButtonState
from gui.widgets.media_trim_player_widget import MediaTrimPlayerWidget
from gui.tabs.editing_media.editing_media_icons import get_svg_icon
from core.services.editor_integration_manager import EditorIntegrationManager
from core.logger.logger_manager import logger


class SubclipItemWidget(QWidget):
    """Elemento individual de la lista de subclips creados."""
    def __init__(self, index: int, name: str, in_sec: float, out_sec: float, on_preview, on_delete, on_rename, parent=None):
        super().__init__(parent)
        self.setFixedHeight(58)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 4, 6, 4)
        layout.setSpacing(2)

        # Fila superior: play + nombre editable + botón eliminar
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(6)

        self.btn_play = QPushButton()
        self.btn_play.setFixedSize(22, 22)
        self.btn_play.setIcon(get_svg_icon("play_arrow.svg"))
        self.btn_play.setIconSize(QSize(14, 14))
        self.btn_play.setStyleSheet(f"""
            QPushButton {{
                background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                border: 1px solid {get_theme_token('borde_sutil', '#333333')};
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('acento_primario', '#B9E640')};
            }}
        """)
        self.btn_play.clicked.connect(lambda: on_preview(index))
        top_row.addWidget(self.btn_play)

        self.txt_name = QLineEdit(name)
        self.txt_name.setStyleSheet(f"""
            QLineEdit {{
                background: {get_theme_token('fondo_secundario', '#121212')};
                color: {get_theme_token('acento_primario', '#B9E640')};
                border: 1px solid {get_theme_token('borde_sutil', '#333')};
                border-radius: 6px;
                padding: 1px 4px;
                font-size: 11px;
                font-weight: bold;
            }}
            QLineEdit:focus {{
                border: 1px solid {get_theme_token('acento_primario', '#B9E640')};
            }}
        """)
        self.txt_name.setFixedHeight(20)
        self.txt_name.textChanged.connect(lambda t: on_rename(index, t))
        top_row.addWidget(self.txt_name, 1)

        btn_del = QPushButton()
        btn_del.setIcon(get_svg_icon("delete.svg"))
        btn_del.setIconSize(QSize(15, 15))
        btn_del.setFixedSize(22, 22)
        btn_del.setToolTip("Eliminar subclip")
        btn_del.setStyleSheet("""
            QPushButton { background: transparent; border: none; border-radius: 6px; }
            QPushButton:hover { background: rgba(229,57,53,160); }
        """)
        btn_del.clicked.connect(lambda: on_delete(index))
        top_row.addWidget(btn_del)
        layout.addLayout(top_row)

        # Fila inferior: tiempos
        dur = out_sec - in_sec
        in_fmt = self._format_time(in_sec)
        out_fmt = self._format_time(out_sec)
        lbl = QLabel(f"{in_fmt} ➔ {out_fmt} ({dur:.2f}s)")
        lbl.setStyleSheet("color: #999; font-size: 11px;")
        layout.addWidget(lbl)

    def _format_time(self, seconds: float) -> str:
        ms = int((seconds % 1) * 1000)
        total_sec = int(seconds)
        s = total_sec % 60
        m = (total_sec // 60) % 60
        h = total_sec // 3600
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


class SubclipEditorDialog(QDialog):
    """Diálogo Modal para recortar partes de un medio (In/Out points) y enviar subclips.

    El reproductor + waveform de alta resolución + controles de recorte viven en
    MediaTrimPlayerWidget (gui/widgets/media_trim_player_widget.py), compartido con otras
    partes de la app. Este diálogo solo aporta la columna derecha (lista de subclips
    guardados + envío a editor) y el botón "Añadir subclip".
    """

    def __init__(self, media_path: str, media_type: str = "video", duration_sec: float = 0.0, fps: float = 30.0, existing_subclips: list = None, initial_in_sec: float = None, initial_out_sec: float = None, pending_download: bool = False, display_name: str = None, parent=None):
        super().__init__(parent)
        self.media_path = media_path
        self.media_type = media_type.lower()
        self.duration_sec = duration_sec or 1.0
        self.fps = fps if fps > 0 else 30.0
        self.in_sec = initial_in_sec if initial_in_sec is not None else 0.0
        self.out_sec = initial_out_sec if initial_out_sec is not None else self.duration_sec
        self.subclips = list(existing_subclips) if existing_subclips else []
        # Modo "pendiente": el medio es remoto y aún se está descargando en alta calidad en segundo plano.
        self.pending_download = pending_download
        self._display_name = display_name or os.path.basename(media_path) or "Medio remoto"

    def __init__(self, media_path: str, media_type: str = "video", duration_sec: float = 0.0, fps: float = 30.0, existing_subclips: list = None, initial_in_sec: float = None, initial_out_sec: float = None, pending_download: bool = False, display_name: str = None, parent=None):
        super().__init__(parent)
        self.media_path = media_path
        self.media_type = media_type.lower()
        self.duration_sec = duration_sec or 1.0
        self.fps = fps if fps > 0 else 30.0
        self.in_sec = initial_in_sec if initial_in_sec is not None else 0.0
        self.out_sec = initial_out_sec if initial_out_sec is not None else self.duration_sec
        self.subclips = list(existing_subclips) if existing_subclips else []
        self.pending_download = pending_download
        self._display_name = display_name or os.path.basename(media_path) or "Medio remoto"

        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle(f"Edición de Subclips - {self._display_name}")
        self.setObjectName("subclipDialogOverlay")

        self.init_ui()

        self.trim_player.load_media(
            self.media_path, self.media_type, self.duration_sec, self.fps,
            initial_in_sec=self.in_sec, initial_out_sec=self.out_sec
        )

        if self.pending_download:
            logger.info(f"[SubclipDialog] Ventana abierta en modo pendiente de descarga para '{self._display_name}'.")
            self._set_pending_state(True)

    def showEvent(self, event):
        super().showEvent(event)
        win = self.parent().window() if self.parent() else None
        if win:
            pos = win.mapToGlobal(QPoint(0, 0))
            self.setGeometry(pos.x(), pos.y(), win.width(), win.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 185))
        painter.end()
        super().paintEvent(event)

    def mousePressEvent(self, event):
        if hasattr(self, 'card') and not self.card.geometry().contains(event.pos()):
            self.reject()
        else:
            super().mousePressEvent(event)

    def init_ui(self):
        overlay_layout = QVBoxLayout(self)
        overlay_layout.setContentsMargins(24, 16, 24, 16)
        overlay_layout.setAlignment(Qt.AlignCenter)

        # ── Tarjeta Central Inamovible ────────────────────────
        self.card = QFrame()
        self.card.setObjectName("subclipDialogCard")
        self.card.setMinimumSize(940, 580)
        self.card.setMaximumSize(1080, 680)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        # ── Barra de Título Customizada ───────────────────────
        title_bar = QWidget()
        title_bar.setObjectName("subclipTitleBar")
        title_bar.setFixedHeight(38)
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(16, 0, 10, 0)

        self.title_lbl = QLabel(f"Edición de Subclips (In/Out) — {self._display_name}")
        self.title_lbl.setObjectName("subclipTitleLabel")
        tb_layout.addWidget(self.title_lbl)
        tb_layout.addStretch()

        btn_close = QPushButton()
        btn_close.setObjectName("modalCloseBtn")
        btn_close.setIcon(get_svg_icon("close.svg"))
        btn_close.setIconSize(QSize(14, 14))
        btn_close.setFixedSize(26, 26)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setToolTip(self.tr("Cerrar (Esc)"))
        btn_close.clicked.connect(self.reject)
        tb_layout.addWidget(btn_close)

        card_layout.addWidget(title_bar)

        # ── Contenido Principal ───────────────────────────────
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(14, 12, 14, 14)
        content_layout.setSpacing(12)

        # ── Columna Izquierda: Reproductor + Waveform + Controles In/Out ──────
        self.trim_player = MediaTrimPlayerWidget()
        self.trim_player.range_changed.connect(self._on_trim_range_changed)
        self.trim_player.media_player.durationChanged.connect(self._on_duration_changed)
        content_layout.addWidget(self.trim_player, 70)

        # Botón para Añadir Subclip, insertado en la barra de controles del reproductor
        # justo después del botón "Out", igual que en el diseño original.
        self.btn_add_subclip = QPushButton()
        self.btn_add_subclip.setIcon(get_svg_icon("add.svg"))
        self.btn_add_subclip.setIconSize(QSize(18, 18))
        self.btn_add_subclip.setFixedSize(32, 32)
        self.btn_add_subclip.setToolTip(self.tr("Añadir subclip"))
        self.btn_add_subclip.setStyleSheet(f"""
            QPushButton {{
                background-color: {get_theme_token('acento_secundario', '#1DC038')};
                border: none;
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('acento_primario', '#B9E640')};
            }}
        """)
        self.btn_add_subclip.clicked.connect(self._add_current_subclip)
        self.trim_player.ctrl_bar.insertSpacing(9, 8)
        self.trim_player.ctrl_bar.insertWidget(10, self.btn_add_subclip)

        # ── Columna Derecha: Lista de Subclips Guardados + Enviar NLE ─────────
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        lbl_list_title = QLabel(self.tr("Subclips del Medio"))
        lbl_list_title.setStyleSheet("font-weight: bold; font-size: 13px; color: white;")
        right_layout.addWidget(lbl_list_title)

        borde_norm = get_theme_token('borde_normal', '#222222')
        bg_list = get_theme_token('fondo_secundario', '#121212')
        bg_elem = get_theme_token('fondo_elemento', '#1a1a1a')
        select_bg = get_theme_token('seleccion_fondo', '#222222')

        self.list_subclips = QListWidget()
        self.list_subclips.setStyleSheet("""
            QListWidget {
                background-color: %s;
                border: 1px solid %s;
                border-radius: 6px;
                outline: none;
            }
            QListWidget::item {
                background-color: %s;
                border-bottom: 1px solid %s;
                border-radius: 0px;
                padding: 0px;
                margin: 0px;
            }
            QListWidget::item:selected {
                background-color: #1b3b22;
                border-bottom: 1px solid #224;
            }
        """ % (bg_list, borde_norm, bg_elem, borde_norm))
        right_layout.addWidget(self.list_subclips, 1)

        # Botón Split de Envío a Editores
        self.btn_send = QToolButton()
        self.btn_send.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_send.setPopupMode(QToolButton.MenuButtonPopup)
        self.btn_send.setFixedHeight(32)
        self.btn_send.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.btn_send.setStyleSheet("""
            QToolButton {
                background-color: %s;
                border: 1px solid %s;
                border-radius: 6px;
                color: #ffffff;
                font-weight: bold;
                padding-left: 10px;
            }
            QToolButton::menu-button {
                border-left: 1px solid %s;
                width: 22px;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
            }
            QToolButton:hover {
                background-color: %s;
            }
        """ % (bg_elem, borde_norm, borde_norm, select_bg))

        self.send_menu = QMenu(self.btn_send)
        self.action_send_single = self.send_menu.addAction(self.tr("Enviar solo subclip actual"))
        self.btn_send.setMenu(self.send_menu)

        self.btn_send.clicked.connect(self._on_send_subclips_clicked)
        self.action_send_single.triggered.connect(self._on_send_single_subclip_clicked)
        self._send_state = SendButtonState(self.btn_send, restore_callback=self._update_send_button)

        right_layout.addWidget(self.btn_send)
        content_layout.addWidget(right_widget, 30)

        card_layout.addWidget(content_widget, 1)
        overlay_layout.addWidget(self.card)
        self._update_send_button()
        self._refresh_subclip_list()

    def keyPressEvent(self, event):
        """Maneja los atajos de teclado I (In), O (Out) y Espacio (Play/Pause) a nivel de
        diálogo, para que funcionen sin importar qué control tenga el foco (mientras ese
        control no consuma la tecla, p.ej. al escribir en un QLineEdit)."""
        key = event.key()
        if key == Qt.Key_I:
            self.trim_player.set_in_point()
        elif key == Qt.Key_O:
            self.trim_player.set_out_point()
        elif key == Qt.Key_Space:
            self.trim_player.toggle_play_pause()
        else:
            super().keyPressEvent(event)

    def _on_trim_range_changed(self, in_sec: float, out_sec: float):
        self.in_sec = in_sec
        self.out_sec = out_sec

    def _on_duration_changed(self, dur_ms: int):
        if dur_ms > 0:
            self.duration_sec = dur_ms / 1000.0
            self._update_saved_subclip_ratios()

    def _set_pending_state(self, pending: bool):
        """Activa/desactiva el modo 'pendiente de descarga': deshabilita controles de edición/envío
        y muestra el estado especial de descarga en la waveform (el botón de cerrar sigue disponible)."""
        self.pending_download = pending
        self.trim_player.set_pending(pending)
        self.btn_add_subclip.setEnabled(not pending)
        if pending:
            self.btn_send.setEnabled(False)
        else:
            self._update_send_button()

    def set_resolved_media_path(self, local_path: str):
        """
        Reemplaza el medio pendiente por el archivo real ya descargado en alta calidad:
        recarga el reproductor (lo que recalcula duración real vía durationChanged),
        refresca el FPS y vuelve a extraer la waveform de alta resolución del archivo correcto.
        """
        logger.info(f"[SubclipDialog] Medio resuelto en alta calidad: {local_path}")
        self.media_path = local_path
        self._display_name = os.path.basename(local_path) or self._display_name
        self.setWindowTitle(f"Edición de Subclips - {self._display_name}")
        if hasattr(self, "title_lbl"):
            self.title_lbl.setText(f"Edición de Subclips (In/Out) — {self._display_name}")

        try:
            from core.tabs.editing_media.ffprobe_metadata_manager import FFprobeMetadataManager
            meta = FFprobeMetadataManager.get_instance().get_metadata_instant(local_path, self.media_type)
            fps_str = str(meta.get("fps", "")).replace("fps", "").strip()
            if fps_str:
                self.fps = float(fps_str)
        except Exception as e:
            logger.error(f"[SubclipDialog] No se pudo refrescar el FPS tras la descarga: {e}")

        self.trim_player.set_resolved_media_path(local_path, fps=self.fps)
        self._set_pending_state(False)

    def set_resolve_error(self, message: str):
        """Muestra el error de descarga en la waveform; los controles quedan deshabilitados."""
        logger.error(f"[SubclipDialog] Error resolviendo el medio en alta calidad: {message}")
        self.trim_player.set_resolve_error(message)

    def _add_current_subclip(self):
        if self.out_sec <= self.in_sec:
            return

        count = len(self.subclips) + 1
        sub_name = f"{os.path.splitext(os.path.basename(self.media_path))[0]}_clip{count:02d}"

        clip_data = {
            "name": sub_name,
            "in": self.in_sec,
            "out": self.out_sec
        }
        self.subclips.append(clip_data)
        self._refresh_subclip_list()
        self._update_send_button()

    def _refresh_subclip_list(self):
        self.list_subclips.clear()
        for idx, sc in enumerate(self.subclips):
            item = QListWidgetItem(self.list_subclips)
            w = SubclipItemWidget(
                index=idx,
                name=sc["name"],
                in_sec=sc["in"],
                out_sec=sc["out"],
                on_preview=self._preview_subclip,
                on_delete=self._delete_subclip,
                on_rename=self._rename_subclip
            )
            item.setSizeHint(QSize(220, 66))
            self.list_subclips.setItemWidget(item, w)

        self._update_saved_subclip_ratios()

    def _update_saved_subclip_ratios(self):
        """Envía a la waveform los rangos de los subclips ya guardados para mostrarlos de
        fondo con baja opacidad."""
        if self.duration_sec <= 0:
            return
        ranges = [(sc["in"] / self.duration_sec, sc["out"] / self.duration_sec) for sc in self.subclips]
        self.trim_player.set_saved_ranges(ranges)

    def _preview_subclip(self, index: int):
        if 0 <= index < len(self.subclips):
            sc = self.subclips[index]
            self.trim_player.preview_range(sc["in"], sc["out"])

    def _delete_subclip(self, index: int):
        if 0 <= index < len(self.subclips):
            self.subclips.pop(index)
            self._refresh_subclip_list()
            self._update_send_button()

    def _rename_subclip(self, index: int, new_name: str):
        if 0 <= index < len(self.subclips):
            self.subclips[index]["name"] = new_name

    def get_subclips(self) -> list:
        """Devuelve la lista actual de subclips creados."""
        return list(self.subclips)

    def _update_send_button(self):
        editor_mgr = EditorIntegrationManager.get_instance()
        active = editor_mgr.active_editor if editor_mgr else None

        if not active:
            self.btn_send.setText(self.tr("Ningún editor conectado"))
            self.btn_send.setIcon(QIcon())
            self.btn_send.setEnabled(False)
            return

        if active == "premiere":
            icon_file = "premiere pro.svg"
        elif active == "aftereffects":
            icon_file = "after effects.svg"
        else:
            icon_file = "davinci resolve.svg"

        count = len(self.subclips)
        if count > 0:
            self.btn_send.setText(f"Enviar ({count}) subclips")
        else:
            self.btn_send.setText(f"Enviar rango actual")

        icon = get_svg_icon(icon_file)
        if not icon.isNull():
            self.btn_send.setIcon(icon)
            self.btn_send.setIconSize(QSize(20, 20))

        self.btn_send.setEnabled(True)

    def _send_subclip_payload(self, payload: dict, log_desc: str):
        """Envía el payload de subclips mostrando el estado animado en btn_send y cerrando el diálogo en éxito."""
        editor_mgr = EditorIntegrationManager.get_instance()
        if not editor_mgr or not editor_mgr.active_editor:
            return
        if self.pending_download:
            logger.warning("[SubclipDialog] Envío bloqueado: el medio aún se está descargando en alta calidad.")
            return

        logger.info(f"[SubclipDialog] {log_desc} a {editor_mgr.active_editor}")
        self._send_state.start("Enviando")

        ok = False
        try:
            ok = editor_mgr.send_subclips(payload)
        except Exception as e:
            logger.error(f"[SubclipDialog] Excepción enviando subclips: {e}")
            ok = False

        if ok:
            logger.info("[SubclipDialog] Subclips enviados correctamente.")
        else:
            logger.error("[SubclipDialog] Error al enviar los subclips al editor.")

        self._send_state.finish(ok, "Éxito" if ok else "Error")
        if ok:
            QTimer.singleShot(1200, self.accept)

    def _on_send_subclips_clicked(self):
        items_to_send = self.subclips if self.subclips else [{
            "name": f"{os.path.splitext(os.path.basename(self.media_path))[0]}_range",
            "in": self.in_sec,
            "out": self.out_sec
        }]
        payload = {
            "filePath": self.media_path.replace('\\', '/'),
            "subclips": items_to_send
        }
        self._send_subclip_payload(payload, f"Enviando {len(items_to_send)} subclips")

    def _on_send_single_subclip_clicked(self):
        payload = {
            "filePath": self.media_path.replace('\\', '/'),
            "subclips": [{
                "name": f"{os.path.splitext(os.path.basename(self.media_path))[0]}_range",
                "in": self.in_sec,
                "out": self.out_sec
            }]
        }
        self._send_subclip_payload(payload, "Enviando rango actual como subclip")

    def closeEvent(self, event):
        self.trim_player.cleanup()
        super().closeEvent(event)

    def accept(self):
        self.trim_player.cleanup()
        super().accept()

    def reject(self):
        self.trim_player.cleanup()
        super().reject()
