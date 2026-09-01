"""
Script de compilación multiplataforma para DowP 2.0 (Windows / macOS / Linux).

Compila para el sistema operativo actual usando PyInstaller en modo --onedir:
genera un .exe en Windows, un .app en macOS y un binario en Linux.

Uso:
    python build_cross_platform.py
"""
import os
import sys
import platform

import PyInstaller.__main__

APP_NAME = "DowP"
APP_VERSION = "2.0.0"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_SCRIPT = os.path.join(SCRIPT_DIR, "main.py")
SRC_DIR = os.path.join(SCRIPT_DIR, "src")

CURRENT_SYSTEM = platform.system()
CURRENT_ARCH = platform.machine()
IS_WINDOWS = CURRENT_SYSTEM == "Windows"
IS_MACOS = CURRENT_SYSTEM == "Darwin"

if IS_WINDOWS:
    ICON_FILE = os.path.join(SRC_DIR, "assets", "icons", "app", "DowP_Logo.ico")
elif IS_MACOS:
    ICON_FILE = os.path.join(SRC_DIR, "assets", "icons", "app", "DowP_Logo.icns")
else:
    ICON_FILE = None  # PyInstaller no soporta --icon nativamente en Linux

if not os.path.exists(MAIN_SCRIPT):
    print(f"ERROR: no se encontro main.py en {MAIN_SCRIPT}")
    sys.exit(1)

DIST_DIR = os.path.join(SCRIPT_DIR, "dist")
BUILD_DIR = os.path.join(SCRIPT_DIR, "build")
path_sep = ";" if IS_WINDOWS else ":"

# ─────────────────────────────────────────────────────────────────────────
# Módulos de PySide6 confirmados como NO usados (grep sobre src/: solo se
# importan QtCore, QtGui, QtWidgets, QtMultimedia, QtMultimediaWidgets,
# QtSvg y QtSvgWidgets). Se excluyen explícitamente para no arrastrar
# QtWebEngine (trae su propio Chromium embebido), QtQml/Quick, Qt3D, etc.
#
# Si agregas una feature que use un módulo de esta lista, quítalo de aquí
# (o vuelve a correr un grep de "from PySide6" sobre src/ para confirmar
# qué se usa realmente antes del próximo build).
# ─────────────────────────────────────────────────────────────────────────
UNUSED_QT_MODULES = [
    "Qt3DAnimation", "Qt3DCore", "Qt3DExtras", "Qt3DInput", "Qt3DLogic", "Qt3DRender",
    "QtAxContainer", "QtBluetooth", "QtCanvasPainter", "QtCharts", "QtConcurrent",
    "QtDBus", "QtDataVisualization", "QtDesigner", "QtGraphs", "QtGraphsWidgets",
    "QtHelp", "QtHttpServer", "QtLocation", "QtNetworkAuth", "QtNfc",
    "QtPositioning", "QtQml", "QtQuick", "QtQuick3D",
    "QtQuickControls2", "QtQuickTest", "QtQuickWidgets", "QtRemoteObjects",
    "QtScxml", "QtSensors", "QtSerialBus", "QtSerialPort", "QtSpatialAudio",
    "QtSql", "QtStateMachine", "QtTest", "QtTextToSpeech", "QtUiTools",
    "QtWebChannel", "QtWebEngineCore", "QtWebEngineQuick", "QtWebEngineWidgets",
    "QtWebSockets", "QtWebView", "QtXml",
]

args = [
    MAIN_SCRIPT,

    "--name", APP_NAME,
    "--onedir",
    "--windowed",
    "--clean",
    "--noconfirm",

    "--distpath", DIST_DIR,
    "--workpath", BUILD_DIR,
    "--specpath", BUILD_DIR,

    # main.py hace sys.path.append(.../src) en runtime, pero eso no ayuda al
    # análisis estático de PyInstaller (no ejecuta el script) — sin esto no
    # resolvería imports como "from gui.main_window import MainWindow".
    "--paths", SRC_DIR,

    # ── Datos: toda la carpeta src/ (fuentes, iconos, .qm, jsons de datos) ──
    # Los módulos de la app resuelven assets como base_dir/src/assets/...,
    # con base_dir derivado de __file__ de main.py — en modo --onedir
    # congelado eso cae dentro de _internal/, así que la carpeta destino
    # debe llamarse "src" para que esas rutas seguan resolviendo sin tocar
    # el código de la app.
    f"--add-data={SRC_DIR}{path_sep}src",

    # python-engineio resuelve su driver async con importlib.import_module()
    # a partir de un string armado en runtime ('engineio.async_drivers.' +
    # async_mode) — invisible para el análisis estático de PyInstaller, así
    # que sin este hidden-import falla con "Invalid async_mode specified" en
    # el .exe aunque funcione perfecto desde fuente. adobe_socket_server.py
    # pide explícitamente async_mode='aiohttp'.
    "--hidden-import=engineio.async_drivers.aiohttp",

    # ── Dependencias de yt-dlp, invisibles para el análisis estático ──
    # yt-dlp NO se instala vía pip: se descarga como .zip en runtime y se
    # importa vía sys.path (ver ytdlp_setup.py). Como nada en el código
    # propio de la app hace "import curl_cffi" / "import mutagen" / etc.
    # directamente, PyInstaller nunca ve esos imports — solo existen dentro
    # del .zip descargado, invisible al analizador. Confirmado empíricamente
    # importando yt_dlp de verdad y revisando qué módulos externos toca.
    # optparse (stdlib) es el parser de CLI interno de yt-dlp; el resto son
    # sus dependencias opcionales reales, ya en requirements.txt pero nunca
    # alcanzadas por el grafo de imports estático.
    "--hidden-import=optparse",
    "--hidden-import=pyexpat",
    "--hidden-import=sqlite3",  # usado por yt-dlp para --cookies-from-browser
    "--hidden-import=fileinput",
    "--hidden-import=textwrap",
    "--hidden-import=gettext",
    "--hidden-import=getpass",
    "--hidden-import=shlex",
    "--hidden-import=netrc",
    "--hidden-import=mimetypes",
    "--hidden-import=csv",
    "--hidden-import=secrets",
    "--hidden-import=hmac",
    "--hidden-import=calendar",
    "--hidden-import=stringprep",
    "--hidden-import=unicodedata",
    "--hidden-import=quopri",
    "--hidden-import=nturl2path",
    "--collect-submodules=xml",
    "--collect-submodules=html",
    "--collect-submodules=email",
    "--collect-submodules=http",
    "--collect-submodules=urllib",
    "--collect-submodules=concurrent",
    "--collect-submodules=importlib",
    "--collect-submodules=asyncio",
    "--collect-submodules=ctypes",
    "--collect-submodules=encodings",
    "--collect-all=curl_cffi",
    "--collect-all=mutagen",
    "--collect-all=Cryptodome",
    "--collect-all=brotli",
    "--collect-all=websockets",
]

for mod in UNUSED_QT_MODULES:
    args.append(f"--exclude-module=PySide6.{mod}")

if IS_MACOS:
    args.extend([
        "--target-arch", CURRENT_ARCH,
        f"--osx-bundle-identifier=com.dowp.{APP_NAME.lower()}",
    ])

if ICON_FILE and os.path.exists(ICON_FILE):
    args.extend(["--icon", ICON_FILE])
else:
    print(f"Icono no encontrado para {CURRENT_SYSTEM} ({ICON_FILE}), se compila sin --icon.")

print(f"Compilando {APP_NAME} v{APP_VERSION} para {CURRENT_SYSTEM} ({CURRENT_ARCH})...")
PyInstaller.__main__.run(args)

# ── Resultado ────────────────────────────────────────────────────────────
if IS_MACOS:
    final_target = os.path.join(DIST_DIR, f"{APP_NAME}.app")
else:
    exe_name = f"{APP_NAME}.exe" if IS_WINDOWS else APP_NAME
    final_target = os.path.join(DIST_DIR, APP_NAME, exe_name)

if os.path.exists(final_target):
    print(f"\nBuild lista en: {final_target}")
else:
    print(f"\nADVERTENCIA: no se encontro el resultado esperado en {final_target}")
    sys.exit(1)
