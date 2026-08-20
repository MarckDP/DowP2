# Migración de WPC a Dependencia Dinámica (No-pip)

Actualmente, `wpc_setup.py` instala el plugin de `yt-dlp-getpot-wpc` en el entorno virtual usando `pip`. Como hemos discutido, esto romperá la aplicación al compilarla a un `.exe` con `--onedir` porque `pip` no estará disponible y las librerías necesarias no estarán empaquetadas.

Esta es la propuesta para convertir WPC en una dependencia completamente compatible con PyInstaller, descargada dinámicamente y con sus dependencias base empaquetadas.

## Cambios Propuestos

### 1. Actualizar `requirements.txt`
Añadiremos `nodriver>=0.30.2` a la lista de dependencias oficiales. 
Esto asegura que cuando compiles el ejecutable con PyInstaller, el motor que controla Chromium se empaquete dentro de tu `.exe` y siempre esté disponible, sin depender de descargas post-instalación.

#### [MODIFY] `requirements.txt`
```diff
  python-socketio>=5.11.0
  aiohttp>=3.9.5
+ nodriver>=0.30.2
```

### 2. Refactorizar `wpc_setup.py` (Descarga desde GitHub)
Eliminaremos la lógica de `subprocess.run(pip)` y la reemplazaremos por una lógica casi idéntica a la de `bgutil`.
- Consultaremos la API de GitHub: `coletdjnz/yt-dlp-getpot-wpc/releases/latest`
- Descargaremos el archivo `.whl` (que internamente es un `.zip`).
- Descomprimiremos su contenido (específicamente la carpeta `yt_dlp_plugins/`) dentro de `bin/dependences/ytdlp/plugins/`.
- De esta forma, el plugin quedará instalado como un archivo `.py` suelto en la misma carpeta que `bgutil`, ¡perfectamente inyectable en tiempo de ejecución!

#### [MODIFY] `src/core/setup/wpc_setup.py`
Se reescribirán las funciones `install_wpc`, `check_wpc`, y las llamadas a la versión para:
- Usar `requests` y `zipfile`.
- Comprobar la existencia del archivo `bin/dependences/ytdlp/plugins/yt_dlp_plugins/extractor/getpot_wpc.py`.
- Evitar por completo `pip show` o la importación global mediante `importlib`.

### 3. Arreglar la Inyección de Plugins y el Bug del Caché
Actualmente, `analyzer.py` inyecta o retira la carpeta de plugins del `sys.path` según el proveedor seleccionado, lo cual genera el problema de caché de módulos de Python del que hablamos antes.
Para solucionarlo de forma limpia y permanente:
- Como ambos plugins (`bgutil` y `wpc`) vivirán en la misma carpeta base `bin/dependences/ytdlp/plugins/`, haremos que `analyzer.py` y `downloader_master.py` **siempre** añadan esta carpeta al `sys.path` antes de importar `yt_dlp` si al menos uno de los plugins existe.
- De este modo, `yt_dlp` cargará ambos plugins en su primera ejecución.
- La decisión de cuál usar no dependerá de ocultarle el código, sino estrictamente de los argumentos que le pasamos (`extractor_args['youtubepot-wpc']` o `extractor_args['youtubepot-bgutilcli']`).

#### [MODIFY] `src/core/ytdlp_logic/analyzer.py` y `src/core/ytdlp_logic/downloader_master.py`
- Eliminar la lógica condicional que retira `plugin_dir` del `sys.path`.
- Inyectar incondicionalmente la ruta del plugin para que `yt_dlp` registre ambos extractores sin problemas de caché.

## Plan de Verificación

1. **Instalación de requisitos:** Ejecutaré `pip install nodriver` manualmente en la terminal para reflejar el cambio del `requirements.txt`.
2. **Ejecución y auto-descarga:** Arrancaremos la aplicación. `wpc_setup.py` debería detectar que no está el archivo suelto, descargarlo de GitHub y extraerlo en `bin`.
3. **Prueba de análisis con WPC:** Cambiaremos el proveedor a WPC y probaremos un enlace. Verificaremos en consola que yt-dlp efectivamente reconoce las opciones de WPC y no se fuerza a usar Chrome por defecto (sino el configurado).
4. **Prueba de análisis con bgutil:** Cambiaremos el proveedor a bgutil y verificaremos que no ocurre el fallo de caché.
