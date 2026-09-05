# src/core/logger/console_log_handler.py
import logging
from collections import deque
from datetime import datetime

from PySide6.QtCore import QObject, Signal


class ConsoleLogHandler(QObject, logging.Handler):
    """Handler de logging que retransmite cada línea formateada como señal Qt, para que la
    consola en vivo de Ajustes (y a futuro cualquier otro visor) pueda mostrarla sin depender de
    un archivo o una consola del sistema operativo (muda en el .exe --windowed).

    emit() puede llegar desde cualquier thread (descargas, ffmpeg, waveform, etc.); Qt entrega
    line_appended por cola al thread del receptor automáticamente mientras este viva en el hilo
    principal, así que no hace falta ninguna sincronización manual aquí."""

    line_appended = Signal(object)
    MAX_LINES = 5000

    def __init__(self):
        QObject.__init__(self)
        logging.Handler.__init__(self)
        # deque.append es atómico en CPython (protegido por el GIL), no hace falta lock.
        self.buffer = deque(maxlen=self.MAX_LINES)

    def emit(self, record):
        try:
            message = record.getMessage()
            line = self.format(record)
        except Exception:
            return
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "levelno": record.levelno,
            "message": message,
            "line": line,
        }
        self.buffer.append(entry)
        self.line_appended.emit(entry)


_instance = None


def get_console_log_handler() -> ConsoleLogHandler:
    """Crea (una sola vez) el handler y lo cuelga del logger 'DowP'. Idempotente: se puede llamar
    varias veces (main.py al arrancar, luego ConsolePage al montarse) y siempre devuelve la misma
    instancia, ya con el historial acumulado desde el arranque de la app."""
    global _instance
    if _instance is None:
        from core.logger.logger_manager import logger, CustomFormatter
        _instance = ConsoleLogHandler()
        _instance.setLevel(logging.DEBUG)
        _instance.setFormatter(CustomFormatter())
        logger.addHandler(_instance)
    return _instance
