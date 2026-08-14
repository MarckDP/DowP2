# AGENTS.md — DowP 2.0

Guía para agentes de código que trabajen en este repositorio. Todo el código, comentarios, documentación y mensajes de commit del proyecto están en **español**; mantén esa convención.

## Visión general del proyecto

**DowP 2.0** es una aplicación de escritorio (GUI) para descargar, convertir y gestionar medios, construida sobre **yt-dlp** y **PySide6 (Qt6)**. Funcionalidades principales:

- **Modo Rápido** (`quick_mode`): pegar una URL y descargar directamente.
- **Proceso Avanzado** (`advanced_process`): análisis de formatos, subtítulos, playlists, fragmentos y opciones de salida.
- **Herramientas de Video** (`video_tools`): conversión/reencode con ffmpeg, cola de procesamiento, proxies de previsualización.
- **Herramientas de Imagen** (`image_tools`): conversión de formatos (incl. RAW), reescalado con IA (Waifu2x, SRMD, Upscayl), eliminación de fondo (modelos ONNX tipo rembg).
- **Medios de Edición** (`editing_media`): explorador/indexador de medios locales con miniaturas, waveforms, integración con Freesound y envío a editores de video (NLEs).
- **Integraciones con editores**: Adobe Premiere Pro / After Effects (servidor socket propio) y DaVinci Resolve, gestionadas por `EditorIntegrationManager`.

La aplicación es **Windows-first** (usa `ctypes.windll`, `subprocess.CREATE_NO_WINDOW`, binarios `.exe`), aunque partes del código de rutas y dependencias contemplan macOS/Linux.

## Stack tecnológico

- **Lenguaje**: Python 3.11 (hay un venv local en `.venv/`, Python 3.11.9).
- **GUI**: PySide6 (Qt6), estilo base `Fusion`, ventana frameless con barra de título propia.
- **Motor de descargas**: yt-dlp cargado como **ZIP app** (`bin/dependences/ytdlp/yt-dlp.zip`) insertado en `sys.path`, no como paquete pip.
- **Dependencias externas (binarios)**: se auto-descargan en tiempo de ejecución a `bin/dependences/` (carpeta gitignored): ffmpeg, Deno (runtime JS para los challenges de YouTube), y el PO Token Provider `bgutil-pot` + su plugin de yt-dlp.
- **Config/estado**: JSON en `%APPDATA%/DowP2/` (Windows) — ver `src/core/utils/paths.py`. Cachés pesados (proxies) en `%LOCALAPPDATA%/DowP2/`.

Dependencias Python (`requirements.txt`):

```
PySide6>=6.11.0, requests, curl_cffi==0.14.0 (¡pineada a propósito!),
mutagen, pycryptodomex, websockets, brotli, watchdog, python-socketio, aiohttp
```

> **Importante**: `curl_cffi` está fijado a `0.14.0` porque es la única versión que funciona con el impersonate TLS de yt-dlp en este entorno. No la actualices sin validar contra la versión de yt-dlp (ver `PO_TOKEN_PROVIDER_DOWP.md`).

## Comandos de build y ejecución

No hay `pyproject.toml`, `setup.py`, empaquetador (PyInstaller) ni CI configurados. El flujo es ejecutar desde fuente:

```bash
# Crear/activar entorno (Windows, Git Bash)
python -m venv .venv
source .venv/Scripts/activate

# Instalar dependencias
pip install -r requirements.txt

# Ejecutar la app
python main.py
```

- Al arrancar, `main.py` muestra un **splash screen** (`src/gui/splash_screen.py`) que verifica y descarga las dependencias faltantes (yt-dlp, ffmpeg, Deno, PO Token Provider) vía `src/core/setup/setup_manager.py`. Si la instalación falla, la app no inicia.
- Verificación manual de dependencias: `python -m src.core.setup.setup_manager` no aplica directamente; cada módulo de setup tiene un bloque `if __name__ == "__main__"` (ej. `python src/core/setup/setup_manager.py`).

## Tests

**No existe suite de tests** (no hay `pytest`, carpeta `tests/`, ni configuración de linter/formateador). La verificación es manual: ejecutar la app y probar el flujo afectado. `prueba.py` en la raíz es un script de prueba aislado de Qt (QComboBox), no un test automatizado.

## Estructura del código

```
main.py                  ← Punto de entrada. Añade src/ a sys.path, configura escalado,
                           fuentes, idioma, splash, y arranca los servicios de editores.
src/
├── core/                ← Lógica de negocio (sin widgets)
│   ├── constants.py     ← Constantes globales: formatos, códecs, dominios, modelos IA, URLs
│   ├── logger/          ← Logger global "DowP" (logging estándar, salida a consola)
│   ├── services/        ← Servicios en background: servidor socket Adobe, servicio DaVinci,
│   │                      EditorIntegrationManager (ciclo de vida de integraciones NLE)
│   ├── setup/           ← Descarga/verificación de dependencias externas
│   │                      (ytdlp_setup, ffmpeg_setup, deno_setup, potprovider_setup, wpc_setup)
│   ├── tabs/            ← Lógica de cada pestaña, espejo de gui/tabs/
│   ├── utils/           ← config_manager, paths, i18n, queue_manager, scaling, caches,
│   │                      stream_proxy, subtitle_manager, hardware_detector, etc.
│   └── ytdlp_logic/     ← Núcleo yt-dlp: analyzer (opciones base), downloader_master,
│                          resilient_downloader, batch_downloader, format_selectors
├── gui/                 ← Todo lo visual (PySide6)
│   ├── main_window.py   ← Ventana principal con QTabWidget y widget de estado de NLEs
│   ├── splash_screen.py ← Splash con verificación de dependencias integrada
│   ├── styles.py        ← Motor de temas (template QSS + tokens JSON)
│   ├── themes/          ← _base.qss + dark.json/light.json (ver themes/TEMAS.md)
│   ├── tabs/            ← Vistas de cada pestaña (advanced_process, quick_mode,
│   │                      video_tools, image_tools, editing_media, settings)
│   ├── dialogs/         ← Diálogos (dependencias, fragmentos, playlists, subclips...)
│   └── widgets/         ← Widgets reutilizables (url_bar, queue_panel, range_slider,
│                          title_bar, toggle_switch, media_trim_player_widget...)
└── assets/              ← Fuentes TTF, iconos SVG, traducciones Qt (.ts/.qm)
bin/dependences/         ← Binarios descargados en runtime (gitignored): ytdlp, ffmpeg, deno, potprovider
```

### Convención de imports

`main.py` hace `sys.path.append(.../src)`, así que **todos los imports internos son absolutos desde `src/`**:

```python
from core.logger.logger_manager import logger
from core.utils.config_manager import get_config
from gui.styles import load_stylesheet
```

No uses imports relativos entre paquetes ni `from src.core...`. Cada archivo suele empezar con un comentario de ruta, ej. `# src/core/utils/paths.py`.

### Arquitectura en tiempo de ejecución

- UI y lógica separadas: `gui/tabs/<nombre>/` (vistas Qt) habla con `core/tabs/<nombre>/` (lógica).
- Descargas centralizadas en `core/ytdlp_logic/downloader_master.py` (`DownloaderMaster`), que recibe diccionarios de la UI y usa hilos + callbacks de progreso. Las opciones base de yt-dlp se construyen en `analyzer.py::get_base_ydl_opts()`.
- Trabajo pesado en background: `QThread`, workers en `gui/tabs/advanced_process/workers.py`, y un `QueueManager` global (`core/utils/queue_manager.py`, acceso vía `get_queue_manager()`).
- yt-dlp no vive en disco como paquete: se importa desde el ZIP. Los **plugins** de yt-dlp (PO Token Provider) viven en `bin/dependences/ytdlp/plugins/yt_dlp_plugins/` y se añaden a `sys.path` antes de importar `yt_dlp` (ver sección 4 de `PO_TOKEN_PROVIDER_DOWP.md`).
- Servicios de editores NLE: `EditorIntegrationManager` arranca/para un servidor socket (Adobe) y el servicio DaVinci; se conectan al `QueueManager`. Limpieza en `app.aboutToQuit`.

## Estilo de código y convenciones

- **Idioma**: código, comentarios, docstrings y strings de UI en **español**. El español es el idioma base de i18n (ver abajo).
- **Commits**: estilo conventional commits en español, ej. `feat(video_tools): redisenar interfaz de herramientas multimedia en 2 paneles unificados`.
- **Logging**: usar siempre el logger global `from core.logger.logger_manager import logger` (nunca `print` en código nuevo).
- **Configuración**: leer/escribir con `get_config()` / `save_config()` de `core/utils/config_manager.py`. El config vive en memoria cacheada; las versiones de dependencias se guardan en `config["dependency_versions"]`.
- **Rutas de datos**: nunca hardcodear rutas de usuario; usar las funciones de `core/utils/paths.py` (`get_app_data_dir()`, `get_cache_dir()`, etc.).
- **Windows**: al lanzar subprocesos usar `creationflags=subprocess.CREATE_NO_WINDOW` si `os.name == 'nt'` (patrón repetido en el código).
- **Temas**: los estilos NO se hardcodean en widgets; se definen en `src/gui/themes/_base.qss` con tokens `{{nombre}}` resueltos desde `dark.json`/`light.json` por `gui/styles.py`. Documentación completa en `src/gui/themes/TEMAS.md`.
- Patrón de setups de dependencias: cada `*_setup.py` expone `get_<dep>_dir()`, `check_<dep>()`, `download_<dep>()` y se registra en `setup_manager.py` (`verify_all_dependencies()` / `download_missing_dependencies()`).

## Internacionalización (i18n)

- El español es el idioma nativo del código: los strings se escriben en español dentro de `self.tr("...")` / `QCoreApplication.translate(...)`.
- Traducción al inglés mediante Qt Linguist: `src/assets/translations/en_US.ts` (fuente) → compilado a `en_US.qm`.
- `core/utils/i18n.py::load_language()` instala el traductor solo si el idioma no es español. Al cambiar strings de UI en español, hay que actualizar el `.ts` y recompilar el `.qm` (`pyside6-lupdate` / `pyside6-lrelease`).

## Consideraciones de seguridad y mantenimiento

- **Anti-bot de YouTube**: la app depende de dos capas — Deno resuelve el JS Challenge (EJS) y el PO Token Provider (bgutil-pot, binario Rust) resuelve BotGuard. Ambos se descargan solos. La referencia técnica completa está en `PO_TOKEN_PROVIDER_DOWP.md` (léela antes de tocar `analyzer.py`, `ytdlp_setup.py` o `potprovider_setup.py`).
- **Versiones acopladas**: yt-dlp se auto-actualiza desde GitHub Releases; `curl_cffi==0.14.0` y el PO Token Provider deben validarse tras cada actualización de yt-dlp. YouTube cambia BotGuard con frecuencia — esto requiere mantenimiento continuo.
- **Credenciales/cookies**: la app maneja cookies de navegador del usuario (página de Ajustes → Cookies) y tokens OAuth de Freesound. No los registres en logs ni los subas al repo.
- **Descargas en runtime**: todo lo que se descarga de internet (binarios, modelos ONNX) va a `bin/dependences/` o al AppData del usuario, nunca al árbol de código. Verifica hashes/URLs oficiales al añadir nuevas descargas (patrón existente: GitHub Releases API).
- **Procesos hijo**: la app arranca procesos persistentes (servidor bgutil-pot, sockets de editores). Asegúrate de que todo proceso/servicio nuevo tenga cierre limpio conectado a `app.aboutToQuit` (ver `main.py::on_app_exit`).
