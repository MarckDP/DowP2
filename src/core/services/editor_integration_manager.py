import os
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
        self.is_auto_send_enabled = True
        
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

    def connect_to_queue(self, queue_mgr):
        """Conecta el gestor de editores con el QueueManager para auto-enviar descargas."""
        queue_mgr.job_status_changed.connect(self._on_job_status_changed)
        self._queue_mgr = queue_mgr
        logger.info("[EditorManager] Conectado al QueueManager.")

    def _on_job_status_changed(self, job_id, status):
        """Callback cuando cambia el estado de un trabajo en el QueueManager."""
        if not self.is_auto_send_enabled:
            return
            
        if status == "COMPLETED" and self.active_editor:
            job = self._queue_mgr.get_job(job_id)
            if job and job.final_filepath:
                self.process_completed_job(job)

    def process_completed_job(self, job):
        """Empaqueta y envía un trabajo de cola completado al editor activo."""
        self.process_raw_download(job.final_filepath, job.request_data)

    def process_raw_download(self, final_filepath, request_data):
        """Empaqueta y envía un archivo descargado al editor activo."""
        if not final_filepath or not os.path.exists(final_filepath):
            return
            
        output_dir = os.path.dirname(final_filepath)
        raw_base_name = os.path.splitext(os.path.basename(final_filepath))[0]
        
        selected_fragments = request_data.get("selected_fragments", []) if request_data else []
        is_fragmented = bool(selected_fragments)
        
        # Determinar el nombre base limpio de forma 100% precisa
        if is_fragmented:
            last_frag = selected_fragments[-1]
            last_suffix = last_frag[2] if len(last_frag) > 2 else "fragment"
            target_suffix = f"_{last_suffix}"
            if raw_base_name.endswith(target_suffix):
                clean_base_name = raw_base_name[:-len(target_suffix)]
            else:
                clean_base_name = raw_base_name
        else:
            clean_base_name = raw_base_name
            # Si fue descagado individualmente con suffixos de DowP Lite (_recoded)
            if clean_base_name.endswith('_recoded'):
                clean_base_name = clean_base_name.rsplit('_recoded', 1)[0]
                
        expected_thumb_path = os.path.join(output_dir, f"{clean_base_name}.jpg")
        if not os.path.exists(expected_thumb_path):
            expected_thumb_path = None
        else:
            expected_thumb_path = expected_thumb_path.replace('\\', '/')
            
        file_packages = []
        
        # Si fue descarga de múltiples fragmentos, generamos sus nombres exactos.
        if is_fragmented:
            try:
                for i, frag in enumerate(selected_fragments):
                    suffix = frag[2] if len(frag) > 2 else f"fragment{i+1:02d}"
                    frag_base = f"{clean_base_name}_{suffix}"
                    
                    # Buscar el archivo de video (podría ser .mp4, .mkv, etc)
                    vid_path = None
                    for ext in ('.mp4', '.mkv', '.webm', '.mov', '.avi', '.flv', '.wmv', '.m4v', '.mp3', '.m4a', '.wav', '.flac', '.aac', '.ogg', '.opus', '.weba'):
                        candidate = os.path.join(output_dir, frag_base + ext)
                        if os.path.exists(candidate):
                            vid_path = candidate.replace('\\', '/')
                            break
                            
                    if vid_path:
                        # Buscar subtítulo exacto para este fragmento
                        sub_path = None
                        for s in os.listdir(output_dir):
                            if s.startswith(frag_base) and s.lower().endswith('.srt'):
                                sub_path = os.path.join(output_dir, s).replace('\\', '/')
                                break
                                
                        # Buscar miniatura específica de este fragmento
                        frag_thumb_path = os.path.join(output_dir, f"{frag_base}.jpg")
                        if not os.path.exists(frag_thumb_path):
                            frag_thumb_path = expected_thumb_path # Fallback a la miniatura base si existe
                        else:
                            frag_thumb_path = frag_thumb_path.replace('\\', '/')
                                
                        file_packages.append({
                            "video": vid_path,
                            "thumbnail": frag_thumb_path,
                            "subtitle": sub_path
                        })
            except Exception as e:
                logger.error(f"Error empaquetando fragmentos: {e}")
        else:
            # Archivo único normal
            vid_path = final_filepath.replace('\\', '/')
            sub_path = None
            try:
                for s in os.listdir(output_dir):
                    if s.startswith(clean_base_name) and s.lower().endswith('.srt'):
                        sub_path = os.path.join(output_dir, s).replace('\\', '/')
                        break
            except Exception: pass
            
            if final_filepath.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                file_packages.append({
                    "video": None,
                    "thumbnail": vid_path,
                    "subtitle": None
                })
            else:
                file_packages.append({
                    "video": vid_path,
                    "thumbnail": expected_thumb_path,
                    "subtitle": sub_path
                })
                
        if not file_packages:
            return
            
        if len(file_packages) == 1:
            logger.info(f"[EditorManager] Paquete listo para enviar: {file_packages[0]}")
            self.send_file(file_packages[0])
        else:
            logger.info(f"[EditorManager] Lote de {len(file_packages)} archivos (fragmentos) listos para enviar.")
            self.send_batch(file_packages)
