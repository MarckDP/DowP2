# tools/updater/keygen.py
"""Genera el par de claves Ed25519 del updater. Se corre UNA vez.

    python tools/updater/keygen.py

La privada va a secrets/private_key.pem (gitignored -- guardala tambien en un
secret de GitHub Actions para cuando exista la pieza 6, CI). La publica se
escribe DIRECTAMENTE dentro del paquete de la app (app/src/core/updater/),
porque es ahi donde vive el cliente de descarga que la necesita embebida para
verificar el manifiesto antes de aplicar nada -- el publicador (este mismo
tools/updater/) nunca la usa, solo firma.
"""
import os
import sys

from signing import generate_keypair

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
PRIVATE_KEY_PATH = os.path.join(HERE, "secrets", "private_key.pem")
PUBLIC_KEY_PATH = os.path.join(REPO_ROOT, "app", "src", "core", "updater", "updater_public_key.pem")


if __name__ == "__main__":
    try:
        generate_keypair(PRIVATE_KEY_PATH, PUBLIC_KEY_PATH)
    except FileExistsError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print(f"Clave privada: {PRIVATE_KEY_PATH}  (NO commitear -- ya esta en .gitignore)")
    print(f"Clave publica: {PUBLIC_KEY_PATH}  (commitear -- el cliente la necesita)")
