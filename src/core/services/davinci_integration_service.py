import os
import sys
import platform
import re
import time
from PySide6.QtCore import QObject
from core.logger.logger_manager import logger
from core.utils.config_manager import get_config

class DaVinciIntegrationService(QObject):
    """
    Servicio para interactuar con DaVinci Resolve a través de su API de Python.
    Permite importar archivos al Media Pool, crear carpetas y agregar a la línea de tiempo.
    """
    _instance = None
    
    def __init__(self):
        super().__init__()
        self.resolve = None
        DaVinciIntegrationService._instance = self

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = DaVinciIntegrationService()
        return cls._instance

    def _get_short_path(self, long_name):
        """Obtiene la ruta corta (8.3) de Windows para evitar problemas con caracteres especiales."""
        if platform.system() != "Windows":
            return long_name
        try:
            import ctypes
            from ctypes import wintypes
            _GetShortPathNameW = ctypes.windll.kernel32.GetShortPathNameW
            _GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
            _GetShortPathNameW.restype = wintypes.DWORD
            output_buf_size = 260
            output_buf = ctypes.create_unicode_buffer(output_buf_size)
            result = _GetShortPathNameW(long_name, output_buf, output_buf_size)
            if result > 0 and result <= output_buf_size:
                return output_buf.value
        except Exception:
            pass
        return long_name

    def _preparar_entorno(self):
        """Configura las variables de entorno necesarias, especialmente para PyInstaller."""
        if platform.system() != "Windows":
            return
            
        base_api = r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting"
        ruta_modulos = os.path.join(base_api, "Modules")
        if os.path.exists(ruta_modulos) and ruta_modulos not in sys.path:
            sys.path.append(ruta_modulos)
            
        os.environ['RESOLVE_SCRIPT_API'] = base_api
        
        # Buscar dinámicamente fusionscript.dll en la carpeta de instalación
        config = get_config()
        integrations = config.get('integrations', {})
        davinci_exe = integrations.get('davinci_path', r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe")
        
        davinci_dir = os.path.dirname(davinci_exe)
        fusionscript_path = os.path.join(davinci_dir, "fusionscript.dll")
        
        if not os.path.exists(fusionscript_path):
            # Fallback a la ruta por defecto
            fusionscript_path = r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
            
        os.environ['RESOLVE_SCRIPT_LIB'] = fusionscript_path
        
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
            internal_dir = os.path.join(exe_dir, '_internal')
            if not os.path.exists(internal_dir):
                internal_dir = exe_dir
            os.environ['PYTHONHOME'] = internal_dir
            os.environ['RESOLVE_PYTHON3_BIN'] = sys.executable
            paths = [ruta_modulos, internal_dir]
            for sub in ['lib', 'lib-dynload', 'site-packages']:
                p = os.path.join(internal_dir, sub)
                if os.path.exists(p):
                    paths.append(p)
            os.environ['PYTHONPATH'] = os.pathsep.join(paths)
            if internal_dir not in os.environ.get('PATH', ''):
                os.environ['PATH'] = internal_dir + os.pathsep + os.environ.get('PATH', '')
        else:
            if 'PYTHONPATH' not in os.environ:
                os.environ['PYTHONPATH'] = ruta_modulos
            elif ruta_modulos not in os.environ['PYTHONPATH']:
                os.environ['PYTHONPATH'] += os.pathsep + ruta_modulos

    def _get_resolve(self):
        """Intenta obtener o reconectar la instancia de DaVinci Resolve."""
        if self.resolve:
            try:
                self.resolve.GetProductName()
                return self.resolve
            except Exception:
                self.resolve = None
                
        self._preparar_entorno()
        
        try:
            import imp
            api_path = ""
            if platform.system() == "Windows":
                api_path = os.path.expandvars(r"%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules\DaVinciResolveScript.py")
            elif platform.system() == "Darwin":
                api_path = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/DaVinciResolveScript.py"
            
            if os.path.exists(api_path):
                dvr_script = imp.load_source('DaVinciResolveScript', api_path)
                self.resolve = dvr_script.scriptapp("Resolve")
            else:
                import DaVinciResolveScript as dvr_script
                self.resolve = dvr_script.scriptapp("Resolve")
                
            return self.resolve
        except Exception as e:
            logger.error(f"[DaVinci] Error conectando a Resolve: {e}")
            return None

    def _get_or_create_folder(self, media_pool, parent_folder, name):
        """Busca o crea una subcarpeta en el Media Pool de forma robusta."""
        if not parent_folder:
            return None
        subfolders = parent_folder.GetSubFolderList()
        # En Python 3 puede devolver dict o list
        if isinstance(subfolders, dict):
            for folder in subfolders.values():
                if folder.GetName() == name:
                    return folder
        elif isinstance(subfolders, list):
            for folder in subfolders:
                if folder.GetName() == name:
                    return folder
        try:
            return media_pool.AddSubFolder(parent_folder, name)
        except Exception:
            return None
        
    def _timecode_to_frames(self, timecode, framerate):
        """Convierte un código de tiempo (HH:MM:SS:FF) a fotogramas absolutos."""
        try:
            parts = re.split(r'[:;]', timecode)
            if len(parts) == 4:
                hh, mm, ss, ff = [int(p) for p in parts]
                fps = float(framerate)
                total_seconds = hh * 3600 + mm * 60 + ss
                return int(total_seconds * fps) + ff
        except Exception as e:
            pass
        return 0

    def _pista_esta_libre(self, timeline, track_type, index, start_frame, end_frame):
        """Verifica si hay espacio en una pista específica para un rango de frames."""
        items = timeline.GetItemListInTrack(track_type, index)
        if not items:
            return True
        for item in items:
            i_start = item.GetStart()
            i_end = item.GetEnd()
            if not (end_frame <= i_start or start_frame >= i_end):
                return False
        return True

    def _organize_clip_in_folders(self, media_pool, clip_item, file_path):
        """Organiza un clip recién importado en la estructura de carpetas de DowP Imports."""
        config = get_config()
        create_folders = config.get('integrations', {}).get('davinci_create_folders', True)
        
        ext = os.path.splitext(file_path)[1].lower()
        ext_map = {
            "Video": [".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"],
            "Imágenes": [".jpg", ".jpeg", ".png", ".gif", ".tiff", ".webp", ".bmp", ".svg"],
            "Audio": [".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus"]
        }
        
        folder_type = "Otros"
        for category, extensions in ext_map.items():
            if ext in extensions:
                folder_type = category
                break
                
        if folder_type == "Video":
            try:
                props = clip_item.GetClipProperty()
                v_codec = props.get("Video Codec", "") if isinstance(props, dict) else clip_item.GetClipProperty("Video Codec")
                v_res = props.get("Resolution", "") if isinstance(props, dict) else clip_item.GetClipProperty("Resolution")
                if (not v_codec or v_codec == "N/A" or v_codec == "") and (not v_res or v_res == ""):
                    folder_type = "Audio"
            except Exception:
                pass
                
        if create_folders:
            target_root = media_pool.GetRootFolder()
            main_folder = self._get_or_create_folder(media_pool, target_root, "DowP Imports")
            target_folder = self._get_or_create_folder(media_pool, main_folder, folder_type)
            if target_folder:
                media_pool.MoveClips([clip_item], target_folder)
                
        return folder_type

    def send_files_to_davinci(self, file_packages):
        """Envía un lote de archivos a DaVinci Resolve."""
        resolve = self._get_resolve()
        if not resolve:
            logger.warning("[DaVinci] DaVinci Resolve no está conectado.")
            return False

        project_manager = resolve.GetProjectManager()
        project = project_manager.GetCurrentProject()
        if not project:
            logger.warning("[DaVinci] No hay proyecto abierto.")
            return False
            
        media_pool = project.GetMediaPool()
        timeline = project.GetCurrentTimeline()
        
        config = get_config()
        integrations = config.get('integrations', {})
        import_timeline = integrations.get('davinci_import_timeline', True)
        import_images = integrations.get('davinci_import_images_timeline', False)
        create_folders = integrations.get('davinci_create_folders', True)
        
        target_root = media_pool.GetRootFolder()
        main_folder = target_root
        if create_folders:
            main_folder = self._get_or_create_folder(media_pool, target_root, "DowP Imports")
            media_pool.SetCurrentFolder(target_root)
        
        ext_map = {
            "Video": [".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"],
            "Imágenes": [".jpg", ".jpeg", ".png", ".gif", ".tiff", ".webp", ".bmp", ".svg"],
            "Audio": [".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus"]
        }
        
        success = True
        
        # Aplanar los diccionarios de paquetes de descarga
        flat_paths = []
        for pkg in file_packages:
            if isinstance(pkg, dict):
                if "subclips" in pkg:
                    self.send_subclips_to_davinci(pkg)
                    continue
                for key, val in pkg.items():
                    if val and isinstance(val, str) and os.path.exists(val):
                        if key == 'subtitle':
                            continue # Evitar importar subtítulos al media pool
                        flat_paths.append(val)
            elif isinstance(pkg, str) and os.path.exists(pkg):
                flat_paths.append(pkg)
                
        for path in flat_paths:
            abs_path = os.path.abspath(path)
            
            # Intento 1: Ruta normal
            clips_pool = media_pool.ImportMedia([abs_path])
            if not clips_pool:
                # Intento 2: Ruta corta 8.3
                short_path = self._get_short_path(abs_path)
                if short_path != abs_path:
                    clips_pool = media_pool.ImportMedia([short_path])
            
            if not clips_pool:
                logger.error(f"[DaVinci] Falló importación de {path}")
                success = False
                continue
                
            clip_item = clips_pool[0]
            
            folder_type = self._organize_clip_in_folders(media_pool, clip_item, abs_path)
            
            has_video = folder_type in ("Video", "Imágenes")
            has_audio = folder_type in ("Video", "Audio")
            
            if import_timeline and timeline:
                if folder_type == "Imágenes" and not import_images:
                    continue
                    
                tc_string = timeline.GetCurrentTimecode()
                fps = float(project.GetSetting("timelineFrameRate"))
                start_frame = self._timecode_to_frames(tc_string, fps)
                
                try:
                    start_p = float(clip_item.GetClipProperty("Start"))
                    end_p = float(clip_item.GetClipProperty("End"))
                    duracion = end_p - start_p
                except Exception:
                    duracion = 0
                    
                end_frame = start_frame + duracion
                pista_final = None
                
                num_v_tracks = timeline.GetTrackCount("video")
                num_a_tracks = timeline.GetTrackCount("audio")
                max_pistas = max(num_v_tracks, num_a_tracks)
                
                # Buscar primera pista libre
                for i in range(1, max_pistas + 2):
                    video_ok = True
                    if has_video and i <= num_v_tracks:
                        video_ok = self._pista_esta_libre(timeline, "video", i, start_frame, end_frame)
                        
                    audio_ok = True
                    if has_audio and i <= num_a_tracks:
                        audio_ok = self._pista_esta_libre(timeline, "audio", i, start_frame, end_frame)
                        
                    if video_ok and audio_ok:
                        pista_final = i
                        break
                        
                # Crear pistas si no existen
                while timeline.GetTrackCount("video") < pista_final:
                    timeline.AddTrack("video")
                while timeline.GetTrackCount("audio") < (pista_final if has_audio else 0):
                    timeline.AddTrack("audio", "stereo")
                    
                clip_info = {
                    "mediaPoolItem": clip_item,
                    "trackIndex": int(pista_final),
                    "recordFrame": float(start_frame),
                    "mediaType": 0
                }
                
                if media_pool.AppendToTimeline([clip_info]):
                    logger.info(f"[DaVinci] Insertado en línea de tiempo: {path}")
                else:
                    logger.warning(f"[DaVinci] Falló inserción en línea de tiempo (recordFrame). Usando fallback.")
                    media_pool.AppendToTimeline([clip_item])
                    
        return success

    def send_subclips_to_davinci(self, payload):
        """
        Importa el medio original en DaVinci Resolve y recorta/inserta los subclips con puntos In/Out.
        payload: {"filePath": str, "subclips": [{"name": str, "in": float, "out": float}]}
        """
        file_path = payload.get("filePath")
        subclips = payload.get("subclips", [])
        if not file_path or not os.path.exists(file_path) or not subclips:
            return False
            
        resolve = self._get_resolve()
        if not resolve:
            logger.error("[DaVinci] No hay conexión activa con Resolve para enviar subclips.")
            return False

        pm = resolve.GetProjectManager()
        project = pm.GetCurrentProject() if pm else None
        if not project:
            return False
            
        media_pool = project.GetMediaPool()
        if not media_pool:
            return False

        abs_path = os.path.abspath(file_path)
        clips_pool = media_pool.ImportMedia([abs_path])
        if not clips_pool:
            short_path = self._get_short_path(abs_path)
            clips_pool = media_pool.ImportMedia([short_path])
            
        if not clips_pool:
            logger.error(f"[DaVinci] Error importando medio base para subclips: {file_path}")
            return False

        clip_item = clips_pool[0]
        self._organize_clip_in_folders(media_pool, clip_item, abs_path)

        fps = float(project.GetSetting("timelineFrameRate") or 24.0)
        
        timeline = project.GetCurrentTimeline()
        
        config = get_config()
        integrations = config.get('integrations', {})
        import_timeline = integrations.get('davinci_import_timeline', True)
        
        current_record_frame = 0
        if timeline and import_timeline:
            tc_string = timeline.GetCurrentTimecode()
            current_record_frame = self._timecode_to_frames(tc_string, fps)
        
        for sc in subclips:
            in_sec = sc.get("in", 0.0)
            out_sec = sc.get("out", 0.0)
            name = sc.get("name", "Subclip")
            
            start_f = int(in_sec * fps)
            end_f = int(out_sec * fps)
            
            try:
                clip_item.SetClipProperty("In", str(start_f))
                clip_item.SetClipProperty("Out", str(end_f))
            except Exception: pass
            
            if timeline and import_timeline:
                clip_info = {
                    "mediaPoolItem": clip_item,
                    "startFrame": start_f,
                    "endFrame": end_f,
                    "recordFrame": float(current_record_frame)
                }
                try:
                    if media_pool.AppendToTimeline([clip_info]):
                        current_record_frame += (end_f - start_f)
                    else:
                        media_pool.AppendToTimeline([clip_item])
                    logger.info(f"[DaVinci] Subclip '{name}' ({in_sec:.2f}s - {out_sec:.2f}s) insertado en timeline.")
                except Exception as e:
                    logger.error(f"[DaVinci] Error insertando subclip en timeline: {e}")
                    
        return True
