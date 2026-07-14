import json
import os
import sys
import traceback
import re
from core.logger.logger_manager import logger
from core.utils.config_manager import get_config
from core.setup.ytdlp_setup import get_ytdlp_path
from core.setup.setup_manager import get_dependency_env

def strip_ansi_codes(text):
    """Elimina códigos de color ANSI como [0;31m del texto."""
    if not text:
        return ""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

import time

class YTDLLogger:
    """Redirige los logs de yt-dlp al logger de DowP con limitador de velocidad."""
    def __init__(self, progress_callback=None):
        self._last_download_log = 0
        self.progress_callback = progress_callback
        self.errors = []

    def _process_message(self, msg):
        if self.progress_callback:
            try:
                clean_msg = strip_ansi_codes(msg)
                if "Downloading item" in clean_msg or "Downloading video" in clean_msg:
                    match = re.search(r'(?:item|video)\s+(\d+)\s+of\s+(\d+)', clean_msg, re.IGNORECASE)
                    if match:
                        current = int(match.group(1))
                        total = int(match.group(2))
                        self.progress_callback(current, total)
            except Exception:
                pass

    def debug(self, msg):
        self._process_message(msg)
        # Filtrar mensajes de progreso de descarga (muy ruidosos)
        if "[download]" in msg:
            current_time = time.time()
            if current_time - self._last_download_log < 0.33:
                return
            self._last_download_log = current_time
            
        logger.debug(f"[yt-dlp] {msg}")

    def info(self, msg):
        self._process_message(msg)
        logger.info(f"[yt-dlp] {msg}")

    def warning(self, msg):
        logger.warning(f"[yt-dlp] {msg}")

    def error(self, msg):
        logger.error(f"[yt-dlp] {msg}")
        self.errors.append(msg)

def get_base_ydl_opts(extra_opts=None):
    """
    Genera el diccionario de opciones base (cookies, impersonate, deno, etc.)
    que deben compartir tanto el analizador como el descargador.
    """
    config = get_config()
    
    from core.setup.ffmpeg_setup import get_ffmpeg_dir
    ffmpeg_dir = get_ffmpeg_dir()
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'timeout': 30,
        'logger': YTDLLogger(),
        'ffmpeg_location': ffmpeg_dir,
    }

    if extra_opts:
        ydl_opts.update(extra_opts)

    # --- LÓGICA DE COOKIES ---
    mode = config.get("cookies_mode", "none")
    use_cookies = False

    if mode == "file":
        file_path = config.get("cookies_file", "")
        if file_path and os.path.exists(file_path):
            ydl_opts['cookiefile'] = file_path
            use_cookies = True
            logger.info(f"Analyzer: Usando archivo de cookies: {file_path}")
    elif mode == "browser":
        browser = config.get("cookies_browser", "")
        if browser:
            profile = config.get("cookies_profile", "")
            spec = f"{browser}:{profile}" if profile else browser
            ydl_opts['cookiesfrombrowser'] = (spec,)
            use_cookies = True
            logger.info(f"Analyzer: Usando cookies del navegador: {browser}")

    # --- PARCHE DE IMPERSONATE ---
    from .utils import get_impersonate_target
    if config.get("use_impersonate", False):
        target = get_impersonate_target("chrome")
        if target:
            ydl_opts['impersonate'] = target

    # --- PARCHES ESPECÍFICOS Y JS RUNTIMES ---
    # El DowP 1.0 aplicaba apply_yt_patch() SIEMPRE para YouTube,
    # no solo con cookies. Replicamos ese comportamiento.
    env = get_dependency_env()
    deno_dir = next((p for p in env.get('PATH', '').split(os.pathsep) if 'deno' in p.lower()), '')
    deno_path = os.path.join(deno_dir, 'deno.exe') if deno_dir else 'deno'
    
    ydl_opts['js_runtimes'] = {'deno': {'path': deno_path}}
    ydl_opts['remote_components'] = ['ejs:github']
    ydl_opts['extractor_args'] = {
        'youtube': {
            'player_client': ['web_safari', 'android', 'web', 'tv'],
            'n_client': ['web_safari', 'android', 'tv'],
            'skip': []
        }
    }
        
    return ydl_opts

def get_video_info(url, extra_opts=None, progress_callback=None):
    """
    Análisis de video usando la lógica del DowP viejo (ZIP + API Nativa) 
    y respetando estrictamente los ajustes del usuario.
    """
    ytdlp_path = get_ytdlp_path()
    
    if not os.path.exists(ytdlp_path):
        logger.error(f"yt-dlp not found at {ytdlp_path}")
        return None, "yt-dlp binary not found."

    # Solo recargar módulos si el path del ZIP cambió (evita reimportación innecesaria)
    if ytdlp_path not in sys.path:
        # Path nuevo: purgar módulos viejos y añadir el nuevo
        if 'yt_dlp' in sys.modules:
            for mod in list(sys.modules.keys()):
                if mod.startswith('yt_dlp'):
                    del sys.modules[mod]
        sys.path.insert(0, ytdlp_path)

    try:
        import yt_dlp
    except ImportError:
        logger.error("Failed to import yt_dlp from zip")
        return None, "Error: yt-dlp could not be imported."

    ydl_opts = get_base_ydl_opts(extra_opts)
    if progress_callback:
        ydl_opts['logger'] = YTDLLogger(progress_callback)
    ydl_opts['skip_download'] = True

    # Inyectar entorno (PATH) para dependencias internas
    env = get_dependency_env()
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = env["PATH"]

    try:
        logger.info(f"Analyzing URL: {url}")
        logger.debug(f"Analyzer: ydl_opts finales: { {k:v for k,v in ydl_opts.items() if k != 'logger'} }")
        
        # Guardar referencia al logger para extraer errores
        yt_logger = ydl_opts.get('logger')
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.info("Analyzer: Instancia de YoutubeDL creada exitosamente. Iniciando extracción...")
            info_dict = ydl.extract_info(url, download=False)
            logger.info("Analyzer: Extracción completada.")
            
        if info_dict is None:
            err_msg = ""
            if yt_logger and hasattr(yt_logger, "errors") and yt_logger.errors:
                err_msg = "\n".join(yt_logger.errors)
            return None, strip_ansi_codes(err_msg) or "No se pudo obtener información de la URL."
            
        return info_dict, None
        
    except Exception as e:
        err_detail = traceback.format_exc()
        logger.error(f"Unexpected error in analyzer: {err_detail}")
        return None, strip_ansi_codes(str(e)) or "Error desconocido durante el análisis."
        
    finally:
        os.environ["PATH"] = old_path
