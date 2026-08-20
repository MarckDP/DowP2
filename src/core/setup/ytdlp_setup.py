# src/core/setup/ytdlp_setup.py
import os
import requests
from core.logger.logger_manager import logger

YTDLP_URL = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
FILENAME = "yt-dlp.zip"

def get_ytdlp_dir():
    """Returns the directory path for yt-dlp."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    ytdlp_dir = os.path.join(base_dir, "bin", "dependences", "ytdlp")
    if not os.path.exists(ytdlp_dir):
        logger.info(f"Creating directory: {ytdlp_dir}")
        os.makedirs(ytdlp_dir)
    return ytdlp_dir

def get_ytdlp_path():
    """Returns the full path of the yt-dlp.zip file."""
    return os.path.join(get_ytdlp_dir(), FILENAME)

_ytdlp_checked = False

def check_ytdlp():
    """Verifies if yt-dlp.zip exists."""
    global _ytdlp_checked
    exists = os.path.exists(get_ytdlp_path())
    if not _ytdlp_checked:
        logger.debug(f"Checking yt-dlp.zip existence: {exists}")
        _ytdlp_checked = True
    return exists

def download_ytdlp(progress_callback=None):
    """Downloads the latest version of yt-dlp and cleans shebang."""
    try:
        logger.info(f"Fetching latest release info from {YTDLP_URL}")
        response = requests.get(YTDLP_URL)
        response.raise_for_status()
        data = response.json()
        
        download_url = None
        for asset in data.get("assets", []):
            if asset["name"] == "yt-dlp": # ZipApp asset (no extension)
                download_url = asset["browser_download_url"]
                break
        
        if not download_url:
            # Fallback to .pyz if 'yt-dlp' asset is missing
            for asset in data.get("assets", []):
                if asset["name"] == "yt-dlp.pyz":
                    download_url = asset["browser_download_url"]
                    break

        if not download_url:
            logger.error("yt-dlp asset not found in latest release")
            return False, "yt-dlp asset not found."

        target_path = get_ytdlp_path()
        logger.info(f"Downloading yt-dlp from {download_url}")
        r = requests.get(download_url, stream=True)
        r.raise_for_status()
        
        total_size = int(r.headers.get('content-length', 0))
        downloaded = 0
        
        with open(target_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total_size > 0:
                        percent = int((downloaded / total_size) * 100)
                        progress_callback(percent)
                
        # Limpieza de shebang (Lógica DowP Viejo)
        try:
            with open(target_path, "rb") as f:
                content = f.read()
            start_idx = content.find(b"PK\x03\x04")
            if start_idx > 0:
                with open(target_path, "wb") as f:
                    f.write(content[start_idx:])
                logger.info("Shebang de yt-dlp limpiado (convertido a ZIP puro).")
        except Exception as e:
            logger.error(f"No se pudo limpiar el shebang: {e}")
        
        logger.info(f"yt-dlp.zip listo en {target_path}")
        return True, "yt-dlp descargado y procesado correctamente."
    except Exception as e:
        logger.error(f"Error downloading yt-dlp: {e}")
        return False, str(e)

import sys
from core.utils.config_manager import get_config, save_config

def get_local_version(force_check=False):
    """
    Lee la versión de yt-dlp importándolo en el mismo proceso (via sys.path
    sobre el .zip), cacheándola en config.json para evitar reimportar.

    No usa subprocess.run([sys.executable, ...]) — eso asume que
    sys.executable es un intérprete genérico capaz de ejecutar un script
    pasado como argumento, cierto en modo fuente (python.exe) pero falso en
    el .exe compilado, donde sys.executable es el propio DowP.exe: esa
    llamada terminaba lanzando una segunda instancia completa de la app en
    vez de imprimir la versión.
    """
    if not check_ytdlp():
        return None

    config = get_config()
    versions = config.get("dependency_versions", {})
    if not force_check and "ytdlp" in versions:
        return versions["ytdlp"]

    try:
        ytdlp_path = get_ytdlp_path()
        if ytdlp_path not in sys.path:
            if 'yt_dlp' in sys.modules:
                for mod in list(sys.modules.keys()):
                    if mod.startswith('yt_dlp'):
                        del sys.modules[mod]
            sys.path.insert(0, ytdlp_path)

        import yt_dlp
        version = yt_dlp.version.__version__

        # Save to config
        versions["ytdlp"] = version
        config["dependency_versions"] = versions
        save_config(config)

        return version
    except Exception as e:
        logger.error(f"Error getting local yt-dlp version: {e}")
        return None

def get_latest_remote_version():
    """Fetches the latest version string from GitHub API."""
    try:
        response = requests.get(YTDLP_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("tag_name", "").lstrip("v")
    except Exception as e:
        logger.error(f"Error getting remote yt-dlp version: {e}")
        return None

if __name__ == "__main__":
    if not check_ytdlp():
        download_ytdlp()

