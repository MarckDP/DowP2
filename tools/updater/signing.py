# tools/updater/signing.py
"""Firma y verificacion Ed25519 del manifiesto, con pycryptodomex (ya es dependencia
de la app -- ver app/requirements.txt). No hace falta pynacl.

La firma cubre los BYTES CRUDOS del archivo, nunca una reserializacion del JSON:
asi un cambio de formato (espacios, orden de claves) en una libreria futura no
puede invalidar una firma valida sin que el contenido real haya cambiado.
"""
import os

from Cryptodome.PublicKey import ECC
from Cryptodome.Signature import eddsa


def generate_keypair(private_path: str, public_path: str) -> None:
    """Genera un par Ed25519 nuevo y lo escribe en PEM. Se llama una sola vez
    (tools/updater/keygen.py); volver a llamarla invalida cualquier firma anterior
    que el cliente ya hubiera embebido."""
    if os.path.exists(private_path):
        raise FileExistsError(
            f"Ya existe una clave privada en {private_path}. Borrala a mano si "
            "de verdad quieres generar un par nuevo (invalida todo lo firmado antes)."
        )

    key = ECC.generate(curve="ed25519")

    os.makedirs(os.path.dirname(private_path) or ".", exist_ok=True)
    with open(private_path, "wt", encoding="utf-8") as f:
        f.write(key.export_key(format="PEM"))

    os.makedirs(os.path.dirname(public_path) or ".", exist_ok=True)
    with open(public_path, "wt", encoding="utf-8") as f:
        f.write(key.public_key().export_key(format="PEM"))


def sign_file(private_key_path: str, file_path: str) -> bytes:
    """Firma el contenido binario de file_path. Devuelve la firma cruda (64 bytes)."""
    with open(private_key_path, "rt", encoding="utf-8") as f:
        key = ECC.import_key(f.read())

    with open(file_path, "rb") as f:
        data = f.read()

    signer = eddsa.new(key, mode="rfc8032")
    return signer.sign(data)


def verify_file(public_key_path: str, file_path: str, signature: bytes) -> bool:
    """True si signature es una firma Ed25519 valida de file_path con esta clave publica."""
    with open(public_key_path, "rt", encoding="utf-8") as f:
        key = ECC.import_key(f.read())

    with open(file_path, "rb") as f:
        data = f.read()

    verifier = eddsa.new(key, mode="rfc8032")
    try:
        verifier.verify(data, signature)
        return True
    except ValueError:
        return False
