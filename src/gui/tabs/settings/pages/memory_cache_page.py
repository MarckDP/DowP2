# src/gui/tabs/settings/pages/memory_cache_page.py
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea, 
    QPushButton, QMessageBox, QProgressBar, QSizePolicy
)
from PySide6.QtCore import Qt
from core.utils.i18n import logger
from core.utils.cache_manager import CacheManager, format_bytes


class CacheCard(QFrame):
    """Tarjeta individual para representar y controlar un proveedor de caché específico."""

    def __init__(self, key: str, name: str, description: str, on_clear_callback, parent=None):
        super().__init__(parent)
        self.key = key
        self.name = name
        self.description = description
        self.on_clear_callback = on_clear_callback

        self.setObjectName("settingsCard")
        self.setStyleSheet("""
            QFrame#settingsCard {
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 8px;
                padding: 12px;
            }
        """)

        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        # Información (Izquierda)
        info_vbox = QVBoxLayout()
        info_vbox.setSpacing(4)

        self.lbl_title = QLabel(self.name)
        self.lbl_title.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 13px;")

        self.lbl_desc = QLabel(self.description)
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setStyleSheet("color: #888888; font-size: 11px;")

        self.lbl_stats = QLabel("Calculando...")
        self.lbl_stats.setStyleSheet("color: #4CAF50; font-size: 11px; font-weight: bold;")

        info_vbox.addWidget(self.lbl_title)
        info_vbox.addWidget(self.lbl_desc)
        info_vbox.addWidget(self.lbl_stats)

        # Botón de acción (Derecha)
        self.btn_clear = QPushButton(self.tr("Limpiar"))
        self.btn_clear.setFixedHeight(30)
        self.btn_clear.setFixedWidth(90)
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.setStyleSheet("""
            QPushButton {
                background-color: #2d2d2d;
                color: #ffffff;
                border: 1px solid #3d3d3d;
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #e74c3c;
                border-color: #c0392b;
            }
            QPushButton:pressed {
                background-color: #a93226;
            }
        """)
        self.btn_clear.clicked.connect(lambda: self.on_clear_callback(self.key, self.name))

        layout.addLayout(info_vbox, 1)
        layout.addWidget(self.btn_clear, 0, Qt.AlignVCenter)

    def update_stats(self, file_count: int, size_bytes: int):
        formatted_size = format_bytes(size_bytes)
        self.lbl_stats.setText(f"{file_count} archivos  |  Tamaño: {formatted_size}")


class FutureCacheCard(QFrame):
    """Tarjeta reservada para futuras cachés de la aplicación."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("futureCacheCard")
        self.setStyleSheet("""
            QFrame#futureCacheCard {
                background-color: #181818;
                border: 1px dashed #3a3a3a;
                border-radius: 8px;
                padding: 12px;
            }
        """)
        init_layout = QHBoxLayout(self)
        init_layout.setContentsMargins(12, 10, 12, 10)

        vbox = QVBoxLayout()
        vbox.setSpacing(4)

        lbl_title = QLabel(self.tr("Espacio reservado para más cachés"))
        lbl_title.setStyleSheet("color: #aaaaaa; font-weight: bold; font-size: 12px;")


        lbl_desc = QLabel(self.tr("Aquí se integrarán automáticamente las nuevas cachés del sistema a medida que se añadan nuevas funciones (descargas de red, ondas de audio, etc.)."))
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #666666; font-size: 11px;")

        vbox.addWidget(lbl_title)
        vbox.addWidget(lbl_desc)
        init_layout.addLayout(vbox)


class MemoryCachePage(QWidget):
    """Pestaña de ajustes para centralizar el monitoreo y limpieza de la memoria y caché de la app."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cache_cards: dict[str, CacheCard] = {}
        self.init_ui()
        self.refresh_stats()

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(12)

        # ---------------- TÍTULO Y SEPARADOR ----------------
        self.title_label = QLabel(self.tr("Memoria y Caché"))
        self.title_label.setObjectName("settingsTitle")
        self.main_layout.addWidget(self.title_label)

        line = QFrame()
        line.setObjectName("settingsDivider")
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        self.main_layout.addWidget(line)

        # ---------------- SCROLL AREA ----------------
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("background-color: transparent;")

        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("settingsScrollContent")
        self.scroll_content.setStyleSheet("QWidget#settingsScrollContent { background-color: transparent; }")

        self.content_layout = QVBoxLayout(self.scroll_content)
        self.content_layout.setContentsMargins(0, 10, 10, 0)
        self.content_layout.setSpacing(16)
        self.content_layout.setAlignment(Qt.AlignTop)

        # ---------------- TARJETA RESUMEN TOTAL / MEDIDOR GLOBAL ----------------
        self.total_card = QFrame()
        self.total_card.setObjectName("totalCacheCard")
        self.total_card.setStyleSheet("""
            QFrame#totalCacheCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #25282a, stop:1 #1c1d1f);
                border: 1px solid #383c40;
                border-radius: 10px;
                padding: 16px;
            }
        """)

        total_layout = QVBoxLayout(self.total_card)
        total_layout.setSpacing(10)

        # Encabezado del total
        header_hbox = QHBoxLayout()
        lbl_total_title = QLabel(self.tr("Uso Total de Caché"))
        lbl_total_title.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: bold;")
        
        self.lbl_total_size = QLabel("0 B")
        self.lbl_total_size.setStyleSheet("color: #B9E640; font-size: 18px; font-weight: bold;")
        
        header_hbox.addWidget(lbl_total_title)
        header_hbox.addStretch()
        header_hbox.addWidget(self.lbl_total_size)
        total_layout.addLayout(header_hbox)

        # Medidor / Barra de progreso global
        self.meter_bar = QProgressBar()
        self.meter_bar.setFixedHeight(8)
        self.meter_bar.setTextVisible(False)
        self.meter_bar.setRange(0, 100)
        self.meter_bar.setValue(0)
        self.meter_bar.setStyleSheet("""
            QProgressBar {
                background-color: #121212;
                border-radius: 4px;
                border: none;
            }
            QProgressBar::chunk {
                background-color: #B9E640;
                border-radius: 4px;
            }
        """)
        total_layout.addWidget(self.meter_bar)

        # Subtítulo de resumen y botón de borrar todo
        action_hbox = QHBoxLayout()
        self.lbl_total_details = QLabel(self.tr("Calculando uso de memoria y archivos..."))
        self.lbl_total_details.setStyleSheet("color: #aaaaaa; font-size: 11px;")

        self.btn_clear_all = QPushButton(self.tr("Borrar toda la caché"))
        self.btn_clear_all.setFixedHeight(34)
        self.btn_clear_all.setCursor(Qt.PointingHandCursor)
        self.btn_clear_all.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: #ffffff;
                border: 1px solid #c0392b;
                border-radius: 6px;
                padding: 6px 16px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #ff4d4d;
                border-color: #e74c3c;
            }
            QPushButton:pressed {
                background-color: #962d22;
            }
        """)
        self.btn_clear_all.clicked.connect(self.on_clear_all_clicked)

        action_hbox.addWidget(self.lbl_total_details)
        action_hbox.addStretch()
        action_hbox.addWidget(self.btn_clear_all)
        total_layout.addLayout(action_hbox)

        # Límite de Caché
        from PySide6.QtWidgets import QDoubleSpinBox, QAbstractSpinBox
        from core.utils.config_manager import get_config
        
        limit_hbox = QHBoxLayout()
        self.lbl_limit = QLabel(self.tr("Límite máximo:"))
        self.lbl_limit.setStyleSheet("color: #aaaaaa; font-size: 13px;")
        
        self.limit_spinbox = QDoubleSpinBox()
        self.limit_spinbox.setRange(0.0, 999.0)
        self.limit_spinbox.setDecimals(1)
        self.limit_spinbox.setSingleStep(1.0)
        self.limit_spinbox.setSuffix(self.tr(" GB"))
        self.limit_spinbox.setSpecialValueText(self.tr("Sin límite"))
        self.limit_spinbox.setFixedWidth(140)
        self.limit_spinbox.setButtonSymbols(QAbstractSpinBox.PlusMinus)
        self.limit_spinbox.setStyleSheet("""
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                font-size: 9px;
                padding: 0px;
            }
        """)
        
        # Cargar valor inicial
        current_limit = get_config().get("max_cache_size_gb", 0.0)
        self.limit_spinbox.setValue(current_limit)
        self.limit_spinbox.valueChanged.connect(self.on_limit_changed)

        limit_hbox.addWidget(self.lbl_limit)
        limit_hbox.addWidget(self.limit_spinbox)
        limit_hbox.addStretch()

        total_layout.addLayout(limit_hbox)

        self.content_layout.addWidget(self.total_card)

        # ---------------- SECCIÓN DE CACHÉS INDIVIDUALES ----------------
        lbl_sec_title = QLabel(self.tr("Cachés de la Aplicación"))
        lbl_sec_title.setObjectName("settingsSectionTitle")
        lbl_sec_title.setStyleSheet("color: #dddddd; font-size: 13px; font-weight: bold; margin-top: 8px;")
        self.content_layout.addWidget(lbl_sec_title)

        # Construir tarjetas de proveedores registrados en CacheManager
        cache_mgr = CacheManager.get_instance()
        for provider in cache_mgr.get_providers():
            card = CacheCard(
                key=provider.key,
                name=provider.name,
                description=provider.description,
                on_clear_callback=self.on_clear_single_clicked,
                parent=self.scroll_content
            )
            self.cache_cards[provider.key] = card
            self.content_layout.addWidget(card)

        # Tarjeta reservada para futuras cachés
        self.content_layout.addWidget(FutureCacheCard(parent=self.scroll_content))

        # Finalizar setup del scroll area
        self.scroll_area.setWidget(self.scroll_content)
        self.main_layout.addWidget(self.scroll_area)

    def refresh_stats(self):
        """Obtiene las estadísticas actualizadas de CacheManager y refresca la UI."""
        stats = CacheManager.get_instance().get_all_stats()

        total_files = stats.get("total_files", 0)
        total_bytes = stats.get("total_bytes", 0)
        formatted_total = stats.get("formatted_total_size", "0 B")

        self.lbl_total_size.setText(formatted_total)
        self.lbl_total_details.setText(
            self.tr(f"Archivos acumulados en caché: {total_files}  •  Almacenamiento total: {formatted_total}")
        )

        # Actualizar medidor (barra visual)
        from core.utils.config_manager import get_config
        limit_gb = get_config().get("max_cache_size_gb", 0.0)

        if limit_gb > 0:
            max_reference_bytes = limit_gb * 1024 * 1024 * 1024
        else:
            import os
            import shutil
            try:
                # Obtenemos el espacio libre del disco donde está AppData
                app_data = os.getenv('APPDATA', 'C:\\')
                total, used, free = shutil.disk_usage(app_data)
                # El tamaño visual máximo será el caché actual + el espacio libre que le queda al disco
                max_reference_bytes = total_bytes + free
            except Exception:
                max_reference_bytes = 100 * 1024 * 1024

        percentage = min(100, int((total_bytes / max_reference_bytes) * 100)) if max_reference_bytes > 0 else 0
        self.meter_bar.setValue(percentage if total_bytes > 0 else 0)

        # Actualizar tarjetas individuales
        for p_stat in stats.get("providers", []):
            key = p_stat.get("key")
            if key in self.cache_cards:
                self.cache_cards[key].update_stats(
                    file_count=p_stat.get("file_count", 0),
                    size_bytes=p_stat.get("size_bytes", 0)
                )

    def on_clear_single_clicked(self, key: str, name: str):
        """Elimina la caché de un proveedor específico previa confirmación."""
        reply = QMessageBox.question(
            self,
            self.tr("Confirmar Limpieza"),
            self.tr(f"¿Estás seguro de que deseas vaciar la '{name}'?"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            res = CacheManager.get_instance().clear_provider(key)
            freed_str = format_bytes(res.get("bytes_freed", 0))
            QMessageBox.information(
                self,
                self.tr("Caché Limpiada"),
                self.tr(f"Se ha limpiado la '{name}' correctamente.\nSe eliminaron {res.get('files_removed', 0)} archivos y se liberaron {freed_str}.")
            )
            self.refresh_stats()

    def on_clear_all_clicked(self):
        """Elimina absolutamente todas las cachés del sistema."""
        reply = QMessageBox.question(
            self,
            self.tr("Confirmar Limpieza Total"),
            self.tr("¿Deseas eliminar TODA la caché de la aplicación (imágenes, miniaturas y metadatos)?\nEsta acción liberará espacio de almacenamiento."),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            res = CacheManager.get_instance().clear_all()
            if res:
                QMessageBox.information(
                    self,
                    self.tr("Caché Total Limpiada"),
                    self.tr(f"Limpieza total completada con éxito.\nSe eliminaron {res.get('files_removed', 0)} archivos y se liberaron {res.get('formatted_freed', '0 B')}.")
                )
                self.refresh_stats()

    def on_limit_changed(self, value):
        from core.utils.config_manager import get_config, save_config
        config = get_config()
        config["max_cache_size_gb"] = value
        save_config(config)
        # Refrescar la barra para que recalcule de inmediato con el nuevo límite
        self.refresh_stats()
