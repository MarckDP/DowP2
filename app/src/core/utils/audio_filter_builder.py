# src/core/utils/audio_filter_builder.py
"""
Constructor de filtros de audio de FFmpeg para normalización de sonoridad y picos.

Módulo puro de lógica (sin dependencias de GUI) para construir argumentos de
filtros de audio (-af) según los estándares de la industria:
- Sonoridad Percibida (EBU R128 / ITU-R BS.1770 / LUFS) vía loudnorm.
- Dinámica Inteligente (Dynamic Audio Normalizer) vía dynaudnorm.
- Normalización por Pico (dBFS) vía alimiter/peak limiter.
"""

import math


def build_loudnorm_filter(
    integrated_lufs: float = -14.0,
    true_peak_dbtp: float = -1.0,
    lra_lu: float = 11.0,
) -> str:
    """
    Construye el filtro EBU R128 / ITU-R BS.1770 con loudnorm.

    Args:
        integrated_lufs: Sonoridad integrada objetivo en LUFS (típicamente -70.0 a -5.0, ej: -14.0 para streaming).
        true_peak_dbtp: Límite de pico real máximo en dBTP (típicamente -9.0 a 0.0, ej: -1.0).
        lra_lu: Rango de sonoridad objetivo en LU (típicamente 1.0 a 50.0, ej: 11.0 para música/voz, 7.0 para broadcast).

    Returns:
        Cadena del filtro FFmpeg, ej: 'loudnorm=I=-14.0:TP=-1.0:LRA=11.0'
    """
    i = round(float(integrated_lufs), 1)
    tp = round(float(true_peak_dbtp), 1)
    lra = round(float(lra_lu), 1)
    return f"loudnorm=I={i:.1f}:TP={tp:.1f}:LRA={lra:.1f}"


def build_dynaudnorm_filter(
    max_gain_db: float = 10.0,
    peak_factor: float = 0.95,
    frame_len_ms: int = 500,
) -> str:
    """
    Construye el filtro Dynamic Audio Normalizer (dynaudnorm) para compresión inteligente
    que eleva partes bajas y contiene explosiones sin alterar la ecualización.

    Args:
        max_gain_db: Ganancia máxima permitida en dB (ej: 10.0 dB).
        peak_factor: Nivel de pico objetivo relativo a 1.0 (ej: 0.95 = 95%).
        frame_len_ms: Longitud de la ventana de análisis en milisegundos (ej: 500 ms).

    Returns:
        Cadena del filtro FFmpeg, ej: 'dynaudnorm=f=500:g=31:p=0.95:m=10.0'
    """
    f = max(10, int(frame_len_ms))
    p = max(0.1, min(1.0, float(peak_factor)))
    m = max(1.0, float(max_gain_db))
    # g (filter_size): número impar de frames para suavizado gaussiano, 31 es el valor óptimo estándar
    return f"dynaudnorm=f={f}:g=31:p={p:.2f}:m={m:.1f}"


def build_peak_filter(peak_db: float = -1.0) -> str:
    """
    Construye un filtro de limitador de pico digital (alimiter) para asegurar
    que el nivel máximo no supere el techo en dBFS sin saturar.

    Args:
        peak_db: Techo máximo de pico en dB (típicamente -30.0 a 0.0, ej: -1.0 dB).

    Returns:
        Cadena del filtro FFmpeg, ej: 'alimiter=limit=0.8913:level=false'
    """
    db = min(0.0, float(peak_db))
    # Convertir dB a factor lineal (0 dB = 1.0, -1 dB ≈ 0.89125, -6 dB ≈ 0.501)
    linear_limit = max(0.0625, min(1.0, math.pow(10.0, db / 20.0)))
    return f"alimiter=limit={linear_limit:.4f}:level=false"


def build_audio_normalization_filter(method: str, params: dict | None = None) -> str | None:
    """
    Despachador para construir el filtro según el método seleccionado.

    Args:
        method: 'loudnorm', 'dynaudnorm', o 'peak'.
        params: Diccionario con parámetros numéricos opcionales.

    Returns:
        Cadena del filtro FFmpeg para pasar a '-af', o None si el método no es reconocido.
    """
    params = params or {}
    clean_method = (method or "").strip().lower()

    if clean_method in ("loudnorm", "lufs", "ebu_r128"):
        i = params.get("integrated_lufs", -14.0)
        tp = params.get("true_peak_dbtp", -1.0)
        lra = params.get("lra_lu", 11.0)
        return build_loudnorm_filter(i, tp, lra)

    if clean_method in ("dynaudnorm", "dynamic", "dinamica"):
        m = params.get("max_gain_db", 10.0)
        p = params.get("peak_factor", 0.95)
        f = params.get("frame_len_ms", 500)
        return build_dynaudnorm_filter(m, p, f)

    if clean_method in ("peak", "pico", "dbfs"):
        peak_db = params.get("peak_db", -1.0)
        return build_peak_filter(peak_db)

    return None
