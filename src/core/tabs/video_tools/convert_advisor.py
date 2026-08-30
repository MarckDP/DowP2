# src/core/tabs/video_tools/convert_advisor.py
"""
Logica de decision para la pestana "Convertir": a diferencia de Comprimir (que siempre
recodifica, el eje es tamano/calidad), acá el objetivo es cambiar de contenedor
preservando calidad y velocidad cuando se pueda - si el codec de origen ya es compatible
con el contenedor destino (confirmado por el matrix, ver
recode_guard.is_stream_copy_compatible), la conversion correcta es un remux (-c copy,
instantaneo, sin perdida), no una recodificacion. Video y audio se deciden por separado:
queue_manager._execute_recode ya soporta video_mode/audio_mode independientes.

Todo lo que es "¿este codec entra en este contenedor?" sale del matrix (ver
recode_guard.py), nunca de una tabla adivinada a mano por contenedor - una prueba rapida
mostro que una tabla a mano se equivoca facil (ej. "ogg" parece audio-only por el nombre,
pero el matrix confirma que si acepta video Theora/VP8).
"""
import os

from core.utils.recode_guard import (
    is_stream_copy_compatible, resolve_encoder, get_compatible_codecs, container_supports_video,
)
from core.tabs.video_tools.size_estimator import source_codec_id
from core.tabs.video_tools.codec_profiles import build_custom_quality_args, build_custom_audio_bitrate_args

# Orden de preferencia cuando el matrix confirma VARIOS códecs válidos para el mismo
# contenedor (ej. WAV acepta pcm/aac/mp3/vorbis/...): no hay un "correcto" único, es una
# eleccion editorial entre opciones YA verificadas como validas - a diferencia de la
# version anterior, acá nunca se elige algo que el matrix no haya confirmado.
_VIDEO_CODEC_PREFERENCE = ["h264", "hevc", "vp9", "av1", "vp8", "mpeg4", "theora"]
_AUDIO_CODEC_PREFERENCE = ["aac", "mp3", "opus", "vorbis", "flac", "alac", "ac3", "pcm_s16le"]

DEFAULT_VIDEO_CRF = 18  # Convertir prioriza fidelidad (no tamaño): mas alto que Comprimir.
DEFAULT_AUDIO_KBPS = 256

# Codecs cuyo control de calidad no es un bitrate objetivo (build_custom_audio_bitrate_args
# no aplica): PCM no tiene bitrate configurable, FLAC usa nivel de compresion.
_AUDIO_CODECS_WITHOUT_BITRATE = {"pcm_s16le", "pcm_s24le", "pcm_s32le", "flac"}


def _pick_preferred(compatible_ids: list[str], preference: list[str]) -> str | None:
    for codec_id in preference:
        if codec_id in compatible_ids:
            return codec_id
    return compatible_ids[0] if compatible_ids else None


def plan_conversion(meta: dict, container_id: str) -> dict:
    """Decide, para UN archivo, si cada pista se copia o se recodifica.

    Returns: {"video": "copy"|"recode"|None, "audio": "copy"|"recode"|None,
              "video_codec_source": str|None, "audio_codec_source": str|None,
              "video_dropped_audio_only_container": bool}
    None en video/audio significa que esa pista no va a existir en la salida - o porque
    el origen no la tiene, o porque el matrix confirma que este contenedor no acepta
    NINGÚN códec de video (ver recode_guard.container_supports_video) y por lo tanto el
    video se descarta sin importar el codec de origen."""
    video_codec_source = source_codec_id((meta or {}).get("video_codec"))
    audio_codec_source = source_codec_id((meta or {}).get("audio_codec"))
    container_accepts_video = container_supports_video(container_id)

    video_plan = None
    if video_codec_source is not None and container_accepts_video:
        video_plan = "copy" if is_stream_copy_compatible(video_codec_source, container_id) else "recode"

    audio_plan = None
    if audio_codec_source is not None:
        audio_plan = "copy" if is_stream_copy_compatible(audio_codec_source, container_id) else "recode"

    return {
        "video": video_plan,
        "audio": audio_plan,
        "video_codec_source": video_codec_source,
        "audio_codec_source": audio_codec_source,
        "video_dropped_audio_only_container": (not container_accepts_video) and video_codec_source is not None,
    }


def _native_audio_args(codec_id: str, encoder: str) -> list[str]:
    if codec_id in _AUDIO_CODECS_WITHOUT_BITRATE:
        if codec_id == "flac":
            return ["-c:a", "flac", "-compression_level", "5"]
        return ["-c:a", encoder]
    return build_custom_audio_bitrate_args(encoder, DEFAULT_AUDIO_KBPS)


def build_settings(meta: dict, container_id: str) -> dict:
    """Arma el dict de settings final para UN archivo, en modo automático (Rápido: copia
    lo que sea compatible; si hay que recodificar, elige el códec preferido de entre los
    que el matrix confirma como válidos para ESTE contenedor - ver
    recode_guard.get_compatible_codecs). Manual arma su propio dict (ver
    convert_panel.py), este solo cubre la decisión automática."""
    plan = plan_conversion(meta, container_id)

    stream_mode = "video+audio"
    if plan["video"] is None and plan["audio"] is not None:
        stream_mode = "audio_only"
    elif plan["audio"] is None and plan["video"] is not None:
        stream_mode = "video_only"

    settings = {"container": container_id, "stream_mode": stream_mode}

    if plan["video"] is not None:
        if plan["video"] == "copy":
            settings["video_mode"] = "copy"
            settings["video_codec"] = plan["video_codec_source"]
            settings["video_args"] = []
        else:
            compatible = get_compatible_codecs(container_id, "video")
            video_codec_id = _pick_preferred(compatible, _VIDEO_CODEC_PREFERENCE) or "h264"
            encoder = resolve_encoder(video_codec_id) or "libx264"
            settings["video_mode"] = "recode"
            settings["video_codec"] = video_codec_id
            settings["video_args"] = build_custom_quality_args(encoder, DEFAULT_VIDEO_CRF)

    if plan["audio"] is not None:
        if plan["audio"] == "copy":
            settings["audio_mode"] = "copy"
            settings["audio_codec"] = plan["audio_codec_source"]
            settings["audio_args"] = []
        else:
            compatible = get_compatible_codecs(container_id, "audio")
            audio_codec_id = _pick_preferred(compatible, _AUDIO_CODEC_PREFERENCE) or "aac"
            encoder = resolve_encoder(audio_codec_id) or audio_codec_id
            settings["audio_mode"] = "recode"
            settings["audio_codec"] = audio_codec_id
            settings["audio_args"] = _native_audio_args(audio_codec_id, encoder)

    return settings


def summarize_queue(entries: list[tuple[str, dict]], container_id: str) -> dict:
    """entries: lista de (filepath, meta) de toda la cola (ver set_queue_entries).
    Devuelve cuántos archivos remuxean completo (sin recodificar nada) vs cuántos
    necesitan recodificar al menos una pista, con sus nombres para mostrar en el
    resumen agregado."""
    total = len(entries)
    full_copy = 0
    needs_recode: list[str] = []
    for filepath, meta in entries:
        plan = plan_conversion(meta, container_id)
        video_ok = plan["video"] in (None, "copy")
        audio_ok = plan["audio"] in (None, "copy")
        if video_ok and audio_ok:
            full_copy += 1
        else:
            needs_recode.append(os.path.basename(filepath))
    return {"total": total, "full_copy": full_copy, "needs_recode_names": needs_recode}
