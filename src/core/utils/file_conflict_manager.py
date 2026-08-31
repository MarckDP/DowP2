# src/core/utils/file_conflict_manager.py
"""
Gestor centralizado de conflictos de archivo (medio de salida ya existente).

Cubre las tres políticas silenciosas (Sobrescribir/Conservar/Omitir, usadas por
Modo Rápido y Proceso Avanzado en modo LOTES) y sirve de base para el modo SOLO,
donde el resultado del diálogo interactivo (ConflictDialog) se traduce a estas
mismas acciones antes de llegar aquí.

Sin dependencias de Qt: es lógica pura, igual que cleanup_manager.py y
recode_guard.py, para poder probarla/usarla desde cualquier hilo sin tocar widgets.

Backups: al "sobrescribir" no se borra el archivo original directamente, se
renombra a "<archivo>.dbak". Quien llame debe confirmar (commit_backup, borra el
.dbak) si el proceso terminó bien, o revertir (rollback_backup, restaura el
original) si falló/se canceló. Cada backup creado se registra en un manifiesto en
disco (pending_backups.json) para poder recuperarlo si la app se cierra a la fuerza
a mitad de la operación (ver recover_orphaned_backups).
"""
import json
import os
import threading

from core.logger.logger_manager import logger
from core.utils.paths import get_app_data_dir

BACKUP_SUFFIX = ".dbak"

_manifest_lock = threading.Lock()


def _manifest_path() -> str:
    return os.path.join(get_app_data_dir(), "pending_backups.json")


def _load_manifest() -> dict:
    path = _manifest_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"FileConflictManager: No se pudo leer el manifiesto de backups: {e}")
        return {}


def _save_manifest(manifest: dict):
    path = _manifest_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"FileConflictManager: No se pudo escribir el manifiesto de backups: {e}")


def _register_pending_backup(original_path: str, backup_path: str):
    with _manifest_lock:
        manifest = _load_manifest()
        manifest[backup_path] = original_path
        _save_manifest(manifest)


def _unregister_pending_backup(backup_path: str):
    with _manifest_lock:
        manifest = _load_manifest()
        if backup_path in manifest:
            del manifest[backup_path]
            _save_manifest(manifest)


def predict_final_extension(video_ext: str | None, audio_ext: str | None, mode: str,
                             is_combined: bool = False) -> str:
    """
    Predice la extensión de archivo más probable que yt-dlp usará al fusionar (o
    extraer) los streams elegidos. Puerto de _predict_final_extension de DowP-Lite
    (src/gui/single_download_tab.py), adaptado a los nombres de campo de DowP 2.0.

    Esta predicción se usa además para fijar 'merge_output_format' en las opciones
    de yt-dlp (ver downloader_master.py), de forma que deje de ser una suposición:
    yt-dlp queda obligado a respetar el contenedor predicho.
    """
    if mode == "audio_only":
        return f".{audio_ext or 'mp3'}"

    if is_combined:
        return f".{video_ext or 'mp4'}"

    if not audio_ext or audio_ext == "none":
        return f".{video_ext}" if video_ext else ".mp4"

    if video_ext == "mp4" and audio_ext in ("m4a", "mp4"):
        return ".mp4"

    if video_ext == "webm" and audio_ext in ("webm", "opus"):
        return ".webm"

    return ".mkv"


def find_available_rename(desired_path: str) -> str:
    """Busca 'nombre (1).ext', 'nombre (2).ext'... hasta encontrar uno libre."""
    base, ext = os.path.splitext(desired_path)
    counter = 1
    while True:
        candidate = f"{base} ({counter}){ext}"
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def resolve_conflict(desired_path: str, policy: str) -> tuple[str | None, str | None]:
    """
    Resuelve un posible conflicto de archivo según la política dada.

    policy: "sobrescribir" | "conservar" | "omitir"

    Returns:
        (final_path, backup_path)
        - Sin conflicto: (desired_path, None)
        - "omitir" con conflicto: (None, None) — quien llame debe tratarlo como
          "no descargar, no es un error".
        - "sobrescribir" con conflicto: (desired_path, "<desired_path>.dbak")
        - "conservar" con conflicto: (nuevo_path_libre, None)
    """
    if not os.path.exists(desired_path):
        return desired_path, None

    if policy == "omitir":
        logger.info(f"FileConflictManager: Omitido por conflicto: {desired_path}")
        return None, None

    if policy == "sobrescribir":
        backup_path = desired_path + BACKUP_SUFFIX
        try:
            if os.path.exists(backup_path):
                os.remove(backup_path)
            os.rename(desired_path, backup_path)
        except OSError as e:
            raise Exception(f"No se pudo respaldar el archivo original: {e}")
        _register_pending_backup(desired_path, backup_path)
        logger.info(f"FileConflictManager: Backup creado para sobrescritura: {backup_path}")
        return desired_path, backup_path

    if policy == "conservar":
        final_path = find_available_rename(desired_path)
        logger.info(f"FileConflictManager: Conservando ambos, nuevo nombre: {final_path}")
        return final_path, None

    raise ValueError(f"Política de conflicto desconocida: {policy}")


def quarantine_for_recode(original_path: str) -> str:
    """
    Pone en cuarentena un archivo EXISTENTE (ej. un medio recién descargado) antes de una
    operación que puede fallar (ej. recodificación), renombrándolo a "<original>.dbak" y
    registrándolo en el mismo manifiesto que usa resolve_conflict() — así, si la app se
    cierra a la fuerza a mitad de la operación, recover_orphaned_backups() lo restaura solo
    al reabrir.

    A diferencia de resolve_conflict() (que respalda un archivo de SALIDA que ya existe,
    para no perderlo al sobrescribirlo), esto respalda el archivo de ENTRADA sin importar si
    su nombre choca con algo — el llamador decide después, con commit_backup() (confirmar,
    borra el .dbak) o rollback_backup() (restaurar, sea por fallo o porque el usuario elige
    conservar el original), qué hacer con la cuarentena.
    """
    backup_path = original_path + BACKUP_SUFFIX
    try:
        if os.path.exists(backup_path):
            os.remove(backup_path)
        os.rename(original_path, backup_path)
    except OSError as e:
        raise Exception(f"No se pudo poner en cuarentena el archivo original: {e}")
    _register_pending_backup(original_path, backup_path)
    logger.info(f"FileConflictManager: Original puesto en cuarentena para recodificación: {backup_path}")
    return backup_path


def commit_backup(backup_path: str | None):
    """Descarta un backup pendiente porque la operación terminó bien."""
    if not backup_path:
        return
    try:
        if os.path.exists(backup_path):
            from core.utils.cleanup_manager import CleanupManager
            if not CleanupManager.safe_remove(backup_path):
                logger.warning(f"FileConflictManager: No se pudo eliminar el backup '{backup_path}' tras reintentos.")
        logger.debug(f"FileConflictManager: Backup confirmado (eliminado): {backup_path}")
    except OSError as e:
        logger.warning(f"FileConflictManager: No se pudo eliminar el backup '{backup_path}': {e}")
    finally:
        _unregister_pending_backup(backup_path)


def rollback_backup(backup_path: str | None):
    """Restaura un backup pendiente porque la operación falló o se canceló."""
    if not backup_path:
        return
    original_path = backup_path[: -len(BACKUP_SUFFIX)] if backup_path.endswith(BACKUP_SUFFIX) else backup_path
    try:
        if not os.path.exists(backup_path):
            logger.warning(f"FileConflictManager: Backup ya no existe, nada que revertir: {backup_path}")
            return
        if os.path.exists(original_path) and os.path.normpath(original_path) != os.path.normpath(backup_path):
            os.remove(original_path)
        os.rename(backup_path, original_path)
        logger.info(f"FileConflictManager: Backup restaurado: {original_path}")
    except OSError as e:
        logger.error(f"FileConflictManager: No se pudo restaurar el backup '{backup_path}': {e}")
    finally:
        _unregister_pending_backup(backup_path)


def recover_orphaned_backups() -> list[str]:
    """
    Pasada de recuperación al arrancar la app: si una sesión anterior se cerró a la
    fuerza a mitad de una sobrescritura, el .dbak queda huérfano en el manifiesto.
    Siempre se restaura el original (nunca se descarta en silencio).

    Returns: lista de rutas originales restauradas.
    """
    with _manifest_lock:
        manifest = _load_manifest()

    if not manifest:
        return []

    recovered = []
    for backup_path, original_path in list(manifest.items()):
        if not os.path.exists(backup_path):
            # El backup ya no existe (se confirmó/revirtió en algún punto sin
            # limpiar el manifiesto, o fue borrado manualmente): solo limpiar la entrada.
            _unregister_pending_backup(backup_path)
            continue
        try:
            if os.path.exists(original_path) and os.path.normpath(original_path) != os.path.normpath(backup_path):
                os.remove(original_path)
            os.rename(backup_path, original_path)
            recovered.append(original_path)
            logger.info(f"FileConflictManager: Backup huérfano recuperado tras cierre inesperado: {original_path}")
        except OSError as e:
            logger.error(f"FileConflictManager: No se pudo recuperar el backup huérfano '{backup_path}': {e}")
            continue
        finally:
            _unregister_pending_backup(backup_path)

    return recovered
