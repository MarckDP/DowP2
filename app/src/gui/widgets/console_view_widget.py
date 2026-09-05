# src/gui/widgets/console_view_widget.py
from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget, QLabel
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QTextCursor, QTextCharFormat, QColor

from gui.styles import get_theme_token
from core.logger.console_log_handler import get_console_log_handler

_LEVEL_TOKENS = {
    "DEBUG": "consola_debug",
    "INFO": "consola_texto",
    "WARNING": "consola_advertencia",
    "ERROR": "consola_error",
    "CRITICAL": "consola_critico",
}
_DEFAULT_LEVEL_COLOR = "#ffffff"


class ConsoleViewWidget(QWidget):
    """Widget de contenido puro para la consola en vivo: solo el visor de texto + el estado
    'desactivada'. Sin chrome de página de ajustes, para poder montarse también dentro de
    BottomConsolePanel (gui/widgets/bottom_console_panel.py) más adelante sin reescribirlo."""

    FLUSH_INTERVAL_MS = 120

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pending_entries = []
        self._capturing = False
        self._handler = get_console_log_handler()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.text_view = QPlainTextEdit()
        self.text_view.setReadOnly(True)
        mono_font = QFont("Consolas")
        mono_font.setStyleHint(QFont.Monospace)  # Qt sustituye por una monoespaciada del sistema si "Consolas" no existe
        mono_font.setPointSize(9)
        self.text_view.setFont(mono_font)
        self.text_view.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {get_theme_token('consola_fondo', '#000000')};
                color: {get_theme_token('consola_texto', '#ffffff')};
                border: 1px solid {get_theme_token('borde_normal', '#222222')};
                border-radius: 6px;
                padding: 6px;
            }}
        """)
        layout.addWidget(self.text_view)

        self.placeholder = QLabel(self.tr("Consola desactivada"))
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setStyleSheet("color: #666666; font-size: 12px;")
        layout.addWidget(self.placeholder)
        self.placeholder.hide()

        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(self.FLUSH_INTERVAL_MS)
        self._flush_timer.timeout.connect(self._flush_pending)

        # Estado inicial: apagada hasta que el llamador (ConsolePage) aplique la config cargada.
        self.text_view.hide()
        self.placeholder.show()

    def set_wrap_enabled(self, enabled: bool):
        self.text_view.setLineWrapMode(
            QPlainTextEdit.WidgetWidth if enabled else QPlainTextEdit.NoWrap
        )

    def set_capturing(self, capturing: bool):
        if capturing == self._capturing:
            return
        self._capturing = capturing

        if capturing:
            self.placeholder.hide()
            self.text_view.show()
            self.text_view.clear()
            cursor = self.text_view.textCursor()
            cursor.movePosition(QTextCursor.End)
            for entry in self._handler.buffer:
                self._insert_entry(cursor, entry)
            self.text_view.setTextCursor(cursor)
            self._pending_entries.clear()
            self._handler.line_appended.connect(self._on_line_appended)
            self._flush_timer.start()
        else:
            self._flush_timer.stop()
            try:
                self._handler.line_appended.disconnect(self._on_line_appended)
            except (RuntimeError, TypeError):
                pass
            self._pending_entries.clear()
            self.text_view.hide()
            self.placeholder.show()

    def get_export_lines(self) -> list:
        """Copia de las entradas acumuladas (buffer persistente, no solo lo visible en pantalla),
        para que Copiar/Exportar funcionen igual esté la consola activada o no."""
        return list(self._handler.buffer)

    def clear_all(self):
        """Limpia tanto el buffer persistente del handler como la vista — usado por el botón
        'Limpiar'. Si solo se limpiara la vista, reactivar la captura la repoblaría con lo ya
        'borrado'."""
        self._handler.buffer.clear()
        self._pending_entries.clear()
        self.text_view.clear()

    def _on_line_appended(self, entry: dict):
        self._pending_entries.append(entry)

    def _flush_pending(self):
        if not self._pending_entries:
            return
        entries, self._pending_entries = self._pending_entries, []
        cursor = self.text_view.textCursor()
        cursor.movePosition(QTextCursor.End)
        for entry in entries:
            self._insert_entry(cursor, entry)
        self.text_view.setTextCursor(cursor)
        self._trim_to_max_lines()

    def _insert_entry(self, cursor, entry: dict):
        """Inserta una línea completa con el color de su nivel; CRITICAL además resalta en
        negrita solo el tag del nivel dentro de la línea."""
        color = get_theme_token(_LEVEL_TOKENS.get(entry["level"]), _DEFAULT_LEVEL_COLOR)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))

        if entry["level"] == "CRITICAL":
            tag, sep, rest = entry["line"].partition(entry["level"])
            cursor.setCharFormat(fmt)
            cursor.insertText(tag)
            bold_fmt = QTextCharFormat(fmt)
            bold_fmt.setFontWeight(QFont.Bold)
            cursor.setCharFormat(bold_fmt)
            cursor.insertText(sep)  # sep == entry["level"] si se encontró, "" si no
            cursor.setCharFormat(fmt)
            cursor.insertText(rest + "\n")
        else:
            cursor.setCharFormat(fmt)
            cursor.insertText(entry["line"] + "\n")

    def _trim_to_max_lines(self):
        max_lines = self._handler.MAX_LINES
        doc = self.text_view.document()
        excess = doc.blockCount() - max_lines
        if excess <= 0:
            return
        cursor = QTextCursor(doc)
        cursor.movePosition(QTextCursor.Start)
        cursor.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor, excess)
        cursor.removeSelectedText()
