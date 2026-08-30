# src/core/tabs/video_tools/compress_advisor.py
"""
Logica de recomendacion para la pestana "Comprimir" (modo Rapido): a partir de la
resolucion/bitrate real del archivo en preview (ffprobe), estima el peso resultante para
los 3 niveles (Ligero/Equilibrado/Agresivo) y sugiere cual conviene.

A diferencia de un perfil de calidad constante (CRF/CQ), los 3 niveles se expresan como
FRACCION del bitrate de video de origen (o de un bitrate de referencia por resolucion
cuando el origen no tiene un bitrate fijo conocido). Eso es lo que permite estimar el
peso final de antemano con size_estimator.estimate_size_mb: un CRF fijo no lo permite -
su tamano de salida depende del contenido, no es predecible sin codificar de verdad (ver
advanced_recode_panel._update_size_estimate, que ya devuelve "sin bitrate fijo, no
incluido" para perfiles CRF/CQ).
"""
from core.tabs.video_tools.size_estimator import parse_duration_to_seconds, parse_kbps_from_label, estimate_size_mb
from core.tabs.video_tools.codec_profiles import build_custom_bitrate_args
from core.utils.recode_guard import resolve_encoder

LEVELS = ("ligero", "equilibrado", "agresivo")

LEVEL_LABELS = {
    "ligero": "Ligero",
    "equilibrado": "Equilibrado",
    "agresivo": "Agresivo",
}

# Fraccion del bitrate de video de origen (o de referencia) que apunta cada nivel. No es
# un valor exacto de salida (el VBR real deja margen con maxrate/bufsize, ver
# codec_profiles.build_custom_bitrate_args), es el objetivo que arma tanto el estimado
# como el -b:v real.
LEVEL_FACTOR = {
    "ligero": 0.65,
    "equilibrado": 0.42,
    "agresivo": 0.25,
}

# Bitrate de video de referencia (kbps) por resolucion, para cuando el archivo de origen
# no trae un bitrate fijo conocido (ej. viene de un codec CRF/VFR, o la metadata todavia
# no esta lista) - valores curados a mano, igual de criterio que codec_profiles.py, para
# calidad "buena para web/distribucion" en H.264/HEVC.
_REFERENCE_BITRATE_BY_HEIGHT = [
    (2160, 35000),
    (1440, 16000),
    (1080, 8000),
    (720, 5000),
    (480, 2500),
    (360, 1200),
    (0, 800),
]

AUDIO_BITRATE_BY_LEVEL = {
    "ligero": 192,
    "equilibrado": 128,
    "agresivo": 96,
}

# Piso duro: nunca proponer un bitrate de video por debajo de esto, sin importar el
# nivel/factor (evita targets absurdos en fuentes ya muy livianas).
_MIN_VIDEO_KBPS = 300


def reference_video_kbps(height: int | None) -> int:
    if not height or height <= 0:
        return 4000
    for min_h, kbps in _REFERENCE_BITRATE_BY_HEIGHT:
        if height >= min_h:
            return kbps
    return _REFERENCE_BITRATE_BY_HEIGHT[-1][1]


def source_wh(meta: dict) -> tuple[int, int] | None:
    raw = (meta or {}).get("resolución", "-")
    try:
        w_str, h_str = raw.lower().split("x")
        w, h = int(w_str), int(h_str)
        if w > 0 and h > 0:
            return w, h
    except (ValueError, AttributeError):
        pass
    return None


def source_video_kbps(meta: dict) -> float | None:
    return parse_kbps_from_label((meta or {}).get("bitrate_video"))


def source_audio_kbps(meta: dict) -> float | None:
    return parse_kbps_from_label((meta or {}).get("bitrate_audio"))


def baseline_video_kbps(meta: dict) -> float:
    """Bitrate base sobre el que se calculan los 3 niveles: el real del origen si se
    conoce, si no una referencia razonable segun resolucion."""
    known = source_video_kbps(meta)
    if known:
        return known
    wh = source_wh(meta)
    height = wh[1] if wh else None
    return float(reference_video_kbps(height))


def target_video_kbps(meta: dict, level: str) -> int:
    base = baseline_video_kbps(meta)
    target = base * LEVEL_FACTOR[level]
    return max(_MIN_VIDEO_KBPS, round(target))


def pick_family(prefer_compat: bool) -> str:
    """'h264' si se prioriza compatibilidad; si no, 'hevc' cuando hay un encoder real
    disponible en este equipo (hardware o software), si no cae a 'h264'. AV1 queda fuera
    de Rapido a proposito (motor menos universal); solo se ofrece en Manual."""
    if prefer_compat:
        return "h264"
    encoder = resolve_encoder("hevc")
    return "hevc" if encoder else "h264"


def build_level_video_args(meta: dict, level: str, encoder: str) -> list[str]:
    kbps = target_video_kbps(meta, level)
    return build_custom_bitrate_args(encoder, "vbr", kbps)


def estimate_level_size_mb(meta: dict, level: str) -> float | None:
    duration_sec = parse_duration_to_seconds((meta or {}).get("duración", "0"))
    if duration_sec <= 0:
        return None
    video_kbps = target_video_kbps(meta, level)
    audio_kbps = AUDIO_BITRATE_BY_LEVEL[level]
    return estimate_size_mb(video_kbps, audio_kbps, duration_sec)


def source_size_mb(meta: dict) -> float | None:
    duration_sec = parse_duration_to_seconds((meta or {}).get("duración", "0"))
    if duration_sec <= 0:
        return None
    return estimate_size_mb(source_video_kbps(meta), source_audio_kbps(meta), duration_sec)


def analyze_source(meta: dict) -> dict:
    """Recomienda un nivel para el archivo en preview, comparando su bitrate real contra
    el que ya propondria el nivel 'equilibrado' para su resolucion. Determinista y
    explicable: no hay heuristica estadistica, solo un umbral razonable por resolucion."""
    if not meta:
        return {"known": False, "recommended_level": "equilibrado", "note": ""}

    known_kbps = source_video_kbps(meta)
    wh = source_wh(meta)
    height = wh[1] if wh else None
    reference = reference_video_kbps(height)

    if known_kbps is None:
        return {
            "known": False,
            "recommended_level": "equilibrado",
            "note": "No se pudo leer el bitrate de origen todavía; se sugiere Equilibrado por defecto.",
        }

    equilibrado_target = reference * LEVEL_FACTOR["equilibrado"]
    if known_kbps <= equilibrado_target:
        return {
            "known": True,
            "recommended_level": "ligero",
            "note": (
                "Este archivo ya está eficientemente comprimido para su resolución: "
                "recomprimirlo agresivamente ahorraría poco y perdería calidad. Se sugiere Ligero."
            ),
        }
    if known_kbps >= reference * 1.3:
        return {
            "known": True,
            "recommended_level": "agresivo",
            "note": (
                "El bitrate de origen está bastante por encima de lo necesario para su "
                "resolución: hay margen grande de ahorro. Se sugiere Agresivo."
            ),
        }
    return {
        "known": True,
        "recommended_level": "equilibrado",
        "note": "El bitrate de origen es razonable para su resolución. Equilibrado da un buen balance de ahorro/calidad.",
    }


def estimate_queue_totals(entries: list[dict], level: str) -> dict:
    """entries: lista de metadatos ffprobe (uno por archivo de la cola, mismo esquema que
    set_source_media). Devuelve el peso actual total vs el proyectado a ese nivel."""
    current_total = 0.0
    projected_total = 0.0
    counted = 0
    for meta in entries:
        cur = source_size_mb(meta)
        proj = estimate_level_size_mb(meta, level)
        if cur is not None:
            current_total += cur
        if proj is not None:
            projected_total += proj
            counted += 1
    return {
        "current_total_mb": current_total,
        "projected_total_mb": projected_total,
        "file_count": counted,
    }
