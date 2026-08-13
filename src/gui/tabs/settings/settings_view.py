from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                                 QStackedWidget, QButtonGroup, QPushButton, QFrame, QApplication)
from PySide6.QtCore import Qt, Signal
from core.utils.i18n import logger

from .pages.general_page import GeneralPage
from .pages.memory_cache_page import MemoryCachePage
from .pages.network_page import NetworkPage
from .pages.downloads_page import DownloadsPage
from .pages.cookies_page import CookiesPage
from .pages.deps_page import DependenciesPage
from .pages.labels_page import LabelsPage
from .pages.integrations_page import IntegrationsPage
from .pages.system_page import SystemPage

class SidebarButton(QPushButton):
    """Custom button for sidebar to handle styling via objectName and QSS"""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setObjectName("sidebarButton")
        self.setCheckable(True)
        self.setFixedHeight(36)
        self.setCursor(Qt.PointingHandCursor)

class SettingsTab(QWidget):
    language_changed = Signal(str)
    theme_changed = Signal(str)
    integrations_changed = Signal()

    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # ---------------- LEFT SIDEBAR ----------------
        self.sidebar_frame = QFrame()
        self.sidebar_frame.setObjectName("settingsSidebar")
        self.sidebar_frame.setFixedWidth(200)

        sidebar_layout = QVBoxLayout(self.sidebar_frame)
        sidebar_layout.setContentsMargins(0, 20, 0, 20)
        sidebar_layout.setSpacing(5)

        # Title
        options_label = QLabel(self.tr("Opciones"))
        font = options_label.font()
        font.setBold(True)
        font.setPointSize(12)
        options_label.setFont(font)
        options_label.setAlignment(Qt.AlignCenter)
        sidebar_layout.addWidget(options_label)
        sidebar_layout.addSpacing(20)

        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)

        # Buttons
        self.btn_general = SidebarButton(self.tr("General"))
        self.btn_memory_cache = SidebarButton(self.tr("Memoria y Caché"))
        self.btn_network = SidebarButton(self.tr("Conexión y Red"))
        self.btn_downloads = SidebarButton(self.tr("Descargas"))
        self.btn_cookies = SidebarButton(self.tr("Cookies"))
        self.btn_deps = SidebarButton(self.tr("Dependencias"))
        self.btn_labels = SidebarButton(self.tr("Etiquetas"))
        self.btn_integrations = SidebarButton(self.tr("Integraciones"))
        self.btn_system = SidebarButton(self.tr("Acerca de"))
        self.btn_models = SidebarButton(self.tr("Modelos"))
        self.btn_console = SidebarButton(self.tr("Consola"))

        self.btn_group.addButton(self.btn_general, 0)
        self.btn_group.addButton(self.btn_memory_cache, 1)
        self.btn_group.addButton(self.btn_network, 2)
        self.btn_group.addButton(self.btn_downloads, 3)
        self.btn_group.addButton(self.btn_cookies, 4)
        self.btn_group.addButton(self.btn_deps, 5)
        self.btn_group.addButton(self.btn_labels, 6)
        self.btn_group.addButton(self.btn_integrations, 7)
        self.btn_group.addButton(self.btn_system, 8)
        self.btn_group.addButton(self.btn_models, 9)
        self.btn_group.addButton(self.btn_console, 10)

        sidebar_layout.addWidget(self.btn_general)
        sidebar_layout.addWidget(self.btn_memory_cache)
        sidebar_layout.addWidget(self.btn_network)
        sidebar_layout.addWidget(self.btn_downloads)
        sidebar_layout.addWidget(self.btn_cookies)
        sidebar_layout.addWidget(self.btn_deps)
        sidebar_layout.addWidget(self.btn_labels)
        sidebar_layout.addWidget(self.btn_integrations)
        sidebar_layout.addWidget(self.btn_system)
        sidebar_layout.addWidget(self.btn_models)
        sidebar_layout.addWidget(self.btn_console)
        sidebar_layout.addStretch()

        # Version Label
        version = QApplication.instance().applicationVersion()
        self.version_label = QLabel(f"v{version}")
        self.version_label.setStyleSheet("color: #555555; font-size: 11px; margin-bottom: 10px;")
        self.version_label.setAlignment(Qt.AlignCenter)
        sidebar_layout.addWidget(self.version_label)

        self.main_layout.addWidget(self.sidebar_frame)

        # ---------------- RIGHT CONTENT AREA ----------------
        self.content_area = QFrame()
        self.content_area.setObjectName("settingsContentArea")
        
        content_layout = QVBoxLayout(self.content_area)
        content_layout.setContentsMargins(30, 30, 30, 30)

        self.stacked_widget = QStackedWidget()
        
        # Pages
        self.page_general = GeneralPage()
        self.page_memory_cache = MemoryCachePage()
        self.page_network = NetworkPage()
        self.page_downloads = DownloadsPage()
        self.page_cookies = CookiesPage()
        self.page_deps = DependenciesPage()
        self.page_labels = LabelsPage()
        self.page_integrations = IntegrationsPage()
        self.page_system = SystemPage()
        self.page_placeholder_models = QWidget()  # Modelos
        self.page_placeholder_console = QWidget()  # Consola

        self.stacked_widget.addWidget(self.page_general)            # 0
        self.stacked_widget.addWidget(self.page_memory_cache)       # 1
        self.stacked_widget.addWidget(self.page_network)            # 2
        self.stacked_widget.addWidget(self.page_downloads)          # 3
        self.stacked_widget.addWidget(self.page_cookies)            # 4
        self.stacked_widget.addWidget(self.page_deps)               # 5
        self.stacked_widget.addWidget(self.page_labels)             # 6
        self.stacked_widget.addWidget(self.page_integrations)       # 7
        self.stacked_widget.addWidget(self.page_system)             # 8
        self.stacked_widget.addWidget(self.page_placeholder_models)  # 9
        self.stacked_widget.addWidget(self.page_placeholder_console) # 10

        content_layout.addWidget(self.stacked_widget)
        self.main_layout.addWidget(self.content_area, 1)

        # Connections
        self.btn_group.idClicked.connect(self._on_tab_changed)
        
        # Pass signals from general page
        self.page_general.language_changed.connect(self.language_changed.emit)
        self.page_general.theme_changed.connect(self.theme_changed.emit)

        # Pass signal from integrations page
        self.page_integrations.integration_toggled.connect(lambda app_id, checked: self.integrations_changed.emit())

        # Default selection
        self.btn_general.setChecked(True)
        self.stacked_widget.setCurrentIndex(0)


    def _on_tab_changed(self, index: int):
        self.stacked_widget.setCurrentIndex(index)
        if index == 1:
            self.page_memory_cache.refresh_stats()



