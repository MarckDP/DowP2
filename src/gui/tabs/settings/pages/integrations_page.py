from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                                 QFrame, QScrollArea, QPushButton, QSizePolicy)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QPixmap
from core.services.editor_integration_manager import EditorIntegrationManager
import os

class IntegrationsPage(QWidget):
    """Página de ajustes de Integraciones para NLEs."""

    def __init__(self):
        super().__init__()
        self.init_ui()
        
        # Conectar al EditorIntegrationManager
        self.editor_mgr = EditorIntegrationManager.get_instance()
        if self.editor_mgr:
            self.editor_mgr.active_editor_changed.connect(self.update_adobe_status)
            self.update_adobe_status(self.editor_mgr.active_editor)

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(12)

        # Title
        self.title_label = QLabel(self.tr("Integraciones"))
        self.title_label.setObjectName("settingsTitle")
        self.main_layout.addWidget(self.title_label)

        # Divider
        line = QFrame()
        line.setObjectName("settingsDivider")
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        self.main_layout.addWidget(line)

        # Crear el QScrollArea
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("background-color: transparent;")

        # Widget contenedor para el contenido del scroll
        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("settingsScrollContent")
        self.scroll_content.setStyleSheet("QWidget#settingsScrollContent { background-color: transparent; }")

        # Layout para el contenido del scroll
        self.content_layout = QVBoxLayout(self.scroll_content)
        self.content_layout.setContentsMargins(0, 10, 10, 0)
        self.content_layout.setSpacing(20)
        self.content_layout.setAlignment(Qt.AlignTop)

        # --- SECCIÓN ADOBE ---
        self.create_adobe_section()
        
        # --- SECCIÓN DAVINCI (Placeholder) ---
        self.create_davinci_section()

        self.content_layout.addStretch(1)

        # Finalizar setup del scroll area
        self.scroll_area.setWidget(self.scroll_content)
        self.main_layout.addWidget(self.scroll_area)
        
    def create_card_frame(self):
        card = QFrame()
        card.setObjectName("settingsCard")
        # Reuse existing settingsCard stylesheet logic or provide a fallback
        card.setStyleSheet("""
            QFrame#settingsCard {
                background-color: rgba(255, 255, 255, 0.05);
                border-radius: 8px;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
        """)
        return card

    def create_adobe_section(self):
        self.adobe_card = self.create_card_frame()
        card_layout = QVBoxLayout(self.adobe_card)
        card_layout.setContentsMargins(15, 15, 15, 15)
        card_layout.setSpacing(15)
        
        # Header (Title + Status)
        header_layout = QHBoxLayout()
        title = QLabel(self.tr("Adobe Premiere Pro & After Effects"))
        title.setObjectName("settingsSectionTitle")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        
        self.adobe_status_lbl = QLabel(self.tr("Desconectado"))
        self.adobe_status_lbl.setStyleSheet("color: #ff5555; font-weight: bold;")
        
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.adobe_status_lbl)
        card_layout.addLayout(header_layout)
        
        # Icons & Description
        content_layout = QHBoxLayout()
        
        icons_layout = QHBoxLayout()
        icons_layout.setSpacing(10)
        
        self.lbl_icon_pr = QLabel()
        self.lbl_icon_pr.setFixedSize(48, 48)
        self.set_icon(self.lbl_icon_pr, "premiere pro.svg", opacity=0.3)
        
        self.lbl_icon_ae = QLabel()
        self.lbl_icon_ae.setFixedSize(48, 48)
        self.set_icon(self.lbl_icon_ae, "after effects.svg", opacity=0.3)
        
        icons_layout.addWidget(self.lbl_icon_pr)
        icons_layout.addWidget(self.lbl_icon_ae)
        
        desc = QLabel(self.tr("Instala la extensión DowP Importer en Adobe Premiere Pro o After Effects. Al mantener la ventana de la extensión abierta, DowP se conectará automáticamente para enviar medios y subtítulos."))
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #aaaaaa;")
        
        content_layout.addLayout(icons_layout)
        content_layout.addSpacing(20)
        content_layout.addWidget(desc, 1)
        card_layout.addLayout(content_layout)
        
        self.content_layout.addWidget(self.adobe_card)

    def create_davinci_section(self):
        self.davinci_card = self.create_card_frame()
        card_layout = QVBoxLayout(self.davinci_card)
        card_layout.setContentsMargins(15, 15, 15, 15)
        card_layout.setSpacing(15)
        
        # Header
        header_layout = QHBoxLayout()
        title = QLabel(self.tr("DaVinci Resolve"))
        title.setObjectName("settingsSectionTitle")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        
        status_lbl = QLabel(self.tr("Próximamente"))
        status_lbl.setStyleSheet("color: #888888; font-weight: bold;")
        
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(status_lbl)
        card_layout.addLayout(header_layout)
        
        # Icons & Description
        content_layout = QHBoxLayout()
        
        lbl_icon_dv = QLabel()
        lbl_icon_dv.setFixedSize(48, 48)
        self.set_icon(lbl_icon_dv, "davinci resolve.svg", opacity=1.0)
        
        desc = QLabel(self.tr("La integración directa con DaVinci Resolve estará disponible en una futura actualización."))
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #aaaaaa;")
        
        content_layout.addWidget(lbl_icon_dv)
        content_layout.addSpacing(20)
        content_layout.addWidget(desc, 1)
        card_layout.addLayout(content_layout)
        
        self.content_layout.addWidget(self.davinci_card)
        
    def set_icon(self, label, icon_name, opacity=1.0):
        # Asegurar que el icono existe
        icon_path = os.path.join("src", "assets", "icons", "svg", icon_name)
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path).scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            label.setPixmap(pixmap)
            
            # Simple forma de aplicar opacidad: usar QGraphicsOpacityEffect o StyleSheet, 
            # pero dado que es SVG plano, podemos bajar la opacidad con QGraphicsOpacityEffect
            from PySide6.QtWidgets import QGraphicsOpacityEffect
            effect = QGraphicsOpacityEffect(label)
            effect.setOpacity(opacity)
            label.setGraphicsEffect(effect)

    def update_adobe_status(self, active_editor):
        if active_editor == 'premiere':
            self.adobe_status_lbl.setText(self.tr("Conectado (Premiere Pro)"))
            self.adobe_status_lbl.setStyleSheet("color: #55ff55; font-weight: bold;")
            self.set_icon(self.lbl_icon_pr, "premiere pro.svg", opacity=1.0)
            self.set_icon(self.lbl_icon_ae, "after effects.svg", opacity=0.3)
        elif active_editor == 'aftereffects':
            self.adobe_status_lbl.setText(self.tr("Conectado (After Effects)"))
            self.adobe_status_lbl.setStyleSheet("color: #55ff55; font-weight: bold;")
            self.set_icon(self.lbl_icon_pr, "premiere pro.svg", opacity=0.3)
            self.set_icon(self.lbl_icon_ae, "after effects.svg", opacity=1.0)
        else:
            self.adobe_status_lbl.setText(self.tr("Desconectado"))
            self.adobe_status_lbl.setStyleSheet("color: #ff5555; font-weight: bold;")
            self.set_icon(self.lbl_icon_pr, "premiere pro.svg", opacity=0.3)
            self.set_icon(self.lbl_icon_ae, "after effects.svg", opacity=0.3)

