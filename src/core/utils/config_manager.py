# src/core/utils/config_manager.py
import os
import json
from core.logger.logger_manager import logger

# Calcular ruta absoluta del proyecto para que la config sea persistente
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CONFIG_FILE = os.path.join(BASE_DIR, "bin", "config.json")

_cached_config = None

def get_config():
    """Lee el archivo de configuración y lo mantiene en memoria."""
    global _cached_config
    if _cached_config is not None:
        return _cached_config

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                _cached_config = json.load(f)
        except Exception as e:
            logger.error(f"ConfigManager: Error leyendo config: {e}")

    if _cached_config is None:
        _cached_config = {}

    # Rellenar con valores por defecto si no existen
    defaults = {
        "language": "es", 
        "theme": "dark", 
        "auto_analyze": False,
        "use_impersonate": False,
        "adobe_compat_default": True,
        "auto_paste_url": True,
        "labels": []
    }
    for k, v in defaults.items():
        if k not in _cached_config:
            _cached_config[k] = v

    # Opciones transitorias de AdvancedProcessTab (siempre inician en su valor por defecto al arrancar)
    transient_defaults = {
        "analyze_playlist": True,
        "fast_mode": True,
        "batch_thumbnail_mode": "manual",
        "global_download_mode": "manual",
        "global_download_quality": "manual"
    }
    for k, v in transient_defaults.items():
        _cached_config[k] = v

    return _cached_config

def save_config(config):
    """Guarda la configuración en archivo, omitiendo las opciones transitorias."""
    global _cached_config
    _cached_config = config

    # Filtrar las opciones transitorias de la AdvancedProcessTab
    save_dict = config.copy()
    transient_keys = [
        "analyze_playlist",
        "fast_mode",
        "batch_thumbnail_mode",
        "global_download_mode",
        "global_download_quality"
    ]
    for key in transient_keys:
        save_dict.pop(key, None)

    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(save_dict, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"ConfigManager: Error guardando config: {e}")
