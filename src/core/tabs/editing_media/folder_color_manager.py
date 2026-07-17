# src/core/tabs/editing_media/folder_color_manager.py
import os
import json
import random
from core.utils.config_manager import get_config, save_config

def get_theme_color(token_key: str, default_value: str = None) -> str:
    """Resuelve un color de tema directamente desde los archivos de tema en la GUI sin importar módulos GUI."""
    config = get_config()
    theme_name = config.get("theme", "dark")
    
    # Localizar la ruta de temas
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    json_path = os.path.join(base_dir, "src", "gui", "themes", f"{theme_name}.json")
    
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("colores", {}).get(token_key, default_value)
        except Exception:
            pass
    return default_value

def get_item_color(item_key: str) -> str:
    """Obtiene el color personalizado para una carpeta o colección desde la configuración."""
    config = get_config()
    folder_colors = config.get("folder_colors", {})
    return folder_colors.get(item_key)

def set_item_color(item_key: str, color_hex: str):
    """Guarda o remueve un color personalizado para una carpeta o colección en la configuración."""
    config = get_config()
    if "folder_colors" not in config:
        config["folder_colors"] = {}
    if color_hex:
        config["folder_colors"][item_key] = color_hex
    else:
        config["folder_colors"].pop(item_key, None)
    save_config(config)

def get_random_label_color() -> str:
    """Obtiene un color aleatorio basado en las etiquetas de Ajustes o paleta de temas."""
    config = get_config()
    # 1. Intentar usar los colores de las etiquetas del usuario en Ajustes
    user_label_colors = [lbl.get("color") for lbl in config.get("labels", []) if lbl.get("color")]
    if user_label_colors:
        return random.choice(user_label_colors)
        
    # 2. Si no hay etiquetas del usuario, usar la paleta de colores por defecto
    default_colors = [
        get_theme_color("etiqueta_combinado", "#3498db"),
        get_theme_color("etiqueta_multi_idioma", "#9b59b6"),
        get_theme_color("etiqueta_estrella", "#f1c40f"),
        get_theme_color("etiqueta_peligro", "#e74c3c"),
        get_theme_color("acento_primario", "#B9E640"),
        "#2ecc71", # Verde
        "#e67e22", # Naranja
        "#e84393"  # Rosa/Magenta
    ]
    return random.choice(default_colors)
