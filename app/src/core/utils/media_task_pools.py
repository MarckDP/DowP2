# src/core/utils/media_task_pools.py
"""Pools de hilos dedicados para las tareas de miniaturas/waveforms de medios.

Se usan pools propios (no QThreadPool.globalInstance()) por dos razones:
1. Aislarlos de otros consumidores del pool global de Qt (p.ej. las descargas de
   preview de Freesound), para poder pausarlos/repriorizarlos sin efectos secundarios.
2. Separar en dos pools independientes la generación masiva de fondo (miniaturas/
   waveforms de la lista mientras se hace scroll) de las solicitudes interactivas
   (lo que el usuario pide ver AHORA: clic en un ítem, waveform de alta resolución
   del reproductor). Así una previsualización nunca queda esperando en la misma cola
   FIFO detrás de decenas de tareas de fondo ya encoladas.
"""
from PySide6.QtCore import QThreadPool
from core.logger.logger_manager import logger

# Prioridad para QThreadPool.start(runnable, priority): a mayor valor, antes se ejecuta.
# Solo importa dentro de un mismo pool; los pools de fondo e interactivo ya están
# separados, pero se deja para uso futuro (p.ej. si el pool interactivo llegara a
# tener más de un hilo y varias solicitudes en cola).
PRIORITY_BACKGROUND = 0
PRIORITY_INTERACTIVE = 10

_BACKGROUND_MAX_THREADS = 2
_INTERACTIVE_MAX_THREADS = 1

_background_pool: QThreadPool | None = None
_interactive_pool: QThreadPool | None = None


def get_background_pool() -> QThreadPool:
    """Pool para generación masiva en segundo plano (miniaturas/waveforms de filas
    visibles en la lista). Se puede pausar por completo con set_background_throttled()."""
    global _background_pool
    if _background_pool is None:
        _background_pool = QThreadPool()
        _background_pool.setMaxThreadCount(_BACKGROUND_MAX_THREADS)
    return _background_pool


def get_interactive_pool() -> QThreadPool:
    """Pool separado, siempre disponible, para lo que el usuario pide ver en este
    instante (miniatura/waveform del ítem seleccionado, waveform de alta resolución
    del reproductor/editor de subclips). Nunca compite por hilos con la generación
    masiva de fondo ni se ve afectado por su pausa."""
    global _interactive_pool
    if _interactive_pool is None:
        _interactive_pool = QThreadPool()
        _interactive_pool.setMaxThreadCount(_INTERACTIVE_MAX_THREADS)
    return _interactive_pool


def set_background_throttled(throttled: bool):
    """Pausa (throttled=True) o reanuda la generación de fondo.

    Pausar no cancela ni interrumpe las tareas ya en ejecución (siguen hasta
    terminar), solo evita que arranquen tareas nuevas mientras el usuario está
    reproduciendo un video/audio, para no competir por CPU/disco con la
    reproducción en vivo. Se reanuda automáticamente al detener la reproducción.
    """
    pool = get_background_pool()
    target = 0 if throttled else _BACKGROUND_MAX_THREADS
    if pool.maxThreadCount() != target:
        pool.setMaxThreadCount(target)
        logger.debug(
            f"media_task_pools: generación de fondo {'pausada' if throttled else 'reanudada'} "
            f"(maxThreadCount={target})."
        )
