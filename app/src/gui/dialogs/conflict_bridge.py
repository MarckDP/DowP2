# src/gui/dialogs/conflict_bridge.py
"""
Puente entre el hilo de descarga (worker) y el hilo principal (UI) para mostrar
ConflictDialog de forma modal sin manejar eventos a mano.

DownloaderMaster corre dentro de un QThread (ver gui/tabs/advanced_process/workers.py
y core/utils/queue_manager.py) y necesita poder preguntarle al usuario qué hacer
cuando el archivo de salida ya existe (modo SOLO). Como los widgets de Qt solo se
pueden tocar desde el hilo principal, se usa una señal conectada con
Qt.BlockingQueuedConnection: emitirla desde el hilo worker bloquea ese hilo hasta que
el slot conectado termina de correr en el hilo dueño del objeto (el principal, donde
se instancia este puente), sin necesidad de un threading.Event manual.

Debe instanciarse una única vez, en el hilo principal (ver gui/main_window.py), antes
de que pueda arrancar cualquier descarga.
"""
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication


class ConflictDialogBridge(QObject):
    _ask_signal = Signal(str)

    _instance = None

    def __init__(self):
        super().__init__()
        self._last_result = "cancel"
        # BlockingQueuedConnection explícita: sin importar desde qué hilo se emita
        # _ask_signal, este connect obliga a Qt a bloquear al emisor hasta que
        # _on_ask (que corre en el hilo de este objeto, el principal) retorne.
        self._ask_signal.connect(self._on_ask, Qt.ConnectionType.BlockingQueuedConnection)
        ConflictDialogBridge._instance = self

    def ask(self, filename: str) -> str:
        """
        Llamado desde el hilo de descarga (worker). Bloquea ese hilo hasta que el
        usuario cierra el diálogo en el hilo principal. Retorna
        "overwrite" / "rename" / "cancel".
        """
        self._ask_signal.emit(filename)
        return self._last_result

    def _on_ask(self, filename: str):
        """Corre en el hilo principal (conexión BlockingQueuedConnection)."""
        from gui.dialogs.conflict_dialog import ConflictDialog

        parent = QApplication.activeWindow()
        if parent is None:
            top_levels = QApplication.topLevelWidgets()
            parent = top_levels[0] if top_levels else None

        dialog = ConflictDialog(parent, filename)
        dialog.exec()
        self._last_result = dialog.result


def get_conflict_bridge() -> ConflictDialogBridge | None:
    """Retorna la instancia única creada en MainWindow, o None si aún no existe."""
    return ConflictDialogBridge._instance
