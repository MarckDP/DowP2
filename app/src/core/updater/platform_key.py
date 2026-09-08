# src/core/updater/platform_key.py
"""Clave de plataforma del manifiesto del updater ("windows-x64", "macos-arm64", ...).

Compartida a proposito entre el cliente (este paquete, viaja con la app) y
tools/updater/publish.py (fuera del bundle, se importa via sys.path igual que
ya hace con version.py) -- que ambos calculen la clave con la MISMA funcion es
lo que evita que un publicador tecleado a mano ("--platform windows-x64" vs
"win-x64" vs "windows_x64") deje un manifiesto que el cliente nunca encuentra
para su plataforma real.
"""
import platform


def get_platform_key() -> str:
    system = platform.system()
    machine = platform.machine().lower()
    is_arm = machine in ("arm64", "aarch64")

    if system == "Windows":
        return "windows-arm64" if is_arm else "windows-x64"
    if system == "Darwin":
        return "macos-arm64" if is_arm else "macos-x64"
    if system == "Linux":
        return "linux-arm64" if is_arm else "linux-x64"

    raise RuntimeError(f"Sistema operativo no soportado por el updater: {system}")
