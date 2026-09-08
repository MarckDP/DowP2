# src/core/tabs/single_process/output_logic.py
import os
import platform
from pathlib import Path
from core.logger.logger_manager import logger

def get_default_download_path():
    """
    Retorna la ruta de la carpeta de Descargas predeterminada del sistema
    (Windows, macOS, Linux).
    """
    try:
        # Path.home() es multiplataforma
        home = Path.home()
        downloads = home / "Downloads"
        
        # En algunos sistemas (como Linux en español), la carpeta puede llamarse "Descargas"
        # Pero internamente Path.home() / "Downloads" suele funcionar si están las XDG user dirs.
        # Por seguridad, si no existe "Downloads", probamos con "Descargas"
        if not downloads.exists():
            alternate = home / "Descargas"
            if alternate.exists():
                downloads = alternate
        
        # Si aún no existe, devolvemos el Home como fallback
        if not downloads.exists():
            logger.warning(f"No se encontró la carpeta de Descargas estándar, usando Home: {home}")
            return str(home)
            
        return str(downloads)
    except Exception as e:
        logger.error(f"Error detectando carpeta de descargas: {e}")
        return os.getcwd()

def initialize_output_path(widget_input):
    """
    Establece la ruta por defecto en el QLineEdit proporcionado.
    """
    path = get_default_download_path()
    if widget_input:
        widget_input.setText(path)
        logger.info(f"Ruta de salida inicializada en: {path}")
