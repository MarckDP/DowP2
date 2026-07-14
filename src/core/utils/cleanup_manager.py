# src/core/utils/cleanup_manager.py
import os
import glob
import time
import threading
import gc
from core.logger.logger_manager import logger

class DownloadCancelledError(Exception):
    """Excepción lanzada cuando el usuario cancela una descarga."""
    pass

class CleanupManager:
    """
    Gestor centralizado para la limpieza de residuos de descargas y procesos de FFmpeg.
    """
    
    @staticmethod
    def cleanup_ytdlp_temp_files(output_dir, base_title, keep_thumbnail=False):
        """
        Limpia archivos temporales específicos de yt-dlp (.part, fragmentos, etc.)
        basándose en el título del archivo.
        """
        if not output_dir or not base_title:
            return

        import re
        # Reemplazar caracteres ilegales de Windows con '*' para que glob encuentre el archivo
        # sin importar cómo yt-dlp haya sanitizado el nombre (ej. '|' a '#', ':' a ' - ').
        safe_title = re.sub(r'[\\/*?:"<>|]', '*', base_title)

        patterns = [
            f"{safe_title}*.part",           # Archivos parciales
            f"{safe_title}*.f[0-9]*",        # Fragmentos de formato
            f"{safe_title}*.ytdl",           # Archivos de metadata
            f"{safe_title}*.temp",           # Temporales genéricos
            f"*.f[0-9]*.part",               # Fragmentos parciales sin título
            f"{safe_title}*.temp.*",
            f"{safe_title}*.part-*",
        ]
        if not keep_thumbnail:
            patterns.extend([
                f"{safe_title}*.webp",       # Miniaturas residuales (originales antes de conversión)
                f"{safe_title}*.jpg",        # Miniaturas residuales (originales antes de conversión)
            ])
        
        cleaned_count = 0
        
        for pattern in patterns:
            full_pattern = os.path.join(output_dir, pattern)
            for temp_file in glob.glob(full_pattern):
                if not os.path.exists(temp_file):
                    continue
                
                # Intentar eliminar con reintentos para archivos bloqueados
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        gc.collect() # Liberar handles si es posible
                        if attempt > 0:
                            time.sleep(0.5 * (2 ** attempt))
                        
                        os.remove(temp_file)
                        logger.debug(f"CleanupManager: Eliminado archivo temporal: {temp_file}")
                        cleaned_count += 1
                        break
                    except (PermissionError, OSError) as e:
                        if attempt == max_retries - 1:
                            logger.warning(f"CleanupManager: No se pudo eliminar (bloqueado): {temp_file}")
        
        if cleaned_count > 0:
            logger.info(f"CleanupManager: Se limpiaron {cleaned_count} archivos residuales en {output_dir}")

    @staticmethod
    def deferred_cleanup(output_dir, base_title, delay=3, keep_thumbnail=False):
        """
        Ejecuta una limpieza en segundo plano tras un retraso.
        Útil para archivos que tardan en desbloquearse tras cerrar un proceso.
        """
        def task():
            time.sleep(delay)
            logger.info(f"CleanupManager: Ejecutando limpieza diferida para '{base_title}'")
            CleanupManager.cleanup_ytdlp_temp_files(output_dir, base_title, keep_thumbnail=keep_thumbnail)
            
        threading.Thread(target=task, daemon=True).start()
