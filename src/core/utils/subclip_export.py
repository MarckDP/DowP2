# src/core/utils/subclip_export.py
import os
import subprocess
import shutil
from core.logger.logger_manager import logger


def cut_subclip_ffmpeg(input_path: str, output_path: str, start_sec: float, end_sec: float) -> bool:
    """Recorta con precisión un fragmento de audio/video usando FFmpeg y lo guarda en output_path.
    Intenta primero un corte por stream copy (rápido, sin pérdida) y si falla recurre a un
    re-encode completo como fallback."""
    from core.setup.ffmpeg_setup import get_ffmpeg_dir

    ffmpeg_exe = os.path.join(get_ffmpeg_dir(), "ffmpeg.exe" if os.name == 'nt' else "ffmpeg")
    if not os.path.exists(ffmpeg_exe):
        ffmpeg_exe = shutil.which("ffmpeg") or "ffmpeg"

    cmd = [
        ffmpeg_exe,
        "-y",
        "-ss", f"{start_sec:.3f}",
        "-to", f"{end_sec:.3f}",
        "-i", input_path,
        "-c", "copy",
        output_path
    ]

    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo, timeout=15)
        if res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            logger.info(f"[SubclipExport] Subclip recortado con éxito (stream copy) -> {output_path}")
            return True

        cmd_fb = [
            ffmpeg_exe,
            "-y",
            "-ss", f"{start_sec:.3f}",
            "-to", f"{end_sec:.3f}",
            "-i", input_path,
            output_path
        ]
        res_fb = subprocess.run(cmd_fb, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo, timeout=15)
        if res_fb.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            logger.info(f"[SubclipExport] Subclip recortado con éxito (re-encode fallback) -> {output_path}")
            return True
    except Exception as e:
        logger.error(f"[SubclipExport] Error ejecutando FFmpeg para recortar subclip: {e}")

    return False


def unique_subclip_path(dest_dir: str, base_name: str, ext: str) -> str:
    """Genera una ruta de archivo <base_name>_subclip_NN<ext> en dest_dir que no exista todavía,
    incrementando NN desde 01 hasta encontrar un nombre libre."""
    count = 1
    sub_filename = f"{base_name}_subclip_{count:02d}{ext}"
    sub_path = os.path.join(dest_dir, sub_filename).replace("\\", "/")
    while os.path.exists(sub_path):
        count += 1
        sub_filename = f"{base_name}_subclip_{count:02d}{ext}"
        sub_path = os.path.join(dest_dir, sub_filename).replace("\\", "/")
    return sub_path


def exact_or_unique_path(dest_dir: str, base_name: str, ext: str) -> str:
    """Genera <base_name><ext> tal cual en dest_dir si ese nombre está libre -- a diferencia de
    unique_subclip_path, NO agrega "_subclip_NN" por convención, respeta el nombre que se le
    pase. Solo si ya existe un archivo con ese nombre exacto agrega el sufijo numérico mínimo
    (_2, _3, ...) para no pisarlo."""
    base_path = os.path.join(dest_dir, f"{base_name}{ext}").replace("\\", "/")
    if not os.path.exists(base_path):
        return base_path
    count = 2
    while True:
        candidate = os.path.join(dest_dir, f"{base_name}_{count}{ext}").replace("\\", "/")
        if not os.path.exists(candidate):
            return candidate
        count += 1


def export_subclip(input_path: str, in_sec: float, out_sec: float, dest_dir: str = None, base_name: str = None, unique_suffix: bool = True) -> str:
    """Corta físicamente un subclip de input_path entre in_sec/out_sec y lo guarda en dest_dir
    (o en core.utils.paths.get_subclips_dir() si dest_dir es None).

    unique_suffix=True (default): nombre <base_name>_subclip_NN<ext> -- comportamiento original,
    usado por el arrastre en la waveform del Gestor de Medios (ver
    editing_media_playback.py::_on_waveform_subclip_drag_requested), que no se toca.
    unique_suffix=False: respeta <base_name><ext> tal cual (el nombre que el usuario haya puesto
    en la ventana de Edición de Subclips, sin agregarle "_subclip" -- ver
    gui/dialogs/subclip_dialog.py), solo desambiguando con un sufijo numérico si hay colisión
    real de nombre.

    Devuelve la ruta final del archivo generado, o None si el corte con FFmpeg falla."""
    if dest_dir is None:
        from core.utils.paths import get_subclips_dir
        dest_dir = get_subclips_dir()
    os.makedirs(dest_dir, exist_ok=True)

    name_stub, ext = os.path.splitext(os.path.basename(input_path))
    if not ext:
        ext = ".wav"
    base = base_name or name_stub

    sub_path = unique_subclip_path(dest_dir, base, ext) if unique_suffix else exact_or_unique_path(dest_dir, base, ext)

    if cut_subclip_ffmpeg(input_path, sub_path, in_sec, out_sec):
        return sub_path
    return None
