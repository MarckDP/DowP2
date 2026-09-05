# src/core/ytdlp_logic/format_selectors.py
from urllib.parse import urlparse


def _extract_domain(url: str) -> str:
    """Extrae el dominio en minúsculas a partir de una URL dada."""
    if not url:
        return ""
    try:
        netloc = urlparse(url).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


def is_youtube_url(url: str) -> bool:
    """Determina si la URL pertenece al ecosistema de YouTube."""
    domain = _extract_domain(url)
    return any(yt in domain for yt in ("youtube.com", "youtu.be", "youtube-nocookie.com"))


def is_pinterest_url(url: str) -> bool:
    """Determina si la URL pertenece a Pinterest."""
    domain = _extract_domain(url)
    return "pinterest." in domain or domain.endswith("pin.it") or domain == "pin.it"


def is_soundcloud_url(url: str) -> bool:
    """Determina si la URL pertenece a SoundCloud."""
    domain = _extract_domain(url)
    return "soundcloud.com" in domain


# ----------------------------------------------------------------------
# 1. Reglas específicas para YouTube (Preserva códecs compatibles NLE)
# ----------------------------------------------------------------------
def _youtube_format_selector(mode: str, quality: str) -> str:
    if mode == "audio_only":
        if quality == "best_compatible":
            return "bestaudio[ext=m4a]/bestaudio[ext=mp4]/bestaudio[ext=mp3]/bestaudio[ext=wav]/bestaudio/best"
        return "bestaudio/best"

    if mode == "video_only":
        if quality == "best_compatible":
            return "bestvideo[vcodec~='^(avc1|h264|hevc|h265|prores|dnxhd|dnxhr|cfhd)']/bestvideo[ext=mp4]/bestvideo/best"
        if quality == "best":
            return "bestvideo/best"
        if str(quality).isdigit():
            return f"bestvideo[height<={quality}]/best[height<={quality}]/best"
        return "bestvideo/best"

    # video+audio
    if quality == "best_compatible":
        return (
            "bestvideo[vcodec~='^(avc1|h264|hevc|h265|prores|dnxhd|dnxhr|cfhd)']+bestaudio[acodec~='^(aac|mp4a|pcm_s16le|pcm_s24le|mp3|ac3)']/"
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
            "best[ext~='^(mp4|mov|avi)'][vcodec~='^(avc1|h264|hevc|h265|prores|dnxhd|dnxhr|cfhd)']/best"
        )
    if quality == "best":
        return "bestvideo+bestaudio/best"
    if str(quality).isdigit():
        h = str(quality)
        return f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"
    return "bestvideo+bestaudio/best"


# ----------------------------------------------------------------------
# 2. Reglas específicas para Pinterest (HLS m3u8 con audio mp4/acodec None)
# ----------------------------------------------------------------------
def _pinterest_format_selector(mode: str, quality: str) -> str:
    if mode == "audio_only":
        return "bestaudio/best"

    if mode == "video_only":
        if str(quality).isdigit():
            return f"bestvideo[height<={quality}]/bestvideo/best"
        return "bestvideo/best"

    # video+audio
    if str(quality).isdigit():
        h = str(quality)
        return f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/bestvideo+bestaudio/best"
    return "bestvideo+bestaudio/best"


# ----------------------------------------------------------------------
# 3. Reglas específicas para SoundCloud (Audio puro)
# ----------------------------------------------------------------------
def _soundcloud_format_selector(mode: str, quality: str) -> str:
    return "bestaudio/best"


# ----------------------------------------------------------------------
# 4. Reglas Genéricas (Compatible-first con fallback seguro)
# ----------------------------------------------------------------------
def _generic_format_selector(mode: str, quality: str) -> str:
    if mode == "audio_only":
        if quality == "best_compatible":
            return "bestaudio[ext=m4a]/bestaudio[ext=mp4]/bestaudio[ext=mp3]/bestaudio[ext=wav]/bestaudio/best"
        return "bestaudio/best"

    if mode == "video_only":
        if quality == "best_compatible":
            return "bestvideo[vcodec~='^(avc1|h264|hevc|h265|prores|dnxhd|dnxhr|cfhd)']/bestvideo[ext=mp4]/bestvideo/best"
        if quality == "best":
            return "bestvideo/best"
        if str(quality).isdigit():
            return f"bestvideo[height<={quality}]/best[height<={quality}]/bestvideo/best"
        return "bestvideo/best"

    # video+audio
    if quality == "best_compatible":
        return (
            "bestvideo[vcodec~='^(avc1|h264|hevc|h265|prores|dnxhd|dnxhr|cfhd)']+bestaudio[acodec~='^(aac|mp4a|pcm_s16le|pcm_s24le|mp3|ac3)']/"
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
            "bestvideo[ext=mp4]+bestaudio[ext=mp4]/"
            "best[ext~='^(mp4|mov|avi)'][vcodec~='^(avc1|h264|hevc|h265|prores|dnxhd|dnxhr|cfhd)']/"
            "bestvideo+bestaudio/best"
        )
    if quality == "best":
        return "bestvideo+bestaudio/best"
    if str(quality).isdigit():
        h = str(quality)
        return f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/bestvideo+bestaudio/best"
    return "bestvideo+bestaudio/best"


# ----------------------------------------------------------------------
# Despachadores Públicos
# ----------------------------------------------------------------------
def get_site_specific_format_selector(mode: str, quality: str, url: str = "") -> str:
    """
    Selecciona la regla de formato óptima según el dominio/sitio web de origen:
    - YouTube: Reglas estrictas de códecs editables (AVC1/H264 + AAC en MP4).
    - Pinterest: Streams HLS nativos (video + audio mp4 sin códec declarado).
    - SoundCloud: Pistas de audio directo.
    - Genérico: Reglas compatibles con fallback seguro para no fallar en sitios HLS/DASH.
    """
    if not url or is_youtube_url(url):
        return _youtube_format_selector(mode, quality)
    elif is_pinterest_url(url):
        return _pinterest_format_selector(mode, quality)
    elif is_soundcloud_url(url):
        return _soundcloud_format_selector(mode, quality)
    else:
        return _generic_format_selector(mode, quality)


def playlist_format_selector(mode, quality, url=""):
    return get_site_specific_format_selector(mode, quality, url)


def quick_format_selector(mode, quality, url=""):
    return get_site_specific_format_selector(mode, quality, url)

