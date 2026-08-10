import os
import subprocess
from PySide6.QtCore import QObject, Signal, QThread
from core.logger.logger_manager import logger

from core.services.adobe_socket_server import AdobeSocketServer
from core.services.davinci_integration_service import DaVinciIntegrationService

class ProcessMonitorThread(QThread):
    processes_updated = Signal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_running = True
        self.targets = {
            "premiere": "Adobe Premiere Pro.exe",
            "aftereffects": "AfterFX.exe",
            "davinci": "Resolve.exe"
        }
        
    def run(self):
        import time
        while self.is_running:
            try:
                # Use tasklist on Windows to quickly check running processes
                output = subprocess.check_output('tasklist', creationflags=subprocess.CREATE_NO_WINDOW).decode('utf-8', errors='ignore')
                status = {}
                for app_id, exe_name in self.targets.items():
                    status[app_id] = (exe_name in output)
                self.processes_updated.emit(status)
            except Exception as e:
                pass
            time.sleep(3.0)
            
    def stop(self):
        self.is_running = False
        self.wait()


class EditorIntegrationManager(QObject):
    """
    Gestor Maestro para todas las integraciones de editores de video (NLEs).
    Centraliza el estado de conexión y delega las tareas al servicio correspondiente
    (Adobe, DaVinci, Vegas, etc.).
    """
    # Se emite cuando el editor activo cambia (ej. None -> 'premiere' o viceversa)
    active_editor_changed = Signal(object)
    # Se emite cuando cambia el estado de proceso en el SO {app_id: bool}
    process_status_changed = Signal(dict)
    
    _instance = None

    def __init__(self):
        super().__init__()
        self.active_editor = None
        self.is_auto_send_enabled = True
        self.process_status = {}
        
        # Servicios
        self.adobe_service = AdobeSocketServer()
        self.davinci_service = DaVinciIntegrationService.get_instance()
        
        # Conectar señales del servicio Adobe
        self.adobe_service.active_target_changed.connect(self._on_adobe_target_changed)
        
        # Futuros servicios irán aquí:
        # self.vegas_service = VegasIntegrationService()

        EditorIntegrationManager._instance = self
        
        # Monitor de procesos
        self.process_monitor = ProcessMonitorThread()
        self.process_monitor.processes_updated.connect(self._on_processes_updated)

    @classmethod
    def get_instance(cls):
        return cls._instance
        
    def _on_processes_updated(self, status_dict):
        self.process_status = status_dict
        self.process_status_changed.emit(status_dict)

    def start_all_services(self):
        """Inicia todos los servidores de comunicación en segundo plano."""
        logger.info("[EditorManager] Iniciando servicios de integración...")
        self.adobe_service.start()
        self.process_monitor.start()
        # self.vegas_service.start()

    def stop_all_services(self):
        """Detiene todos los servicios al cerrar la aplicación."""
        logger.info("[EditorManager] Deteniendo servicios de integración...")
        try:
            self.process_monitor.stop()
        except Exception: pass
        
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

    def force_adobe_target(self, target_app):
        """Intenta forzar el objetivo activo. Soporta Adobe y DaVinci."""
        if target_app == "davinci":
            self.active_editor = "davinci"
            logger.info(f"[EditorManager] Editor activo establecido a: {self.active_editor}")
            self.active_editor_changed.emit(self.active_editor)
            return True
            
        if self.adobe_service:
            return self.adobe_service.force_active_target(target_app)
        return False

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
            return self.davinci_service.send_files_to_davinci([file_package])
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
            return self.davinci_service.send_files_to_davinci(files)
        elif self.active_editor == 'vegas':
            # return self.vegas_service.send_batch(files)
            pass
        else:
            logger.error(f"[EditorManager] Editor desconocido: {self.active_editor}")
            return False

    def send_subclips(self, payload):
        """
        Envía información de subclips (puntos in/out) al editor activo.
        payload: {"filePath": str, "subclips": [{"name": str, "in": float, "out": float}]}
        """
        if not self.active_editor:
            logger.warning("[EditorManager] No hay un editor activo. No se enviarán los subclips.")
            return False

        if self.active_editor in ('premiere', 'aftereffects'):
            return self.adobe_service.send_subclips_to_adobe(payload)
        elif self.active_editor == 'davinci':
            return self.davinci_service.send_subclips_to_davinci(payload)
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
        if not final_filepath:
            return
            
        import os
        import re
        
        # Buscar el archivo real descargado si la ruta temporal fue eliminada (ej. Streams HLS / merger)
        actual_filepath = final_filepath
        if not os.path.exists(final_filepath):
            parent_dir = os.path.dirname(final_filepath)
            if os.path.exists(parent_dir):
                base_name = os.path.splitext(os.path.basename(final_filepath))[0]
                for temp_ext in ['.temp', '.ytdl', '.part']:
                    if base_name.endswith(temp_ext):
                        base_name = base_name[:-len(temp_ext)]
                base_name = re.sub(r'\.f[a-zA-Z0-9-]+$', '', base_name)
                
                best_match = None
                try:
                    for entry in os.scandir(parent_dir):
                        if entry.is_file():
                            entry_base = os.path.splitext(entry.name)[0]
                            if entry_base == base_name:
                                actual_filepath = entry.path
                                break
                            if entry_base.startswith(base_name):
                                best_match = entry.path
                except Exception:
                    pass
                if actual_filepath == final_filepath and best_match:
                    actual_filepath = best_match
                    
        final_filepath = actual_filepath
        
        mode = request_data.get("mode") if request_data else None
        if mode not in ("thumbnail_only", "subtitle_only") and not os.path.exists(final_filepath):
            logger.error(f"[EditorManager] No se pudo encontrar el archivo final para enviar: {final_filepath}")
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
            vid_path = final_filepath.replace('\\', '/') if os.path.exists(final_filepath) else None
            sub_path = None
            try:
                for s in os.listdir(output_dir):
                    if s.startswith(clean_base_name) and s.lower().endswith('.srt'):
                        sub_path = os.path.join(output_dir, s).replace('\\', '/')
                        break
            except Exception: pass
            
            if final_filepath.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and os.path.exists(final_filepath):
                file_packages.append({
                    "video": None,
                    "thumbnail": vid_path,
                    "subtitle": None
                })
            elif final_filepath.lower().endswith(('.srt', '.vtt', '.ass', '.ssa', '.sub', '.ttml')) and os.path.exists(final_filepath):
                file_packages.append({
                    "video": None,
                    "thumbnail": None,
                    "subtitle": vid_path
                })
            else:
                # Si ni el video ni la miniatura ni el subtitulo existen, ignoramos
                if vid_path or expected_thumb_path or sub_path:
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
