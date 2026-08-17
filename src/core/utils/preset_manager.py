# src/core/utils/preset_manager.py
import json
import os

from PySide6.QtCore import QObject, Signal

from core.logger.logger_manager import logger
from core.utils.paths import get_app_data_dir


def _get_presets_path() -> str:
    """Retorna la ruta al archivo JSON donde se persisten todos los presets."""
    return os.path.join(get_app_data_dir(), "presets.json")


class PresetManager(QObject):
    """
    Gestor genérico de presets (sin UI): guarda/carga/lista/borra diccionarios
    de ajustes con nombre, agrupados por namespace (ej. "video_tools/comprimir").

    El namespace es la clave de reutilización: cada pestaña o módulo de la app
    usa el suyo, y todos comparten el mismo archivo presets.json en AppData.
    Estructura del archivo:
        { "<namespace>": { "<nombre_preset>": { ...ajustes... } } }

    Emite `presets_changed(namespace)` en cada mutación (guardar/eliminar/
    importar), para que cualquier PresetBar abierto se refresque solo sin
    necesidad de llamadas cruzadas manuales entre widgets.
    """
    _instance = None

    presets_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self._data = None  # caché en memoria, se carga lazy desde disco

    @classmethod
    def get_instance(cls) -> "PresetManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load(self):
        if self._data is not None:
            return
        path = _get_presets_path()
        self._data = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._data = data
            except Exception as e:
                logger.error(f"PresetManager: Error al leer presets.json: {e}")

    def _save_to_disk(self):
        try:
            with open(_get_presets_path(), "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"PresetManager: Error al escribir presets.json: {e}")

    def list_names(self, namespace: str) -> list:
        """Lista los nombres de presets de un namespace, ordenados alfabéticamente."""
        self._load()
        return sorted(self._data.get(namespace, {}).keys())

    def get_settings(self, namespace: str, name: str) -> dict:
        """Retorna los ajustes de un preset, o dict vacío si no existe."""
        self._load()
        settings = self._data.get(namespace, {}).get(name, {})
        return dict(settings) if isinstance(settings, dict) else {}

    def save_preset(self, namespace: str, name: str, settings: dict):
        """Guarda (o sobrescribe) un preset con los ajustes dados."""
        self._load()
        self._data.setdefault(namespace, {})[name] = dict(settings)
        self._save_to_disk()
        logger.info(f"PresetManager: Preset '{name}' guardado en '{namespace}'.")
        self.presets_changed.emit(namespace)

    def delete_preset(self, namespace: str, name: str) -> bool:
        """Elimina un preset. Retorna True si existía."""
        self._load()
        presets = self._data.get(namespace, {})
        if name not in presets:
            return False
        del presets[name]
        self._save_to_disk()
        logger.info(f"PresetManager: Preset '{name}' eliminado de '{namespace}'.")
        self.presets_changed.emit(namespace)
        return True

    def export_preset(self, namespace: str, name: str, file_path: str) -> bool:
        """Exporta un preset a un archivo JSON independiente."""
        settings = self.get_settings(namespace, name)
        if not settings:
            return False
        payload = {"nombre": name, "namespace": namespace, "ajustes": settings}
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            logger.info(f"PresetManager: Preset '{name}' exportado a {file_path}.")
            return True
        except Exception as e:
            logger.error(f"PresetManager: Error al exportar preset: {e}")
            return False

    def import_preset(self, namespace: str, file_path: str) -> str:
        """
        Importa un preset desde un archivo JSON al namespace indicado.
        Acepta tanto el formato de exportación ({nombre, ajustes}) como un
        dict plano de ajustes (usa el nombre del archivo en ese caso).
        Retorna el nombre del preset importado, o "" si falló.
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("El archivo no contiene un objeto JSON")
            if "ajustes" in data and isinstance(data["ajustes"], dict):
                name = str(data.get("nombre") or os.path.splitext(os.path.basename(file_path))[0])
                settings = data["ajustes"]
            else:
                name = os.path.splitext(os.path.basename(file_path))[0]
                settings = data
            self.save_preset(namespace, name, settings)
            return name
        except Exception as e:
            logger.error(f"PresetManager: Error al importar preset desde {file_path}: {e}")
            return ""


def get_preset_manager() -> PresetManager:
    """Acceso global al PresetManager (singleton)."""
    return PresetManager.get_instance()
