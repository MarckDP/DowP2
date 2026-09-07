# src/core/updater/swap_executor.py
"""Aplica y deshace un journal (core/updater/journal.py) sobre la instalacion
real. Solo stdlib + hash_tree -- este modulo lo ejecuta el helper de swap
(app/updater_helper.py), que no lleva ni requests ni zstandard ni
pycryptodomex: para cuando llega aqui, los objetos ya estan descargados,
descomprimidos y verificados en staging (pieza 2); esto solo los MUEVE.

Cada operacion se marca "done" y se persiste en el journal en cuanto se
completa -- la unidad de trabajo perdible ante un corte de luz es UNA
operacion, nunca el journal entero. Reanudar (llamar apply_journal otra vez
sobre un journal a medias) es seguro: las operaciones ya "done" se saltan, y
las que no lo estan se comprueban por hash antes de repetir nada.
"""
import os
import platform
import shutil

from core.logger.logger_manager import logger
from core.updater.hash_tree import hash_file
from core.updater.journal import STATUS_DONE, STATUS_ROLLED_BACK, STATUS_SWAPPING, write_journal


class SwapError(Exception):
    """Una operacion se aplico pero el resultado no coincide con lo esperado.
    Quien llama a apply_journal debe atrapar esto y llamar a
    rollback_journal -- nunca dejar la instalacion en un estado a medias."""


def _find_app_bundle_root(path: str):
    """Busca un directorio *.app subiendo desde `path` (hasta 4 niveles) --
    cubre tanto install_dir == el propio .app como install_dir apuntando a
    Contents/MacOS dentro de el. Devuelve None si no encuentra ninguno: la
    firma se salta en vez de fallar el swap por una convencion de rutas que
    todavia no esta cerrada para macOS (ver riesgos en ACTUALIZACIONES.md)."""
    current = os.path.abspath(path)
    for _ in range(4):
        if current.lower().endswith(".app"):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent
    return None


def _apply_one(op: dict, install_dir: str) -> None:
    dest = os.path.join(install_dir, op["relpath"].replace("/", os.sep))

    if op["action"] == "replace" and os.path.exists(dest) and hash_file(dest) == op["hash"]:
        return  # ya esta correcto -- reanudacion, o esta operacion no hacia falta

    if os.path.exists(dest):
        os.makedirs(os.path.dirname(op["backup"]), exist_ok=True)
        if os.path.exists(op["backup"]):
            os.remove(op["backup"])  # backup de un intento anterior a medias
        shutil.move(dest, op["backup"])

    if op["action"] == "replace":
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(op["source"], dest)
        if hash_file(dest) != op["hash"]:
            raise SwapError(f"Hash no coincide tras colocar {op['relpath']}")


def apply_journal(journal: dict, state_dir: str) -> None:
    """Lanza SwapError (o cualquier excepcion de E/S) si algo falla -- quien
    llama debe capturarla y ejecutar rollback_journal sobre el mismo journal."""
    journal["status"] = STATUS_SWAPPING
    write_journal(journal, state_dir)

    install_dir = journal["install_dir"]
    for op in journal["operations"]:
        if op["done"]:
            continue
        _apply_one(op, install_dir)
        op["done"] = True
        write_journal(journal, state_dir)

    if platform.system() == "Darwin":
        from core.updater.macos_sign import SigningError, adhoc_sign
        bundle = _find_app_bundle_root(install_dir)
        if bundle:
            try:
                adhoc_sign(bundle)
            except SigningError as e:
                raise SwapError(f"No se pudo re-firmar {bundle} tras el swap: {e}")
        else:
            logger.warning(f"Updater: no se encontro un .app dentro de {install_dir}, se omite la re-firma.")

    journal["status"] = STATUS_DONE
    write_journal(journal, state_dir)


def rollback_journal(journal: dict, state_dir: str) -> None:
    """Deshace las operaciones ya aplicadas, en orden inverso. Idempotente
    igual que apply_journal: una operacion sin backup (porque nunca llego a
    tocarse, o porque era un archivo nuevo sin equivalente anterior) se
    limpia sin error."""
    install_dir = journal["install_dir"]
    for op in reversed(journal["operations"]):
        if not op["done"]:
            continue
        dest = os.path.join(install_dir, op["relpath"].replace("/", os.sep))

        if op["action"] == "replace" and os.path.exists(dest):
            os.remove(dest)

        if os.path.exists(op["backup"]):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(op["backup"], dest)

        op["done"] = False

    journal["status"] = STATUS_ROLLED_BACK
    write_journal(journal, state_dir)


def purge_backups(state_dir: str) -> None:
    """Confirma un swap exitoso: borra los backups, ya no hacen falta."""
    backups_dir = os.path.join(state_dir, "backups")
    if os.path.exists(backups_dir):
        shutil.rmtree(backups_dir, ignore_errors=True)
