# src/core/tabs/video_tools/size_estimator.py
"""
Estimacion de peso final de un recode, a partir de los metadatos reales (ffprobe) del
archivo seleccionado en la cola, no de un valor de duracion tipeado a mano.
"""
import re


def parse_duration_to_seconds(dur_str) -> float:
    """Convierte 'MM:SS' / 'HH:MM:SS' (formato de FFprobeMetadataManager) a segundos."""
    if not dur_str or dur_str == "-":
        return 0.0
    if isinstance(dur_str, (int, float)):
        return float(dur_str)
    try:
        parts = str(dur_str).split(":")
        if len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    except (ValueError, TypeError):
        pass
    return 0.0


def parse_kbps_from_label(bitrate_str) -> float | None:
    """Convierte etiquetas de FFprobeMetadataManager ('1.23 Mb/s', '850 kb/s') a kbps."""
    if not bitrate_str or bitrate_str == "-":
        return None
    match = re.search(r"([\d.]+)\s*(Mb/s|kb/s|Kb/s)", str(bitrate_str))
    if not match:
        return None
    value, unit = float(match.group(1)), match.group(2).lower()
    return value * 1000 if unit.startswith("m") else value


def estimate_size_mb(video_kbps: float | None, audio_kbps: float | None, duration_sec: float) -> float | None:
    if duration_sec <= 0 or (video_kbps is None and audio_kbps is None):
        return None
    total_kbps = (video_kbps or 0) + (audio_kbps or 0)
    return total_kbps * duration_sec / 8 / 1024


def source_codec_id(ffprobe_codec_name: str | None) -> str | None:
    """Normaliza 'video_codec'/'audio_codec' de FFprobeMetadataManager (ej. 'H264', 'AAC')
    al codec_id que usa ffmpeg_codec_matrix.json (ej. 'h264', 'aac')."""
    if not ffprobe_codec_name or ffprobe_codec_name == "-":
        return None
    return ffprobe_codec_name.strip().lower()
