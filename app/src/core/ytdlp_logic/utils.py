from core.logger.logger_manager import logger

def get_impersonate_target(browser_name="chrome"):
    """
    Obtiene de forma segura el objeto ImpersonateTarget de yt-dlp.
    Esto es vital para evitar ser detectado como bot en versiones modernas de la API.
    """
    try:
        # Intentamos importar localmente para asegurar que sys.path ya tenga el zip
        from yt_dlp.networking.impersonate import ImpersonateTarget
        
        target = ImpersonateTarget.from_str(browser_name)
        logger.info(f"AnalyzerUtils: Disfraz '{browser_name}' (impersonate) generado correctamente.")
        return target
        
    except ImportError:
        logger.warning("AnalyzerUtils: El módulo de impersonación no está disponible en esta versión de yt-dlp.")
    except Exception as e:
        logger.error(f"AnalyzerUtils: Error inesperado al generar el disfraz '{browser_name}': {e}")
        
    return None
