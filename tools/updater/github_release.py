# tools/updater/github_release.py
"""Wrapper fino sobre la API REST de GitHub Releases, con `requests` (ya es
dependencia de la app -- ver app/requirements.txt). Sin CLI `gh`: no esta
instalada en esta maquina, y el token por variable de entorno funciona igual en
local (PAT) que en la futura CI (GITHUB_TOKEN, que Actions inyecta solo).

Todas las funciones reciben `repo` como "owner/nombre" y `token` como el valor
crudo (nunca se loggea).
"""
import requests

API_BASE = "https://api.github.com"
TIMEOUT = 30


def _headers(token: str, accept: str = "application/vnd.github+json") -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_release_by_tag(repo: str, tag: str, token: str) -> dict | None:
    """None si el release no existe todavia (primera plataforma de una version nueva)."""
    res = requests.get(
        f"{API_BASE}/repos/{repo}/releases/tags/{tag}",
        headers=_headers(token), timeout=TIMEOUT,
    )
    if res.status_code == 404:
        return None
    res.raise_for_status()
    return res.json()


def get_latest_release(repo: str, token: str) -> dict | None:
    """El release publicado mas reciente, o None si el repo aun no tiene ninguno
    (primer release de la historia)."""
    res = requests.get(
        f"{API_BASE}/repos/{repo}/releases/latest",
        headers=_headers(token), timeout=TIMEOUT,
    )
    if res.status_code == 404:
        return None
    res.raise_for_status()
    return res.json()


def create_release(repo: str, tag: str, token: str, name: str | None = None) -> dict:
    res = requests.post(
        f"{API_BASE}/repos/{repo}/releases",
        headers=_headers(token),
        json={"tag_name": tag, "name": name or tag, "draft": False, "prerelease": False},
        timeout=TIMEOUT,
    )
    res.raise_for_status()
    return res.json()


def find_asset(release: dict, name: str) -> dict | None:
    for asset in release.get("assets", []):
        if asset["name"] == name:
            return asset
    return None


def upload_asset(release: dict, file_path: str, asset_name: str, token: str,
                  content_type: str = "application/octet-stream") -> dict:
    """Sube file_path como asset_name. Asume que ya se comprobo (con find_asset)
    que no existe todavia -- GitHub responde 422 si el nombre ya esta en uso."""
    upload_url = release["upload_url"].split("{")[0]  # quita el template "{?name,label}"
    with open(file_path, "rb") as f:
        data = f.read()
    res = requests.post(
        upload_url,
        headers={**_headers(token), "Content-Type": content_type},
        params={"name": asset_name},
        data=data,
        timeout=TIMEOUT,
    )
    res.raise_for_status()
    return res.json()


def delete_asset(repo: str, asset_id: int, token: str) -> None:
    res = requests.delete(
        f"{API_BASE}/repos/{repo}/releases/assets/{asset_id}",
        headers=_headers(token), timeout=TIMEOUT,
    )
    if res.status_code not in (204, 404):
        res.raise_for_status()


def replace_asset(release: dict, file_path: str, asset_name: str, repo: str, token: str,
                   content_type: str = "application/octet-stream") -> dict:
    """Sube asset_name, borrando primero cualquier version anterior con el mismo
    nombre. Para archivos que SI cambian en cada corrida (manifest.json y su
    firma) -- a diferencia de los objetos por hash, que son inmutables por
    definicion y nunca deberian pasar por aqui."""
    existing = find_asset(release, asset_name)
    if existing:
        delete_asset(repo, existing["id"], token)
    return upload_asset(release, file_path, asset_name, token, content_type)


def download_asset_content(asset: dict, token: str) -> bytes:
    """Descarga el contenido crudo de un asset via la API (no browser_download_url):
    asi funciona igual para repos publicos y privados, con el mismo token."""
    res = requests.get(
        asset["url"],
        headers=_headers(token, accept="application/octet-stream"),
        timeout=TIMEOUT,
    )
    res.raise_for_status()
    return res.content
