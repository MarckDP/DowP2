# src/core/utils/hardware_detector.py
import os
import platform
import subprocess
import time
from core.logger.logger_manager import logger
from core.setup.setup_manager import get_dependency_env
from core.utils.config_manager import get_config, save_config


def _get_os_name() -> str:
    """Obtiene el nombre comercial exacto del sistema operativo (ej. Windows 11 Pro)."""
    os_system = platform.system()
    arch = platform.architecture()[0]
    try:
        if os_system == "Windows":
            cmd = 'powershell -NoProfile -Command "(Get-CimInstance Win32_OperatingSystem).Caption"'
            res = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=3)
            caption = res.stdout.strip()
            if caption:
                clean_name = caption.replace("Microsoft ", "").strip()
                return f"{clean_name} ({arch})"
            
            import sys
            winver = sys.getwindowsversion()
            if winver.major == 10 and winver.build >= 22000:
                return f"Windows 11 ({arch})"
            elif winver.major == 10:
                return f"Windows 10 ({arch})"
        elif os_system == "Darwin":
            res = subprocess.run(["sw_vers", "-productVersion"], capture_output=True, text=True, timeout=3)
            ver = res.stdout.strip()
            if ver:
                return f"macOS {ver} ({arch})"
        elif os_system == "Linux":
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release", "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("PRETTY_NAME="):
                            pretty = line.split("=")[1].strip().strip('"')
                            return f"{pretty} ({arch})"
    except Exception as e:
        logger.debug(f"HardwareDetector: Error detectando OS: {e}")

    return f"{os_system} {platform.release()} ({arch})"


def _get_cpu_name() -> str:
    """Obtiene el nombre exacto del procesador según el sistema operativo."""
    os_system = platform.system()
    try:
        if os_system == "Windows":
            cmd = 'powershell -NoProfile -Command "(Get-CimInstance Win32_Processor).Name"'
            res = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=3)
            name = res.stdout.strip()
            if name:
                return name.split('\n')[0].strip()
        elif os_system == "Darwin":
            res = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=3)
            name = res.stdout.strip()
            if name:
                return name
        elif os_system == "Linux":
            with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
                for line in f:
                    if "model name" in line:
                        return line.split(":")[1].strip()
    except Exception as e:
        logger.debug(f"HardwareDetector: Fallo detectando CPU: {e}")

    return platform.processor() or platform.machine() or "Procesador Estándar"


def _get_gpu_name() -> str:
    """Obtiene el nombre de la tarjeta gráfica activa según el sistema operativo."""
    os_system = platform.system()
    try:
        if os_system == "Windows":
            cmd = 'powershell -NoProfile -Command "(Get-CimInstance Win32_VideoController).Name"'
            res = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=3)
            lines = [line.strip() for line in res.stdout.strip().split('\n') if line.strip()]
            if lines:
                return " / ".join(lines)
        elif os_system == "Darwin":
            cmd = "system_profiler SPDisplaysDataType | grep 'Chipset Model'"
            res = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=3)
            lines = [line.split(":")[1].strip() for line in res.stdout.strip().split('\n') if ":" in line]
            if lines:
                return " / ".join(lines)
            return "Apple Silicon GPU" if platform.processor() == "arm" or platform.machine().startswith("arm") else "macOS GPU"
        elif os_system == "Linux":
            res = subprocess.run("lspci | grep -i 'vga\\|3d'", capture_output=True, text=True, shell=True, timeout=3)
            lines = [line.split(":")[-1].strip() for line in res.stdout.strip().split('\n') if line.strip()]
            if lines:
                return " / ".join(lines)
    except Exception as e:
        logger.debug(f"HardwareDetector: Fallo detectando GPU: {e}")

    return "Gráficos integrados / Estándar"


def _get_ffmpeg_supported_encoders() -> tuple[list[str], str]:
    """
    Inspecciona el ejecutable ffmpeg.exe empaquetado para listar los encoders
    disponibles en este sistema y determinar el mejor encoder por hardware.
    """
    env = get_dependency_env()
    ffmpeg_exe = "ffmpeg"
    supported = []
    
    # Encoders posibles a verificar en orden de prioridad
    candidate_encoders = [
        ("h264_nvenc", "NVIDIA NVENC", "NVIDIA"),
        ("h264_videotoolbox", "Apple VideoToolbox", "Apple"),
        ("h264_qsv", "Intel QuickSync", "Intel"),
        ("h264_amf", "AMD AMF", "AMD"),
        ("h264_vaapi", "Linux VA-API", "Linux"),
        ("libx264", "CPU Software (x264)", "CPU"),
    ]

    try:
        res = subprocess.run([ffmpeg_exe, "-encoders"], capture_output=True, text=True, env=env, timeout=4)
        stdout = res.stdout
        for enc_code, label, vendor in candidate_encoders:
            if f"V..... {enc_code}" in stdout or f"V....D {enc_code}" in stdout or enc_code in stdout:
                supported.append(enc_code)
    except Exception as e:
        logger.warning(f"HardwareDetector: Error al ejecutar ffmpeg -encoders: {e}")
        supported = ["libx264"]

    if not supported:
        supported = ["libx264"]

    # Seleccionar el encoder preferido por prioridad
    priority_order = ["h264_nvenc", "h264_videotoolbox", "h264_qsv", "h264_amf", "h264_vaapi", "libx264"]
    preferred = "libx264"
    for enc in priority_order:
        if enc in supported:
            preferred = enc
            break

    return supported, preferred


def _get_ram_info() -> str:
    """Obtiene la memoria RAM total instalada en el sistema."""
    os_system = platform.system()
    try:
        if os_system == "Windows":
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                gb = stat.ullTotalPhys / (1024 ** 3)
                return f"{gb:.1f} GB"
        elif os_system == "Darwin":
            res = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=3)
            bytes_val = int(res.stdout.strip())
            gb = bytes_val / (1024 ** 3)
            return f"{gb:.1f} GB"
        elif os_system == "Linux":
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    if "MemTotal" in line:
                        kb = int(line.split(":")[1].replace("kB", "").strip())
                        gb = kb / (1024 ** 2)
                        return f"{gb:.1f} GB"
    except Exception as e:
        logger.debug(f"HardwareDetector: Error detectando RAM: {e}")

    return "No detectada"


def _generate_ffmpeg_log_files(supported_encoders: list, preferred_encoder: str) -> tuple[str, str]:
    """
    Genera el log de capacidades en formato JSON (ffmpeg_encoders_log.json)
    y el informe estructurado básico en JSON (ffmpeg_capabilities.json) en AppData.
    """
    import json
    from core.utils.paths import get_app_data_dir
    app_data = get_app_data_dir()
    log_json_path = os.path.join(app_data, "ffmpeg_encoders_log.json")
    json_path = os.path.join(app_data, "ffmpeg_capabilities.json")
    env = get_dependency_env()

    # 1. Generar JSON estructurado para el motor de la app
    hw_accel_status = {
        "nvenc": "h264_nvenc" in supported_encoders,
        "videotoolbox": "h264_videotoolbox" in supported_encoders,
        "qsv": "h264_qsv" in supported_encoders,
        "amf": "h264_amf" in supported_encoders,
        "vaapi": "h264_vaapi" in supported_encoders,
    }

    capabilities_json = {
        "preferred_encoder": preferred_encoder,
        "supported_video_encoders": supported_encoders,
        "hardware_acceleration": hw_accel_status,
        "is_gpu_accelerated": preferred_encoder != "libx264",
        "last_scan_timestamp": int(time.time()),
    }

    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(capabilities_json, f, indent=2, ensure_ascii=False)
        logger.info(f"HardwareDetector: Archivo JSON de capacidades creado en: {json_path}")
    except Exception as e:
        logger.error(f"HardwareDetector: No se pudo escribir ffmpeg_capabilities.json: {e}")

    # 2. Generar JSON completo de capacidades
    full_log_data = {
        "app_info": "DowP 2.0 - Informe Completo de Capacidades de FFmpeg",
        "diagnostic_date": time.strftime('%Y-%m-%d %H:%M:%S'),
        "detected_preferred_encoder": preferred_encoder,
        "supported_encoders_summary": supported_encoders,
        "capabilities": {}
    }

    sections = {
        "version": ["ffmpeg", "-version"],
        "encoders": ["ffmpeg", "-encoders"],
        "decoders": ["ffmpeg", "-decoders"],
        "formats": ["ffmpeg", "-formats"],
        "filters": ["ffmpeg", "-filters"],
        "muxers": ["ffmpeg", "-muxers"],
        "demuxers": ["ffmpeg", "-demuxers"],
        "codecs": ["ffmpeg", "-codecs"],
        "hwaccels": ["ffmpeg", "-hwaccels"],
        "protocols": ["ffmpeg", "-protocols"],
        "bsfs": ["ffmpeg", "-bsfs"],
        "layouts": ["ffmpeg", "-layouts"],
        "colors": ["ffmpeg", "-colors"]
    }

    for key, cmd in sections.items():
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=5)
            output = res.stdout or res.stderr or ""
            full_log_data["capabilities"][key] = [line for line in output.split("\n") if line.strip()]
        except Exception as e:
            full_log_data["capabilities"][key] = [f"Error al ejecutar {' '.join(cmd)}: {e}"]

    try:
        with open(log_json_path, "w", encoding="utf-8") as f:
            json.dump(full_log_data, f, indent=2, ensure_ascii=False)
        logger.info(f"HardwareDetector: Log de capacidades de FFmpeg generado en: {log_json_path}")
    except Exception as e:
        logger.error(f"HardwareDetector: No se pudo escribir ffmpeg_encoders_log.json: {e}")

    return log_json_path, json_path


def detect_hardware(force_refresh: bool = False) -> dict:
    """
    Realiza la detección completa del hardware y la guarda en la configuración.
    Si force_refresh es False y ya existe hardware_info en la config y el archivo log existe, lo devuelve directamente.
    """
    config = get_config()
    cached_info = config.get("hardware_info", {})
    from core.utils.paths import get_app_data_dir
    log_path = os.path.join(get_app_data_dir(), "ffmpeg_encoders_log.json")

    if not force_refresh and cached_info and cached_info.get("cpu_name") and cached_info.get("ram_size") and os.path.exists(log_path):
        return cached_info

    logger.info("HardwareDetector: Iniciando escaneo de hardware del sistema...")
    start_time = time.time()
    
    cpu_name = _get_cpu_name()
    gpu_name = _get_gpu_name()
    ram_size = _get_ram_info()
    supported_encoders, preferred_encoder = _get_ffmpeg_supported_encoders()
    txt_log_path, json_log_path = _generate_ffmpeg_log_files(supported_encoders, preferred_encoder)
    
    os_name = _get_os_name()
    
    hardware_info = {
        "os_name": os_name,
        "cpu_name": cpu_name,
        "gpu_name": gpu_name,
        "ram_size": ram_size,
        "preferred_encoder": preferred_encoder,
        "supported_encoders": supported_encoders,
        "ffmpeg_log_path": txt_log_path,
        "ffmpeg_json_path": json_log_path,
        "last_checked": int(time.time()),
        "scan_duration_sec": round(time.time() - start_time, 2)
    }

    config["hardware_info"] = hardware_info
    save_config(config)
    logger.info(f"HardwareDetector: Escaneo finalizado. RAM: {ram_size} | Encoder preferido: '{preferred_encoder}' en {hardware_info['scan_duration_sec']}s")
    
    return hardware_info
