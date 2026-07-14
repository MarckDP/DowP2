from PySide6.QtWidgets import QFileDialog
from core.logger.logger_manager import logger

def download_thumbnail(widget):
    """
    Descarga la miniatura actual mostrada en el widget VideoDetailsWidget.
    Abre un diálogo de guardado para que el usuario elija el destino y el formato.
    """
    if getattr(widget.thumb_container, '_pixmap', None) is None or widget.thumb_container._pixmap.isNull():
        return
        
    base_name = widget.title_input.text()
    for c in ['<', '>', ':', '"', '/', '\\', '|', '?', '*']:
        base_name = base_name.replace(c, '')
    if not base_name.strip():
        base_name = "miniatura"
        
    dialog = QFileDialog(widget)
    dialog.setWindowTitle(widget.tr("Guardar miniatura"))
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dialog.setDirectory("") 
    dialog.selectFile(f"{base_name}.png")
    dialog.setNameFilters([
        "PNG Image (*.png)",
        "JPEG Image (*.jpg *.jpeg)",
        "WebP Image (*.webp)",
        "All Files (*.*)"
    ])
    dialog.setDefaultSuffix("png")
    
    if dialog.exec() == QFileDialog.DialogCode.Accepted:
        save_path = dialog.selectedFiles()[0]
        if save_path:
            try:
                widget.thumb_container._pixmap.save(save_path)
                from gui.dialogs.dialogs import show_info
                show_info(widget, widget.tr("Éxito"), widget.tr("Miniatura guardada correctamente."))
            except Exception as e:
                logger.error(f"Error guardando miniatura: {e}")
                from gui.dialogs.dialogs import show_warning
                show_warning(widget, widget.tr("Error"), widget.tr("Hubo un error al guardar la miniatura."))

from core.ytdlp_logic.analyzer import get_video_info

def analyze_media_for_queue(url, analyze_playlist=True, fast_mode=True, progress_callback=None):
    """
    Analiza una URL para la cola avanzada.
    - Sin playlist: fuerza un solo medio.
    - Playlist lenta: extrae entradas completas.
    - Playlist rápida: usa extracción flat para abrir selector de items.
    """
    opts = {
        'noplaylist': not analyze_playlist,
        'listsubtitles': False,
        'ignoreerrors': True,
    }
    if not analyze_playlist:
        opts.update({
            'playlist_items': '1',
            'playlistend': 1
        })
    elif fast_mode:
        opts['extract_flat'] = 'in_playlist'
    return get_video_info(url, extra_opts=opts, progress_callback=progress_callback)

def analyze_single_media(url):
    """
    Analiza una URL asegurándose de obtener siempre un solo medio.
    Si la URL es una lista de reproducción o contiene múltiples medios,
    fuerza a yt-dlp a extraer únicamente el primer elemento o el video especificado.
    """
    opts = {
        'noplaylist': True,
        'playlist_items': '1',
        'playlistend': 1
    }
    return get_video_info(url, extra_opts=opts)
