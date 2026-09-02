# src/core/setup/ghostscript_setup.py
"""Descarga e instalación de Ghostscript -- dependencia OPCIONAL (Ajustes >
Dependencias, ver gui/tabs/settings/pages/deps_page.py) que habilita EPS/PS en
el Editor de Imagen (ver core/tabs/image_tools/image_converter.py::_load_eps_ps).

Windows-only por ahora: el único release oficial (ArtifexSoftware/ghostpdl-
downloads) es un instalador NSIS, sin build portable ni instalación silenciosa
desde la 10.01.0 -- así que en vez de correr el instalador, se lo EXTRAE con
7-Zip sin ejecutarlo (confirmado que funciona: el instalador se abre como
archivo NSIS y expone bin/gswin64c.exe + lib/ + Resource/ intactos, la
disposición estándar que Ghostscript necesita en tiempo de ejecución).

7-Zip en sí no es una dependencia del proyecto (no hay ninguna acá) -- se
bootstrapea desde el paquete NuGet "7-Zip.x64" (un ZIP plano, a diferencia de
la "Extra" del propio 7-zip.org, que es un .7z y sería circular). Se cachea
una sola vez en bin/dependences/_tools/7zip/ (prefijo "_tools": detalle interno,
no es una tarjeta propia de Ajustes)."""
import os
import platform
import shutil
import subprocess
import tempfile
import zipfile

import requests

from core.logger.logger_manager import logger

GS_VERSION = "10.07.1"
_GS_INSTALLER_URL = (
    "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/"
    "gs10071/gs10071w64.exe"
)
# 7-Zip.x64 16.2.1 -- verificado en vivo: ZIP plano, trae tools/7z.exe +
# tools/7z.dll (el 7-Zip completo, con soporte NSIS vía plugin -- a diferencia
# de "7-Zip.CommandLine", cuyo 7za.exe es la build standalone SIN plugins y
# falla con "Unsupported archive type" al pedirle NSIS).
_SEVENZIP_NUGET_URL = "https://www.nuget.org/api/v2/package/7-Zip.x64/16.2.1"
_GS_KEEP_DIRS = ("bin", "lib", "Resource")


def get_managed_ghostscript_dir() -> str:
    """Mismo patrón que get_managed_ffmpeg_dir() (ffmpeg_setup.py)."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    gs_dir = os.path.join(base_dir, "bin", "dependences", "ghostscript")
    os.makedirs(gs_dir, exist_ok=True)
    return gs_dir


def _tools_dir() -> str:
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    d = os.path.join(base_dir, "bin", "dependences", "_tools", "7zip")
    os.makedirs(d, exist_ok=True)
    return d


def _ensure_7zip_tool(progress_callback=None) -> str | None:
    """Devuelve la ruta a un 7z.exe usable (con su 7z.dll al lado), descargando
    y cacheando el paquete NuGet la primera vez -- None si algo falla."""
    tools_dir = _tools_dir()
    exe_path = os.path.join(tools_dir, "7z.exe")
    dll_path = os.path.join(tools_dir, "7z.dll")
    if os.path.isfile(exe_path) and os.path.isfile(dll_path):
        return exe_path

    try:
        with tempfile.TemporaryDirectory(prefix="dowp_7zip_") as tmp_dir:
            temp_zip = os.path.join(tmp_dir, "7zip.nupkg")
            r = requests.get(_SEVENZIP_NUGET_URL, stream=True, timeout=30)
            r.raise_for_status()
            total_size = int(r.headers.get("content-length", 0))
            downloaded = 0
            with open(temp_zip, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size > 0:
                            progress_callback(int((downloaded / total_size) * 10))

            with zipfile.ZipFile(temp_zip, "r") as zip_ref:
                zip_ref.extract("tools/7z.exe", tmp_dir)
                zip_ref.extract("tools/7z.dll", tmp_dir)

            shutil.copy2(os.path.join(tmp_dir, "tools", "7z.exe"), exe_path)
            shutil.copy2(os.path.join(tmp_dir, "tools", "7z.dll"), dll_path)
        return exe_path
    except Exception as e:
        logger.error(f"Ghostscript: no se pudo preparar la herramienta de extracción (7-Zip): {e}")
        return None


def check_ghostscript() -> bool:
    """True solo en Windows con Ghostscript ya instalado -- en Mac/Linux
    siempre False por ahora (no hay build bundleable, ver nota en
    core/constants.py; a futuro: detectar un `gs` del sistema ahí)."""
    if platform.system() != "Windows":
        return False
    exe = get_gs_exe_path()
    return bool(exe and os.path.isfile(exe))


def get_gs_exe_path() -> str | None:
    """Ruta al gswin64c.exe gestionado, o None si no aplica a este SO / no está
    instalado todavía."""
    if platform.system() != "Windows":
        return None
    return os.path.join(get_managed_ghostscript_dir(), "bin", "gswin64c.exe")


def get_local_version() -> str | None:
    return GS_VERSION if check_ghostscript() else None


def download_ghostscript(progress_callback=None) -> tuple[bool, str]:
    """Descarga el instalador oficial de Ghostscript y lo extrae con 7-Zip SIN
    ejecutarlo (ver nota del módulo) -- deja bin/lib/Resource listos en
    get_managed_ghostscript_dir()."""
    if platform.system() != "Windows":
        return False, "Ghostscript solo está disponible en Windows por ahora."

    try:
        seven_zip = _ensure_7zip_tool(progress_callback)
        if not seven_zip:
            return False, "No se pudo preparar la herramienta de extracción (7-Zip)."

        with tempfile.TemporaryDirectory(prefix="dowp_ghostscript_") as tmp_dir:
            installer_path = os.path.join(tmp_dir, "gs_installer.exe")
            logger.info(f"Ghostscript: descargando instalador desde {_GS_INSTALLER_URL}")
            r = requests.get(_GS_INSTALLER_URL, stream=True, timeout=60)
            r.raise_for_status()
            total_size = int(r.headers.get("content-length", 0))
            downloaded = 0
            with open(installer_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=16384):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size > 0:
                            pct = 10 + int((downloaded / total_size) * 60)
                            progress_callback(pct)

            extract_dir = os.path.join(tmp_dir, "extracted")
            logger.info("Ghostscript: extrayendo el instalador con 7-Zip (sin ejecutarlo)...")
            result = subprocess.run(
                [seven_zip, "x", installer_path, f"-o{extract_dir}", "-y"],
                capture_output=True, text=True, timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if progress_callback:
                progress_callback(90)
            if result.returncode != 0:
                logger.error(f"Ghostscript: 7-Zip falló extrayendo el instalador: {result.stderr}")
                return False, f"No se pudo extraer el instalador: {result.stderr[:300]}"

            extracted_bin = os.path.join(extract_dir, "bin", "gswin64c.exe")
            if not os.path.isfile(extracted_bin):
                return False, "El instalador se extrajo pero no se encontró gswin64c.exe."

            dest_dir = get_managed_ghostscript_dir()
            if os.path.isdir(dest_dir):
                shutil.rmtree(dest_dir, ignore_errors=True)
            os.makedirs(dest_dir, exist_ok=True)
            for name in _GS_KEEP_DIRS:
                src = os.path.join(extract_dir, name)
                if os.path.isdir(src):
                    shutil.copytree(src, os.path.join(dest_dir, name))

        if progress_callback:
            progress_callback(100)

        if not check_ghostscript():
            return False, "La instalación terminó pero Ghostscript no quedó detectable."

        logger.info(f"Ghostscript: instalación completada en {get_managed_ghostscript_dir()}")
        return True, f"Ghostscript {GS_VERSION} instalado correctamente."
    except Exception as e:
        logger.error(f"Ghostscript: error durante la descarga/instalación: {e}", exc_info=True)
        return False, str(e)
