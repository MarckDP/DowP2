# tools/updater/smoke_test_swap.py
"""Prueba de humo del helper de swap contra un build YA COMPILADO real.

NUNCA toca el --dist original: copia el arbol entero, simula una actualizacion
de un archivo pequeno dentro de la copia, y aplica el swap con el
DowP_Updater que salio DENTRO de esa copia al compilar (no uno aparte) --
asi se prueba exactamente el binario que se va a distribuir.

    python tools/updater/smoke_test_swap.py --dist app/dist/DowP        (Windows/Linux)
    python tools/updater/smoke_test_swap.py --dist app/dist/DowP.app     (macOS)

Comprueba: el archivo cambio y su hash coincide, y en macOS que la firma
ad-hoc sigue siendo valida tras el swap (`codesign --verify --deep --strict`).

Lo que NO comprueba de forma fiable en macOS: si la app relanzada de verdad
"arranco bien". 'open -n' no devuelve el PID del proceso real dentro del
bundle, asi que la heuristica de "¿sigue vivo tras N segundos?" que usa el
helper no es fiable ahi (limitacion ya documentada en ACTUALIZACIONES.md) --
en macOS, confirma a mano si aparecio la ventana de DowP.
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO_ROOT, "app", "src"))

from core.updater import journal as journal_mod  # noqa: E402
from core.updater import launcher  # noqa: E402
from core.updater.hash_tree import hash_file  # noqa: E402


def find_small_file(root: str, exclude_names: set):
    """El archivo regular mas chico del arbol, excluyendo los ejecutables --
    para simular un cambio real sin arriesgar el arranque de la copia de prueba."""
    best = None
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name in exclude_names:
                continue
            full = os.path.join(dirpath, name)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            if size == 0:
                continue
            if best is None or size < best[1]:
                best = (full, size)
    return best[0] if best else None


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dist", required=True, help="Carpeta o .app ya compilado (nunca se modifica)")
    args = parser.parse_args()

    dist = os.path.abspath(args.dist)
    if not os.path.exists(dist):
        print(f"ERROR: no existe {dist}")
        sys.exit(1)

    is_macos_bundle = dist.lower().endswith(".app")
    if is_macos_bundle:
        # El sufijo tiene que ir ANTES de ".app": spawn_detached() y
        # find_app_bundle_root() detectan un bundle mirando si la ruta
        # termina en ".app" -- "DowP.app_smoketest_copy" ya no califica,
        # y eso hace que se intente ejecutar el directorio como si fuera
        # un binario (PermissionError) en vez de usar 'open -n'.
        base = dist[: -len(".app")]
        copy_root = base + "_smoketest_copy.app"
        scratch = base + "_smoketest_scratch"
    else:
        copy_root = dist.rstrip(os.sep) + "_smoketest_copy"
        scratch = dist.rstrip(os.sep) + "_smoketest_scratch"
    for d in (copy_root, scratch):
        if os.path.exists(d):
            shutil.rmtree(d)

    print(f"1) Copiando {dist}\n   -> {copy_root}\n   (el original no se toca; puede tardar segun el tamano)")
    shutil.copytree(dist, copy_root, symlinks=True)

    if is_macos_bundle:
        # El .app ENTERO, no Contents/MacOS: el onedir real de un bundle de
        # macOS queda partido entre Contents/Frameworks y Contents/Resources
        # (con symlinks cruzados) -- Contents/MacOS solo tiene los dos
        # ejecutables. Ver install_dir_from_executable() en launcher.py.
        install_root = copy_root
        relaunch_exe = copy_root  # se abre el .app entero, via 'open'
        main_exe_name = "DowP"
    elif platform.system() == "Windows":
        install_root = copy_root
        relaunch_exe = os.path.join(copy_root, "DowP.exe")
        main_exe_name = "DowP.exe"
    else:
        install_root = copy_root
        relaunch_exe = os.path.join(copy_root, "DowP")
        main_exe_name = "DowP"

    helper_path = launcher.helper_path_in(install_root)
    if not os.path.exists(helper_path):
        print(f"ERROR: no se encontro el helper compilado en {helper_path}")
        print("¿Se corrio build_cross_platform.py con los cambios de la pieza 3 (helper de swap)?")
        sys.exit(1)

    target = find_small_file(install_root, exclude_names={main_exe_name, launcher.helper_name()})
    if target is None:
        print("ERROR: no se encontro ningun archivo para simular un cambio.")
        sys.exit(1)
    rel_target = os.path.relpath(target, install_root).replace(os.sep, "/")
    print(f"2) Archivo elegido para simular una actualizacion: {rel_target}")

    staging_dir = os.path.join(scratch, "staging")
    state_dir = os.path.join(scratch, "state")
    os.makedirs(staging_dir, exist_ok=True)
    os.makedirs(state_dir, exist_ok=True)

    staged_path = os.path.join(staging_dir, rel_target.replace("/", os.sep))
    os.makedirs(os.path.dirname(staged_path), exist_ok=True)
    with open(staged_path, "wb") as f:
        f.write(b"SMOKE TEST: contenido puesto por smoke_test_swap.py\n")
    new_hash = hash_file(staged_path)

    class FakeUpdateInfo:
        pass

    info = FakeUpdateInfo()
    info.files_to_download = {rel_target: {"hash": new_hash, "size": os.path.getsize(staged_path)}}
    info.extra_local_files = []

    j = journal_mod.build_journal(info, install_root, staging_dir, state_dir, relaunch_exe)
    journal_mod.write_journal(j, state_dir)

    # PID ya terminado: en esta prueba no hay una "app vieja" de verdad corriendo.
    dummy = subprocess.Popen([sys.executable, "-c", "pass"])
    dummy.wait()

    print("3) Entregando el swap al DowP_Updater compilado de verdad (no uno aparte)...")
    launcher.hand_off_to_helper(state_dir, install_root, dummy.pid, relaunch_exe)

    print("4) Esperando a que el helper termine (hasta 40s)...")
    journal_file = journal_mod.journal_path(state_dir)
    for _ in range(40):
        time.sleep(1)
        if not os.path.exists(journal_file):
            break
    else:
        print("   AVISO: el journal no desaparecio en 40s -- puede seguir corriendo en segundo plano.")

    ok = True
    if os.path.exists(target) and hash_file(target) == new_hash:
        print("5) OK: el archivo se reemplazo y el hash coincide.")
    else:
        print("5) FALLO: el archivo no cambio o el hash no coincide.")
        ok = False

    if is_macos_bundle:
        print("6) Verificando la firma ad-hoc tras el swap (codesign --verify --deep --strict)...")
        result = subprocess.run(
            ["codesign", "--verify", "--deep", "--strict", "--verbose=2", copy_root],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print("   OK: la firma sigue siendo valida tras el swap.")
        else:
            print("   FALLO: la firma NO verifica tras el swap:")
            print("   " + result.stderr.replace("\n", "\n   "))
            ok = False
        print(f"\n7) Revisa A MANO si aparecio la ventana de DowP al relanzar {copy_root}")
        print("   ('open -n' no permite comprobar esto automaticamente en macOS).")
    else:
        print(f"6) Revisa si aparecio la ventana de DowP al relanzar {relaunch_exe}.")

    print(f"\n{'RESULTADO: OK' if ok else 'RESULTADO: FALLO'}  (copia de prueba en {copy_root})")
    # NO se borra la copia automaticamente: el swap relanza esa misma copia de la app, que
    # puede seguir abierta (ventana visible) en este momento -- intentar rmtree con archivos
    # todavia en uso falla en silencio (ignore_errors) y deja restos a medias, mas confuso
    # que simplemente pedir que se borre a mano una vez cerrada la ventana.
    print(f"Borra {copy_root}\n  y {scratch}\na mano una vez hayas cerrado la ventana de DowP que se abrio.")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
