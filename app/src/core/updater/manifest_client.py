# src/core/updater/manifest_client.py
"""Descarga y verifica el manifiesto firmado del release mas reciente.

Repo publico: ni la consulta a la API ni la descarga de los assets necesitan
token (mismo patron ya usado en core/setup/ffmpeg_setup.py contra la API de
GitHub para las releases de FFmpeg).
"""
import json
import os

import requests
from Cryptodome.PublicKey import ECC
from Cryptodome.Signature import eddsa

from core.logger.logger_manager import logger

API_BASE = "https://api.github.com"
TIMEOUT = 30
PUBLIC_KEY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "updater_public_key.pem")


class ManifestVerificationError(Exception):
    """La firma del manifiesto no verifico contra la clave publica embebida.

    Fallo cerrado a proposito: un manifiesto sin verificar NUNCA debe tratarse
    como equivalente a "no hay actualizacion disponible" -- eso enmascararia
    un manifiesto corrupto o manipulado como un simple "estas al dia"."""


def _verify_signature(data: bytes, signature: bytes) -> bool:
    with open(PUBLIC_KEY_PATH, "rt", encoding="utf-8") as f:
        key = ECC.import_key(f.read())
    verifier = eddsa.new(key, mode="rfc8032")
    try:
        verifier.verify(data, signature)
        return True
    except ValueError:
        return False


def _find_asset(release: dict, name: str) -> dict | None:
    for asset in release.get("assets", []):
        if asset["name"] == name:
            return asset
    return None


def fetch_and_verify_manifest(repo: str) -> dict:
    """Descarga manifest.json + manifest.json.sig del release `latest` de
    `repo` ("owner/nombre") y devuelve el manifiesto ya parseado, solo si la
    firma es valida.

    Lanza ManifestVerificationError si la firma no verifica, y
    requests.HTTPError / requests.ConnectionError si falla la red -- ninguno
    de los dos casos debe interpretarse silenciosamente como "sin novedades"."""
    res = requests.get(f"{API_BASE}/repos/{repo}/releases/latest", timeout=TIMEOUT)
    res.raise_for_status()
    release = res.json()

    manifest_asset = _find_asset(release, "manifest.json")
    sig_asset = _find_asset(release, "manifest.json.sig")
    if manifest_asset is None or sig_asset is None:
        raise ManifestVerificationError(
            f"El release {release.get('tag_name')} de {repo} no trae manifest.json/.sig todavia."
        )

    manifest_bytes = requests.get(manifest_asset["browser_download_url"], timeout=TIMEOUT).content
    signature = requests.get(sig_asset["browser_download_url"], timeout=TIMEOUT).content

    if not _verify_signature(manifest_bytes, signature):
        raise ManifestVerificationError(
            f"La firma de manifest.json ({release.get('tag_name')}) no es valida."
        )

    logger.info(f"Updater: manifiesto de {repo}@{release.get('tag_name')} verificado correctamente.")
    return json.loads(manifest_bytes)
