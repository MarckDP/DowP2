# src/core/utils/paths.py
import os
import sys
import shutil
import platform
from core.logger.logger_manager import logger


def get_src_dir() -> str:
    """
    Devuelve el equivalente de '<repo_root>/src' tanto en modo fuente como en
    el .exe compilado (--onedir). Es el ancla correcta para cualquier ruta a
    assets, iconos, temas, etc.

    No usar conteos de os.path.dirname(__file__) para esto: el número de
    niveles a subir depende de dónde vive cada módulo bajo src/, y en el .exe
    congelado PyInstaller aplana los paquetes fuera del árbol 'src'
    (_internal/gui/... en vez de _internal/src/gui/...), así que ese cálculo
    da un resultado distinto — y roto — según el módulo.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, "src")
    # Este archivo vive en <repo_root>/src/core/utils/paths.py
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def get_bin_root_dir() -> str:
    """Carpeta que contiene bin/ (dependencias gestionadas -- ffmpeg/ghostscript/
    deno/yt-dlp/WPC -- y modelos de IA descargados): junto al .exe/.app en modo
    congelado, NO adentro de _internal/, o la raíz del repo en modo fuente.

    A propósito NO reutiliza sys._MEIPASS (eso es lo que usa get_src_dir(), y
    está bien ahí): en un --onedir moderno de PyInstaller (desde que separó
    --contents-directory en la 6.0), _MEIPASS apunta a _internal/ -- el árbol
    interno reemplazable del bundle, correcto para assets read-only (iconos,
    temas, .qm) pero NO para datos que el usuario descarga (pueden pesar varios
    GB) y espera encontrar junto al ejecutable, sobreviviendo a una reinstalación
    que pise _internal/ entero. sys.executable sigue apuntando al .exe/.app, un
    nivel arriba de _internal/ -- confirmado simulando el modo congelado contra
    un build real de este repo (dist/DowP)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(get_src_dir())


def get_app_data_dir() -> str:
    r"""
    Retorna la ruta absoluta del directorio AppData del sistema para DowP2.
    - Windows: %APPDATA%/DowP2 (ej. C:\Users\<user>\AppData\Roaming\DowP2)
    - macOS: ~/Library/Application Support/DowP2
    - Linux/Otros: ~/.config/DowP2
    """
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
    elif system == "Darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    
    app_dir = os.path.join(base, "DowP2")
    os.makedirs(app_dir, exist_ok=True)
    return app_dir

def get_models_dir() -> str:
    """Retorna bin/models (junto a bin/dependences), donde se instalan los modelos de
    IA (rembg, motores de upscaling). A diferencia de las dependencias, los modelos
    NUNCA se descargan solos al abrir la app -- solo cuando el usuario los pide."""
    models_dir = os.path.join(get_bin_root_dir(), "bin", "models")
    os.makedirs(models_dir, exist_ok=True)
    return models_dir

def get_cache_dir() -> str:
    """Retorna el directorio principal de caché persistente de disco (ej. AppData/DowP2/cache)."""
    cache_dir = os.path.join(get_app_data_dir(), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir

def get_thumbnail_cache_dir() -> str:
    """Retorna el directorio de caché para miniaturas de imágenes y videos."""
    thumb_dir = os.path.join(get_cache_dir(), "thumbnails")
    os.makedirs(thumb_dir, exist_ok=True)
    return thumb_dir

def get_freesound_cache_dir() -> str:
    """Retorna el directorio de caché para previas de audio de Freesound (máximo 10 archivos LRU)."""
    fs_dir = os.path.join(get_cache_dir(), "freesound_previews")
    os.makedirs(fs_dir, exist_ok=True)
    return fs_dir

def get_waveform_cache_dir() -> str:
    """Retorna el directorio de caché para las ondas de audio cacheadas (waveforms)."""
    wf_dir = os.path.join(get_cache_dir(), "waveforms")
    os.makedirs(wf_dir, exist_ok=True)
    return wf_dir

def get_remote_thumbnail_cache_dir() -> str:
    """Retorna el directorio de caché para miniaturas ya renderizadas por un origen web
    (ej. thumburl de Wikimedia) — imágenes chicas descargadas tal cual, sin ffmpeg."""
    rt_dir = os.path.join(get_cache_dir(), "remote_thumbnails")
    os.makedirs(rt_dir, exist_ok=True)
    return rt_dir

def get_local_app_data_dir() -> str:
    r"""
    Retorna un directorio de datos NO itinerante (no roaming) para archivos grandes que no
    tiene sentido sincronizar entre equipos en entornos con perfiles de Windows en red:
    - Windows: %LOCALAPPDATA%/DowP2 (a diferencia de get_app_data_dir(), que usa %APPDATA%)
    - macOS/Linux: coincide con get_app_data_dir() (no existe la distinción roaming/local ahí)
    """
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/AppData/Local")
        app_dir = os.path.join(base, "DowP2")
        os.makedirs(app_dir, exist_ok=True)
        return app_dir
    return get_app_data_dir()

def get_proxy_cache_dir() -> str:
    """Retorna el directorio de caché para los proxies de previsualización (video de baja
    resolución generado para hacer scrubbing fluido de medios pesados/RAW). A diferencia del
    resto de cachés (thumbnails, waveforms, metadatos), vive en el perfil LOCAL (no roaming)
    porque estos archivos pueden pesar cientos de MB o varios GB por sesión de trabajo."""
    proxy_dir = os.path.join(get_local_app_data_dir(), "cache", "proxies")
    os.makedirs(proxy_dir, exist_ok=True)
    return proxy_dir

def get_subclips_dir() -> str:
    """Retorna el directorio para guardar subclips rápidos de medios cuando no hay editores conectados."""
    from core.utils.config_manager import get_default_subclip_dir
    return get_default_subclip_dir()

def get_sent_thumbnails_dir() -> str:
    """Retorna el directorio para miniaturas guardadas al enviarlas a Editor de Imagen
    desde "Enviar a H.I". Deliberadamente separado de get_thumbnail_cache_dir()/
    get_remote_thumbnail_cache_dir(): esos son cachés con eviction gestionados por
    cache_manager.py que el usuario puede vaciar manualmente desde Ajustes > Caché —
    un archivo ahí podría desaparecer mientras sigue en la cola de Editor de Imagen."""
    d = os.path.join(get_app_data_dir(), "sent_thumbnails")
    os.makedirs(d, exist_ok=True)
    return d

def get_default_download_dir() -> str:
    """Retorna el directorio predeterminado de descargas del usuario."""
    from core.tabs.advanced_process.output_logic import get_default_download_path
    return get_default_download_path()



def get_user_fonts_dir() -> str:
    """Retorna el directorio de fuentes personalizadas del usuario (%APPDATA%/DowP2/fonts)."""
    fonts_dir = os.path.join(get_app_data_dir(), "fonts")
    os.makedirs(fonts_dir, exist_ok=True)
    return fonts_dir


def get_user_themes_dir() -> str:
    """Retorna el directorio de temas personalizados del usuario (%APPDATA%/DowP2/themes)."""
    themes_dir = os.path.join(get_app_data_dir(), "themes")
    os.makedirs(themes_dir, exist_ok=True)
    return themes_dir


def get_config_path() -> str:
    """Retorna la ruta al archivo de configuración general config.json."""
    return os.path.join(get_app_data_dir(), "config.json")

def get_indexed_media_path() -> str:
    """Retorna la ruta al archivo de base de datos de medios indexados indexed_media.json."""
    return os.path.join(get_app_data_dir(), "indexed_media.json")

def migrate_legacy_data():
    """Migra archivos de configuración y caché antiguos desde bin/ al nuevo directorio AppData/DowP2 si existen."""
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        legacy_bin = os.path.join(project_root, "bin")
        if not os.path.exists(legacy_bin):
            return

        # 1. Migrar config.json
        legacy_config = os.path.join(legacy_bin, "config.json")
        new_config = get_config_path()
        if os.path.exists(legacy_config) and not os.path.exists(new_config):
            shutil.copy2(legacy_config, new_config)
            logger.info(f"Paths: Migrado {legacy_config} -> {new_config}")

        # 2. Migrar indexed_media.json
        legacy_indexed = os.path.join(legacy_bin, "indexed_media.json")
        new_indexed = get_indexed_media_path()
        if os.path.exists(legacy_indexed) and not os.path.exists(new_indexed):
            shutil.copy2(legacy_indexed, new_indexed)
            logger.info(f"Paths: Migrado {legacy_indexed} -> {new_indexed}")

        # 3. Migrar miniaturas en caché
        legacy_thumb_dir = os.path.join(legacy_bin, "cache", "thumbnails")
        new_thumb_dir = get_thumbnail_cache_dir()
        if os.path.exists(legacy_thumb_dir):
            for file_name in os.listdir(legacy_thumb_dir):
                old_file = os.path.join(legacy_thumb_dir, file_name)
                new_file = os.path.join(new_thumb_dir, file_name)
                if os.path.isfile(old_file) and not os.path.exists(new_file):
                    shutil.copy2(old_file, new_file)
            logger.info(f"Paths: Migradas miniaturas desde {legacy_thumb_dir} -> {new_thumb_dir}")

    except Exception as e:
        logger.error(f"Paths: Error al migrar datos legacy: {e}")

# Ejecutar migración legacy al cargar el módulo por primera vez
migrate_legacy_data()
