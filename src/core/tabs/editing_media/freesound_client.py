# src/core/tabs/editing_media/freesound_client.py
import os
import requests
from core.logger.logger_manager import logger

BASE_URL = "https://freesound.org/apiv2"

class FreesoundClient:
    """Cliente HTTP simple para la APIv2 de Freesound."""

    def __init__(self):
        self.session = requests.Session()

    def search(
        self,
        query: str,
        token: str,
        duration_min: float = None,
        duration_max: float = None,
        license_type: str = None,
        sort_order: str = None,
        page: int = 1,
        page_size: int = 30
    ) -> dict:
        """Realiza una búsqueda de sonidos en Freesound.
        
        Args:
            token: Access token OAuth2 (Bearer) o API key legacy (Token).
        """
        if not token:
            raise ValueError("Token de Freesound API requerido.")

        if not query or query.strip() == "":
            query = ""
            if not sort_order:
                sort_order = "Mejor calificados"

        url = f"{BASE_URL}/search/"
        
        # Campos detallados para evitar peticiones individuales extras
        fields = "id,name,tags,username,license,previews,duration,filesize,images,description,avg_rating,num_downloads,type"

        
        params = {
            "query": query,
            "fields": fields,
            "page": page,
            "page_size": page_size
        }

        # Usar Bearer auth (OAuth2) en vez de token como parámetro GET
        headers = {"Authorization": f"Bearer {token}"}

        # Construir filtros
        filters = []
        if duration_min is not None or duration_max is not None:
            dur_min_str = f"{duration_min}" if duration_min is not None else "*"
            dur_max_str = f"{duration_max}" if duration_max is not None else "*"
            filters.append(f"duration:[{dur_min_str} TO {dur_max_str}]")

        if license_type and license_type != "Cualquiera":
            if license_type == "CC0":
                filters.append('license:"Creative Commons 0"')
            elif license_type == "Attribution":
                filters.append('license:"Attribution"')
            elif license_type == "Attribution NonCommercial":
                filters.append('license:"Attribution NonCommercial"')

        if filters:
            params["filter"] = " ".join(filters)

        # Mapear ordenamiento
        sort_mapping = {
            "Relevancia": "score",
            "Duración (Largo primero)": "duration_desc",
            "Duración (Corto primero)": "duration_asc",
            "Más nuevos": "created_desc",
            "Más descargados": "downloads_desc",
            "Mejor calificados": "rating_desc"
        }
        if sort_order in sort_mapping:
            params["sort"] = sort_mapping[sort_order]

        try:
            logger.debug(f"FreesoundClient: Realizando búsqueda con parámetros: {params}")
            response = self.session.get(url, params=params, headers=headers, timeout=10)
            if response.status_code == 401:
                raise ValueError("Token expirado o inválido. Inicie sesión de nuevo en Freesound.")
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"FreesoundClient: Error en la petición de búsqueda: {e}")
            raise IOError(f"Error de red al conectar con Freesound: {e}")

    def download_file(self, url: str, dest_path: str, token: str = None, progress_callback=None) -> bool:
        """Descarga un archivo remoto (ej. vista previa o archivo original si está autorizado)."""
        try:
            logger.debug(f"FreesoundClient: Iniciando descarga de {url} hacia {dest_path}")
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            if token:
                headers["Authorization"] = f"Bearer {token}"

            response = self.session.get(url, headers=headers, stream=True, timeout=20)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            bytes_written = 0
            
            with open(dest_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=16384):
                    if chunk:
                        f.write(chunk)
                        bytes_written += len(chunk)
                        if progress_callback and total_size > 0:
                            progreso = int((bytes_written / total_size) * 100)
                            progress_callback(progreso)
            
            logger.info(f"FreesoundClient: Descarga completada exitosamente.")
            return True
        except Exception as e:
            logger.error(f"FreesoundClient: Error al descargar archivo: {e}")
            if os.path.exists(dest_path):
                try:
                    os.remove(dest_path)
                except Exception:
                    pass
            raise e

