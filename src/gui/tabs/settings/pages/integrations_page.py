from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame, QScrollArea
from PySide6.QtCore import Qt


class IntegrationsPage(QWidget):
    """Página de ajustes de Integraciones (placeholder para futuras integraciones)."""

    def __init__(self):
        super().__init__()
        self.init_ui()

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
        self.content_layout.setSpacing(12)
        self.content_layout.setAlignment(Qt.AlignTop)

        # --- PLACEHOLDER ---
        self.placeholder_label = QLabel(self.tr("Próximamente"))
        self.placeholder_label.setObjectName("settingsSectionTitle")
        self.content_layout.addWidget(self.placeholder_label)

        self.desc_label = QLabel(self.tr(
            "Aquí podrás configurar las integraciones con software de edición:\n\n"
            "• Adobe Premiere Pro\n"
            "• DaVinci Resolve\n"
            "• Sony Vegas Pro"
        ))
        self.desc_label.setObjectName("settingsLabel")
        self.desc_label.setStyleSheet("color: #888888; font-size: 12px; line-height: 1.6;")
        self.desc_label.setWordWrap(True)
        self.content_layout.addWidget(self.desc_label)

        # Finalizar setup del scroll area
        self.scroll_area.setWidget(self.scroll_content)
        self.main_layout.addWidget(self.scroll_area)
