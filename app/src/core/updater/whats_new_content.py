# src/core/updater/whats_new_content.py
"""Contenido de la ventana de "Novedades" -- una entrada por version, que se
muestra una sola vez tras actualizar (ver core/updater/launcher y
gui/dialogs/whats_new_dialog.py) y de forma permanente en Ajustes > Acerca de.

No es una clase Qt (vive en core/, no en gui/), asi que las cadenas no pueden
usar self.tr() -- se usa QCoreApplication.translate(contexto, texto), la via
estandar de Qt para marcar cadenas traducibles fuera de un QObject.

El contexto ("WhatsNewContent") va como STRING LITERAL en cada llamada, nunca
como variable/constante: el escaneo de pyside6-lupdate es estatico (no
ejecuta el codigo), asi que QCoreApplication.translate(UNA_VARIABLE, "...")
no lo detecta -- confirmado empiricamente, ver ACTUALIZACIONES.md.
"""
from PySide6.QtCore import QCoreApplication


def get_whats_new_items(version: str) -> list:
    """Devuelve [(titulo, descripcion), ...] para `version`, o [] si esa
    version no tiene novedades registradas (nunca deberia pasar para una
    version publicada, pero evita un IndexError/KeyError si se llama con
    algo inesperado)."""
    if version == "2.0.0":
        return [
            (
                QCoreApplication.translate("WhatsNewContent", "Interfaz renovada"),
                QCoreApplication.translate("WhatsNewContent", "Rediseño visual completo de la aplicación."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Modo Rápido"),
                QCoreApplication.translate("WhatsNewContent", "Nueva forma de descargar en segundos, sin pasar por el proceso avanzado."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Proceso Avanzado unificado"),
                QCoreApplication.translate("WhatsNewContent", "Proceso único y proceso por lotes ahora viven en una sola pestaña."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Editor de Imagen mejorado"),
                QCoreApplication.translate("WhatsNewContent", "Interfaz renovada para las herramientas de imagen."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Recodificación mejorada"),
                QCoreApplication.translate("WhatsNewContent", "Proceso de recodificación con su propia pestaña dentro de Herramientas Multimedia."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Organizador de medios"),
                QCoreApplication.translate("WhatsNewContent", "Nueva ventana para organizar archivos, cortar fragmentos, y buscar medios en Wikimedia y Freesound."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Envío a editores mejorado"),
                QCoreApplication.translate("WhatsNewContent", "Sistema mejorado para mandar medios a los editores compatibles (Premiere, After Effects, DaVinci...)."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Arrastre universal"),
                QCoreApplication.translate("WhatsNewContent", "Arrastra fragmentos, medios locales o descargas directamente a cualquier editor, como si arrastraras desde una carpeta."),
            ),
            (
                QCoreApplication.translate("WhatsNewContent", "Multiplataforma"),
                QCoreApplication.translate("WhatsNewContent", "Ahora compatible con macOS, y en teoría con Linux."),
            ),
        ]
    return []
