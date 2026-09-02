# src/core/setup/models_setup.py
"""Descarga e instalación de modelos de IA (rembg, motores de upscaling NCNN-Vulkan).

A diferencia de las dependencias (ffmpeg, yt-dlp, etc., ver core/setup/ffmpeg_setup.py),
los modelos NUNCA se descargan solos al abrir la app -- solo cuando el usuario los pide
desde Ajustes > Modelos (o, más adelante, desde el Editor de Imagen). Mismo patrón de
descarga que el resto de core/setup/*.py (requests streamed + callback de porcentaje,
sin checksum -- DowP 1 tampoco lo hacía)."""
import os
import shutil
import sys
import tempfile
import zipfile
import requests
from core.logger.logger_manager import logger
from core.utils.paths import get_models_dir


def _current_platform() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _platform_value(value):
    """Resuelve un campo que puede ser un dict {"windows"/"macos"/"linux": ...} (motores
    de upscaling, un binario y una URL de release distintos por SO) o un string plano
    (modelos rembg: son .onnx, el mismo archivo sirve para los tres SO) -- devuelve
    directo el string, o None si el dict no tiene build para la plataforma actual."""
    if isinstance(value, dict):
        return value.get(_current_platform())
    return value


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


def get_engine_exe_path(tool_info: dict) -> str | None:
    """Ruta completa al ejecutable del motor para la plataforma actual, o None si
    ese motor no tiene build para este SO (ver _platform_value) -- usada tanto para
    chequear instalación acá como para invocarlo de verdad desde
    core/tabs/image_tools/upscale_engine.py."""
    exe_name = _platform_value(tool_info["exe"])
    if not exe_name:
        return None
    return os.path.join(_engine_dir(tool_info), exe_name)


def is_upscaling_engine_installed(tool_info: dict) -> bool:
    exe_path = get_engine_exe_path(tool_info)
    return exe_path is not None and os.path.exists(exe_path)


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


# Upscayl es deliberadamente "más global" que el repo custom-models solo -- estos 2
# releases oficiales (Real-ESRGAN/RealSR) aportan modelos que custom-models no tiene
# (ver la nota en UPSCAYL_MODELS_MAP, core/constants.py). Un solo URL por fuente
# alcanza para los 3 SO: los .bin/.param son datos de pesos, idénticos sin importar
# qué build (windows/macos/ubuntu) del binario los acompañe -- confirmado contra el
# árbol real de ambos releases en GitHub, así que no hace falta _platform_value() acá,
# a diferencia de UPSCALING_TOOLS (que sí baja un ejecutable real por SO).
_UPSCAYL_LEGACY_MODEL_SOURCES = [
    ("Real-ESRGAN", "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip", "realesrgan-x4plus.bin"),
    ("RealSR", "https://github.com/nihui/realsr-ncnn-vulkan/releases/download/20220728/realsr-ncnn-vulkan-20220728-windows.zip", "DF2K_x4.bin"),
]

# Ver sanitize_upscayl_models() en el setup.pyc decompilado de DowP1: purga estos 2
# modelos por inestabilidad conocida (no se ofrecen ni en UPSCAYL_MODELS_MAP ni acá).
_UPSCAYL_UNSTABLE_MODELS = ("realesr-animevideov3-x2", "realesr-animevideov3-x3")


def _sanitize_upscayl_models(models_dir: str):
    """Purga modelos conocidos por causar errores/inestabilidad -- mismo criterio que
    sanitize_upscayl_models() en DowP1."""
    if not os.path.isdir(models_dir):
        return
    for name in _UPSCAYL_UNSTABLE_MODELS:
        for ext in (".bin", ".param"):
            path = os.path.join(models_dir, name + ext)
            if os.path.exists(path):
                try:
                    os.remove(path)
                    logger.info(f"Upscayl: modelo purgado por inestabilidad -- {name}{ext}")
                except OSError as e:
                    logger.warning(f"Upscayl: no se pudo purgar {name}{ext}: {e}")


def _download_upscayl_legacy_models(models_dir: str, progress_callback=None):
    """Descarga los modelos de Real-ESRGAN/RealSR que NO vienen en custom-models --
    mismo criterio que DowP1 (canario: si el archivo ya está, se salta la descarga
    completa, evita re-bajar ~60-80MB en cada instalación). Se filtran solo .bin/
    .param del zip completo (que también trae el ejecutable/LICENSE/README de ese
    proyecto, irrelevantes acá)."""
    os.makedirs(models_dir, exist_ok=True)
    for name, url, canary in _UPSCAYL_LEGACY_MODEL_SOURCES:
        if os.path.exists(os.path.join(models_dir, canary)):
            logger.info(f"Upscayl: modelos de {name} ya presentes, se omite su descarga.")
            continue
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                extract_dir = os.path.join(tmp_dir, "extracted")
                logger.info(f"Upscayl: descargando modelos legacy de {name} desde {url}")
                _download_and_extract_zip(url, extract_dir, progress_callback)
                for root, _dirs, files in os.walk(extract_dir):
                    for fname in files:
                        if not fname.endswith((".bin", ".param")):
                            continue
                        dst_name = fname
                        parent_name = os.path.basename(root)
                        # El zip de RealSR trae sub-modelos nombrados genéricamente
                        # "x4.bin"/"x4.param" dentro de subcarpetas "models-DF2K"/
                        # "models-DF2K_JPEG" -- sin prefijo se pisarían entre sí, así
                        # que se renombran igual que hacía DowP1 (nombre de la
                        # subcarpeta sin el prefijo "models-" + "_" + nombre original).
                        if fname.startswith("x4") and parent_name.startswith("models-"):
                            dst_name = f"{parent_name[len('models-'):]}_{fname}"
                        dst_path = os.path.join(models_dir, dst_name)
                        if not os.path.exists(dst_path):
                            shutil.copy2(os.path.join(root, fname), dst_path)
        except Exception as e:
            logger.warning(f"Upscayl: no se pudieron descargar los modelos legacy de {name}: {e}")
    _sanitize_upscayl_models(models_dir)


def download_upscaling_engine(tool_info: dict, progress_callback=None) -> tuple[bool, str]:
    """Descarga e instala un motor de upscaling NCNN-Vulkan completo (ejecutable +
    modelos que trae el propio zip) en bin/models/{folder}. Si el motor además define
    `models_url` (ej. Upscayl), descarga ese zip de modelos aparte, directo en
    {folder}/ -- NO en {folder}/models/: el repo custom-models de Upscayl ya trae su
    propia carpeta "models/" adentro (una vez desenvuelto el wrapper de GitHub
    Archive, ver _download_and_extract_zip), así que fusionarlo en {folder}/models/
    duplicaba el nivel y dejaba los .param en {folder}/models/models/ -- confirmado
    con una descarga real (ver upscale_engine.py, que espera {folder}/models/*.param
    directo). El release de GitHub trae un .zip distinto por SO (windows/macos/
    linux) -- ver _platform_value()."""
    try:
        url = _platform_value(tool_info["url"])
        if not url:
            return False, f"'{tool_info['name']}' no tiene una build disponible para este sistema operativo."

        dest_dir = _engine_dir(tool_info)
        has_models_zip = bool(tool_info.get("models_url"))
        is_upscayl = tool_info.get("folder") == "upscayl"
        engine_weight = (0, 40) if has_models_zip else (0, 100)

        logger.info(f"Descargando motor de upscaling '{tool_info['name']}' desde {url}")
        _download_and_extract_zip(url, dest_dir, progress_callback, weight=engine_weight)

        if has_models_zip:
            logger.info(f"Descargando modelos de '{tool_info['name']}' desde {tool_info['models_url']}")
            _download_and_extract_zip(tool_info["models_url"], dest_dir, progress_callback,
                                       weight=(40, 70) if is_upscayl else (40, 100))

        if is_upscayl:
            _download_upscayl_legacy_models(os.path.join(dest_dir, "models"), progress_callback)

        if not is_upscaling_engine_installed(tool_info):
            return False, f"No se encontró {_platform_value(tool_info['exe'])} tras la instalación."

        if _current_platform() != "windows":
            # Los binarios de macOS/Linux necesitan el bit +x -- zipfile no siempre
            # preserva los permisos unix del zip al extraer, así que se fuerza acá
            # en vez de depender de eso.
            exe_path = os.path.join(dest_dir, _platform_value(tool_info["exe"]))
            os.chmod(exe_path, 0o755)

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
