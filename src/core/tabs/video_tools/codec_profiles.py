# src/core/tabs/video_tools/codec_profiles.py
"""
Perfiles/preajustes de calidad por encoder de ffmpeg, para el combobox "Perfil" de la
pestaña Avanzado (ej. Apple ProRes -> 422 Proxy / LT / Standard / HQ / 4444 / 4444 XQ;
H.264 -> Alta/Media/Rapida calidad, etc.).

Es conocimiento curado a mano (igual que lo era en DowP Lite), no datos verificados
empiricamente como ffmpeg_codec_matrix.json - los valores de CRF/CQ/bitrate son
recomendaciones razonables, no una garantia de que ese codec exista en este ffmpeg (eso
ya lo resuelve recode_guard.py por separado).

Cada perfil es {"label": str, "args": [...]} con los flags de ffmpeg a agregar, o
{"label": str, "custom": "vbr"/"cbr"} para las opciones de bitrate manual (la UI debe
pedir el valor aparte; todavia no hay campo numerico conectado para esto).

Los codecs sin tabla curada todavia devuelven un unico perfil "Predeterminado" con los
flags minimos (-c:v/-c:a <encoder>), para no romper la UI mientras se amplia esta lista.
"""

VIDEO_ENCODER_PROFILES = {
    "libx264": [
        {"label": "Alta Calidad (CRF 18)", "args": ["-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p"]},
        {"label": "Calidad Media (CRF 23)", "args": ["-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p"]},
        {"label": "Calidad Rápida (CRF 28)", "args": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p"]},
        {"label": "Calidad Constante Personalizada (CRF/CQ)", "custom": "cq"},
        {"label": "Bitrate Personalizado (VBR)", "custom": "vbr"},
        {"label": "Bitrate Personalizado (CBR)", "custom": "cbr"},
    ],
    "h264_nvenc": [
        {"label": "Alta Calidad (CQ 18)", "args": ["-c:v", "h264_nvenc", "-preset", "p7", "-rc", "vbr", "-cq", "18", "-pix_fmt", "yuv420p"]},
        {"label": "Calidad Media (CQ 23)", "args": ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "23", "-pix_fmt", "yuv420p"]},
        {"label": "Calidad Constante Personalizada (CRF/CQ)", "custom": "cq"},
        {"label": "Bitrate Personalizado (VBR)", "custom": "vbr"},
        {"label": "Bitrate Personalizado (CBR)", "custom": "cbr"},
    ],
    "h264_qsv": [
        {"label": "Alta Calidad", "args": ["-c:v", "h264_qsv", "-preset", "veryslow", "-global_quality", "18", "-pix_fmt", "yuv420p"]},
        {"label": "Calidad Media", "args": ["-c:v", "h264_qsv", "-preset", "medium", "-global_quality", "23", "-pix_fmt", "yuv420p"]},
        {"label": "Calidad Constante Personalizada (CRF/CQ)", "custom": "cq"},
        {"label": "Bitrate Personalizado (VBR)", "custom": "vbr"},
        {"label": "Bitrate Personalizado (CBR)", "custom": "cbr"},
    ],
    "h264_amf": [
        {"label": "Alta Calidad", "args": ["-c:v", "h264_amf", "-quality", "quality", "-rc", "cqp", "-qp_i", "18", "-qp_p", "18", "-pix_fmt", "yuv420p"]},
        {"label": "Calidad Balanceada", "args": ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp", "-qp_i", "23", "-qp_p", "23", "-pix_fmt", "yuv420p"]},
        {"label": "Calidad Constante Personalizada (CRF/CQ)", "custom": "cq"},
        {"label": "Bitrate Personalizado (VBR)", "custom": "vbr"},
        {"label": "Bitrate Personalizado (CBR)", "custom": "cbr"},
    ],
    "h264_videotoolbox": [
        {"label": "Alta Calidad", "args": ["-c:v", "h264_videotoolbox", "-profile:v", "high", "-q:v", "70"]},
        {"label": "Calidad Media", "args": ["-c:v", "h264_videotoolbox", "-profile:v", "main", "-q:v", "50"]},
        {"label": "Bitrate Personalizado (CBR)", "custom": "cbr"},
    ],
    "libx265": [
        {"label": "Calidad Alta (CRF 20)", "args": ["-c:v", "libx265", "-preset", "slow", "-crf", "20", "-tag:v", "hvc1"]},
        {"label": "Calidad Media (CRF 24)", "args": ["-c:v", "libx265", "-preset", "medium", "-crf", "24", "-tag:v", "hvc1"]},
        {"label": "Calidad Constante Personalizada (CRF/CQ)", "custom": "cq"},
        {"label": "Bitrate Personalizado (VBR)", "custom": "vbr"},
        {"label": "Bitrate Personalizado (CBR)", "custom": "cbr"},
    ],
    "hevc_nvenc": [
        {"label": "Calidad Alta (CQ 20)", "args": ["-c:v", "hevc_nvenc", "-preset", "p7", "-rc", "vbr", "-cq", "20", "-pix_fmt", "yuv420p"]},
        {"label": "Calidad Media (CQ 24)", "args": ["-c:v", "hevc_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "24", "-pix_fmt", "yuv420p"]},
        {"label": "Calidad Constante Personalizada (CRF/CQ)", "custom": "cq"},
        {"label": "Bitrate Personalizado (VBR)", "custom": "vbr"},
        {"label": "Bitrate Personalizado (CBR)", "custom": "cbr"},
    ],
    "hevc_qsv": [
        {"label": "Alta Calidad", "args": ["-c:v", "hevc_qsv", "-preset", "veryslow", "-global_quality", "20"]},
        {"label": "Calidad Media", "args": ["-c:v", "hevc_qsv", "-preset", "medium", "-global_quality", "24"]},
        {"label": "Calidad Constante Personalizada (CRF/CQ)", "custom": "cq"},
        {"label": "Bitrate Personalizado (VBR)", "custom": "vbr"},
        {"label": "Bitrate Personalizado (CBR)", "custom": "cbr"},
    ],
    "hevc_amf": [
        {"label": "Alta Calidad", "args": ["-c:v", "hevc_amf", "-quality", "quality", "-rc", "cqp", "-qp_i", "20", "-qp_p", "20", "-pix_fmt", "yuv420p"]},
        {"label": "Calidad Balanceada", "args": ["-c:v", "hevc_amf", "-quality", "balanced", "-rc", "cqp", "-qp_i", "24", "-qp_p", "24", "-pix_fmt", "yuv420p"]},
        {"label": "Calidad Constante Personalizada (CRF/CQ)", "custom": "cq"},
        {"label": "Bitrate Personalizado (VBR)", "custom": "vbr"},
        {"label": "Bitrate Personalizado (CBR)", "custom": "cbr"},
    ],
    "hevc_videotoolbox": [
        {"label": "Alta Calidad", "args": ["-c:v", "hevc_videotoolbox", "-profile:v", "main", "-q:v", "80"]},
        {"label": "Calidad Media", "args": ["-c:v", "hevc_videotoolbox", "-profile:v", "main", "-q:v", "65"]},
        {"label": "Bitrate Personalizado (CBR)", "custom": "cbr"},
    ],
    "libsvtav1": [
        {"label": "Calidad Alta (CRF 28)", "args": ["-c:v", "libsvtav1", "-preset", "4", "-crf", "28"]},
        {"label": "Calidad Media (CRF 35)", "args": ["-c:v", "libsvtav1", "-preset", "6", "-crf", "35"]},
        {"label": "Calidad Constante Personalizada (CRF/CQ)", "custom": "cq"},
        {"label": "Bitrate Personalizado (VBR)", "custom": "vbr"},
    ],
    "libaom-av1": [
        {"label": "Calidad Alta (CRF 28)", "args": ["-c:v", "libaom-av1", "-cpu-used", "4", "-crf", "28"]},
        {"label": "Calidad Media (CRF 35)", "args": ["-c:v", "libaom-av1", "-cpu-used", "6", "-crf", "35"]},
        {"label": "Calidad Constante Personalizada (CRF/CQ)", "custom": "cq"},
        {"label": "Bitrate Personalizado (VBR)", "custom": "vbr"},
    ],
    "av1_nvenc": [
        {"label": "Calidad Alta (CQ 24)", "args": ["-c:v", "av1_nvenc", "-preset", "p7", "-rc", "vbr", "-cq", "24"]},
        {"label": "Calidad Media (CQ 28)", "args": ["-c:v", "av1_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "28"]},
        {"label": "Calidad Constante Personalizada (CRF/CQ)", "custom": "cq"},
        {"label": "Bitrate Personalizado (VBR)", "custom": "vbr"},
        {"label": "Bitrate Personalizado (CBR)", "custom": "cbr"},
    ],
    "av1_qsv": [
        {"label": "Calidad Alta", "args": ["-c:v", "av1_qsv", "-global_quality", "25", "-preset", "slow"]},
        {"label": "Calidad Media", "args": ["-c:v", "av1_qsv", "-global_quality", "30", "-preset", "medium"]},
        {"label": "Calidad Constante Personalizada (CRF/CQ)", "custom": "cq"},
        {"label": "Bitrate Personalizado (VBR)", "custom": "vbr"},
        {"label": "Bitrate Personalizado (CBR)", "custom": "cbr"},
    ],
    "av1_amf": [
        {"label": "Alta Calidad", "args": ["-c:v", "av1_amf", "-quality", "quality", "-rc", "cqp", "-qp_i", "28", "-qp_p", "28"]},
        {"label": "Calidad Balanceada", "args": ["-c:v", "av1_amf", "-quality", "balanced", "-rc", "cqp", "-qp_i", "32", "-qp_p", "32"]},
        {"label": "Calidad Constante Personalizada (CRF/CQ)", "custom": "cq"},
        {"label": "Bitrate Personalizado (VBR)", "custom": "vbr"},
        {"label": "Bitrate Personalizado (CBR)", "custom": "cbr"},
    ],
    "libvpx-vp9": [
        {"label": "Calidad Alta (CRF 28)", "args": ["-c:v", "libvpx-vp9", "-crf", "28", "-b:v", "0"]},
        {"label": "Calidad Media (CRF 33)", "args": ["-c:v", "libvpx-vp9", "-crf", "33", "-b:v", "0"]},
        {"label": "Calidad Constante Personalizada (CRF/CQ)", "custom": "cq"},
        {"label": "Bitrate Personalizado (VBR)", "custom": "vbr"},
    ],
    "vp9_qsv": [
        {"label": "Calidad Alta", "args": ["-c:v", "vp9_qsv", "-global_quality", "25", "-preset", "slow"]},
        {"label": "Calidad Media", "args": ["-c:v", "vp9_qsv", "-global_quality", "30", "-preset", "medium"]},
        {"label": "Calidad Constante Personalizada (CRF/CQ)", "custom": "cq"},
        {"label": "Bitrate Personalizado (VBR)", "custom": "vbr"},
        {"label": "Bitrate Personalizado (CBR)", "custom": "cbr"},
    ],
    "libvpx": [
        {"label": "Calidad Alta (CRF 10)", "args": ["-c:v", "libvpx", "-crf", "10", "-b:v", "0"]},
        {"label": "Calidad Media (CRF 20)", "args": ["-c:v", "libvpx", "-crf", "20", "-b:v", "0"]},
        {"label": "Calidad Constante Personalizada (CRF/CQ)", "custom": "cq"},
        {"label": "Bitrate Personalizado (VBR)", "custom": "vbr"},
    ],
    "prores_ks": [
        {"label": "422 Proxy", "args": ["-c:v", "prores_ks", "-profile:v", "0", "-pix_fmt", "yuv422p10le", "-threads", "0"]},
        {"label": "422 LT", "args": ["-c:v", "prores_ks", "-profile:v", "1", "-pix_fmt", "yuv422p10le", "-threads", "0"]},
        {"label": "422 Standard", "args": ["-c:v", "prores_ks", "-profile:v", "2", "-pix_fmt", "yuv422p10le", "-threads", "0"]},
        {"label": "422 HQ", "args": ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le", "-threads", "0"]},
        {"label": "4444", "args": ["-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuv444p10le", "-threads", "0"]},
        {"label": "4444 XQ", "args": ["-c:v", "prores_ks", "-profile:v", "5", "-pix_fmt", "yuv444p10le", "-threads", "0"]},
    ],
    "prores_aw": [
        {"label": "422 Proxy", "args": ["-c:v", "prores_aw", "-profile:v", "0", "-pix_fmt", "yuv422p10le", "-threads", "0"]},
        {"label": "422 LT", "args": ["-c:v", "prores_aw", "-profile:v", "1", "-pix_fmt", "yuv422p10le", "-threads", "0"]},
        {"label": "422 Standard", "args": ["-c:v", "prores_aw", "-profile:v", "2", "-pix_fmt", "yuv422p10le", "-threads", "0"]},
        {"label": "422 HQ", "args": ["-c:v", "prores_aw", "-profile:v", "3", "-pix_fmt", "yuv422p10le", "-threads", "0"]},
        {"label": "4444", "args": ["-c:v", "prores_aw", "-profile:v", "4", "-pix_fmt", "yuv444p10le", "-threads", "0"]},
        {"label": "4444 XQ", "args": ["-c:v", "prores_aw", "-profile:v", "5", "-pix_fmt", "yuv444p10le", "-threads", "0"]},
    ],
    "dnxhd": [
        {"label": "DNxHD 1080p25 (145 Mbps)", "args": ["-c:v", "dnxhd", "-b:v", "145M", "-pix_fmt", "yuv422p"]},
        {"label": "DNxHD 1080p29.97 (145 Mbps)", "args": ["-c:v", "dnxhd", "-b:v", "145M", "-pix_fmt", "yuv422p"]},
        {"label": "DNxHD 1080i50 (120 Mbps)", "args": ["-c:v", "dnxhd", "-b:v", "120M", "-pix_fmt", "yuv422p", "-flags", "+ildct+ilme", "-top", "1"]},
        {"label": "DNxHD 720p50 (90 Mbps)", "args": ["-c:v", "dnxhd", "-b:v", "90M", "-pix_fmt", "yuv422p"]},
        {"label": "DNxHR LB (8-bit 4:2:2)", "args": ["-c:v", "dnxhd", "-profile:v", "dnxhr_lb", "-pix_fmt", "yuv422p"]},
        {"label": "DNxHR SQ (8-bit 4:2:2)", "args": ["-c:v", "dnxhd", "-profile:v", "dnxhr_sq", "-pix_fmt", "yuv422p"]},
        {"label": "DNxHR HQ (8-bit 4:2:2)", "args": ["-c:v", "dnxhd", "-profile:v", "dnxhr_hq", "-pix_fmt", "yuv422p"]},
        {"label": "DNxHR HQX (10-bit 4:2:2)", "args": ["-c:v", "dnxhd", "-profile:v", "dnxhr_hqx", "-pix_fmt", "yuv422p10le"]},
        {"label": "DNxHR 444 (10-bit 4:4:4)", "args": ["-c:v", "dnxhd", "-profile:v", "dnxhr_444", "-pix_fmt", "yuv444p10le"]},
    ],
}

AUDIO_ENCODER_PROFILES = {
    "aac": [
        {"label": "Alta Calidad (~256kbps)", "args": ["-c:a", "aac", "-b:a", "256k"]},
        {"label": "Buena Calidad (~192kbps)", "args": ["-c:a", "aac", "-b:a", "192k"]},
        {"label": "Calidad Media (~128kbps)", "args": ["-c:a", "aac", "-b:a", "128k"]},
    ],
    "libmp3lame": [
        {"label": "320kbps (CBR)", "args": ["-c:a", "libmp3lame", "-b:a", "320k"]},
        {"label": "256kbps aprox. (VBR)", "args": ["-c:a", "libmp3lame", "-q:a", "0"]},
        {"label": "192kbps (CBR)", "args": ["-c:a", "libmp3lame", "-b:a", "192k"]},
    ],
    "libopus": [
        {"label": "Calidad Transparente (~256kbps)", "args": ["-c:a", "libopus", "-b:a", "256k"]},
        {"label": "Calidad Alta (~192kbps)", "args": ["-c:a", "libopus", "-b:a", "192k"]},
        {"label": "Calidad Media (~128kbps)", "args": ["-c:a", "libopus", "-b:a", "128k"]},
    ],
    "libvorbis": [
        {"label": "Calidad Muy Alta (q8)", "args": ["-c:a", "libvorbis", "-q:a", "8"]},
        {"label": "Calidad Alta (q6)", "args": ["-c:a", "libvorbis", "-q:a", "6"]},
        {"label": "Calidad Media (q4)", "args": ["-c:a", "libvorbis", "-q:a", "4"]},
    ],
    "ac3": [
        {"label": "Stereo (192kbps)", "args": ["-c:a", "ac3", "-b:a", "192k"]},
        {"label": "Stereo (256kbps)", "args": ["-c:a", "ac3", "-b:a", "256k"]},
        {"label": "Surround 5.1 (448kbps)", "args": ["-c:a", "ac3", "-b:a", "448k", "-ac", "6"]},
        {"label": "Surround 5.1 (640kbps)", "args": ["-c:a", "ac3", "-b:a", "640k", "-ac", "6"]},
    ],
    "alac": [
        {"label": "Estándar (sin pérdida)", "args": ["-c:a", "alac"]},
    ],
    "flac": [
        {"label": "Compresión nivel 5", "args": ["-c:a", "flac", "-compression_level", "5"]},
        {"label": "Compresión nivel 8 (más lento)", "args": ["-c:a", "flac", "-compression_level", "8"]},
    ],
    "pcm_s24le": [
        {"label": "PCM 16-bit", "args": ["-c:a", "pcm_s16le"]},
        {"label": "PCM 24-bit", "args": ["-c:a", "pcm_s24le"]},
    ],
    "wmav2": [
        {"label": "Calidad Alta (192kbps)", "args": ["-c:a", "wmav2", "-b:a", "192k"]},
        {"label": "Calidad Media (128kbps)", "args": ["-c:a", "wmav2", "-b:a", "128k"]},
    ],
}


# Codecs con mas de una implementacion de encoder valida en ffmpeg, sin que haya una
# "mejor" objetiva para todos los casos (a diferencia de hardware vs software, donde
# hardware_detector.py ya elige el mejor real por probe-encode). Se ofrecen ambas y que
# el usuario elija. prores_ks (Kostya Shishkov) es el default moderno de ffmpeg, mas
# preciso; prores_aw (Anatoliy Wasserman) es una reimplementacion mas rapida en varios
# sistemas. La misma logica aplicaria a libsvtav1 vs libaom-av1 en AV1 (hoy
# hardware_detector.py elige libsvtav1 automaticamente como "software" preferido).
ENCODER_VARIANTS = {
    "prores": [
        ("prores_ks", "prores_ks (más preciso, recomendado)"),
        ("prores_aw", "prores_aw (más rápido en algunos sistemas)"),
    ],
}


# Audio recomendado por codec de video, para autocompletar y agilizar el flujo. No es
# una regla tecnica (varios funcionarian) sino la pareja mas convencional/segura por
# familia: entrega web/consumo -> AAC (o Opus para la familia libre VP8/VP9/AV1), NLE
# profesional (ProRes/DNxHR) -> PCM sin comprimir. Los codecs sin entrada usan "aac" por
# ser el mas ampliamente compatible.
RECOMMENDED_AUDIO_CODEC = {
    "h264": "aac",
    "hevc": "aac",
    "av1": "opus",
    "vp9": "opus",
    "vp8": "opus",
    "theora": "vorbis",
    "prores": "pcm_s24le",
    "dnxhd": "pcm_s24le",
    "mpeg2video": "ac3",
}
DEFAULT_RECOMMENDED_AUDIO_CODEC = "aac"


def recommend_audio_codec(video_codec_id: str | None) -> str:
    return RECOMMENDED_AUDIO_CODEC.get(video_codec_id, DEFAULT_RECOMMENDED_AUDIO_CODEC)


# Encoders donde el mecanismo clasico de 2 pasadas de ffmpeg (-pass 1 / -pass 2) tiene
# sentido: encoders de software orientados a bitrate objetivo. Los de hardware (NVENC/
# QSV/AMF) tienen sus propios mecanismos de multipass no equivalentes a este flag, asi
# que no se ofrecen aca para no prometer algo no verificado.
TWO_PASS_CAPABLE_ENCODERS = {"libx264", "libx265", "libvpx", "libvpx-vp9", "libaom-av1", "libsvtav1"}


def encoder_is_two_pass_capable(encoder: str | None) -> bool:
    return bool(encoder) and encoder in TWO_PASS_CAPABLE_ENCODERS


def supports_two_pass(encoder: str | None, profile: dict | None) -> bool:
    """2 pasadas solo tiene sentido cuando hay un bitrate objetivo (VBR/CBR, sea
    personalizado o un perfil con '-b:v' fijo) - con CRF/CQ no hay nada que converger."""
    if not encoder or encoder not in TWO_PASS_CAPABLE_ENCODERS or not profile:
        return False
    if profile.get("custom"):
        return True
    return "-b:v" in profile.get("args", [])


def build_pass_args(base_args: list[str], pass_num: int) -> list[str]:
    return [*base_args, "-pass", str(pass_num)]



def build_custom_quality_args(encoder: str, cq_value: int) -> list[str]:
    base = ["-c:v", encoder]
    if "nvenc" in encoder:
        return base + ["-rc", "vbr", "-cq", str(cq_value)]
    if "qsv" in encoder:
        return base + ["-global_quality", str(cq_value)]
    if "amf" in encoder:
        return base + ["-rc", "cqp", "-qp_i", str(cq_value), "-qp_p", str(cq_value)]
    return base + ["-crf", str(cq_value)]

def build_custom_bitrate_args(encoder: str, mode: str, bitrate_kbps: int) -> list[str]:
    """
    Arma los flags de ffmpeg para un bitrate de video elegido a mano.
    mode: "vbr" (deja margen con maxrate/bufsize) o "cbr" (fuerza min=max=bitrate).
    """
    b = f"{bitrate_kbps}k"
    if mode == "cbr":
        return ["-c:v", encoder, "-b:v", b, "-minrate", b, "-maxrate", b, "-bufsize", b]
    maxrate = f"{int(bitrate_kbps * 1.5)}k"
    bufsize = f"{bitrate_kbps * 2}k"
    return ["-c:v", encoder, "-b:v", b, "-maxrate", maxrate, "-bufsize", bufsize]


def extract_bitrate_kbps(args: list[str], flag: str = "-b:v") -> float | None:
    """Extrae un valor kbps de una lista de args de ffmpeg (ej. '-b:v 145M' -> 145000.0)."""
    if not args or flag not in args:
        return None
    try:
        raw = args[args.index(flag) + 1]
    except IndexError:
        return None
    raw = raw.strip().lower()
    try:
        if raw.endswith("k"):
            return float(raw[:-1])
        if raw.endswith("m"):
            return float(raw[:-1]) * 1000
        return float(raw) / 1000
    except ValueError:
        return None


def _default_profile(kind: str, encoder: str) -> list[dict]:
    flag = "-c:v" if kind == "video" else "-c:a"
    return [{"label": "Predeterminado", "args": [flag, encoder]}]


def get_profiles(kind: str, encoder: str | None) -> list[dict]:
    """Lista de perfiles disponibles para un encoder. 'kind' es 'video' o 'audio'."""
    if not encoder:
        return []
    table = VIDEO_ENCODER_PROFILES if kind == "video" else AUDIO_ENCODER_PROFILES
    return table.get(encoder) or _default_profile(kind, encoder)
