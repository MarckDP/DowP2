from PySide6.QtCore import QObject, Signal
from core.logger.logger_manager import logger

from core.services.adobe_socket_server import AdobeSocketServer

class EditorIntegrationManager(QObject):
    """
    Gestor Maestro para todas las integraciones de editores de video (NLEs).
    Centraliza el estado de conexión y delega las tareas al servicio correspondiente
    (Adobe, DaVinci, Vegas, etc.).
    """
    # Se emite cuando el editor activo cambia (ej. None -> 'premiere' o viceversa)
    active_editor_changed = Signal(object)
    
    _instance = None

    def __init__(self):
        super().__init__()
        self.active_editor = None
        
        # Servicios
        self.adobe_service = AdobeSocketServer()
        
        # Conectar señales del servicio Adobe
        self.adobe_service.active_target_changed.connect(self._on_adobe_target_changed)
        
        # Futuros servicios irán aquí:
        # self.davinci_service = DaVinciIntegrationService()
        # self.vegas_service = VegasIntegrationService()

        EditorIntegrationManager._instance = self

    @classmethod
    def get_instance(cls):
        return cls._instance

    def start_all_services(self):
        """Inicia todos los servidores de comunicación en segundo plano."""
        logger.info("[EditorManager] Iniciando servicios de integración...")
        self.adobe_service.start()
        # self.davinci_service.start()
        # self.vegas_service.start()

    def stop_all_services(self):
        """Detiene todos los servicios al cerrar la aplicación."""
        logger.info("[EditorManager] Deteniendo servicios de integración...")
        try:
            self.adobe_service.stop()
        except Exception as e:
            logger.error(f"[EditorManager] Error deteniendo Adobe service: {e}")

    def _on_adobe_target_changed(self, target_app):
        """Callback cuando Premiere o After Effects cambian de estado."""
        if target_app:
            self.active_editor = target_app
            logger.info(f"[EditorManager] Editor activo establecido a: {self.active_editor}")
        else:
            # Si Adobe se desconectó, revisamos si otro está activo o lo dejamos en None
            self.active_editor = None
            logger.info("[EditorManager] Ningún editor activo conectado.")
            
        self.active_editor_changed.emit(self.active_editor)

    def send_file(self, file_package):
        """
        Envía un archivo descargado al editor activo actual.
        """
        if not self.active_editor:
            logger.warning("[EditorManager] No hay un editor activo. No se enviará el archivo.")
            return False

        if self.active_editor in ('premiere', 'aftereffects'):
            return self.adobe_service.send_file_to_adobe(file_package)
        elif self.active_editor == 'davinci':
            # return self.davinci_service.send_file(file_package)
            pass
        elif self.active_editor == 'vegas':
            # return self.vegas_service.send_file(file_package)
            pass
        else:
            logger.error(f"[EditorManager] Editor desconocido: {self.active_editor}")
            return False

    def send_batch(self, files, target_bin=None):
        """
        Envía un lote de archivos al editor activo actual.
        """
        if not self.active_editor:
            logger.warning("[EditorManager] No hay un editor activo. No se enviará el lote.")
            return False

        if self.active_editor in ('premiere', 'aftereffects'):
            return self.adobe_service.send_batch_to_adobe(files, target_bin)
        elif self.active_editor == 'davinci':
            # return self.davinci_service.send_batch(files)
            pass
        elif self.active_editor == 'vegas':
            # return self.vegas_service.send_batch(files)
            pass
        else:
            logger.error(f"[EditorManager] Editor desconocido: {self.active_editor}")
            return False
