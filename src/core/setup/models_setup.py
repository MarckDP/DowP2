# src/core/setup/models_setup.py
"""Descarga e instalación de modelos de IA (rembg, motores de upscaling NCNN-Vulkan).

A diferencia de las dependencias (ffmpeg, yt-dlp, etc., ver core/setup/ffmpeg_setup.py),
los modelos NUNCA se descargan solos al abrir la app -- solo cuando el usuario los pide
desde Ajustes > Modelos (o, más adelante, desde el Editor de Imagen). Mismo patrón de
descarga que el resto de core/setup/*.py (requests streamed + callback de porcentaje,
sin checksum -- DowP 1 tampoco lo hacía)."""
import os
import shutil
import tempfile
import zipfile
import requests
from core.logger.logger_manager import logger
from core.utils.paths import get_models_dir


def _model_path(model_info: dict) -> str:
    return os.path.join(get_models_dir(), model_info["folder"], model_info["file"])


def is_rembg_model_installed(model_info: dict) -> bool:
    path = _model_path(model_info)
    return os.path.exists(path) and os.path.getsize(path) > 1024


def is_rembg_model_gated(model_info: dict) -> bool:
    """True si la URL apunta a una página de HuggingFace (no a un archivo directo) --
    esos modelos necesitan descarga manual con cuenta, no se pueden bajar solos."""
    url = model_info.get("url", "")
    return "huggingface.co" in url and "/resolve/" not in url and "?download=" not in url


def download_rembg_model(model_info: dict, progress_callback=None) -> tuple[bool, str]:
    """Descarga un modelo rembg a bin/models/{folder}/{file}, con .part temporal y
    rename atómico al terminar (evita dejar un archivo corrupto a medias si se corta)."""
    part_path = None
    try:
        target_path = _model_path(model_info)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        part_path = target_path + ".part"

        logger.info(f"Descargando modelo rembg desde {model_info['url']}")
        r = requests.get(model_info["url"], stream=True, timeout=30)
        r.raise_for_status()

        total_size = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(part_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total_size > 0:
                        progress_callback(int((downloaded / total_size) * 100))

        if os.path.exists(target_path):
            os.remove(target_path)
        os.rename(part_path, target_path)

        if not is_rembg_model_installed(model_info):
            return False, "El archivo descargado quedó vacío o incompleto."
        logger.info(f"Modelo rembg instalado en {target_path}")
        return True, "Modelo descargado correctamente."
    except Exception as e:
        logger.error(f"Error descargando modelo rembg '{model_info.get('file')}': {e}")
        try:
            if part_path and os.path.exists(part_path):
                os.remove(part_path)
        except Exception:
            pass
        return False, str(e)


def delete_rembg_model(model_info: dict) -> bool:
    try:
        path = _model_path(model_info)
        if os.path.exists(path):
            os.remove(path)
        return True
    except Exception as e:
        logger.error(f"Error eliminando modelo rembg '{model_info.get('file')}': {e}")
        return False


def _engine_dir(tool_info: dict) -> str:
    return os.path.join(get_models_dir(), tool_info["folder"])


def is_upscaling_engine_installed(tool_info: dict) -> bool:
    exe_path = os.path.join(_engine_dir(tool_info), tool_info["exe"])
    return os.path.exists(exe_path)


def _download_and_extract_zip(url: str, dest_dir: str, progress_callback=None, weight=(0, 100)):
    """Descarga un zip a un temporal, lo extrae, y fusiona su contenido en dest_dir --
    si el zip trae todo envuelto en una única subcarpeta (patrón común de releases de
    GitHub), fusiona esa subcarpeta directo en vez de crear un nivel de anidación extra."""
    start_pct, end_pct = weight
    span = end_pct - start_pct

    with tempfile.TemporaryDirectory() as tmp_dir:
        temp_zip = os.path.join(tmp_dir, "download.zip")
        r = requests.get(url, stream=True, timeout=30)
        r.raise_for_status()
        total_size = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(temp_zip, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total_size > 0:
                        pct = start_pct + int((downloaded / total_size) * span)
                        progress_callback(pct)

        extract_dir = os.path.join(tmp_dir, "extracted")
        with zipfile.ZipFile(temp_zip, "r") as zip_ref:
            zip_ref.extractall(extract_dir)

        # Si todo el contenido quedó envuelto en una única subcarpeta, fusionar esa
        # subcarpeta directo en vez de duplicar el nivel de anidación.
        entries = os.listdir(extract_dir)
        source_dir = extract_dir
        if len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0])):
            source_dir = os.path.join(extract_dir, entries[0])

        os.makedirs(dest_dir, exist_ok=True)
        try:
            shutil.copytree(source_dir, dest_dir, dirs_exist_ok=True)
        except Exception as e:
            logger.warning(f"copytree falló fusionando en {dest_dir} ({e}), reintentando con rmtree+move")
            if os.path.exists(dest_dir):
                shutil.rmtree(dest_dir)
            shutil.move(source_dir, dest_dir)


def download_upscaling_engine(tool_info: dict, progress_callback=None) -> tuple[bool, str]:
    """Descarga e instala un motor de upscaling NCNN-Vulkan completo (ejecutable +
    modelos que trae el propio zip) en bin/models/{folder}. Si el motor además define
    `models_url` (ej. Upscayl), descarga ese zip de modelos aparte en {folder}/models."""
    try:
        dest_dir = _engine_dir(tool_info)
        has_models_zip = bool(tool_info.get("models_url"))
        engine_weight = (0, 60) if has_models_zip else (0, 100)

        logger.info(f"Descargando motor de upscaling '{tool_info['name']}' desde {tool_info['url']}")
        _download_and_extract_zip(tool_info["url"], dest_dir, progress_callback, weight=engine_weight)

        if has_models_zip:
            models_dest = os.path.join(dest_dir, "models")
            logger.info(f"Descargando modelos de '{tool_info['name']}' desde {tool_info['models_url']}")
            _download_and_extract_zip(tool_info["models_url"], models_dest, progress_callback, weight=(60, 100))

        if not is_upscaling_engine_installed(tool_info):
            return False, f"No se encontró {tool_info['exe']} tras la instalación."
        logger.info(f"Motor '{tool_info['name']}' instalado en {dest_dir}")
        return True, "Motor instalado correctamente."
    except Exception as e:
        logger.error(f"Error instalando motor de upscaling '{tool_info.get('name')}': {e}")
        return False, str(e)


def delete_upscaling_engine(tool_info: dict) -> bool:
    try:
        dest_dir = _engine_dir(tool_info)
        if os.path.exists(dest_dir):
            shutil.rmtree(dest_dir)
        return True
    except Exception as e:
        logger.error(f"Error eliminando motor de upscaling '{tool_info.get('name')}': {e}")
        return False


def get_folder_size(path: str) -> int:
    """Suma recursiva del tamaño en disco de un archivo o carpeta (0 si no existe)."""
    if not os.path.exists(path):
        return 0
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _dirs, files in os.walk(path):
        for fname in files:
            try:
                total += os.path.getsize(os.path.join(root, fname))
            except OSError:
                pass
    return total
