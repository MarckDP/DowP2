# src/gui/tabs/editing_media/editing_media_playback.py
import os
import re
import datetime
import subprocess
import platform
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QImageReader, QImage
from PySide6.QtMultimedia import QMediaPlayer
from core.logger.logger_manager import logger
from gui.tabs.editing_media.editing_media_icons import get_svg_icon, get_colored_svg_icon
from core.tabs.editing_media.editing_media_logic import WaveformExtractorThread

class PlaybackMixin:
    """Mixin que maneja la reproducción de audio, extracción de metadata y waveform."""
    
    def _parse_duration_to_seconds(self, dur_str: str) -> float:
        if not dur_str or dur_str == "-":
            return 0.0
        if isinstance(dur_str, (int, float)):
            return float(dur_str)
        try:
            parts = str(dur_str).split(":")
            if len(parts) == 2:
                return float(parts[0]) * 60 + float(parts[1])
            elif len(parts) == 3:
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        except Exception:
            pass
        return 0.0

    def _on_media_clicked(self, list_item):
        item_data = list_item.data(Qt.UserRole)
        if not item_data:
            return

        if item_data.get("tipo") == "load_more":
            self._max_display_count = getattr(self, "_max_display_count", 500) + 500
            self._update_media_list()
            return

        name = item_data["nombre"]
        tipo = item_data["tipo"]
        path = item_data["ruta"]
        is_remote = path.startswith("http://") or path.startswith("https://")

        # Asegurar metadatos para archivos locales (necesitamos la duración exacta)
        if not is_remote and path not in self._metadata_cache:
            self._metadata_cache[path] = self._extract_rich_metadata(path, tipo)

        # Detener cualquier audio previo al cambiar de archivo
        self._stop_audio_playback()

        self.current_playing_path = path
        self.current_playing_type = tipo

        # 1. Controlar la visualización del espectro de audio y header de carátula
        if tipo in ("audio", "video"):
            self.audio_panel.setVisible(True)
            self.audio_controls_widget.setVisible(tipo == "audio")
            
            # Header de carátula e información solo para audios
            if hasattr(self, "audio_header_widget"):
                self.audio_header_widget.setVisible(tipo == "audio")
                if tipo == "audio":
                    self.lbl_audio_name.setText(name)
                    dur_str = item_data.get("duración", "-")
                    if not is_remote and path in self._metadata_cache:
                        dur_str = self._metadata_cache[path].get("duración", dur_str)
                    self.lbl_audio_sub.setText(f"AUDIO • {dur_str}")

                    # Cargar carátula incrustada si existe o icono por defecto
                    from core.tabs.editing_media.thumbnail_cache_manager import ThumbnailCacheManager
                    from gui.styles import get_theme_token
                    from gui.tabs.editing_media.editing_media_icons import get_colored_svg_icon
                    from PySide6.QtGui import QPixmap

                    accent_color = get_theme_token("acento_primario", "#B9E640")
                    fallback_icon = get_colored_svg_icon("music_note.svg", accent_color, size=32)

                    thumb_path = ThumbnailCacheManager.get_instance().get_cached_thumbnail_path(path)
                    if thumb_path and os.path.exists(thumb_path):
                        pix = QPixmap(thumb_path).scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        self.lbl_cover_art.setPixmap(pix)
                    else:
                        self.lbl_cover_art.setPixmap(fallback_icon.pixmap(32, 32))
                        if not is_remote:
                            ThumbnailCacheManager.get_instance().request_thumbnail(path, "audio")

            self.waveform_widget.set_audio_path(path)
            self.waveform_widget.set_playback_ratio(0.0)
            
            # Detener hilo de extracción previo si estuviera corriendo
            if hasattr(self, "waveform_thread") and self.waveform_thread and self.waveform_thread.isRunning():
                self.waveform_thread.stop()
                self.waveform_thread.wait()

            if hasattr(self, "remote_waveform_thread") and self.remote_waveform_thread and self.remote_waveform_thread.isRunning():
                try:
                    self.remote_waveform_thread.finished.disconnect()
                except Exception:
                    pass
                
            # Calcular cantidad ideal de picos basándose en el ancho actual del widget
            w_width = self.waveform_widget.width()
            num_peaks = max(50, min((w_width - 24) // 5, 180)) if w_width > 50 else 80
            
            # Activar el estado de carga y animación en el widget
            self.waveform_widget.set_loading(True)

            # Si es remoto y tiene imágenes del waveform, usarlas
            if is_remote and "images" in item_data and item_data["images"].get("waveform_m"):
                waveform_url = item_data["images"]["waveform_m"]
                from core.tabs.editing_media.editing_media_logic import RemoteWaveformLoaderThread
                
                self.remote_waveform_thread = RemoteWaveformLoaderThread(waveform_url, num_peaks, self)
                self.remote_waveform_thread.finished.connect(self.waveform_widget.set_peaks)
                self.remote_waveform_thread.start()
            else:
                # Obtener duración en segundos para el muestreo progresivo
                dur_str = item_data.get("duración", "-")
                if not is_remote:
                    dur_str = self._metadata_cache[path].get("duración", "-")
                if dur_str == "-":
                    dur_str = self.controller.get_media_duration_for_file(path)
                duration_sec = self._parse_duration_to_seconds(dur_str)

                # Iniciar extracción asíncrona progresiva de amplitudes reales
                self.waveform_thread = WaveformExtractorThread(
                    audio_path=path,
                    num_peaks=num_peaks,
                    duration_sec=duration_sec,
                    parent=self
                )
                
                # Conectar la señal de actualización progresiva
                self.waveform_thread.peaks_updated.connect(self.waveform_widget.set_peaks)
                
                if tipo == "video":
                    # Para videos: si no hay audio, ocultar el panel automáticamente
                    self.waveform_thread.finished_extraction.connect(
                        lambda peaks: self._on_video_waveform_ready(peaks)
                    )
                else:
                    self.waveform_thread.finished_extraction.connect(self.waveform_widget.set_peaks)
                self.waveform_thread.start()

            # Controles de reproducción de audio solo para archivos de audio puros
            if tipo == "audio" and self.audio_player:
                try:
                    if is_remote:
                        self.audio_player.setSource(QUrl(path))
                        self.lbl_time.setText("00:00:00.000 / 00:00:00.000")
                    else:
                        self.audio_player.setSource(QUrl.fromLocalFile(path))
                        self.lbl_time.setText("00:00:00.000 / 00:00:00.000")
                    
                    # Aplicar bucle según configuración actual (por defecto activo)
                    loops = QMediaPlayer.Infinite if getattr(self, "_audio_loop_active", True) else 1
                    self.audio_player.setLoops(loops)
                    
                    # Auto-reproducir audio al hacer clic (igual que en video)
                    self.audio_player.play()
                    from gui.styles import apply_player_play_button_style
                    apply_player_play_button_style(self.btn_play, is_playing=True, icon_size=14)
                except Exception as e:
                    logger.error(f"EditingMediaTab: Error cargando fuente de audio: {e}")
        else:
            self.audio_panel.setVisible(False)

        # 2. Actualizar Vista Previa (Columna Derecha - Superior)
        if tipo == "imagen":
            self.preview_box.setVisible(True)
            self.preview_box.show_image_preview(path)
        elif tipo == "video":
            self.preview_box.setVisible(True)
            self.preview_box.show_video_preview(path)
        elif tipo == "audio":
            # Para audios ocultamos el cuadro superior inútil de video
            self.preview_box.stop_media()
            self.preview_box.setVisible(False)

        # 3. Actualizar Detalles e Info Técnica (Columna Derecha - Inferior)
        self.metadata_labels["nombre"].setText(name)
        self.metadata_labels["ruta"].setText(path)
        self.metadata_labels["tipo"].setText(tipo.upper())
        self.metadata_labels["tamaño"].setText(item_data.get("tamaño", "-"))
        
        # Ocultar/mostrar botones según tipo local/online
        self.btn_reveal.setVisible(not is_remote)
        self.btn_reveal.setEnabled(not is_remote)
        self.btn_download.setVisible(is_remote)
        self.btn_download.setEnabled(is_remote)

        if is_remote:
            self.license_panel.setVisible(True)
            
            def get_friendly_license_name(url: str) -> str:
                if not url:
                    return "Licencia"
                url_lower = url.lower()
                if "zero" in url_lower or "cc0" in url_lower:
                    return "CC0 (Public Domain)"
                elif "by-nc" in url_lower:
                    return "CC BY-NC (Attribution Non-Commercial)"
                elif "by-nd" in url_lower:
                    return "CC BY-ND (Attribution NoDerivatives)"
                elif "by-sa" in url_lower:
                    return "CC BY-SA (Attribution ShareAlike)"
                elif "by" in url_lower:
                    return "CC BY (Attribution)"
                elif "sampling" in url_lower:
                    return "Sampling Plus"
                return "Ver Licencia"
                
            license_url = item_data.get("license", "-")
            if license_url.startswith("http"):
                friendly_name = get_friendly_license_name(license_url)
                self.lbl_license_text.setText(
                    self.tr('Licencia: <a href="{url}" style="color: #B9E640; text-decoration: underline;">{name}</a>').format(
                        url=license_url, name=friendly_name
                    )
                )
            else:
                self.lbl_license_text.setText(self.tr("Licencia: ") + license_url)
            
            self.metadata_header_labels["video_codec"].setText(self.tr("Usuario:"))
            self.metadata_header_labels["video_profile"].setText(self.tr("Licencia:"))
            self.metadata_header_labels["aspecto"].setText(self.tr("Estadísticas:"))
            
            self.metadata_labels["creado"].setText("-")
            self.metadata_labels["modificado"].setText("-")
            self.metadata_labels["duración"].setText(item_data.get("duración", "-"))
            self.metadata_labels["resolución"].setText("-")
            self.metadata_labels["video_codec"].setText(item_data.get("username", "-"))
            self.metadata_labels["video_profile"].setText(item_data.get("license", "-"))
            self.metadata_labels["fps"].setText("-")
            self.metadata_labels["aspecto"].setText(f"Rating: {item_data.get('avg_rating', '-')} | Descargas: {item_data.get('num_downloads', '-')}")
            self.metadata_labels["bitrate_video"].setText("-")
            self.metadata_labels["color"].setText("-")
            self.metadata_labels["audio_codec"].setText("REMOTO (Freesound)")
            self.metadata_labels["samplerate"].setText("-")
            self.metadata_labels["canales"].setText("-")
            self.metadata_labels["bitrate_audio"].setText("-")
        else:
            self.license_panel.setVisible(False)
            self.metadata_header_labels["video_codec"].setText(self.tr("Códec Video:"))
            self.metadata_header_labels["video_profile"].setText(self.tr("Perfil Video:"))
            self.metadata_header_labels["aspecto"].setText(self.tr("Rel. Aspecto:"))
            
            # Obtener metadatos ricos de la cache o extraerlos
            if path not in self._metadata_cache:
                self._metadata_cache[path] = self._extract_rich_metadata(path, tipo)
                
            rich_meta = self._metadata_cache[path]
            
            # Llenar todos los campos en la UI
            self.metadata_labels["creado"].setText(rich_meta.get("creado", "-"))
            self.metadata_labels["modificado"].setText(rich_meta.get("modificado", "-"))
            self.metadata_labels["duración"].setText(rich_meta.get("duración", "-"))
            self.metadata_labels["resolución"].setText(rich_meta.get("resolución", "-"))
            self.metadata_labels["video_codec"].setText(rich_meta.get("video_codec", "-"))
            self.metadata_labels["video_profile"].setText(rich_meta.get("video_profile", "-"))
            self.metadata_labels["fps"].setText(rich_meta.get("fps", "-"))
            self.metadata_labels["aspecto"].setText(rich_meta.get("aspecto", "-"))
            self.metadata_labels["bitrate_video"].setText(rich_meta.get("bitrate_video", "-"))
            self.metadata_labels["color"].setText(rich_meta.get("color", "-"))
            self.metadata_labels["audio_codec"].setText(rich_meta.get("audio_codec", "-"))
            self.metadata_labels["samplerate"].setText(rich_meta.get("samplerate", "-"))
            self.metadata_labels["canales"].setText(rich_meta.get("canales", "-"))
            self.metadata_labels["bitrate_audio"].setText(rich_meta.get("bitrate_audio", "-"))

    def _on_video_waveform_ready(self, peaks: list):
        """Callback para el waveform de videos: muestra los peaks si hay audio, oculta el panel si no."""
        if peaks:
            self.waveform_widget.set_peaks(peaks)
        else:
            # El video no tiene pista de audio — ocultar el panel de waveform
            self.audio_panel.setVisible(False)

    def _extract_rich_metadata(self, path: str, tipo: str) -> dict:
        from core.tabs.editing_media.ffprobe_metadata_manager import FFprobeMetadataManager
        return FFprobeMetadataManager.get_instance().get_metadata_instant(path, tipo)

    def _on_async_metadata_ready(self, path: str, meta: dict):
        """Callback cuando la extracción de ffprobe en segundo plano finaliza."""
        if not hasattr(self, "_metadata_cache"):
            self._metadata_cache = {}
        self._metadata_cache[path] = meta

        # Si el archivo procesado es el que se está mostrando actualmente en la UI, actualizar panel
        if getattr(self, "current_playing_path", None) == path:
            if hasattr(self, "metadata_labels"):
                self.metadata_labels["creado"].setText(meta.get("creado", "-"))
                self.metadata_labels["modificado"].setText(meta.get("modificado", "-"))
                self.metadata_labels["duración"].setText(meta.get("duración", "-"))
                self.metadata_labels["resolución"].setText(meta.get("resolución", "-"))
                self.metadata_labels["video_codec"].setText(meta.get("video_codec", "-"))
                self.metadata_labels["video_profile"].setText(meta.get("video_profile", "-"))
                self.metadata_labels["fps"].setText(meta.get("fps", "-"))
                self.metadata_labels["aspecto"].setText(meta.get("aspecto", "-"))
                self.metadata_labels["bitrate_video"].setText(meta.get("bitrate_video", "-"))
                self.metadata_labels["color"].setText(meta.get("color", "-"))
                self.metadata_labels["audio_codec"].setText(meta.get("audio_codec", "-"))
                self.metadata_labels["samplerate"].setText(meta.get("samplerate", "-"))
                self.metadata_labels["canales"].setText(meta.get("canales", "-"))
                self.metadata_labels["bitrate_audio"].setText(meta.get("bitrate_audio", "-"))

            if getattr(self, "current_playing_type", None) == "audio" and hasattr(self, "lbl_audio_sub"):
                dur_str = meta.get("duración", "-")
                self.lbl_audio_sub.setText(f"AUDIO • {dur_str}")


    # ── Métodos de Control para el Reproductor de Audio Central ─────────────
    def _on_play_clicked(self):
        from gui.styles import apply_player_play_button_style
        if not self.audio_player:
            return
        
        state = self.audio_player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.audio_player.pause()
            apply_player_play_button_style(self.btn_play, is_playing=False, icon_size=14)
        else:
            self.audio_player.play()
            apply_player_play_button_style(self.btn_play, is_playing=True, icon_size=14)

    def _on_volume_changed(self, value):
        float_val = value if isinstance(value, float) else value / 100.0
        if self.audio_output:
            self.audio_output.setVolume(float_val)

    def _on_waveform_seek_requested(self, ratio):
        selected_item = self.media_list.currentItem()
        tipo = None
        if selected_item:
            item_data = selected_item.data(Qt.UserRole)
            if item_data:
                tipo = item_data.get("tipo")

        if tipo == "video":
            if self.preview_box and self.preview_box.media_player and self.preview_box.media_player.duration() > 0:
                pos = int(self.preview_box.media_player.duration() * ratio)
                self.preview_box.media_player.setPosition(pos)
        else:
            if self.audio_player and self.audio_player.duration() > 0:
                pos = int(self.audio_player.duration() * ratio)
                self.audio_player.setPosition(pos)

    def _on_video_position_changed(self, position):
        if not self.preview_box or not self.preview_box.media_player:
            return
        selected_item = self.media_list.currentItem()
        if selected_item:
            item_data = selected_item.data(Qt.UserRole)
            if item_data and item_data.get("tipo") == "video":
                duration = self.preview_box.media_player.duration()
                if duration > 0:
                    ratio = position / duration
                    self.waveform_widget.set_playback_ratio(ratio)

    def _format_time_ms(self, ms: int) -> str:
        """Formatea milisegundos a HH:MM:SS.mmm (estándar de edición de video)."""
        if not ms or ms < 0:
            ms = 0
        ms = int(ms)
        s, ms_r = divmod(ms, 1000)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}.{ms_r:03d}"

    def _on_audio_position_changed(self, position):
        if not self.audio_player:
            return
        duration = self.audio_player.duration()
        if duration > 0:
            ratio = position / duration
            self.waveform_widget.set_playback_ratio(ratio)
            self.lbl_time.setText(f"{self._format_time_ms(position)} / {self._format_time_ms(duration)}")

    def _on_audio_duration_changed(self, duration):
        if self.audio_player:
            pos = self.audio_player.position()
            self.lbl_time.setText(f"{self._format_time_ms(pos)} / {self._format_time_ms(duration)}")

    def _stop_audio_playback(self):
        from gui.styles import apply_player_play_button_style
        if self.audio_player:
            try:
                self.audio_player.stop()
                apply_player_play_button_style(self.btn_play, is_playing=False, icon_size=14)
            except Exception:
                pass

    def _clear_metadata(self):
        for lbl in self.metadata_labels.values():
            lbl.setText("-")
        self.btn_reveal.setEnabled(False)
        if hasattr(self, "license_panel"):
            self.license_panel.setVisible(False)

    def _on_reveal_clicked(self):
        selected = self.media_list.currentItem()
        if not selected:
            return
        item_data = selected.data(Qt.UserRole)
        if item_data:
            path = item_data.get("ruta")
            if path and os.path.exists(path):
                norm_path = os.path.normpath(path)
                sys_os = platform.system().lower()
                try:
                    if sys_os == "windows":
                        subprocess.Popen(['explorer', '/select,', norm_path])
                    elif sys_os == "darwin":
                        subprocess.Popen(['open', '-R', norm_path])
                    else:
                        # Linux: intenta nautilus --select o abre carpeta contenedora
                        try:
                            subprocess.Popen(['nautilus', '--select', norm_path])
                        except Exception:
                            from PySide6.QtGui import QDesktopServices
                            from PySide6.QtCore import QUrl
                            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(norm_path)))
                except Exception as e:
                    logger.error(f"Error al revelar archivo en explorador: {e}")

    def _on_toggle_audio_loop(self):
        """Alterna el modo de repetición del reproductor de audio."""
        from gui.styles import apply_player_loop_button_style

        self._audio_loop_active = not self._audio_loop_active
        if self.audio_player:
            if self._audio_loop_active:
                self.audio_player.setLoops(QMediaPlayer.Infinite)
            else:
                self.audio_player.setLoops(1)
        apply_player_loop_button_style(self.btn_loop_audio, is_active=self._audio_loop_active, icon_size=14)
