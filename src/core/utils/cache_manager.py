# src/core/utils/cache_manager.py
import os
from abc import ABC, abstractmethod
from typing import Dict, List, Any
from core.logger.logger_manager import logger
from core.utils.paths import get_thumbnail_cache_dir, get_cache_dir, get_indexed_media_path


def format_bytes(bytes_size: int) -> str:
    """Formatea bytes en una representación legible para el usuario (B, KB, MB, GB)."""
    if bytes_size <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    size = float(bytes_size)
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return f"{size:.2f} {units[i]}" if i > 0 else f"{int(size)} {units[i]}"


class BaseCacheProvider(ABC):
    """Clase base abstracta para cualquier proveedor de caché en la aplicación."""

    @property
    @abstractmethod
    def key(self) -> str:
        """Clave identificadora única del proveedor de caché."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Nombre visible para el usuario."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Descripción explicativa de qué almacena esta caché."""
        pass

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """
        Retorna las estadísticas actuales de la caché.
        Respuesta esperada: {
            "key": str,
            "name": str,
            "description": str,
            "file_count": int,
            "size_bytes": int,
            "formatted_size": str
        }
        """
        pass

    @abstractmethod
    def clear(self) -> Dict[str, Any]:
        """
        Elimina el contenido de la caché.
        Respuesta esperada: {
            "files_removed": int,
            "bytes_freed": int
        }
        """
        pass


class ImageThumbnailCacheProvider(BaseCacheProvider):
    """Proveedor de caché para imágenes y miniaturas generadas."""

    @property
    def key(self) -> str:
        return "thumbnails"

    @property
    def name(self) -> str:
        return "Caché de Imágenes y Miniaturas"

    @property
    def description(self) -> str:
        return "Miniaturas en disco generadas para previas rápidas de imágenes, videos y audios."

    def get_stats(self) -> Dict[str, Any]:
        thumb_dir = get_thumbnail_cache_dir()
        file_count = 0
        total_size = 0

        if os.path.exists(thumb_dir):
            for entry in os.scandir(thumb_dir):
                if entry.is_file():
                    file_count += 1
                    try:
                        total_size += entry.stat().st_size
                    except Exception:
                        pass

        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "file_count": file_count,
            "size_bytes": total_size,
            "formatted_size": format_bytes(total_size)
        }

    def clear(self) -> Dict[str, Any]:
        stats_before = self.get_stats()
        from core.tabs.editing_media.thumbnail_cache_manager import ThumbnailCacheManager
        deleted_count = ThumbnailCacheManager.get_instance().clear_cache()
        return {
            "files_removed": deleted_count,
            "bytes_freed": stats_before["size_bytes"]
        }


class IndexingMetadataCacheProvider(BaseCacheProvider):
    """Proveedor de caché para indexación y metadatos extraídos con FFprobe."""

    @property
    def key(self) -> str:
        return "indexing_metadata"

    @property
    def name(self) -> str:
        return "Caché de Indexación y Metadatos"

    @property
    def description(self) -> str:
        return "Base de datos y caché de metadatos multimedia extraídos para optimizar la carga del árbol."

    def get_stats(self) -> Dict[str, Any]:
        cache_dir = get_cache_dir()
        meta_cache_file = os.path.join(cache_dir, "metadata_cache.json")
        
        file_count = 0
        total_size = 0

        # Verificar metadata_cache.json
        if os.path.exists(meta_cache_file):
            try:
                from core.tabs.editing_media.ffprobe_metadata_manager import FFprobeMetadataManager
                mgr = FFprobeMetadataManager.get_instance()
                file_count += len(mgr.cache)
                total_size += os.path.getsize(meta_cache_file)
            except Exception:
                pass

        # Verificar indexed_media.json si existe
        indexed_path = get_indexed_media_path()
        if os.path.exists(indexed_path):
            try:
                total_size += os.path.getsize(indexed_path)
            except Exception:
                pass

        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "file_count": file_count,
            "size_bytes": total_size,
            "formatted_size": format_bytes(total_size)
        }

    def clear(self) -> Dict[str, Any]:
        stats_before = self.get_stats()
        from core.tabs.editing_media.ffprobe_metadata_manager import FFprobeMetadataManager
        deleted_count = FFprobeMetadataManager.get_instance().clear_cache()
        return {
            "files_removed": deleted_count,
            "bytes_freed": stats_before["size_bytes"]
        }


class FreesoundPreviewCacheProvider(BaseCacheProvider):
    """Proveedor de caché para previsualizaciones de audio de Freesound (máximo 10 archivos LRU)."""

    @property
    def key(self) -> str:
        return "freesound_previews"

    @property
    def name(self) -> str:
        return "Caché de Previsualización Freesound"

    @property
    def description(self) -> str:
        return "Audios en caché local para preescucha instantánea al explorar Freesound (máx 10 archivos)."

    def get_stats(self) -> Dict[str, Any]:
        from core.utils.paths import get_freesound_cache_dir
        fs_dir = get_freesound_cache_dir()
        file_count = 0
        total_size = 0

        if os.path.exists(fs_dir):
            for entry in os.scandir(fs_dir):
                if entry.is_file() and not entry.name.endswith(".tmp"):
                    file_count += 1
                    try:
                        total_size += entry.stat().st_size
                    except Exception:
                        pass

        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "file_count": file_count,
            "size_bytes": total_size,
            "formatted_size": format_bytes(total_size)
        }

    def clear(self) -> Dict[str, Any]:
        stats_before = self.get_stats()
        from core.tabs.editing_media.freesound_preview_cache import FreesoundPreviewCacheManager
        deleted_count = FreesoundPreviewCacheManager.get_instance().clear_cache()
        return {
            "files_removed": deleted_count,
            "bytes_freed": stats_before["size_bytes"]
        }


class CacheManager:
    """Servicio centralizado que administra todos los proveedores de caché de la aplicación."""

    _instance = None

    @classmethod
    def get_instance(cls) -> "CacheManager":
        if cls._instance is None:
            cls._instance = CacheManager()
        return cls._instance

    def __init__(self):
        self._providers: Dict[str, BaseCacheProvider] = {}
        self._register_default_providers()

    def _register_default_providers(self):
        """Registra los proveedores por defecto de la aplicación."""
        self.register_provider(ImageThumbnailCacheProvider())
        self.register_provider(IndexingMetadataCacheProvider())
        self.register_provider(FreesoundPreviewCacheProvider())


    def register_provider(self, provider: BaseCacheProvider):
        """Permite registrar un nuevo proveedor de caché dinámicamente."""
        self._providers[provider.key] = provider
        logger.info(f"CacheManager: Proveedor de caché registrado: '{provider.key}' ({provider.name})")

    def get_providers(self) -> List[BaseCacheProvider]:
        """Retorna la lista de proveedores registrados."""
        return list(self._providers.values())

    def get_all_stats(self) -> Dict[str, Any]:
        """
        Retorna estadísticas de cada proveedor y el total acumulado.
        """
        provider_stats = []
        total_files = 0
        total_bytes = 0

        for provider in self._providers.values():
            try:
                st = provider.get_stats()
                provider_stats.append(st)
                total_files += st.get("file_count", 0)
                total_bytes += st.get("size_bytes", 0)
            except Exception as e:
                logger.error(f"CacheManager: Error obteniendo stats de '{provider.key}': {e}")

        return {
            "total_files": total_files,
            "total_bytes": total_bytes,
            "formatted_total_size": format_bytes(total_bytes),
            "providers": provider_stats
        }

    def clear_provider(self, key: str) -> Dict[str, Any]:
        """Limpia un proveedor específico por su clave."""
        if key in self._providers:
            try:
                res = self._providers[key].clear()
                logger.info(f"CacheManager: Caché '{key}' limpiada correctamente.")
                return res
            except Exception as e:
                logger.error(f"CacheManager: Error limpiando caché '{key}': {e}")
        return {"files_removed": 0, "bytes_freed": 0}

    def clear_all(self) -> Dict[str, Any]:
        """Limpia todas las cachés registradas."""
        total_removed = 0
        total_freed = 0
        for key, provider in self._providers.items():
            try:
                res = provider.clear()
                total_removed += res.get("files_removed", 0)
                total_freed += res.get("bytes_freed", 0)
            except Exception as e:
                logger.error(f"CacheManager: Error limpiando todas las cachés en '{key}': {e}")

        logger.info(f"CacheManager: Limpieza total completada. Archivos: {total_removed}, Tamaño liberado: {format_bytes(total_freed)}")
        return {
            "files_removed": total_removed,
            "bytes_freed": total_freed,
            "formatted_freed": format_bytes(total_freed)
        }
