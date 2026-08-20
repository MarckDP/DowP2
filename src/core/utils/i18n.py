# src/core/utils/i18n.py
"""
Sistema de internacionalización (i18n) de DowP 2.0
====================================================
Idioma base: Español (es) — los strings en el código fuente están en español.
Traducciones disponibles: Inglés (en) via en_US.qm

Cuando el idioma es español, no se carga traductor (ya es el idioma nativo del código).
Cuando el idioma es otro (ej: inglés), se carga el archivo .qm correspondiente.
"""
import os
from PySide6.QtCore import QTranslator, QCoreApplication
from core.logger.logger_manager import logger
from core.utils.paths import get_src_dir

_translator = None

def load_language(app, lang_code):
    """
    Carga e instala un traductor para el idioma solicitado.
    
    - 'es' (español): No se carga traductor — es el idioma base del código.
    - 'en' (inglés): Carga en_US.qm para traducir del español al inglés.
    """
    global _translator
    
    # Remover traductor anterior si existe
    if _translator:
        QCoreApplication.removeTranslator(_translator)
        _translator = None
    
    # Español es el idioma base — no necesita traductor
    if lang_code == "es":
        logger.info("i18n: Español (idioma base) — sin traductor")
        return True

    # Para otros idiomas, buscar el archivo .qm correspondiente
    trans_dir = os.path.join(get_src_dir(), "assets", "translations")
    possible_names = [
        f"{lang_code}_{lang_code.upper()}.qm",  # en_EN.qm (no existe pero por si acaso)
        f"{lang_code}_US.qm",                     # en_US.qm
        f"{lang_code}_ES.qm",                     # xx_ES.qm
        f"{lang_code}.qm"                         # xx.qm
    ]
    
    qm_path = None
    for name in possible_names:
        path = os.path.join(trans_dir, name)
        if os.path.exists(path):
            qm_path = path
            break

    if qm_path:
        _translator = QTranslator()
        if _translator.load(qm_path):
            app.installTranslator(_translator)
            logger.info(f"i18n: Idioma cargado: {lang_code} ({os.path.basename(qm_path)})")
            return True
        else:
            logger.error(f"i18n: Error cargando archivo .qm: {qm_path}")
    else:
        logger.warning(f"i18n: Archivo de traducción no encontrado para: {lang_code}")
    
    return False
