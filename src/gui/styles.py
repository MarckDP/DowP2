# src/gui/styles.py
"""
Motor de Temas DowP 2.0
========================
Lee un template QSS (_base.qss) y un archivo de tokens JSON ({tema}.json),
reemplaza las variables {{token}} por sus valores, y genera assets dinámicos
como el ícono SVG del triángulo del ComboBox.

Para crear un tema custom:
  1. Copiar dark.json o light.json
  2. Renombrar (ej: monokai.json)
  3. Cambiar los colores
  4. Seleccionarlo desde Ajustes
"""
import os
import json
import tempfile
from core.logger.logger_manager import logger

# Directorio base de temas
_THEMES_DIR = os.path.join(os.path.dirname(__file__), "themes")
_BASE_QSS = os.path.join(_THEMES_DIR, "_base.qss")

# Directorio temporal para assets generados (SVGs, etc.)
_TEMP_DIR = os.path.join(tempfile.gettempdir(), "dowp_theme_assets")
os.makedirs(_TEMP_DIR, exist_ok=True)

# Cache de tokens para evitar lecturas de disco repetitivas
_THEME_CACHE = {}


def _generate_triangle_svg(color: str) -> str:
    """
    Genera un archivo SVG de triángulo invertido (▼) con el color dado.
    Retorna la ruta al archivo SVG generado.
    """
    # Normalizar color para nombre de archivo seguro
    safe_color = color.replace("#", "").replace(" ", "")
    svg_path = os.path.join(_TEMP_DIR, f"triangle_{safe_color}.svg")
    
    # Solo generar si no existe ya
    if not os.path.exists(svg_path):
        svg_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 8" width="12" height="8">
  <polygon points="0,0 12,0 6,8" fill="{color}"/>
</svg>'''
        try:
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg_content)
            logger.debug(f"Temas: SVG triángulo generado: {svg_path}")
        except Exception as e:
            logger.error(f"Temas: Error generando SVG: {e}")
            return ""
    
    return svg_path.replace("\\", "/")


def _generate_spinbox_symbol_svg(symbol: str, color: str) -> str:
    """
    Genera SVGs pequenos para los botones +/- de QSpinBox/QDoubleSpinBox.
    """
    safe_color = color.replace("#", "").replace(" ", "")
    svg_path = os.path.join(_TEMP_DIR, f"spinbox_{symbol}_{safe_color}.svg")

    if not os.path.exists(svg_path):
        if symbol == "plus":
            shape = (
                '<rect x="5" y="1" width="2" height="10" rx="1" fill="{color}"/>'
                '<rect x="1" y="5" width="10" height="2" rx="1" fill="{color}"/>'
            )
        else:
            shape = '<rect x="1" y="5" width="10" height="2" rx="1" fill="{color}"/>'

        svg_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 12" width="12" height="12">
  {shape.format(color=color)}
</svg>'''
        try:
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg_content)
            logger.debug(f"Temas: SVG spinbox generado: {svg_path}")
        except Exception as e:
            logger.error(f"Temas: Error generando SVG spinbox: {e}")
            return ""

    return svg_path.replace("\\", "/")


def _load_theme_tokens(theme_name: str) -> dict:
    """
    Carga los tokens de color desde el archivo JSON del tema con cache.
    """
    if theme_name in _THEME_CACHE:
        return _THEME_CACHE[theme_name]

    json_path = os.path.join(_THEMES_DIR, f"{theme_name}.json")
    
    if not os.path.exists(json_path):
        logger.error(f"Temas: Archivo de tema no encontrado: {json_path}")
        return {}
    
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            tokens = data.get("colores", {})
            _THEME_CACHE[theme_name] = tokens
            return tokens
    except Exception as e:
        logger.error(f"Temas: Error leyendo tokens del tema: {e}")
        return {}


def _load_base_template() -> str:
    """
    Carga el template QSS base.
    """
    if not os.path.exists(_BASE_QSS):
        logger.error(f"Temas: Template base no encontrado: {_BASE_QSS}")
        return ""
    
    try:
        with open(_BASE_QSS, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.error(f"Temas: Error leyendo template base: {e}")
        return ""


def get_available_themes() -> list:
    """
    Retorna una lista de temas disponibles (nombres sin extensión).
    Útil para poblar el selector de temas en Ajustes.
    """
    themes = []
    if os.path.isdir(_THEMES_DIR):
        for filename in os.listdir(_THEMES_DIR):
            if filename.endswith(".json"):
                themes.append(filename.replace(".json", ""))
    return themes


def get_theme_token(token_key: str, default_value: str = None) -> str:
    """
    Obtiene un token de color del tema actual.
    """
    from core.utils.config_manager import get_config
    config = get_config()
    theme_name = config.get("theme", "dark")
    tokens = _load_theme_tokens(theme_name)
    return tokens.get(token_key, default_value)


def load_stylesheet(theme_name: str = "dark") -> str:
    """
    Genera el QSS final para el tema solicitado.
    
    1. Lee _base.qss (template con {{variables}})
    2. Lee {theme_name}.json (definición de colores)
    3. Genera el SVG del triángulo con el color de acento
    4. Reemplaza todas las {{variables}} por sus valores
    5. Retorna el QSS listo para aplicar
    """
    # 1. Cargar template base
    template = _load_base_template()
    if not template:
        logger.warning("Temas: Template vacío, usando estilos por defecto")
        return ""
    
    # 2. Cargar tokens del tema
    tokens = _load_theme_tokens(theme_name)
    if not tokens:
        logger.warning(f"Temas: No se pudieron cargar tokens para '{theme_name}'")
        return ""
    
    # 3. Generar SVG del triángulo con el color de acento primario
    triangle_color = tokens.get("acento_primario", "#B9E640")
    triangle_path = _generate_triangle_svg(triangle_color)
    tokens["icono_triangulo"] = triangle_path
    tokens["icono_spinbox_plus"] = _generate_spinbox_symbol_svg("plus", triangle_color)
    tokens["icono_spinbox_minus"] = _generate_spinbox_symbol_svg("minus", triangle_color)
    
    # 4. Reemplazar todas las {{variables}}
    result = template
    for key, value in tokens.items():
        result = result.replace("{{" + key + "}}", value)
    
    # 5. Verificar si quedaron variables sin reemplazar
    import re
    unresolved = re.findall(r"\{\{(\w+)\}\}", result)
    if unresolved:
        logger.warning(f"Temas: Variables sin resolver en '{theme_name}': {unresolved}")
    
    # Limpiar cache al recargar el stylesheet para asegurar que los cambios se apliquen
    _THEME_CACHE.clear()
    
    logger.info(f"Temas: Tema '{theme_name}' cargado exitosamente")
    return result


def apply_cut_button_style(btn, status="normal", icon_size=18):
    """
    Aplica el estilo unificado del botón de recorte de fragmentos
    basado en los tokens del tema actual.
    
    Status:
      - 'normal': gris elegante (#2d2d2d / fondo_elemento) con hover claro
      - 'saved': verde (#1DC038 / acento_secundario)
      - 'unsaved': amarillo (#ffc107 / estado_aviso)
    """
    from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
    
    colors = {
        "normal":  {
            "bg": get_theme_token('fondo_elemento', '#2d2d2d'),
            "hover": get_theme_token('seleccion_fondo', '#3d3d3d'),
            "border": f"1px solid {get_theme_token('borde_normal', '#3d3d3d')}",
            "icon": "#FFFFFF"
        },
        "saved":   {
            "bg": get_theme_token('acento_secundario', '#1DC038'),
            "hover": get_theme_token('acento_primario', '#B9E640'),
            "border": "none",
            "icon": "#000000"
        },
        "unsaved": {
            "bg": get_theme_token('estado_aviso', '#ffc107'),
            "hover": "#ffdb58",
            "border": "none",
            "icon": "#000000"
        }
    }
    
    cfg = colors.get(status, colors["normal"])
    btn.setIcon(get_colored_svg_icon("content_cut.svg", cfg["icon"], size=icon_size))
    
    # Calcular radio del borde redondeado para botón circular perfecto
    radius = 17
    if hasattr(btn, 'height') and btn.height() > 0:
        radius = btn.height() // 2
    elif hasattr(btn, 'fixedSize') and btn.fixedSize().height() > 0:
        radius = btn.fixedSize().height() // 2
        
    btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {cfg['bg']};
            border: {cfg['border']};
            border-radius: {radius}px;
            padding: 0px;
        }}
        QPushButton:hover {{
            background-color: {cfg['hover']};
        }}
        QPushButton:disabled {{
            background-color: #555;
        }}
    """)


def apply_player_play_button_style(btn, is_playing: bool = False, icon_size: int = 14):
    """
    Aplica el estilo unificado al botón de Play/Pausa de los reproductores.
    - Icono: pause.svg si is_playing=True, play_arrow.svg si is_playing=False (en #000000).
    - Fondo: verde acento (#1DC038), hover verde claro (#B9E640).
    """
    from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
    
    icon_name = "pause.svg" if is_playing else "play_arrow.svg"
    btn.setIcon(get_colored_svg_icon(icon_name, "#000000", size=icon_size))
    
    radius = 13
    if hasattr(btn, 'height') and btn.height() > 0:
        radius = btn.height() // 2
    elif hasattr(btn, 'fixedSize') and btn.fixedSize().height() > 0:
        radius = btn.fixedSize().height() // 2
        
    btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {get_theme_token('acento_secundario', '#1DC038')};
            border: none;
            border-radius: {radius}px;
            padding: 0px;
        }}
        QPushButton:hover {{
            background-color: {get_theme_token('acento_primario', '#B9E640')};
        }}
        QPushButton:disabled {{
            background-color: #555;
        }}
    """)


def apply_player_loop_button_style(btn, is_active: bool = False, icon_size: int = 14):
    """
    Aplica el estilo unificado al botón de Repetir (Loop) de los reproductores.
    - is_active=True: Fondo verde acento (#1DC038), hover (#B9E640), icono repeat.svg en #000000.
    - is_active=False: Fondo gris (#2d2d2d), border (#2d2d2d), hover (#3d3d3d), icono repeat.svg en #6c7086.
    """
    from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
    
    radius = 13
    if hasattr(btn, 'height') and btn.height() > 0:
        radius = btn.height() // 2
    elif hasattr(btn, 'fixedSize') and btn.fixedSize().height() > 0:
        radius = btn.fixedSize().height() // 2
        
    if is_active:
        btn.setIcon(get_colored_svg_icon("repeat.svg", "#000000", size=icon_size))
        btn.setToolTip("Repetir: Activado")
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {get_theme_token('acento_secundario', '#1DC038')};
                border: none;
                border-radius: {radius}px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('acento_primario', '#B9E640')};
            }}
            QPushButton:disabled {{
                background-color: #555;
            }}
        """)
    else:
        btn.setIcon(get_colored_svg_icon("repeat.svg", "#6c7086", size=icon_size))
        btn.setToolTip("Repetir: Desactivado")
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {get_theme_token('fondo_elemento', '#2d2d2d')};
                border: 1px solid {get_theme_token('borde_normal', '#2d2d2d')};
                border-radius: {radius}px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {get_theme_token('seleccion_fondo', '#3d3d3d')};
            }}
            QPushButton:disabled {{
                background-color: #555;
            }}
        """)


def apply_volume_control_style(btn_mute, slider):
    """
    Aplica el estilo unificado basado en tokens de tema para el botón Mute
    y el Slider de Volumen en cualquier reproductor.
    """
    bg_hover = get_theme_token('seleccion_fondo', '#3d3d3d')
    border_color = get_theme_token('borde_normal', '#444444')
    accent_sec = get_theme_token('acento_secundario', '#1DC038')
    accent_pri = get_theme_token('acento_primario', '#B9E640')

    btn_mute.setStyleSheet(f"""
        QPushButton {{
            background-color: transparent;
            border: none;
            border-radius: 12px;
            padding: 0px;
        }}
        QPushButton:hover {{
            background-color: {bg_hover};
        }}
    """)

    slider.setStyleSheet(f"""
        QSlider::groove:horizontal {{
            border-radius: 2px;
            height: 4px;
            background: {border_color};
        }}
        QSlider::sub-page:horizontal {{
            background: {accent_sec};
            border-radius: 2px;
        }}
        QSlider::handle:horizontal {{
            background: #ffffff;
            width: 8px;
            margin-top: -2px;
            margin-bottom: -2px;
            border-radius: 4px;
        }}
        QSlider::handle:horizontal:hover {{
            background: {accent_pri};
        }}
    """)



