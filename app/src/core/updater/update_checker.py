# src/core/updater/update_checker.py
"""Compara un manifiesto ya verificado contra la instalacion actual. Sin red
a proposito: recibe el manifiesto como dict, para poder probarse con uno
fabricado a mano sin tocar GitHub (ver tools/updater/ para como se genera uno
de verdad)."""
import os
import sys
from dataclasses import dataclass, field

from core.version import APP_VERSION, MIN_UPDATABLE_VERSION
from core.updater.hash_tree import hash_tree
from core.updater.platform_key import get_platform_key

SUPPORTED_FORMAT = 1


@dataclass
class UpdateInfo:
    available: bool
    must_full_install: bool
    current_version: str
    remote_version: str
    platform_key: str
    files_to_download: dict = field(default_factory=dict)
    download_size: int = 0
    extra_local_files: list = field(default_factory=list)


def _version_tuple(v: str) -> tuple:
    """"2.10.1" -> (2, 10, 1). Suficiente para el esquema X.Y.Z de este
    proyecto (ver core/version.py) -- no hace falta packaging.version para eso."""
    return tuple(int(p) for p in v.split("."))


def compute_diff(manifest: dict, install_dir: str | None = None,
                  current_version: str | None = None) -> UpdateInfo:
    """install_dir por defecto es la raiz de la instalacion congelada -- el mismo
    arbol que hashea tools/updater al publicar (ver
    launcher.install_dir_from_executable(): en Windows/Linux es la carpeta del
    .exe, en macOS es el .app completo, no Contents/MacOS) -- en modo fuente no
    hay arbol congelado que hashear, asi que hay que pasarlo a mano (por
    ejemplo, app/dist/DowP o app/dist/DowP.app, para probar contra un build
    real sin instalar nada)."""
    current_version = current_version or APP_VERSION
    remote_version = manifest.get("app_version", "0.0.0")

    unsupported_format = manifest.get("format") != SUPPORTED_FORMAT
    below_min = _version_tuple(current_version) < _version_tuple(
        manifest.get("min_updatable_version", MIN_UPDATABLE_VERSION)
    )
    must_full_install = unsupported_format or below_min

    if _version_tuple(remote_version) <= _version_tuple(current_version):
        return UpdateInfo(
            available=False, must_full_install=False,
            current_version=current_version, remote_version=remote_version,
            platform_key=get_platform_key(),
        )

    platform_key = get_platform_key()
    plat_data = manifest.get("platforms", {}).get(platform_key)

    if must_full_install or plat_data is None:
        return UpdateInfo(
            available=plat_data is not None, must_full_install=must_full_install,
            current_version=current_version, remote_version=remote_version,
            platform_key=platform_key,
        )

    if install_dir is None:
        if getattr(sys, "frozen", False):
            from core.updater.launcher import install_dir_from_executable
            install_dir = install_dir_from_executable(sys.executable)
        else:
            raise ValueError(
                "compute_diff necesita install_dir explicito en modo fuente "
                "(no hay arbol --onedir congelado que hashear)."
            )

    manifest_files = plat_data.get("files", {})
    local_files = hash_tree(install_dir)

    files_to_download, download_size = {}, 0
    for relpath, entry in manifest_files.items():
        local = local_files.get(relpath)
        if local is None or local["hash"] != entry["hash"]:
            files_to_download[relpath] = entry
            download_size += entry["size"]

    extra_local_files = sorted(set(local_files) - set(manifest_files))

    return UpdateInfo(
        available=True, must_full_install=False,
        current_version=current_version, remote_version=remote_version,
        platform_key=platform_key, files_to_download=files_to_download,
        download_size=download_size, extra_local_files=extra_local_files,
    )
