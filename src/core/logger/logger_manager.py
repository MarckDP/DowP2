# src/core/logger/manager.py
import logging
import os
import platform
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler

class CustomFormatter(logging.Formatter):
    """Custom formatter to provide a clean, timestamped output."""
    def format(self, record):
        # No mutar record.msg: el mismo LogRecord pasa por cada handler activo
        # (consola + archivo), y mutarlo duplicaría el prefijo en el segundo.
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = super().format(record)
        return f"[{timestamp}] {record.levelname:<8} [DowP] {message}"


def _get_log_dir() -> str:
    """
    Ruta de logs, calculada aquí en vez de reusar core.utils.paths para no crear
    un import circular (paths.py importa este módulo para su propio logger).
    """
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
    elif system == "Darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "DowP2", "logs")


def setup_logger():
    """Initializes and returns the global logger."""
    logger = logging.getLogger("DowP")
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        formatter = CustomFormatter()

        # Console Handler — silencioso en un .exe --windowed (sys.stdout es None ahí),
        # pero se mantiene para ejecución desde fuente / consola.
        if sys.stdout is not None:
            ch = logging.StreamHandler(sys.stdout)
            ch.setLevel(logging.DEBUG)
            ch.setFormatter(formatter)
            logger.addHandler(ch)

        # File Handler — única fuente de diagnóstico disponible en el .exe compilado
        # sin consola, donde el handler de arriba no escribe a ningún lado visible.
        try:
            log_dir = _get_log_dir()
            os.makedirs(log_dir, exist_ok=True)
            fh = RotatingFileHandler(
                os.path.join(log_dir, "dowp.log"),
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(formatter)
            logger.addHandler(fh)
        except Exception:
            pass  # Si no se puede escribir el log a disco, seguimos solo con consola (si la hay).

    return logger

# Global logger instance
logger = setup_logger()
