import os
import re
import platform
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
        is_windows = platform.system() == "Windows"
        while self.is_running:
            try:
                if is_windows:
                    import ctypes
                    EnumWindows = ctypes.windll.user32.EnumWindows
                    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
                    GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId
                    IsWindowVisible = ctypes.windll.user32.IsWindowVisible

                    GetWindowTextLengthW = ctypes.windll.user32.GetWindowTextLengthW

                    visible_pids = set()

                    def foreach_window(hwnd, lParam):
                        if IsWindowVisible(hwnd):
                            length = GetWindowTextLengthW(hwnd)
                            if length > 0:
                                pid = ctypes.c_ulong()
                                GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                                if pid.value > 0:
                                    visible_pids.add(pid.value)
                        return True

                    EnumWindows(EnumWindowsProc(foreach_window), 0)

                    import csv, io
                    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                    output = subprocess.check_output(['tasklist', '/fo', 'csv', '/nh'], creationflags=creationflags).decode('utf-8', errors='ignore')
                    reader = csv.reader(io.StringIO(output))
                    
                    running_exes = set()
                    for row in reader:
                        if len(row) > 1:
                            exe_name = row[0]
                            pid = int(row[1])
                            if pid in visible_pids:
                                running_exes.add(exe_name)
                                
                    status = {}
                    for app_id, exe_name in self.targets.items():
                        status[app_id] = (exe_name in running_exes)
                        
                    self.processes_updated.emit(status)
                else:
                    output = subprocess.check_output(['ps', '-A', '-o', 'comm'], text=True, errors='ignore')
                    status = {
                        "premiere": "Adobe Premiere Pro" in output,
                        "aftereffects": ("After Effects" in output or "AfterFX" in output),
                        "davinci": bool(re.search(r'(?:^|/|\s)Resolve(?:\.app)?(?:\s|$)', output, re.MULTILINE)),
                    }
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

    def disconnect_editor(self):
        """Desconecta el editor actual forzando a None."""
        self._on_adobe_target_changed(None)

    def force_adobe_target(self, target_app):
        """Intenta forzar el objetivo activo. Soporta Adobe y DaVinci."""
        if target_app is None:
            self.active_editor = None
            logger.info("[EditorManager] Editor activo desvinculado (None).")
            self.active_editor_changed.emit(None)
            if hasattr(self, 'adobe_service') and self.adobe_service:
                self.adobe_service.force_active_target(None)
            return True
            
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
                # Ignorar recodificaciones (generan temporales que se envían desde cada pestaña tras limpiar)
                if job.job_type == "RECODE":
                    return
                # Ignorar descargas si van a recodificarse justo después (la pestaña enviará el recodificado)
                if job.job_type in ("DOWNLOAD", "PLAYLIST"):
                    if job.request_data and job.request_data.get("recode_enabled"):
                        return
                        
                self.process_completed_job(job)

    def process_completed_job(self, job):
        """Empaqueta y envía un trabajo de cola completado al editor activo."""
        self.process_raw_download(job.final_filepath, job.request_data)

    _IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")

    @staticmethod
    def _find_sidecar_image(output_dir, base_name):
        """Miniatura de `base_name` en output_dir, en cualquier formato de imagen.
        Devuelve la ruta con separadores "/" (como la espera el panel) o None."""
        if not output_dir or not base_name:
            return None
        for ext in EditorIntegrationManager._IMAGE_EXTENSIONS:
            candidate = os.path.join(output_dir, base_name + ext)
            if os.path.exists(candidate):
                return candidate.replace(chr(92), "/")
        return None

    def _thumbnail_already_sent(self, thumb_path):
        """True si esta MISMA imagen ya viajó en un envío anterior de la misma tanda de
        fragmentos. Con cortes + recodificación, cada fragmento se envía por separado al
        terminar SU recodificación (ver los _send_to_editor_if_enabled de quick_mode y
        advanced_process) y todos comparten la única miniatura del medio (ver
        DownloaderMaster._consolidate_fragment_thumbnails), así que sin esto la misma
        imagen se importaba una vez por fragmento.

        La identidad incluye tamaño y fecha de modificación: si el usuario vuelve a
        descargar el mismo video, la miniatura se reescribe y se envía de nuevo, como
        corresponde. Solo se consulta en envíos con fragmentos, para no alterar el resto
        de flujos (herramientas de imagen/video, subtítulos, descargas normales).
        """
        try:
            stat = os.stat(thumb_path)
            key = (os.path.normcase(os.path.abspath(thumb_path)), stat.st_size, int(stat.st_mtime))
        except OSError:
            return False

        seen = getattr(self, "_sent_fragment_thumbnails", None)
        if seen is None:
            seen = self._sent_fragment_thumbnails = []
        if key in seen:
            return True
        seen.append(key)
        del seen[:-64]  # memoria acotada: solo importan los envíos recientes
        return False

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
        
        # Prefijo/sufijo que la tarjeta "Recodificar" le puso al archivo de salida (ver
        # preset_manager.build_recode_output_path: "{prefijo}{base}{sufijo}"). Hay que
        # quitarlos para volver al nombre base del medio, del que cuelgan la miniatura y
        # los subtítulos.
        recode_prefix = (request_data.get("recode_filename_prefix") or "") if request_data else ""
        recode_suffix = (request_data.get("recode_filename_suffix") or "") if request_data else ""

        def strip_recode_affixes(name):
            # '_recoded' es el sufijo por defecto histórico: se sigue quitando aunque
            # request_data no traiga los campos (ej. un envío disparado desde la cola).
            for suf in (recode_suffix, '_recoded'):
                if suf and name.endswith(suf):
                    name = name[:-len(suf)]
                    break
            if recode_prefix and name.startswith(recode_prefix):
                name = name[len(recode_prefix):]
            return name

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
            clean_base_name = strip_recode_affixes(raw_base_name)

        # Los sidecars conservan el nombre del medio ORIGINAL, sin los afijos del
        # recodificado ('clip_fragment01.jpg' junto a 'clip_fragment01_recoded.mov').
        sidecar_base_name = strip_recode_affixes(clean_base_name)

        # Cualquier extension de imagen, no solo .jpg: la miniatura conserva el formato
        # de origen cuando la baja la cola (ver QueueWorker._download_best_thumb) o
        # cuando el postprocesador de conversion de yt-dlp no llega a correr, asi que
        # buscar solo ".jpg" dejaba fuera .webp/.png y el paquete viajaba sin miniatura.
        # Candidatos de nombre para la miniatura, del mas especifico al mas general. El
        # segundo hace falta desde que una descarga con cortes deja UNA sola miniatura
        # con el nombre base (ver DownloaderMaster._consolidate_fragment_thumbnails): un
        # fragmento recodificado ('clip_fragment01_recoded.mov') ya no tiene la suya
        # propia y debe caer a la del medio completo ('clip.jpg').
        thumb_base_candidates = [sidecar_base_name]
        for i, frag in enumerate(selected_fragments):
            frag_suffix = frag[2] if len(frag) > 2 else f"fragment{i+1:02d}"
            if sidecar_base_name.endswith(f"_{frag_suffix}"):
                thumb_base_candidates.append(sidecar_base_name[: -len(frag_suffix) - 1])

        expected_thumb_path = None
        for candidate_base in thumb_base_candidates:
            expected_thumb_path = self._find_sidecar_image(output_dir, candidate_base)
            if expected_thumb_path:
                break
            
        file_packages = []
        # Salvo un caso (ver is_plain_fragment_file), si no se pudo armar el lote de
        # fragmentos se empaqueta el archivo recibido tal cual.
        allow_single_fallback = True
        
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
                        frag_thumb_path = self._find_sidecar_image(output_dir, frag_base)
                        if not frag_thumb_path:
                            frag_thumb_path = expected_thumb_path  # respaldo: la del nombre base
                                
                        file_packages.append({
                            "video": vid_path,
                            "thumbnail": frag_thumb_path,
                            "subtitle": sub_path
                        })
            except Exception as e:
                logger.error(f"Error empaquetando fragmentos: {e}")

            # Con cortes, esta función se llama UNA VEZ POR FRAGMENTO y solo la
            # llamada del ÚLTIMO logra reconstruir el lote completo (clean_base_name
            # solo sabe quitar el sufijo del último fragmento); las demás salen sin
            # paquetes a propósito, para no mandar el lote una vez por fragmento. Por
            # eso el fallback de abajo NO debe dispararse cuando el archivo recibido es
            # un fragmento tal cual salió de la descarga: llegaría suelto y otra vez
            # dentro del lote. Solo se usa cuando el nombre ya no es reconstruible
            # (recodificado), que es justo el caso que no enviaba nada.
            is_plain_fragment_file = any(
                raw_base_name.endswith(f"_{frag[2] if len(frag) > 2 else f'fragment{i+1:02d}'}")
                for i, frag in enumerate(selected_fragments)
            )

            allow_single_fallback = not is_plain_fragment_file
            if not file_packages and allow_single_fallback:
                # La reconstrucción "{base}_{sufijo}{ext}" no encontró ningún archivo.
                # Pasa siempre que la descarga con cortes se recodificó: cada fragmento
                # queda como "clip_fragment01_recoded.mov" y se envía por separado al
                # terminar SU recodificación (ver los _send_to_editor_if_enabled de
                # advanced_process y quick_mode), así que ni el nombre reconstruido
                # existe ni tendría sentido rearmar el lote entero — los demás
                # fragmentos todavía se están recodificando y llegarían duplicados.
                # Sin esto, la función salía en silencio por "if not file_packages:
                # return" y NADA llegaba al editor con cortes + recodificación, en
                # Modo Rápido y en Proceso Avanzado, con cualquier editor.
                logger.info(
                    "[EditorManager] Corte sin nombres reconstruibles (recodificado): "
                    f"se envía el archivo recibido tal cual ({os.path.basename(final_filepath)})."
                )

        if not file_packages and allow_single_fallback:
            # Archivo único normal (o el fragmento suelto del fallback de arriba)
            vid_path = final_filepath.replace('\\', '/') if os.path.exists(final_filepath) else None
            sub_path = None
            try:
                for s in os.listdir(output_dir):
                    if s.startswith(sidecar_base_name) and s.lower().endswith('.srt'):
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

        if is_fragmented:
            # Todos los fragmentos comparten una sola miniatura, así que solo el primer
            # paquete la lleva. Dentro de un mismo lote el panel de Adobe ya deduplica
            # (importBatchToProject arma un Set), pero DaVinci importa cada ruta que
            # recibe, y entre envíos sucesivos (fragmentos recodificados, que salen de
            # uno en uno) no deduplica nadie.
            for pkg in file_packages:
                thumb = pkg.get("thumbnail")
                if thumb and self._thumbnail_already_sent(thumb):
                    pkg["thumbnail"] = None

        if len(file_packages) == 1:
            logger.info(f"[EditorManager] Paquete listo para enviar: {file_packages[0]}")
            self.send_file(file_packages[0])
        else:
            # Se listan los paquetes igual que en el envío individual: sin esto, un lote
            # que sale de la app pero no aparece en el editor no dejaba forma de saber
            # desde el log si el problema era lo que se mandó o lo que hizo el panel.
            logger.info(f"[EditorManager] Lote de {len(file_packages)} archivos (fragmentos) listos para enviar: {file_packages}")
            self.send_batch(file_packages)
