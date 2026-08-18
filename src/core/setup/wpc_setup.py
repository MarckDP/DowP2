# src/core/setup/wpc_setup.py
"""
Módulo de configuración para yt-dlp-getpot-wpc (WebPoClient PO Token Provider).

WPC instala como paquete Python en el .venv y usa nodriver para controlar un
navegador Chromium (Chrome, Brave, Edge, Chromium) real que genera los PO Tokens.
No tiene binarios propios — depende de que el usuario tenga un navegador instalado.

Extractor arg en yt-dlp (cuando WPC está activo):
    ydl_opts['extractor_args']['youtubepot-wpc'] = {'browser_path': ['/path/to/browser']}
"""
import os
import sys
import json
import subprocess
import shutil
import platform
from core.logger.logger_manager import logger

PACKAGE_NAME = "yt-dlp-getpot-wpc"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"

# Versión cacheada en memoria
_cached_local_version = None


# ─── Detección ────────────────────────────────────────────────────────────────

def _get_python_executable():
    """Devuelve el ejecutable de Python del venv actual."""
    return sys.executable


def check_wpc() -> bool:
    """Verifica si yt-dlp-getpot-wpc está instalado en el venv actual."""
    try:
        import importlib
        import importlib.util
        importlib.invalidate_caches()
        spec = importlib.util.find_spec("yt_dlp_plugins.extractor.getpot_wpc")
        if spec is not None:
            return True
    except Exception:
        pass
    return get_local_version() is not None


def get_local_version(force_check: bool = False) -> str | None:
    """Devuelve la versión instalada del paquete, o None si no está instalado."""
    global _cached_local_version
    if _cached_local_version and not force_check:
        return _cached_local_version

    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        result = subprocess.run(
            [_get_python_executable(), "-m", "pip", "show", PACKAGE_NAME],
            capture_output=True, text=True, timeout=10, creationflags=flags
        )
        for line in result.stdout.splitlines():
            if line.startswith("Version:"):
                _cached_local_version = line.split(":", 1)[1].strip()
                return _cached_local_version
    except Exception as e:
        logger.debug(f"WPC: Error obteniendo versión local: {e}")
    return None


def get_latest_remote_version() -> str | None:
    """Consulta PyPI para obtener la última versión disponible de WPC."""
    try:
        import urllib.request
        with urllib.request.urlopen(PYPI_URL, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data["info"]["version"]
    except Exception as e:
        logger.debug(f"WPC: Error obteniendo versión remota de PyPI: {e}")
        return None


# ─── Instalación ──────────────────────────────────────────────────────────────

def install_wpc(progress_callback=None) -> tuple:
    """
    Instala / actualiza yt-dlp-getpot-wpc via pip en el venv actual.
    Devuelve (success: bool, message: str).
    """
    global _cached_local_version
    _cached_local_version = None  # Invalidar caché

    python_exe = _get_python_executable()
    logger.info(f"WPC: Instalando {PACKAGE_NAME} con {python_exe}...")

    if progress_callback:
        progress_callback(10)

    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        result = subprocess.run(
            [python_exe, "-m", "pip", "install", "--upgrade", PACKAGE_NAME],
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=flags
        )

        if progress_callback:
            progress_callback(90)

        if result.returncode == 0:
            version = get_local_version(force_check=True)
            msg = f"WPC instalado correctamente: v{version}" if version else "WPC instalado correctamente"
            logger.info(f"WPC: {msg}")
            if progress_callback:
                progress_callback(100)
            return True, msg
        else:
            err = result.stderr.strip() or result.stdout.strip()
            logger.error(f"WPC: Fallo en pip install: {err}")
            return False, f"Error instalando WPC: {err[:300]}"

    except subprocess.TimeoutExpired:
        return False, "Timeout instalando WPC (>120s)"
    except Exception as e:
        logger.error(f"WPC: Excepción instalando: {e}")
        return False, str(e)


# ─── Navegador ────────────────────────────────────────────────────────────────

def _build_search_paths():
    """Construye las rutas de búsqueda según el SO actual."""
    return {
        "Windows": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Chromium\Application\chrome.exe",
        ],
        "Darwin": [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ],
        "Linux": [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/usr/bin/brave-browser",
            "/usr/bin/microsoft-edge",
            "/snap/bin/chromium",
        ]
    }


_NAME_MAP = {
    "chrome": "Google Chrome",
    "brave": "Brave",
    "msedge": "Microsoft Edge",
    "chromium": "Chromium",
    "edge": "Microsoft Edge",
}


def detect_system_browser():
    """
    Auto-detecta el primer navegador Chromium disponible en el sistema.
    Devuelve (path, nombre_amigable) o (None, None) si no se encuentra.
    """
    plat = platform.system()
    search_paths = _build_search_paths()
    paths = search_paths.get(plat, [])

    for path in paths:
        if path and os.path.isfile(path):
            exe_lower = os.path.basename(path).lower()
            name = next((v for k, v in _NAME_MAP.items() if k in exe_lower), "Chromium")
            logger.debug(f"WPC: Navegador detectado → {name} ({path})")
            return path, name

    # Fallback: buscar en PATH del sistema
    for cmd in ("google-chrome", "chromium", "chromium-browser", "brave-browser", "microsoft-edge"):
        found = shutil.which(cmd)
        if found:
            name = next((v for k, v in _NAME_MAP.items() if k in cmd), "Chromium")
            logger.debug(f"WPC: Navegador en PATH → {name} ({found})")
            return found, name

    return None, None


def get_browser_path() -> str:
    """
    Devuelve la ruta del navegador a usar con WPC.
    Prioridad: config.json → auto-detect → '' (vacío = nodriver decide)
    """
    from core.utils.config_manager import get_config
    configured = get_config().get("pot_wpc_browser_path", "").strip()
    if configured and os.path.isfile(configured):
        return configured
    path, _ = detect_system_browser()
    return path or ""


def get_browser_display_name() -> str:
    """Devuelve el nombre amigable del navegador que se usaría con WPC."""
    from core.utils.config_manager import get_config
    configured = get_config().get("pot_wpc_browser_path", "").strip()
    if configured and os.path.isfile(configured):
        exe = os.path.basename(configured).lower()
        return next((v for k, v in _NAME_MAP.items() if k in exe), os.path.basename(configured))
    _, name = detect_system_browser()
    return name or "No detectado"
