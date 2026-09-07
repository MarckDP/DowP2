# src/core/updater/macos_sign.py
"""Firma ad-hoc de macOS, consolidada en un solo sitio.

Antes vivia solo en build_cross_platform.py, para firmar DowP.app justo
despues de compilar. Ahora tambien la necesita:
  - build_cross_platform.py, sin cambios de fondo, para DowP.app Y para el
    binario suelto del helper de swap (DowP_Updater).
  - swap_executor.py, para volver a firmar DowP.app como ULTIMO paso de un
    swap aplicado -- tocar archivos dentro del bundle rompe la firma
    anterior (trampa ya documentada en ACTUALIZACIONES.md).

Una sola implementacion evita que las dos copias diverjan silenciosamente.
"""
import subprocess


class SigningError(Exception):
    """codesign fallo firmando o verificando. Se lanza en vez de terminar el
    proceso a la fuerza: build_cross_platform.py (un script de un solo uso)
    puede atraparla y salir con sys.exit(1), pero swap_executor.py necesita
    poder atraparla para hacer rollback del swap en vez de morir a medias."""


def adhoc_sign(path: str, deep: bool = True) -> None:
    """Firma ad-hoc (-s -): gratis, sin cuenta de Apple, sin notarizacion.
    No quita el aviso de Gatekeeper (el usuario sigue teniendo que hacer clic
    derecho > Abrir la primera vez), pero es lo que hace que el binario
    ARRANQUE en Apple Silicon -- sin firma, el cargador del sistema lo
    rechaza directamente, no es un aviso saltable.

    deep=True para bundles (.app, que traen dylibs anidadas); deep=False
    alcanza para un binario Mach-O suelto como el helper.

    Verifica de verdad con `codesign --verify` en vez de asumir que salio
    bien -- una firma rota se manifiesta como "no arranca" sin ningun mensaje
    util en la maquina del usuario."""
    cmd = ["codesign", "--force"]
    if deep:
        cmd.append("--deep")
    cmd.extend(["--sign", "-", "--timestamp=none", path])

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        raise SigningError(
            "No se encontro 'codesign'. Viene de serie en macOS; si falta, "
            "instala las Command Line Tools de Xcode."
        )
    except subprocess.CalledProcessError as e:
        raise SigningError(f"codesign fallo firmando {path}:\n{e.stderr}")

    verify_cmd = ["codesign", "--verify", "--strict", "--verbose=2", path]
    if deep:
        verify_cmd.insert(2, "--deep")
    try:
        subprocess.run(verify_cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise SigningError(f"La firma de {path} no verifica:\n{e.stderr}")
