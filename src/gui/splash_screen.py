# src/gui/splash_screen.py
"""
Pantalla de inicio (Splash Screen) de DowP 2.0
===============================================
Aparece instantáneamente al iniciar la aplicación. Muestra el logo a la
izquierda centrado y "DowP 2.0.0" + estado de carga a la derecha.

Si las dependencias no están instaladas, muestra el progreso de descarga
e instalación de cada una hasta que todo esté listo.
"""
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QFrame, QGraphicsOpacityEffect, QApplication,
    QSizePolicy, QSpacerItem
)
from PySide6.QtCore import (
    Qt, Signal, Slot, QThread, QTimer, QPropertyAnimation,
    QEasingCurve, QSize
)
from PySide6.QtGui import QFont, QPixmap, QIcon
from PySide6.QtSvgWidgets import QSvgWidget

from gui.styles import get_theme_token
from core.logger.logger_manager import logger
from core.utils.paths import get_src_dir


class DependencyCheckWorker(QThread):
    """
    Hilo que verifica y descarga dependencias faltantes,
    emitiendo progreso para actualizar la splash screen.
    """
    # Señales
    status_update = Signal(str)                  # Mensaje de estado general
    dependency_started = Signal(str, str)         # dep_id, nombre legible
    dependency_progress = Signal(str, int)        # dep_id, porcentaje
    dependency_finished = Signal(str, bool, str)  # dep_id, éxito, versión/msg
    all_ready = Signal()                          # Todo listo
    failed = Signal(str)                          # Mensaje de error

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        try:
            from core.setup.setup_manager import verify_all_dependencies
            from core.setup.ytdlp_setup import (
                check_ytdlp, download_ytdlp,
                get_local_version as get_ytdlp_version,
                get_latest_remote_version as get_ytdlp_remote_version
            )
            from core.setup.ffmpeg_setup import (
                check_ffmpeg, download_ffmpeg,
                get_local_version as get_ffmpeg_version
            )
            from core.setup.deno_setup import (
                check_deno, download_deno,
                get_local_version as get_deno_version
            )
            from core.setup.potprovider_setup import (
                check_all as check_potprovider,
                download_potprovider,
                get_local_version as get_potprovider_version,
            )
            from core.utils.config_manager import get_config

            self.status_update.emit("Verificando dependencias...")

            status = verify_all_dependencies()

            # 1. Si faltan dependencias, descargarlas
            if not all(status.values()):
                deps = [
                    ("ytdlp",        "yt-dlp",      check_ytdlp,       download_ytdlp,       get_ytdlp_version),
                    ("ffmpeg",       "FFmpeg",       check_ffmpeg,      download_ffmpeg,      get_ffmpeg_version),
                    ("deno",         "Deno",         check_deno,        download_deno,        get_deno_version),
                    ("potprovider",  "PO Provider",  check_potprovider, download_potprovider, get_potprovider_version),
                ]

                for dep_id, name, check_fn, download_fn, version_fn in deps:
                    if check_fn():
                        version = version_fn() or "OK"
                        self.dependency_finished.emit(dep_id, True, version)
                        continue

                    self.dependency_started.emit(dep_id, name)
                    self.status_update.emit(f"Descargando {name}...")

                    def make_callback(did):
                        def cb(pct):
                            self.dependency_progress.emit(did, pct)
                        return cb

                    success, msg = download_fn(progress_callback=make_callback(dep_id))

                    if not success:
                        self.dependency_finished.emit(dep_id, False, msg)
                        self.failed.emit(f"Error al instalar {name}: {msg}")
                        return

                    version = version_fn(force_check=True) or "OK"
                    self.dependency_finished.emit(dep_id, True, version)

            # 2. Auto-actualización transparente de yt-dlp si hay nueva versión en el canal activo
            try:
                cfg = get_config()
                channel = cfg.get("ytdlp_channel", "stable")
                self.status_update.emit(f"Verificando actualización de yt-dlp ({channel})...")
                
                remote_ver = get_ytdlp_remote_version(channel=channel)
                local_ver = get_ytdlp_version()
                
                if remote_ver and local_ver:
                    r_clean = str(remote_ver).strip().lstrip('v')
                    l_clean = str(local_ver).strip().lstrip('v')
                    
                    if r_clean != l_clean and r_clean not in l_clean:
                        logger.info(f"SplashScreen: Auto-actualizando yt-dlp ({channel}): {local_ver} -> {remote_ver}")
                        self.status_update.emit(f"Actualizando yt-dlp ({channel}) a {remote_ver}...")
                        self.dependency_started.emit("ytdlp", "yt-dlp")
                        
                        def ytdlp_cb(pct):
                            self.dependency_progress.emit("ytdlp", pct)
                        
                        success, msg = download_ytdlp(channel=channel, progress_callback=ytdlp_cb)
                        if success:
                            self.dependency_finished.emit("ytdlp", True, remote_ver)
                            logger.info(f"SplashScreen: yt-dlp auto-actualizado a {remote_ver}")
                        else:
                            logger.warning(f"SplashScreen: No se pudo auto-actualizar yt-dlp: {msg}")
            except Exception as update_err:
                logger.debug(f"SplashScreen: Verificación de actualización de yt-dlp omitida ({update_err})")

            self.status_update.emit("Todo listo")
            self.all_ready.emit()

        except Exception as e:
            logger.error(f"SplashScreen worker error: {e}", exc_info=True)
            self.failed.emit(str(e))


class SplashScreen(QWidget):
    """
    Pantalla de inicio con logo + nombre de la app.
    Muestra estado de carga y progreso de dependencias.
    
    Emite `ready` con la MainWindow ya construida para eliminar
    cualquier lapso visible entre splash y ventana principal.
    """
    ready = Signal(object)  # Emitida con MainWindow ya construida
    failed = Signal()       # Emitida si las dependencias fallaron

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Window
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(420, 150)

        self.worker = None
        self.dep_rows = {}
        self._main_window = None  # Pre-construida durante el splash

        self._init_ui()
        self._center_on_screen()

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = (geo.width() - self.width()) // 2
            y = (geo.height() - self.height()) // 2
            self.move(x, y)

    def _init_ui(self):
        # ── Colores del tema ──
        bg = get_theme_token("fondo_secundario", "#121212")
        bg_dark = get_theme_token("fondo_principal", "#0a0a0a")
        border = get_theme_token("borde_normal", "#222222")
        text_main = get_theme_token("texto_principal", "#e0e0e0")
        text_sec = get_theme_token("texto_secundario", "#666666")
        accent = get_theme_token("acento_primario", "#B9E640")
        accent2 = get_theme_token("acento_secundario", "#1DC038")
        success = get_theme_token("estado_exito", "#40d66b")
        warning = get_theme_token("estado_aviso", "#d8c94a")
        error = get_theme_token("estado_error", "#ff6b5f")

        # Guardar colores para uso posterior
        self._colors = {
            "bg": bg, "text_main": text_main,
            "text_sec": text_sec, "accent": accent,
            "success": success, "warning": warning, "error": error,
            "bg_dark": bg_dark, "border": border,
        }

        # ── Layout raíz ──
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # ── Contenedor principal con borde redondeado ──
        container = QFrame(self)
        container.setObjectName("splashContainer")
        container.setStyleSheet(f"""
            QFrame#splashContainer {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 16px;
            }}
        """)
        root.addWidget(container)

        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(32, 0, 32, 16)
        container_layout.setSpacing(0)

        # ═══════════════════════════════════════════════════════
        # Zona central: Logo + Texto centrados H y V
        # ═══════════════════════════════════════════════════════
        self._top_spacer = QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding)
        container_layout.addItem(self._top_spacer)

        header = QHBoxLayout()
        header.setSpacing(16)

        # Stretch izquierdo para centrar horizontalmente
        header.addStretch()

        # ── Logo (SVG) ──
        logo_path = os.path.join(get_src_dir(), "assets", "icons", "app", "DowP_Logo.svg")

        logo_widget = QSvgWidget(logo_path, container)
        logo_widget.setFixedSize(QSize(68, 68))
        logo_widget.setStyleSheet("background: transparent; border: none;")
        header.addWidget(logo_widget, 0, Qt.AlignVCenter)

        # ── Columna de texto: nombre + estado ──
        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        text_col.setContentsMargins(0, 0, 0, 0)

        # "DowP 2.0.0" — nombre grande en negrita
        title_lbl = QLabel("DowP 2.0.0", container)
        title_lbl.setStyleSheet(f"""
            color: {text_main};
            font-family: 'Raleway', 'Segoe UI', sans-serif;
            font-size: 26px;
            font-weight: 800;
            background: transparent;
            border: none;
            letter-spacing: 0.5px;
        """)
        text_col.addWidget(title_lbl, 0, Qt.AlignLeft | Qt.AlignBottom)

        # "Cargando..." — texto delgado y pequeño
        self.status_label = QLabel("Cargando...", container)
        self.status_label.setStyleSheet(f"""
            color: {text_sec};
            font-family: 'Raleway', 'Segoe UI', sans-serif;
            font-size: 11px;
            font-weight: 300;
            background: transparent;
            border: none;
            letter-spacing: 0.5px;
        """)
        text_col.addWidget(self.status_label, 0, Qt.AlignLeft | Qt.AlignTop)

        header.addLayout(text_col)

        # Stretch derecho para centrar horizontalmente
        header.addStretch()

        container_layout.addLayout(header)
        self._bottom_spacer = QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding)
        container_layout.addItem(self._bottom_spacer)
        self._container_layout = container_layout

        # ═══════════════════════════════════════════════════════
        # Contenedor de dependencias (oculto hasta que se necesite)
        # ═══════════════════════════════════════════════════════
        self.deps_container = QFrame(container)
        self.deps_container.setObjectName("depsContainer")
        self.deps_container.setStyleSheet(f"""
            QFrame#depsContainer {{
                background-color: {bg_dark};
                border: 1px solid {border};
                border-radius: 10px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
            QProgressBar {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 3px;
                height: 6px;
            }}
            QProgressBar::chunk {{
                background-color: {accent};
                border-radius: 2px;
            }}
        """)
        self.deps_layout = QVBoxLayout(self.deps_container)
        self.deps_layout.setContentsMargins(14, 10, 14, 10)
        self.deps_layout.setSpacing(6)
        self.deps_container.hide()
        container_layout.addWidget(self.deps_container)

        # ── Barra de progreso mínima (pulsante) — pegada abajo ──
        self.loading_bar = QProgressBar(container)
        self.loading_bar.setRange(0, 0)  # Modo indeterminado
        self.loading_bar.setTextVisible(False)
        self.loading_bar.setFixedHeight(3)
        self.loading_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {bg_dark};
                border: none;
                border-radius: 1px;
            }}
            QProgressBar::chunk {{
                background-color: {accent};
                border-radius: 1px;
            }}
        """)
        container_layout.addSpacing(8)
        container_layout.addWidget(self.loading_bar)

    # ── Métodos de dependencias ──

    def _ensure_dep_row(self, dep_id, name):
        """Crea una fila de dependencia si no existe."""
        if dep_id in self.dep_rows:
            return

        colors = self._colors

        row = QHBoxLayout()
        row.setSpacing(8)

        # Dot indicador
        dot = QLabel("●", self.deps_container)
        dot.setFixedWidth(14)
        dot.setStyleSheet(f"color: {colors['text_sec']}; font-size: 10px;")
        dot.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        row.addWidget(dot)

        # Nombre
        name_lbl = QLabel(f"<b>{name}</b>", self.deps_container)
        name_lbl.setStyleSheet(f"""
            color: #cccccc;
            font-family: 'Raleway', 'Segoe UI', sans-serif;
            font-size: 11px;
        """)
        name_lbl.setFixedWidth(60)
        row.addWidget(name_lbl)

        # Barra de progreso
        bar = QProgressBar(self.deps_container)
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(False)
        bar.setFixedHeight(6)
        bar.hide()
        row.addWidget(bar, 1)

        # Status
        status = QLabel("Esperando...", self.deps_container)
        status.setStyleSheet(f"""
            color: {colors['text_sec']};
            font-family: 'Raleway', 'Segoe UI', sans-serif;
            font-size: 10px;
            font-weight: 600;
        """)
        status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status.setMinimumWidth(100)
        row.addWidget(status)

        self.deps_layout.addLayout(row)
        self.dep_rows[dep_id] = {
            "dot": dot, "bar": bar, "status": status, "name": name
        }

        # Mostrar contenedor y agrandar ventana
        if not self.deps_container.isVisible():
            # Eliminar los stretches de centrado vertical
            if self._top_spacer is not None:
                self._container_layout.removeItem(self._top_spacer)
                self._top_spacer = None
            if self._bottom_spacer is not None:
                self._container_layout.removeItem(self._bottom_spacer)
                self._bottom_spacer = None
            # Margen superior compacto en vez de stretch
            self._container_layout.setContentsMargins(32, 16, 32, 16)
            self.deps_container.show()
            self.setFixedSize(420, 230)
            self._center_on_screen()

    # ── Slots del worker ──

    @Slot(str)
    def _on_status_update(self, msg):
        self.status_label.setText(msg)

    @Slot(str, str)
    def _on_dep_started(self, dep_id, name):
        self._ensure_dep_row(dep_id, name)
        row = self.dep_rows[dep_id]
        row["dot"].setStyleSheet(f"color: {self._colors['warning']}; font-size: 10px;")
        row["status"].setText("Descargando... 0%")
        row["status"].setStyleSheet(f"""
            color: {self._colors['warning']};
            font-family: 'Raleway', 'Segoe UI', sans-serif;
            font-size: 10px; font-weight: 600;
        """)
        row["bar"].setValue(0)
        row["bar"].show()

    @Slot(str, int)
    def _on_dep_progress(self, dep_id, pct):
        if dep_id not in self.dep_rows:
            return
        row = self.dep_rows[dep_id]
        row["bar"].setValue(pct)
        row["status"].setText(f"Descargando... {pct}%")

    @Slot(str, bool, str)
    def _on_dep_finished(self, dep_id, success, version_or_msg):
        # Si no existe la fila, crearla (dependencia ya estaba instalada)
        if dep_id not in self.dep_rows:
            names = {
                "ytdlp": "yt-dlp",
                "ffmpeg": "FFmpeg",
                "deno": "Deno",
                "potprovider": "PO Provider",
            }
            self._ensure_dep_row(dep_id, names.get(dep_id, dep_id))

        row = self.dep_rows[dep_id]
        row["bar"].hide()

        if success:
            row["dot"].setStyleSheet(f"color: {self._colors['success']}; font-size: 10px;")
            row["status"].setText(f"v{version_or_msg}")
            row["status"].setStyleSheet(f"""
                color: {self._colors['success']};
                font-family: 'Raleway', 'Segoe UI', sans-serif;
                font-size: 10px; font-weight: 600;
            """)
        else:
            row["dot"].setStyleSheet(f"color: {self._colors['error']}; font-size: 10px;")
            row["status"].setText("Error")
            row["status"].setStyleSheet(f"""
                color: {self._colors['error']};
                font-family: 'Raleway', 'Segoe UI', sans-serif;
                font-size: 10px; font-weight: 600;
            """)

    @Slot()
    def _on_all_ready(self):
        """Dependencias listas → construir MainWindow ANTES de desvanecer."""
        self.status_label.setText("Iniciando aplicación...")
        self.status_label.setStyleSheet(f"""
            color: {self._colors['text_sec']};
            font-family: 'Raleway', 'Segoe UI', sans-serif;
            font-size: 11px;
            font-weight: 300;
            background: transparent;
            border: none;
        """)
        # Dar un frame para que el label se actualice
        QApplication.processEvents()

        # Pre-construir MainWindow mientras el splash sigue visible
        logger.debug("SplashScreen: Pre-construyendo MainWindow...")
        from gui.main_window import MainWindow
        self._main_window = MainWindow()
        logger.debug("SplashScreen: MainWindow construida.")

        # Ahora desvanecer el splash
        self.loading_bar.setRange(0, 100)
        self.loading_bar.setValue(100)
        self._finish()

    @Slot(str)
    def _on_failed(self, msg):
        self.loading_bar.setRange(0, 100)
        self.loading_bar.setValue(0)
        self.status_label.setText(f"Error: {msg}")
        self.status_label.setStyleSheet(f"""
            color: {self._colors['error']};
            font-family: 'Raleway', 'Segoe UI', sans-serif;
            font-size: 11px;
            font-weight: 600;
            background: transparent;
            border: none;
        """)
        # Emitir failed después de un breve delay para que el usuario lea
        QTimer.singleShot(3000, self.failed.emit)

    def _finish(self):
        """Fade out y emitir ready con la MainWindow ya construida."""
        self.effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.effect)

        self.fade_anim = QPropertyAnimation(self.effect, b"opacity")
        self.fade_anim.setDuration(300)
        self.fade_anim.setStartValue(1.0)
        self.fade_anim.setEndValue(0.0)
        self.fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.fade_anim.finished.connect(self._emit_ready)
        self.fade_anim.start()

    def _emit_ready(self):
        if self.worker and self.worker.isRunning():
            self.worker.wait(1000)
        self.hide()
        self.ready.emit(self._main_window)

    # ── API Pública ──

    def start(self):
        """Muestra la splash y arranca la verificación de dependencias."""
        self.show()
        QApplication.processEvents()

        self.worker = DependencyCheckWorker(self)
        self.worker.status_update.connect(self._on_status_update, Qt.QueuedConnection)
        self.worker.dependency_started.connect(self._on_dep_started, Qt.QueuedConnection)
        self.worker.dependency_progress.connect(self._on_dep_progress, Qt.QueuedConnection)
        self.worker.dependency_finished.connect(self._on_dep_finished, Qt.QueuedConnection)
        self.worker.all_ready.connect(self._on_all_ready, Qt.QueuedConnection)
        self.worker.failed.connect(self._on_failed, Qt.QueuedConnection)
        self.worker.start()

    def cleanup(self):
        """Detiene el worker si sigue corriendo."""
        if self.worker and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait(2000)
