# src/core/tabs/image_tools/image_converter.py
"""Motor de conversión de formatos de imagen para "Convertir" (Editor de Imagen).

Reemplaza los binarios externos que usaba DowP1 (Ghostscript/Poppler/Inkscape) por
librerías puro-pip con wheels para Windows/macOS/Linux -- ver la nota en
core/constants.py justo después de UPSCALING_TOOLS. EPS/PS quedan sin soporte por
ahora: no existe un equivalente puro-pip a un intérprete de PostScript real (esa
nota documenta el plan futuro: bundlear Ghostscript solo en Windows, detectar un
`gs` del sistema en Linux/macOS)."""
import io
import os

from PIL import Image, ImageOps

from core.logger.logger_manager import logger
from core.tabs.editing_media.editing_media_logic import RAW_EXTS
from core.constants import INTERPOLATION_METHODS, CANVAS_PRESET_SIZES

# Registro de plugins de Pillow -- opcionales a propósito (mismo criterio que
# CAN_SVG/CAN_PDF en el image_converter.py de DowP1): si faltan, solo se
# deshabilita ese formato puntual (AVIF de salida / HEIC de entrada), en vez de
# tirar abajo el arranque de toda la app con un ImportError a nivel de módulo.
try:
    import pillow_avif  # noqa: F401 -- registra el plugin AVIF de Pillow al importar.
    CAN_AVIF = True
except ImportError:
    CAN_AVIF = False
    logger.warning("Convertir: 'pillow-avif-plugin' no instalado -- no se podrá convertir a AVIF.")

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    logger.warning("Convertir: 'pillow-heif' no instalado -- no se podrán leer archivos HEIC/HEIF.")

_RESIZE_METHOD_MAP = {
    "LANCZOS": Image.Resampling.LANCZOS,
    "BICUBIC": Image.Resampling.BICUBIC,
    "BILINEAR": Image.Resampling.BILINEAR,
    "NEAREST": Image.Resampling.NEAREST,
}

_VECTOR_UNSUPPORTED_EXTS = {".eps", ".ps"}
_SVG_EXTS = {".svg", ".svgz"}
_PDF_LIKE_EXTS = {".pdf", ".ai"}
_VECTOR_EXTS = _SVG_EXTS | _PDF_LIKE_EXTS

_DEFAULT_VECTOR_DPI = 300

_EXT_TO_PASSTHROUGH_FORMAT = {
    ".png": "PNG", ".jpg": "JPG", ".jpeg": "JPG", ".webp": "WEBP",
    ".tiff": "TIFF", ".tif": "TIFF", ".bmp": "BMP",
}


class UnsupportedFormatError(Exception):
    """Formato de entrada reconocido por la cola (ver VALID_VECTOR_EXTS en
    editing_media_logic.py) pero sin soporte de conversión todavía -- hoy: EPS/PS."""


class ImageConverter:
    """Convierte un archivo de imagen a otro formato/tamaño. Sin estado propio entre
    llamadas -- una instancia se puede reusar para todo un lote (ver
    gui/tabs/image_tools/image_convert_worker.py)."""

    def convert_file(self, input_path: str, output_path: str, options: dict,
                      progress_callback=None, cancellation_event=None) -> tuple[bool, str]:
        try:
            if progress_callback:
                progress_callback(5)
            if cancellation_event and cancellation_event.is_set():
                return False, "Cancelado por el usuario."

            input_ext = os.path.splitext(input_path)[1].lower()
            output_format = options.get("format", "No Convertir").upper()

            resize_enabled = options.get("resize_enabled", False)
            target_size = None
            maintain_aspect = options.get("resize_maintain_aspect", True)
            if resize_enabled:
                width, height = options.get("resize_width"), options.get("resize_height")
                if width and height:
                    target_size = (int(width), int(height))

            img = self._load_image(input_path, input_ext, target_size, maintain_aspect, options)
            if progress_callback:
                progress_callback(40)
            if cancellation_event and cancellation_event.is_set():
                return False, "Cancelado por el usuario."

            # Los formatos vectoriales ya se renderizaron directo al tamaño objetivo
            # dentro de _load_image (DPI/escala calculados ahí) -- un resize posterior
            # solo aplica a raster/RAW, que se cargan siempre a tamaño nativo.
            if resize_enabled and target_size and input_ext not in _VECTOR_EXTS:
                img = self._resize_raster_image(img, target_size, maintain_aspect, options)
            if progress_callback:
                progress_callback(60)
            if cancellation_event and cancellation_event.is_set():
                return False, "Cancelado por el usuario."

            # Reescalar IA -- mismo orden que usaba DowP1 (Redimensionar primero,
            # Reescalar IA después): son ejes independientes, no se descartan entre sí.
            if options.get("upscale_enabled", False):
                img = self._apply_ai_upscale(img, options, cancellation_event)
            if progress_callback:
                progress_callback(80)

            # Canvas (preset del menú, ajuste de lote) -- último paso antes de
            # guardar, mismo orden que DowP1 (resize -> upscale IA -> canvas).
            if options.get("canvas_enabled", False):
                img = self._apply_canvas(img, options)
            if progress_callback:
                progress_callback(90)

            if output_format == "NO CONVERTIR":
                self._save_passthrough(img, input_ext, output_path, options)
            else:
                self._save_as(img, output_format, output_path, options)

            if progress_callback:
                progress_callback(100)
            return True, "Conversión completada."
        except UnsupportedFormatError as e:
            logger.warning(f"Convertir: {input_path} -> {e}")
            return False, str(e)
        except Exception as e:
            logger.error(f"Convertir: fallo al procesar {input_path}: {e}")
            return False, str(e)

    # ------------------------------------------------------------------
    # Carga
    # ------------------------------------------------------------------
    def _load_image(self, filepath, ext, target_size, maintain_aspect, options):
        if ext in RAW_EXTS:
            return self._load_raw(filepath)
        if ext in _VECTOR_UNSUPPORTED_EXTS:
            raise UnsupportedFormatError(
                f"{ext.upper()} todavía no está soportado -- requiere un intérprete de "
                "PostScript real (ver la nota EPS/PS en core/constants.py)."
            )
        if ext in _SVG_EXTS:
            return self._load_svg(filepath, target_size, maintain_aspect, options)
        if ext in _PDF_LIKE_EXTS:
            return self._load_pdf_like(filepath, target_size, maintain_aspect, options)
        return Image.open(filepath)

    def _load_raw(self, filepath):
        """Revela RAW con rawpy/LibRaw -- mismos parámetros que ya usaba DowP1."""
        import rawpy
        with rawpy.imread(filepath) as raw:
            rgb = raw.postprocess(
                use_camera_wb=True, half_size=False, no_auto_bright=False,
                output_bps=8, output_color=rawpy.ColorSpace.sRGB,
                demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD, use_auto_wb=False,
                gamma=(2.222, 4.5), bright=1.0, highlight_mode=rawpy.HighlightMode.Blend,
            )
        img = Image.fromarray(rgb)
        return ImageOps.exif_transpose(img)

    def _load_svg(self, filepath, target_size, maintain_aspect, options):
        """Renderiza SVG con resvg_py -- reemplaza CairoSVG+fallback Inkscape de
        DowP1, sin depender de libcairo del sistema (wheel autocontenido)."""
        import resvg_py
        kwargs = {"svg_path": filepath}
        if target_size:
            width, height = target_size
            kwargs["width"] = width
            if not maintain_aspect:
                kwargs["height"] = height
        png_bytes = bytes(resvg_py.svg_to_bytes(**kwargs))
        img = Image.open(io.BytesIO(png_bytes))
        img.load()
        if target_size:
            # resvg ya renderiza cerca del tamaño pedido, pero el ancho/alto exacto
            # (con proporción mantenida) se corrige acá -- mismo criterio que DowP1
            # aplicaba sobre la salida de CairoSVG.
            img = self._resize_raster_image(img, target_size, maintain_aspect, options)
        return img

    def _load_pdf_like(self, filepath, target_size, maintain_aspect, options):
        """Renderiza PDF/AI con pypdfium2 -- reemplaza Poppler (vía pdf2image) de
        DowP1. La inmensa mayoría de .ai modernos (Illustrator 9+) son PDF válido
        por dentro; los .ai pre-PDF (PostScript puro) caen en UnsupportedFormatError,
        mismo bucket que EPS/PS."""
        import pypdfium2 as pdfium
        try:
            pdf = pdfium.PdfDocument(filepath)
        except Exception as e:
            raise UnsupportedFormatError(
                f"No se pudo abrir como PDF ({os.path.basename(filepath)}): {e}. "
                "Los .ai muy antiguos (pre-PDF, PostScript puro) no están soportados."
            )
        try:
            page = pdf[0]
            try:
                if target_size:
                    scale = self._calculate_optimal_dpi(page, target_size, maintain_aspect) / 72.0
                else:
                    scale = _DEFAULT_VECTOR_DPI / 72.0
                bitmap = page.render(scale=scale, fill_color=(0, 0, 0, 0))
                img = bitmap.to_pil()
            finally:
                page.close()
        finally:
            pdf.close()
        if target_size:
            img = self._resize_raster_image(img, target_size, maintain_aspect, options)
        return img

    def _calculate_optimal_dpi(self, page, target_size, maintain_aspect) -> float:
        """Sondea el tamaño real de la página (puntos, 72/pulgada) para calcular el
        DPI que rasteriza justo al tamaño objetivo -- pypdfium2 devuelve esto directo
        con page.get_size(), a diferencia de DowP1, que tenía que parsear el texto de
        pdfinfo (Poppler) con una regex."""
        target_width, target_height = target_size
        doc_width_pts, doc_height_pts = page.get_size()
        doc_width_pts = max(1.0, doc_width_pts)
        doc_height_pts = max(1.0, doc_height_pts)
        dpi_width = target_width / (doc_width_pts / 72.0)
        dpi_height = target_height / (doc_height_pts / 72.0)
        optimal_dpi = min(dpi_width, dpi_height) if maintain_aspect else max(dpi_width, dpi_height)
        return max(72.0, min(optimal_dpi, 4800.0))

    def _resize_raster_image(self, img, target_size, maintain_aspect, options):
        """Reescala una imagen raster con el método de interpolación elegido --
        portado 1:1 de DowP1, reusa INTERPOLATION_METHODS ya definido en
        core/constants.py."""
        target_width, target_height = target_size
        original_width, original_height = img.size
        method_label = options.get("interpolation_method", "Lanczos (Mejor Calidad)")
        method_key = INTERPOLATION_METHODS.get(method_label, "LANCZOS")
        resampling = _RESIZE_METHOD_MAP.get(method_key, Image.Resampling.LANCZOS)

        if not maintain_aspect:
            return img.resize((target_width, target_height), resampling)

        original_aspect = original_width / original_height
        target_aspect = target_width / target_height
        if original_aspect > target_aspect:
            new_width, new_height = target_width, int(target_width / original_aspect)
        else:
            new_height, new_width = target_height, int(target_height * original_aspect)
        if new_width > target_width:
            new_width, new_height = target_width, int(target_width / original_aspect)
        if new_height > target_height:
            new_height, new_width = target_height, int(target_height * original_aspect)
        return img.resize((new_width, new_height), resampling)

    def _apply_ai_upscale(self, img, options: dict, cancellation_event=None):
        """Corre el motor de Reescalar IA (Waifu2x/SRMD/Upscayl, ver
        core/tabs/image_tools/upscale_engine.py) sobre `img` -- los 3 son binarios
        externos (archivo-a-archivo), así que hay que volcar la imagen a un PNG
        temporal, invocar el motor, y recargar el resultado como PIL.Image."""
        import tempfile
        from core.tabs.image_tools.upscale_engine import run_upscale

        with tempfile.TemporaryDirectory(prefix="dowp_upscale_") as tmp_dir:
            temp_in = os.path.join(tmp_dir, "in.png")
            temp_out = os.path.join(tmp_dir, "out.png")
            img.save(temp_in, "PNG")

            success, message = run_upscale(temp_in, temp_out, options, cancellation_event)
            if not success:
                raise Exception(f"Reescalar IA: {message}")

            result = Image.open(temp_out)
            result.load()
            return result

    def _apply_canvas(self, img, options: dict):
        """Canvas como ajuste de LOTE (preset elegido en el popover, clic derecho) --
        puerto directo de _apply_canvas_by_option/_calculate_canvas_position de
        DowP1 (image_converter.pyc decompilado), PIL puro. Cada archivo del lote
        adapta el mismo preset a su propio tamaño nativo -- no es una posición/
        tamaño fijo, se recalcula acá por imagen. El Canvas editado a mano sobre el
        archivo actualmente abierto (clic izquierdo, en vivo) es un concepto
        separado -- ver la nota de Fase 3 en el plan, no pasa por acá."""
        img_width, img_height = img.size
        if img.mode != "RGBA":
            img = img.convert("RGBA")

        canvas_option = options.get("canvas_option", "Sin ajuste")
        if canvas_option == "Añadir Margen Externo":
            margin = int(options.get("canvas_margin", 100))
            canvas_width, canvas_height = img_width + margin * 2, img_height + margin * 2
        elif canvas_option == "Añadir Margen Interno":
            margin = int(options.get("canvas_margin", 100))
            canvas_width, canvas_height = img_width, img_height
            new_width, new_height = max(1, img_width - margin * 2), max(1, img_height - margin * 2)
            if new_width < img_width or new_height < img_height:
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                img_width, img_height = new_width, new_height
        elif canvas_option in CANVAS_PRESET_SIZES:
            canvas_width, canvas_height = CANVAS_PRESET_SIZES[canvas_option]
        elif canvas_option == "Personalizado...":
            canvas_width = int(options.get("canvas_width", img_width))
            canvas_height = int(options.get("canvas_height", img_height))
        else:
            return img

        if canvas_option not in ("Añadir Margen Externo", "Añadir Margen Interno"):
            if img_width > canvas_width or img_height > canvas_height:
                overflow_mode = options.get("canvas_overflow_mode", "Centrar (puede recortar)")
                if overflow_mode == "Advertir y no procesar":
                    raise Exception(
                        f"La imagen ({img_width}×{img_height}) excede el canvas "
                        f"({canvas_width}×{canvas_height})."
                    )
                elif overflow_mode == "Reducir hasta que quepa":
                    scale = min(canvas_width / img_width, canvas_height / img_height)
                    img = img.resize((int(img_width * scale), int(img_height * scale)), Image.Resampling.LANCZOS)
                    img_width, img_height = img.size
                elif overflow_mode in ("Recortar al canvas", "Centrar (puede recortar)"):
                    left = max(0, (img_width - canvas_width) // 2)
                    top = max(0, (img_height - canvas_height) // 2)
                    img = img.crop((left, top, left + canvas_width, top + canvas_height))
                    img_width, img_height = img.size

        canvas = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))
        position = options.get("canvas_position", "Centro")
        x, y = self._calculate_canvas_position(canvas_width, canvas_height, img_width, img_height, position)
        canvas.paste(img, (x, y), img)
        return canvas

    def _calculate_canvas_position(self, canvas_w, canvas_h, img_w, img_h, position: str):
        """Misma fórmula que canvas_popover.py::calc_position (duplicada a
        propósito -- ese vive en gui/, core/ no depende de gui/)."""
        position_map = {
            "Centro": ("center", "center"), "Arriba Izquierda": ("left", "top"),
            "Arriba Centro": ("center", "top"), "Arriba Derecha": ("right", "top"),
            "Centro Izquierda": ("left", "center"), "Centro Derecha": ("right", "center"),
            "Abajo Izquierda": ("left", "bottom"), "Abajo Centro": ("center", "bottom"),
            "Abajo Derecha": ("right", "bottom"),
        }
        h_align, v_align = position_map.get(position, ("center", "center"))
        x = 0 if h_align == "left" else (canvas_w - img_w) // 2 if h_align == "center" else canvas_w - img_w
        y = 0 if v_align == "top" else (canvas_h - img_h) // 2 if v_align == "center" else canvas_h - img_h
        return int(x), int(y)

    # ------------------------------------------------------------------
    # Guardado -- todo Pillow/img2pdf, sin binarios externos.
    # ------------------------------------------------------------------
    def _save_passthrough(self, img, input_ext, output_path, options):
        """"No Convertir": mantiene el formato original si es un raster con escritor
        propio (solo aplica resize); si el origen era vectorial/RAW/algo sin
        escritor, cae a PNG -- mismo comportamiento que DowP1."""
        fmt = _EXT_TO_PASSTHROUGH_FORMAT.get(input_ext, "PNG")
        self._save_as(img, fmt, output_path, options)

    def _save_as(self, img, output_format, output_path, options):
        writers = {
            "PNG": self._save_as_png, "JPG": self._save_as_jpg, "JPEG": self._save_as_jpg,
            "WEBP": self._save_as_webp, "AVIF": self._save_as_avif, "PDF": self._save_as_pdf,
            "TIFF": self._save_as_tiff, "ICO": self._save_as_ico, "BMP": self._save_as_bmp,
        }
        writer = writers.get(output_format)
        if not writer:
            raise Exception(f"Formato de salida no soportado: {output_format}")
        writer(img, output_path, options)

    def _save_as_png(self, img, output_path, options):
        if options.get("png_transparency", True) and img.mode in ("RGBA", "LA", "PA"):
            save_img = img
        else:
            save_img = img.convert("RGB")
        save_img.save(output_path, "PNG", compress_level=options.get("png_compression", 6), optimize=True)

    def _save_as_jpg(self, img, output_path, options):
        if img.mode in ("RGBA", "LA", "PA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1])
            save_img = background
        else:
            save_img = img.convert("RGB")
        subsampling_map = {"4:2:0 (Estándar)": "4:2:0", "4:2:2 (Alta)": "4:2:2", "4:4:4 (Máxima)": "4:4:4"}
        subsampling = subsampling_map.get(options.get("jpg_subsampling", "4:2:0 (Estándar)"), "4:2:0")
        save_img.save(
            output_path, "JPEG",
            quality=options.get("jpg_quality", 90),
            subsampling=subsampling,
            progressive=options.get("jpg_progressive", False),
            optimize=True,
        )

    def _save_as_webp(self, img, output_path, options):
        if options.get("webp_transparency", True) and img.mode in ("RGBA", "LA", "PA"):
            save_img = img
        else:
            save_img = img.convert("RGB")
        kwargs = {"format": "WEBP", "lossless": options.get("webp_lossless", False)}
        if not kwargs["lossless"]:
            kwargs["quality"] = options.get("webp_quality", 90)
        if options.get("webp_metadata", False) and "exif" in img.info:
            kwargs["exif"] = img.info["exif"]
        save_img.save(output_path, **kwargs)

    def _save_as_avif(self, img, output_path, options):
        if not CAN_AVIF:
            raise Exception("No se puede guardar como AVIF -- falta instalar 'pillow-avif-plugin'.")
        save_img = img if img.mode in ("RGBA", "RGB") else img.convert("RGBA" if "A" in img.mode else "RGB")
        save_img.save(output_path, "AVIF", quality=options.get("avif_quality", 80))

    def _save_as_pdf(self, img, output_path, options):
        import img2pdf
        save_img = img if img.mode in ("RGB", "L") else img.convert("RGB")
        temp_png = output_path + ".tmp.png"
        try:
            save_img.save(temp_png, "PNG")
            with open(output_path, "wb") as f:
                f.write(img2pdf.convert(temp_png))
        finally:
            if os.path.exists(temp_png):
                os.remove(temp_png)

    def _save_as_tiff(self, img, output_path, options):
        if options.get("tiff_transparency", True) and img.mode in ("RGBA", "LA", "PA"):
            save_img = img
        else:
            save_img = img.convert("RGB")
        compression_map = {
            "Ninguna": None, "LZW (Recomendada)": "tiff_lzw",
            "Deflate (ZIP)": "tiff_deflate", "PackBits": "packbits",
        }
        compression = compression_map.get(options.get("tiff_compression", "LZW (Recomendada)"))
        kwargs = {"format": "TIFF"}
        if compression:
            kwargs["compression"] = compression
        save_img.save(output_path, **kwargs)

    def _save_as_ico(self, img, output_path, options):
        save_img = img if img.mode == "RGBA" else img.convert("RGBA")
        sizes_dict = options.get("ico_sizes", {})
        selected = [size for size, on in sizes_dict.items() if on] or [32, 256]
        save_img.save(output_path, "ICO", sizes=[(s, s) for s in selected])

    def _save_as_bmp(self, img, output_path, options):
        img.convert("RGB").save(output_path, "BMP")
