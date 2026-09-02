# src/core/tabs/image_tools/upscale_engine.py
"""Motor de ejecución de "Reescalar IA" -- corre los binarios NCNN-Vulkan (Waifu2x/
SRMD/Upscayl) ya descargados vía Ajustes > Modelos (ver core/setup/models_setup.py).
Comandos exactos portados de DowP1 (video_upscaler.pyc decompilado, método
_build_ncnn_cmd) -- los 3 motores son binarios standalone que hacen todo el trabajo
solos, acá solo se arma la línea de comandos correcta y se corre el proceso."""
import os
import subprocess
import multiprocessing

from core.logger.logger_manager import logger
from core.constants import UPSCALING_TOOLS, WAIFU2X_MODELS, SRMD_MODELS, UPSCAYL_MODELS_MAP
from core.setup.models_setup import get_engine_exe_path
from core.utils.paths import get_models_dir

_POWER_THREADS = {
    "Seguro (Estabilidad)": "1:1:1",
    "Equilibrado": "1:2:1",
    "Máximo (Potente)": "2:4:2",
}

_VULKAN_OOM_HINTS = ("vkQueueSubmit failed", "vkAllocateMemory failed", "invalid gpu device", "out of gpu memory")

_POLL_INTERVAL_SEC = 0.2


def _auto_threads() -> str:
    """"Automático": mismo criterio que _thread_args() de DowP1 -- conservador según
    núcleos disponibles, no el máximo posible."""
    try:
        cpu_count = multiprocessing.cpu_count()
    except NotImplementedError:
        cpu_count = 1
    return "1:2:1" if cpu_count >= 12 else "1:1:1"


def _resolve_threads(power_label: str) -> str:
    return _POWER_THREADS.get(power_label, _auto_threads())


def _model_dir_for(engine: str, model_key: str) -> str:
    """Directorio -m para Waifu2x/SRMD -- carpeta propia por familia de modelo
    (ej. models-cunet), a diferencia de Upscayl que comparte una sola carpeta."""
    tool_info = UPSCALING_TOOLS[engine]
    models_lookup = WAIFU2X_MODELS if engine == "Waifu2x" else SRMD_MODELS
    default_dir = "models-cunet" if engine == "Waifu2x" else "models-srmd"
    internal = models_lookup.get(model_key, {}).get("model", default_dir)
    return os.path.join(get_models_dir(), tool_info["folder"], internal)


def _build_cmd(exe: str, input_path: str, output_path: str, options: dict) -> list[str]:
    engine = options["upscale_engine"]
    scale = (options.get("upscale_scale") or "4x").replace("x", "")
    tile = str(options.get("upscale_tile") or "0")
    threads = _resolve_threads(options.get("upscale_power", "Automático"))
    tta = bool(options.get("upscale_tta"))

    if engine == "Upscayl":
        model_key = options.get("upscale_model") or ""
        # UPSCAYL_MODELS_MAP: clave = nombre crudo del archivo, valor = etiqueta
        # amigable -- el popover guarda la clave cruda en currentData(), así que acá
        # ya viene resuelto (no hace falta invertir el mapa).
        # "models" RELATIVO a propósito -- a diferencia de Waifu2x/SRMD (que sí
        # aceptan -m absoluto, confirmado con una corrida real), upscayl-bin resuelve
        # -m relativo a la carpeta de SU PROPIO ejecutable sin chequear si el valor ya
        # es una ruta absoluta -- pasarle una absoluta la duplica y falla
        # ("Failed to open .../upscayl/C:/.../upscayl/models/...param"), confirmado
        # también con una corrida real.
        model_dir = "models"
        cmd = [exe, "-i", input_path, "-o", output_path, "-n", model_key, "-m", model_dir,
               "-s", scale, "-f", "png", "-j", threads]
        if tile != "0":
            cmd += ["-t", tile]
        z_match = None
        for digit in ("2", "3"):
            if f"x{digit}" in model_key.lower():
                z_match = digit
                break
        if z_match:
            cmd += ["-z", z_match]
        if tta:
            cmd += ["-x"]
        return cmd

    # Waifu2x y SRMD -- misma forma (-n es nivel de ruido, no nombre de modelo).
    model_dir = _model_dir_for(engine, options.get("upscale_model") or "")
    denoise = str(options.get("upscale_denoise", "2 (Alta)")).split(" ")[0]
    cmd = [exe, "-i", input_path, "-o", output_path, "-m", model_dir, "-n", denoise,
           "-s", scale, "-t", tile, "-f", "png", "-j", threads]
    if tta:
        cmd += ["-x"]
    return cmd


def run_upscale(input_path: str, output_path: str, options: dict, cancellation_event=None) -> tuple[bool, str]:
    """Corre el motor de "upscale_engine" (Waifu2x/SRMD/Upscayl) sobre UNA imagen.
    Siempre escribe PNG (-f png, igual que DowP1) -- quien llame se encarga de volver
    a cargar el resultado y seguir el pipeline de guardado al formato final."""
    engine = options.get("upscale_engine")
    tool_info = UPSCALING_TOOLS.get(engine)
    if tool_info is None:
        return False, f"Motor de reescalado desconocido: {engine}"

    exe = get_engine_exe_path(tool_info)
    if not exe or not os.path.exists(exe):
        return False, f"'{tool_info['name']}' no está instalado -- andá a Ajustes > Modelos para descargarlo."

    cmd = _build_cmd(exe, input_path, output_path, options)
    logger.info(f"Reescalar IA: {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            # encoding/errors explícitos -- confirmado con una corrida real: upscayl-bin
            # imprime bytes que no son válidos en cp1252 (la codificación default de
            # Popen(text=True) en Windows), y eso hacía crashear communicate() con
            # UnicodeDecodeError en vez de simplemente reportar el error del motor.
            encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except Exception as e:
        return False, f"No se pudo iniciar el motor '{tool_info['name']}': {e}"

    stderr_output = ""
    try:
        while True:
            if cancellation_event and cancellation_event.is_set():
                proc.kill()
                proc.wait(timeout=2.0)
                return False, "Cancelado por el usuario."
            try:
                _, stderr_output = proc.communicate(timeout=_POLL_INTERVAL_SEC)
                break
            except subprocess.TimeoutExpired:
                continue
    except Exception as e:
        proc.kill()
        return False, f"Error esperando al motor '{tool_info['name']}': {e}"

    if proc.returncode != 0:
        tail = (stderr_output or "")[-500:]
        if any(hint in (stderr_output or "") for hint in _VULKAN_OOM_HINTS):
            return False, (
                f"'{tool_info['name']}' se quedó sin memoria de GPU -- probá bajar el "
                f"Tile Size a 128 o 64. Detalle: {tail}"
            )
        return False, f"'{tool_info['name']}' falló (código {proc.returncode}): {tail}"

    if not os.path.exists(output_path) or os.path.getsize(output_path) < 100:
        return False, f"'{tool_info['name']}' no generó una salida válida."

    return True, "Reescalado completado."
