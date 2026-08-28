# src/core/utils/font_manager.py
"""
Gestor Centralizado de Tipografías para DowP 2.0
=================================================
Maneja el escaneo, registro en QFontDatabase y resolución de la fuente activa
tanto para fuentes empaquetadas en assets/fonts como para fuentes personalizadas
agregadas por el usuario en %APPDATA%/DowP2/fonts.
"""
import os
import json
from PySide6.QtGui import QFontDatabase
from core.logger.logger_manager import logger
from core.utils.paths import get_src_dir, get_user_fonts_dir, get_user_themes_dir
from core.utils.config_manager import get_config

# Cache de familias detectadas y registradas
_REGISTERED_FAMILIES = []
_INITIALIZED = False

DEFAULT_FALLBACK_FONT = "Google Sans Flex"


def init_fonts() -> list:
    """
    Escanea y registra todas las fuentes (.ttf, .otf) en:
      1. src/assets/fonts/ (fuentes empaquetadas)
      2. %APPDATA%/DowP2/fonts/ (fuentes de usuario)
    Retorna la lista de familias de fuentes disponibles.
    """
    global _REGISTERED_FAMILIES, _INITIALIZED
    
    discovered_families = set()

    # 1. Fuentes empaquetadas
    builtin_fonts_dir = os.path.join(get_src_dir(), "assets", "fonts")
    _scan_and_register_dir(builtin_fonts_dir, discovered_families, is_user=False)

    # 2. Fuentes de usuario en AppData
    user_fonts_dir = get_user_fonts_dir()
    _scan_and_register_dir(user_fonts_dir, discovered_families, is_user=True)

    # Obtener todas las familias disponibles en el sistema y ordenarlas
    all_db_families = QFontDatabase.families()
    
    # Mantener una lista ordenada priorizando las descubiertas en nuestros directorios
    ordered = []
    # Añadir familias descubiertas que estén en el QFontDatabase
    for f in sorted(discovered_families):
        if f in all_db_families and f not in ordered:
            ordered.append(f)

    # Asegurar que las principales estén si existen
    for prio in ["Google Sans Flex", "Google Sans", "Raleway", "Roboto"]:
        if prio in all_db_families and prio not in ordered:
            ordered.append(prio)

    _REGISTERED_FAMILIES = ordered
    _INITIALIZED = True
    logger.info(f"FontManager: Fuentes inicializadas. Familias disponibles: {_REGISTERED_FAMILIES}")
    return _REGISTERED_FAMILIES


def _scan_and_register_dir(directory: str, families_set: set, is_user: bool = False):
    """Escanea un directorio y registra fuentes en QFontDatabase."""
    if not os.path.isdir(directory):
        return

    for file_name in os.listdir(directory):
        if file_name.lower().endswith((".ttf", ".otf")):
            font_path = os.path.join(directory, file_name)
            try:
                font_id = QFontDatabase.addApplicationFont(font_path)
                if font_id != -1:
                    fams = QFontDatabase.applicationFontFamilies(font_id)
                    if fams:
                        # Usar el nombre principal de la familia (el primero)
                        primary_family = fams[0]
                        families_set.add(primary_family)
                        prefix = "Usuario" if is_user else "Interna"
                        logger.debug(f"FontManager: [{prefix}] Fuente registrada: {primary_family} ({file_name})")
                else:
                    logger.warning(f"FontManager: No se pudo registrar {font_path} (archivo corrupto o formato no soportado)")
            except Exception as e:
                logger.error(f"FontManager: Error al registrar fuente {font_path}: {e}")


def get_available_fonts() -> list:
    """Retorna la lista de familias de fuentes disponibles registradas."""
    global _INITIALIZED
    if not _INITIALIZED:
        init_fonts()
    return list(_REGISTERED_FAMILIES)


def get_theme_defined_font(theme_name: str) -> str:
    """Lee el archivo JSON del tema para ver si especifica una fuente personalizada."""
    if not theme_name:
        return ""

    # Buscar primero en temas de usuario
    user_theme_file = os.path.join(get_user_themes_dir(), f"{theme_name}.json")
    builtin_theme_file = os.path.join(get_src_dir(), "gui", "themes", f"{theme_name}.json")

    json_path = user_theme_file if os.path.exists(user_theme_file) else builtin_theme_file

    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("fuente", "") or data.get("font_family", "")
        except Exception as e:
            logger.debug(f"FontManager: No se pudo leer fuente del tema '{theme_name}': {e}")

    return ""


def get_active_font_family(theme_name: str = None) -> str:
    """
    Resuelve la familia de tipografía activa actual:
      1. Si config['font_family'] tiene una fuente específica (no 'auto'/'theme_default'), se usa.
      2. Si está en 'theme_default' o no configurado, se busca la fuente definida en el tema.
      3. Si el tema no especifica fuente, se usa 'Google Sans Flex' o 'Raleway' o 'Segoe UI'.
    """
    global _INITIALIZED
    if not _INITIALIZED:
        init_fonts()

    config = get_config()
    configured_font = config.get("font_family", "theme_default")

    if configured_font and configured_font not in ("theme_default", "auto"):
        # El usuario seleccionó una fuente explícita
        if configured_font in QFontDatabase.families() or configured_font in _REGISTERED_FAMILIES:
            return configured_font

    # Obtener nombre del tema si no fue provisto
    if not theme_name:
        theme_name = config.get("theme", "dark")

    theme_font = get_theme_defined_font(theme_name)
    if theme_font:
        if theme_font in QFontDatabase.families() or theme_font in _REGISTERED_FAMILIES:
            return theme_font

    # Fallback predeterminado en orden de preferencia
    all_families = QFontDatabase.families()
    for fallback in [DEFAULT_FALLBACK_FONT, "Google Sans", "Raleway", "Segoe UI"]:
        if fallback in all_families or fallback in _REGISTERED_FAMILIES:
            return fallback

    return "Segoe UI"
