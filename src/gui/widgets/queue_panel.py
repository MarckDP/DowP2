# src/gui/widgets/queue_panel.py
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QProgressBar, QFrame, QPushButton
)
from PySide6.QtCore import Qt, QVariantAnimation, QEasingCurve, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap, QPainter
from gui.styles import get_theme_token
from core.logger.logger_manager import logger

def get_colored_icon(path, color_hex, size=16):
    pixmap = QPixmap(path)
    if pixmap.isNull():
        return QIcon()
    pixmap = pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    painter = QPainter(pixmap)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor(color_hex))
    painter.end()
    return QIcon(pixmap)

class QueueItemCard(QFrame):
    """
    Tarjeta individual que representa una descarga en la cola.
    Muestra título, progreso, porcentaje y estado actual.
    """
    card_clicked = Signal(str)
    delete_requested = Signal(str)
    move_up_requested = Signal(str)
    move_down_requested = Signal(str)
    reset_requested = Signal(str)
    configure_requested = Signal(str)
    open_folder_requested = Signal(str)

    def __init__(self, title, job_id, parent=None, is_playlist=False):
        super().__init__(parent)
        self.job_id = job_id
        self.is_playlist = is_playlist
        self._is_selected = False
        self._current_border = get_theme_token('borde', '#2d2d2d')
        self.setObjectName("queueItemCard")
        self.init_ui(title)

    def set_selected(self, selected: bool):
        self._is_selected = selected
        self._apply_style()

    def _apply_style(self):
        bg_color = get_theme_token('fondo_principal', '#121212')
        if self._is_selected:
            new_style = f"""
                QFrame#queueItemCard {{
                    background-color: {get_theme_token('fondo_hover', '#1a1a1a')};
                    border: 1px solid {self._current_border};
                    border-left: 4px solid {get_theme_token('acento_primario', '#B9E640')};
                    border-radius: 6px;
                }}
            """
        else:
            new_style = f"""
                QFrame#queueItemCard {{
                    background-color: {bg_color};
                    border: 1px solid {self._current_border};
                    border-radius: 6px;
                }}
                QFrame#queueItemCard:hover {{
                    background-color: {get_theme_token('fondo_hover', '#1a1a1a')};
                }}
            """
        
        # Solo re-estilizar si el CSS realmente cambió
        if self.styleSheet() == new_style:
            return
        
        self.setStyleSheet(new_style)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
        
    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.card_clicked.emit(self.job_id)
        
    def init_ui(self, title):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        
        # Fila superior: Título e Indicador de Estado
        top_layout = QHBoxLayout()
        
        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet(f"color: {get_theme_token('texto_principal', '#ffffff')}; font-weight: bold;")
        self.title_lbl.setWordWrap(False)
        self.title_lbl.setMinimumWidth(50)
        self.update_title(title)
        
        self.status_lbl = QLabel(self.tr("En espera"))
        self.status_lbl.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#aaaaaa')}; font-size: 10px;")
        self.status_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        # Botones de control
        self.btn_up = QPushButton("▲")
        self.btn_up.setFixedSize(16, 16)
        self.btn_up.setStyleSheet("border: none; color: #888; font-size: 8px;")
        self.btn_up.clicked.connect(lambda: self.move_up_requested.emit(self.job_id))
        
        self.btn_down = QPushButton("▼")
        self.btn_down.setFixedSize(16, 16)
        self.btn_down.setStyleSheet("border: none; color: #888; font-size: 8px;")
        self.btn_down.clicked.connect(lambda: self.move_down_requested.emit(self.job_id))

        self.btn_close = QPushButton()
        self.btn_close.setIcon(get_colored_icon('src/assets/icons/svg/close.svg', '#e74c3c'))
        self.btn_close.setToolTip(self.tr("Eliminar de la cola"))
        self.btn_close.setFixedSize(16, 16)
        self.btn_close.setStyleSheet("border: none; background: transparent;")
        self.btn_close.clicked.connect(lambda: self.delete_requested.emit(self.job_id))
        
        self.btn_reset = QPushButton()
        acento_color = get_theme_token('acento_primario', '#B9E640')
        self.btn_reset.setIcon(get_colored_icon('src/assets/icons/svg/arrow_back.svg', acento_color))
        self.btn_reset.setToolTip(self.tr("Restaurar descarga"))
        self.btn_reset.setFixedSize(16, 16)
        self.btn_reset.setStyleSheet("border: none; background: transparent;")
        self.btn_reset.clicked.connect(lambda: self.reset_requested.emit(self.job_id))
        self.btn_reset.hide()

        self.btn_folder = QPushButton()
        self.btn_folder.setIcon(get_colored_icon('src/assets/icons/svg/folder_open.svg', acento_color))
        self.btn_folder.setToolTip(self.tr("Abrir carpeta contenedora"))
        self.btn_folder.setFixedSize(16, 16)
        self.btn_folder.setStyleSheet("border: none; background: transparent;")
        self.btn_folder.clicked.connect(lambda: self.open_folder_requested.emit(self.job_id))
        self.btn_folder.hide()

        self.btn_configure = QPushButton()
        self.btn_configure.setIcon(get_colored_icon('src/assets/icons/svg/settings.svg', '#888888'))
        self.btn_configure.setToolTip(self.tr("Configurar Playlist"))
        self.btn_configure.setFixedSize(16, 16)
        self.btn_configure.setStyleSheet("border: none; background: transparent;")
        self.btn_configure.clicked.connect(lambda: self.configure_requested.emit(self.job_id))
        if not self.is_playlist:
            self.btn_configure.hide()
        
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(2)
        controls_layout.addWidget(self.btn_configure)
        controls_layout.addWidget(self.btn_reset)
        controls_layout.addWidget(self.btn_folder)
        controls_layout.addWidget(self.btn_up)
        controls_layout.addWidget(self.btn_down)
        controls_layout.addWidget(self.btn_close)

        top_layout.addWidget(self.title_lbl, 3)
        top_layout.addWidget(self.status_lbl, 1)
        top_layout.addLayout(controls_layout)
        layout.addLayout(top_layout)
        
        # Barra de progreso compacta
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {get_theme_token('progreso_fondo', '#0f0f0f')};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {get_theme_token('progreso_inicio', '#35d6b8')}, 
                    stop:1 {get_theme_token('progreso_fin', '#138f7d')});
                border-radius: 3px;
            }}
        """)
        layout.addWidget(self.progress_bar)
        
        # Fila inferior: Info adicional (velocidad / tamaño / porcentaje)
        info_layout = QHBoxLayout()
        
        self.info_lbl = QLabel("")
        self.info_lbl.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#888888')}; font-size: 10px;")
        
        self.percent_lbl = QLabel("0%")
        self.percent_lbl.setStyleSheet(f"color: {get_theme_token('acento_primario', '#B9E640')}; font-size: 10px; font-weight: bold;")
        self.percent_lbl.setAlignment(Qt.AlignRight)
        
        info_layout.addWidget(self.info_lbl)
        info_layout.addWidget(self.percent_lbl)
        layout.addLayout(info_layout)
        
        # Aplicar borde y fondo usando tokens de color del tema
        self.setStyleSheet(f"""
            QFrame#queueItemCard {{
                background-color: {get_theme_token('fondo_principal', '#121212')};
                border: 1px solid {get_theme_token('borde', '#2d2d2d')};
                border-radius: 6px;
            }}
        """)

    def update_progress(self, percent, speed_text=None, status_text=None):
        """Actualiza el progreso y la información de la descarga."""
        self.progress_bar.setValue(int(percent))
        self.percent_lbl.setText(f"{int(percent)}%")
        if speed_text is not None:
            metrics = self.info_lbl.fontMetrics()
            elided = metrics.elidedText(speed_text, Qt.ElideRight, 160)
            self.info_lbl.setText(elided)
            self.info_lbl.setToolTip(speed_text if elided != speed_text else "")
        if status_text:
            self.status_lbl.setText(status_text)
            
            # Cambiar colores según estado
            border_color = get_theme_token('borde', '#2d2d2d')
            if status_text == self.tr("Completado"):
                self.status_lbl.setStyleSheet(f"color: #2ecc71; font-size: 10px; font-weight: bold;")
                self.percent_lbl.setStyleSheet(f"color: #2ecc71; font-size: 10px; font-weight: bold;")
                border_color = "#2ecc71"
            elif status_text == self.tr("Error"):
                self.status_lbl.setStyleSheet(f"color: #e74c3c; font-size: 10px; font-weight: bold;")
                self.percent_lbl.setStyleSheet(f"color: #e74c3c; font-size: 10px; font-weight: bold;")
                border_color = "#e74c3c"
            elif status_text == self.tr("Cancelado"):
                self.status_lbl.setStyleSheet(f"color: #e74c3c; font-size: 10px; font-weight: bold;")
                self.percent_lbl.setStyleSheet(f"color: #e74c3c; font-size: 10px; font-weight: bold;")
                border_color = "#e74c3c"
            elif status_text == self.tr("Descargando"):
                self.status_lbl.setStyleSheet(f"color: {get_theme_token('acento_primario', '#B9E640')}; font-size: 10px;")
                border_color = get_theme_token('acento_primario', '#B9E640')
            elif status_text.startswith(self.tr("Analizando")) or "Analizando" in status_text:
                self.status_lbl.setStyleSheet(f"color: #f39c12; font-size: 10px; font-weight: bold;")
                border_color = "#f39c12"
            elif status_text == self.tr("En espera"):
                # Reseteo completo: restaurar colores neutros, barra a 0, ocultar reset
                self.status_lbl.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#aaaaaa')}; font-size: 10px;")
                self.percent_lbl.setStyleSheet(f"color: {get_theme_token('acento_primario', '#B9E640')}; font-size: 10px; font-weight: bold;")
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(0)
                self.percent_lbl.setText("0%")
                self.info_lbl.setText("")
                self.info_lbl.setToolTip("")
                self.status_lbl.setToolTip("")
                border_color = get_theme_token('borde', '#2d2d2d')

            if status_text in (self.tr("Completado"), self.tr("Error"), self.tr("Cancelado")):
                self.btn_reset.show()
                self.btn_up.hide()
                self.btn_down.hide()
            else:
                self.btn_reset.hide()
                self.btn_up.show()
                self.btn_down.show()

            if status_text == self.tr("Completado"):
                self.btn_folder.show()
            else:
                self.btn_folder.hide()

            self._current_border = border_color
            self._apply_style()

    def update_title(self, title):
        """Actualiza el título con elipsis si es muy largo."""
        metrics = self.title_lbl.fontMetrics()
        elided = metrics.elidedText(title, Qt.ElideRight, 180)
        self.title_lbl.setText(elided)
        self.title_lbl.setToolTip(title)


class QueuePanel(QWidget):
    """
    Panel colapsable que contiene la lista de descargas activas y completadas.
    Soporta animaciones de deslizamiento horizontal a 30% del ancho del padre.
    """
    card_clicked_signal = Signal(str)
    queue_action_signal = Signal(str)  # "cleared" o "reset"
    configure_playlist_signal = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_expanded = False
        self.setFixedWidth(0)
        self.setObjectName("QueuePanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        
        # Mapeo de job_id -> QueueItemCard
        self.cards = {}
        self._selected_card_id = None
        
        # Configurar animación
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.OutQuad)
        self._anim.valueChanged.connect(self._on_width_changed)
        self._anim.finished.connect(self._on_animation_finished)
        # Conectar al gestor de colas global (antes de init_ui para evitar AttributeError)
        from core.utils.queue_manager import get_queue_manager
        self.queue_mgr = get_queue_manager()
        self.queue_mgr.job_added.connect(self._on_job_added)
        self.queue_mgr.job_removed.connect(self._on_job_removed)
        self.queue_mgr.job_status_changed.connect(self._on_job_status_changed)
        self.queue_mgr.job_progress_changed.connect(self._on_job_progress_changed)
        self.queue_mgr.queue_reordered.connect(self._on_queue_reordered)
        
        self.init_ui()
        self.content_widget.hide()

    def init_ui(self):
        # Layout principal de este widget (el cual se encoge/estira)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # Contenedor real para recortar adecuadamente el layout al colapsar
        self.content_widget = QWidget(self)
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(10, 10, 10, 10)
        self.content_layout.setSpacing(12)
        
        # Título del panel
        self.header_lbl = QLabel(self.tr("Cola de Descargas"))
        self.header_lbl.setStyleSheet(f"""
            color: {get_theme_token('acento_primario', '#B9E640')};
            font-size: 12px;
            font-weight: bold;
        """)
        self.header_lbl.setAlignment(Qt.AlignCenter)
        self.content_layout.addWidget(self.header_lbl)
        
        # Scroll Area para el listado de tarjetas
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("background: transparent; border: none;")
        
        # Contenedor interno del Scroll
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(8)
        self.scroll_layout.setAlignment(Qt.AlignTop)
        
        # Mensaje de lista vacía
        self.empty_lbl = QLabel(self.tr("No hay descargas en cola"))
        self.empty_lbl.setStyleSheet(f"color: {get_theme_token('texto_secundario', '#888888')}; font-size: 11px;")
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        self.scroll_layout.addWidget(self.empty_lbl)
        
        self.scroll.setWidget(self.scroll_content)
        self.content_layout.addWidget(self.scroll)
        
        # Botón limpiar lista
        self.btn_clear_list = QPushButton(self.tr("Limpiar Lista"))
        self.btn_clear_list.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {get_theme_token('borde', '#333')};
                border-radius: 6px;
                color: {get_theme_token('texto_secundario', '#aaa')};
                padding: 6px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: rgba(231, 76, 60, 0.15);
                border-color: #e74c3c;
                color: #ff6b6b;
            }}
            QPushButton:pressed {{
                background-color: rgba(231, 76, 60, 0.3);
                color: #ff8b8b;
            }}
        """)
        self.btn_clear_list.clicked.connect(self._on_clear_list_click)

        # Botón resetear estado
        self.btn_reset_all = QPushButton(self.tr("Resetear Estado"))
        self.btn_reset_all.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {get_theme_token('borde', '#333')};
                border-radius: 6px;
                color: {get_theme_token('texto_secundario', '#aaa')};
                padding: 6px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #2a2a2a;
                color: #fff;
            }}
        """)
        self.btn_reset_all.clicked.connect(self._on_reset_all_click)

        # Layout horizontal para los botones de acción global
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(4)
        actions_layout.addWidget(self.btn_clear_list)
        actions_layout.addWidget(self.btn_reset_all)

        self.content_layout.addLayout(actions_layout)

        self.main_layout.addWidget(self.content_widget)
        
        # Estilo de fondo a juego con fondo_secundario del tema con bordes redondeados solo a la izquierda
        self.setStyleSheet(f"""
            QWidget#QueuePanel {{
                background-color: {get_theme_token('fondo_secundario', '#1e1e1e')};
                border-top-left-radius: 12px;
                border-bottom-left-radius: 12px;
                border-left: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-top: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-bottom: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-right: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
            }}
        """)

    def toggle_expanded(self, parent_width):
        """Alterna el estado de expansión usando animaciones."""
        target_width = int(parent_width * 0.3)
        self._anim.stop()
        
        if self.is_expanded:
            # Colapsar
            self._anim.setStartValue(self.width())
            self._anim.setEndValue(0)
            self._anim.start()
            self.is_expanded = False
        else:
            # Expandir
            self.content_widget.show()
            self._anim.setStartValue(self.width())
            self._anim.setEndValue(target_width)
            self._anim.start()
            self.is_expanded = True

    def adjust_width(self, parent_width):
        """Ajusta instantáneamente el tamaño al redimensionar la ventana."""
        if self.is_expanded and self._anim.state() != QVariantAnimation.Running:
            target_width = int(parent_width * 0.3)
            self.setFixedWidth(target_width)

    def add_download(self, title) -> QueueItemCard:
        """Añade una nueva descarga a la cola (obsoleto, usar QueueManager)."""
        self.empty_lbl.hide()
        card = QueueItemCard(title, self)
        self.scroll_layout.addWidget(card)
        return card

    def _on_job_added(self, job_id):
        job = self.queue_mgr.get_job(job_id)
        if not job:
            return
            
        self.empty_lbl.hide()
            
        card = QueueItemCard(job.title, job.job_id, self, is_playlist=(job.job_type == "PLAYLIST"))
        
        # Conectar señales de la tarjeta
        card.card_clicked.connect(self._emit_card_clicked)
        card.delete_requested.connect(self.queue_mgr.remove_job)
        card.move_up_requested.connect(self.queue_mgr.move_job_up)
        card.move_down_requested.connect(self.queue_mgr.move_job_down)
        card.reset_requested.connect(self.queue_mgr.reset_job)
        card.configure_requested.connect(self.configure_playlist_signal.emit)
        card.open_folder_requested.connect(self._on_open_folder_requested)
        
        self.scroll_layout.addWidget(card)
        self.cards[job_id] = card
        
        # Sincronizar estado inicial
        status_text = self.tr("En espera") if job.status == "PENDING" else self.tr("Analizando...")
        card.update_progress(0, status_text=status_text)

    def select_card(self, job_id):
        if self._selected_card_id and self._selected_card_id in self.cards:
            self.cards[self._selected_card_id].set_selected(False)
        self._selected_card_id = job_id
        if job_id in self.cards:
            self.cards[job_id].set_selected(True)

    def _emit_card_clicked(self, job_id):
        self.select_card(job_id)
        if hasattr(self, 'card_clicked_signal'):
            self.card_clicked_signal.emit(job_id)

    def _on_job_removed(self, job_id):
        logger.info(f"QueuePanel: _on_job_removed llamada para {job_id}. Tarjetas actuales: {list(self.cards.keys())}")
        card = self.cards.pop(job_id, None)
        if card:
            logger.info(f"QueuePanel: Tarjeta para {job_id} encontrada. Removiendo...")
            card.hide()
            self.scroll_layout.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        else:
            logger.warning(f"QueuePanel: Tarjeta para {job_id} NO encontrada en self.cards!")
            
        if not self.cards:
            self.empty_lbl.show()

    def _on_job_status_changed(self, job_id, status):
        card = self.cards.get(job_id)
        if not card:
            return
            
        status_translations = {
            "PENDING": self.tr("En espera"),
            "ANALYZING": self.tr("Analizando..."),
            "RUNNING": self.tr("Descargando"),
            "COMPLETED": self.tr("Completado"),
            "FAILED": self.tr("Error"),
            "CANCELLED": self.tr("Cancelado"),
            "SKIPPED": self.tr("Omitido")
        }
        status_text = status_translations.get(status, status)
        
        job = self.queue_mgr.get_job(job_id)
        
        speed_text = ""
        percent = 0.0
        if job:
            card.update_title(job.title)
            percent = job.progress
            if status == "RUNNING":
                speed_text = f"{job.speed} | ETA {job.eta}" if job.speed and job.eta else job.speed
            elif status == "FAILED":
                from core.ytdlp_logic.analyzer import strip_ansi_codes
                clean_err = strip_ansi_codes(job.error_message) if job.error_message else ""
                speed_text = clean_err
                card.status_lbl.setToolTip(clean_err)
            elif status == "COMPLETED":
                speed_text = self.tr("Descargado")
        
        if status in ("COMPLETED", "FAILED", "CANCELLED", "SKIPPED"):
            card.progress_bar.setRange(0, 100)
            
        if job and job.job_type == "PLAYLIST":
            card.btn_configure.show()
            
        has_fragments = bool(job and job.request_data and job.request_data.get("selected_fragments"))
        if status == "RUNNING" and has_fragments:
            card.progress_bar.setRange(0, 0)
            percent = 0
            speed_text = self.tr("Por favor espere...")
            status_text = self.tr("Cortando fragmentos...")
            
        card.update_progress(
            percent=percent,
            speed_text=speed_text,
            status_text=status_text
        )

    def _on_job_progress_changed(self, job_id, percent, speed, eta):
        card = self.cards.get(job_id)
        if not card:
            return
            
        job = self.queue_mgr.get_job(job_id)
        if job and job.status == "ANALYZING":
            card.progress_bar.setRange(0, 100)
            card.update_progress(
                percent=percent,
                speed_text="",
                status_text=speed
            )
            return

        has_fragments = bool(job and job.request_data and job.request_data.get("selected_fragments"))
        
        if has_fragments:
            card.progress_bar.setRange(0, 0)
            card.update_progress(
                percent=0,
                speed_text=self.tr("Por favor espere..."),
                status_text=self.tr("Cortando fragmentos...")
            )
        else:
            card.progress_bar.setRange(0, 100)
            speed_text = f"{speed} | ETA {eta}" if speed and eta else speed
            card.update_progress(
                percent=percent,
                speed_text=speed_text,
                status_text=self.tr("Descargando")
            )

    def _on_width_changed(self, width):
        self.setFixedWidth(width)

    def _on_animation_finished(self):
        if not self.is_expanded:
            self.content_widget.hide()

    def _on_clear_list_click(self):
        """Limpia trabajos inactivos y notifica al padre."""
        self.queue_mgr.clear_inactive_jobs()
        self.queue_action_signal.emit("cleared")

    def _on_reset_all_click(self):
        """Resetea todos los trabajos terminados y notifica al padre."""
        self.queue_mgr.reset_all_terminal_jobs()
        self.queue_action_signal.emit("reset")

    def _on_queue_reordered(self):
        """Reconstruye el orden visual de las tarjetas basado en el QueueManager."""
        self.scroll_content.setUpdatesEnabled(False)
        jobs = self.queue_mgr.get_all_jobs()
        # Eliminar las tarjetas del layout actual sin destruirlas
        for job in jobs:
            card = self.cards.get(job.job_id)
            if card:
                self.scroll_layout.removeWidget(card)
        # Volver a añadirlas en el nuevo orden
        for job in jobs:
            card = self.cards.get(job.job_id)
            if card:
                self.scroll_layout.addWidget(card)
        self.scroll_content.setUpdatesEnabled(True)

    def _on_open_folder_requested(self, job_id):
        job = self.queue_mgr.get_job(job_id)
        if not job:
            return
            
        output_path = None
        # Si no hay final_filepath en el job, intentar usar la ruta del config
        if not job.final_filepath:
            config_to_use = job.request_data if job.request_data else job.config
            output_path = config_to_use.get("output_path")
        else:
            output_path = job.final_filepath
            
        if not output_path:
            return
            
        actual_path = self._find_actual_downloaded_file(output_path)
        if actual_path:
            self._open_and_select(actual_path)

    def _find_actual_downloaded_file(self, filepath):
        if not filepath:
            return None
        if os.path.exists(filepath):
            return filepath
            
        if os.path.isdir(filepath):
            return filepath
            
        parent_dir = os.path.dirname(filepath)
        if not os.path.exists(parent_dir):
            return None
            
        base_name = os.path.splitext(os.path.basename(filepath))[0]
        
        # Eliminar extensiones temporales si las hay
        for temp_ext in ['.temp', '.ytdl', '.part']:
            if base_name.endswith(temp_ext):
                base_name = base_name[:-len(temp_ext)]
                
        best_match = None
        try:
            for entry in os.scandir(parent_dir):
                if entry.is_file():
                    entry_base = os.path.splitext(entry.name)[0]
                    if entry_base == base_name:
                        return entry.path
                    if entry_base.startswith(base_name):
                        best_match = entry.path
        except Exception as e:
            logger.error(f"Error escaneando directorio para encontrar archivo: {e}")
            
        if best_match:
            return best_match
            
        return parent_dir

    def _open_and_select(self, path):
        import subprocess
        import platform
        
        path = os.path.abspath(path)
        if not os.path.exists(path):
            return
            
        try:
            if os.name == 'nt':
                # Windows
                if os.path.isdir(path):
                    os.startfile(path)
                else:
                    # En Windows, para señalar el archivo en Explorer:
                    subprocess.run(['explorer', '/select,', path])
            elif platform.system() == 'Darwin':
                # macOS
                if os.path.isdir(path):
                    subprocess.run(['open', path])
                else:
                    subprocess.run(['open', '-R', path])
            else:
                # Linux (fallback)
                if os.path.isdir(path):
                    subprocess.run(['xdg-open', path])
                else:
                    subprocess.run(['xdg-open', os.path.dirname(path)])
        except Exception as e:
            logger.error(f"Error abriendo explorador en la ruta {path}: {e}")
