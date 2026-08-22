# src/core/tabs/quick_mode/quick_mode_logic.py
import os
import platform
import re
import subprocess
from core.logger.logger_manager import logger
from core.utils.config_manager import get_config
from core.ytdlp_logic.format_selectors import quick_format_selector

def reveal_in_file_manager(path):
    """Abre el gestor de archivos y selecciona/marca el archivo dado. Multiplataforma."""
    path = os.path.normpath(path)
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.Popen(["explorer", "/select,", path])
        elif system == "Darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            # Linux: intentar DBus FileManager1, fallback a xdg-open del directorio
            try:
                subprocess.Popen([
                    "dbus-send", "--session", "--dest=org.freedesktop.FileManager1",
                    "--type=method_call", "/org/freedesktop/FileManager1",
                    "org.freedesktop.FileManager1.ShowItems",
                    f"array:string:file://{path}", "string:"
                ])
            except Exception:
                folder = os.path.dirname(path)
                subprocess.Popen(["xdg-open", folder])
    except Exception as e:
        logger.warning(f"No se pudo revelar archivo en el gestor: {e}")

def build_quick_request_data(url, title, mode, quality, output_path, speed_limit_val,
                             chk_thumb_file_checked, chk_thumb_only_checked,
                             is_playlist=False, playlist_items=None, conflict_policy="conservar"):
    """
    Construye el diccionario de parámetros de descarga de manera pura
    sin dependencias directas de widgets de Qt.
    """
    if chk_thumb_only_checked:
        mode_selector = "thumbnail_only"
        format_selector = "best"
    else:
        mode_selector = mode
        format_selector = quick_format_selector(mode, quality)

    request_title = title
    if is_playlist and title:
        safe_folder = re.sub(r'[<>:"/\\|?*#]', '', str(title)).strip() or "Playlist"
        output_path = os.path.join(output_path, safe_folder)
        request_title = ""

    config = get_config()
    req = {
        "url": url,
        "title": request_title,
        "mode": mode_selector,
        "output_path": output_path,
        "conflict_policy": conflict_policy,
        "format_selector": format_selector,
        "speed_limit": f"{int(speed_limit_val * 1024)}K" if speed_limit_val > 0 else None,
        "download_thumbnail_file": chk_thumb_file_checked or chk_thumb_only_checked,
        "embed_metadata": config.get("embed_metadata", True),
        "embed_thumbnail": config.get("embed_thumbnail", True),
        "remove_sponsors": config.get("remove_sponsors", False),
        "is_playlist": is_playlist,
        "force_audio_extract": mode_selector == "audio_only",
        "audio_ext": "mp3" if mode_selector == "audio_only" and quality in ("320", "192", "128") else None,
        "video_ext": "mp4" if mode_selector != "audio_only" else None,
        "selected_fragments": [],
        "fragment_mode": None,
    }
    if playlist_items:
        req["playlist_items"] = playlist_items
    return req
