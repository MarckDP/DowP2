# src/core/version.py
"""Fuente única de la versión de DowP.

La app y el DowP Importer comparten número de versión a propósito: el panel de
Adobe se instala desde la app y viaja dentro de su bundle, así que no tiene ciclo
de publicación propio ni canal de actualización propio. Que ambos digan lo mismo
es lo que permite detectar "el panel instalado quedó viejo" con una comparación
de cadenas y nada más.

Quien consume este valor:
  - main.py                    -> QApplication.applicationVersion
  - build_cross_platform.py    -> nombre del build y estampado del importer
  - core/setup/importer_setup  -> versión que se instala y con la que se compara
  - importer/CSXS/manifest.xml -> estampado en el build (ExtensionBundleVersion)
  - importer/js/main.js        -> estampado en el build (CURRENT_EXTENSION_VERSION)

Los dos últimos son archivos generados en cuanto al número: no los edites a mano,
el build los reescribe desde aquí y falla si no puede.
"""

APP_VERSION = "2.0.0"

# Primera versión que incluye el sistema de actualizaciones. Un usuario por debajo
# de esta no puede autoactualizarse (no tiene el updater dentro) y necesita bajar el
# instalador completo. Se sube solo ante un cambio estructural que el updater no
# pueda expresar, como mover el directorio de instalación.
MIN_UPDATABLE_VERSION = "2.0.0"

# Repo de GitHub donde tools/updater/publish.py sube los releases y de donde el
# cliente de descarga (core/updater/) los lee. Única fuente -- evita que el "--repo"
# del publicador y el que consulta la app real diverjan.
UPDATE_REPO = "MarckDP/DowP2"
