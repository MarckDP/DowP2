# src/core/utils/taskbar_progress.py
import platform
from core.logger.logger_manager import logger

class TaskbarProgressManager:
    """
    Gestor multiplataforma para el progreso en la barra de tareas/Dock.
    """
    def __init__(self, win_id=None):
        self.os = platform.system()
        self.win_id = win_id
        self._taskbar = None
        self._initialized = False

        if self.os == "Windows" and self.win_id:
            self._init_windows()
        elif self.os == "Darwin":
            self._init_macos()

    def _init_windows(self):
        try:
            import ctypes
            from ctypes import wintypes

            # Constantes de ITaskbarList3
            TBPF_NOPROGRESS = 0x0
            TBPF_INDETERMINATE = 0x1
            TBPF_NORMAL = 0x2
            TBPF_ERROR = 0x4
            TBPF_PAUSED = 0x8

            class GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", wintypes.BYTE * 8)
                ]

                def __init__(self, guid_str):
                    # {XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}
                    g = guid_str.strip("{}").split("-")
                    self.Data1 = int(g[0], 16)
                    self.Data2 = int(g[1], 16)
                    self.Data3 = int(g[2], 16)
                    for i in range(2):
                        self.Data4[i] = int(g[3][i*2:i*2+2], 16)
                    for i in range(6):
                        self.Data4[i+2] = int(g[4][i*2:i*2+2], 16)

            CLSID_TaskbarList = GUID("{56FDF344-FD6D-11D0-958A-006097C9A090}")
            IID_ITaskbarList3 = GUID("{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}")

            # Cargar ole32 para CoCreateInstance
            ole32 = ctypes.windll.ole32
            ole32.CoCreateInstance.argtypes = [
                ctypes.POINTER(GUID), ctypes.c_void_p, wintypes.DWORD,
                ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)
            ]

            # Crear instancia
            ptr = ctypes.c_void_p()
            hr = ole32.CoCreateInstance(
                ctypes.byref(CLSID_TaskbarList), None, 1,
                ctypes.byref(IID_ITaskbarList3), ctypes.byref(ptr)
            )

            if hr == 0:
                self._taskbar = ptr
                # Definir VTable de ITaskbarList3 (simplificado para lo que necesitamos)
                # IUnknown: 0, 1, 2
                # ITaskbarList: 3, 4, 5, 6, 7
                # ITaskbarList2: 8
                # ITaskbarList3: 9 (SetProgressValue), 10 (SetProgressState)...
                
                self._SetProgressValue = ctypes.WINFUNCTYPE(
                    ctypes.c_long, ctypes.c_void_p, wintypes.HWND, ctypes.c_uint64, ctypes.c_uint64
                )(self._get_vtable_func(9))
                
                self._SetProgressState = ctypes.WINFUNCTYPE(
                    ctypes.c_long, ctypes.c_void_p, wintypes.HWND, ctypes.c_int
                )(self._get_vtable_func(10))

                # Inicializar
                init_func = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(self._get_vtable_func(3))
                init_func(self._taskbar)
                
                self._initialized = True
                self.TBPF_NORMAL = TBPF_NORMAL
                self.TBPF_INDETERMINATE = TBPF_INDETERMINATE
                self.TBPF_ERROR = TBPF_ERROR
                self.TBPF_NOPROGRESS = TBPF_NOPROGRESS
                
                logger.info("TaskbarProgressManager: Windows ITaskbarList3 inicializado")
        except Exception as e:
            logger.error(f"TaskbarProgressManager: Error inicializando Windows: {e}")

    def _get_vtable_func(self, index):
        import ctypes
        vtable = ctypes.cast(self._taskbar, ctypes.POINTER(ctypes.c_void_p))[0]
        return ctypes.cast(vtable, ctypes.POINTER(ctypes.c_void_p))[index]

    def _init_macos(self):
        # Placeholder para implementación futura con pyobjc
        logger.info("TaskbarProgressManager: macOS detectado (Placeholder activo)")

    def set_value(self, value, total=100):
        if not self._initialized or not self.win_id:
            return

        if self.os == "Windows":
            try:
                # El win_id de PySide es el HWND en Windows
                self._SetProgressValue(self._taskbar, self.win_id, int(value), int(total))
            except Exception:
                pass

    def set_state(self, state):
        """
        state: "normal", "indeterminate", "error", "none"
        """
        if not self._initialized or not self.win_id:
            return

        if self.os == "Windows":
            flags = self.TBPF_NOPROGRESS
            if state == "normal": flags = self.TBPF_NORMAL
            elif state == "indeterminate": flags = self.TBPF_INDETERMINATE
            elif state == "error": flags = self.TBPF_ERROR
            
            try:
                self._SetProgressState(self._taskbar, self.win_id, flags)
            except Exception:
                pass

    def stop(self):
        self.set_state("none")
        self.set_value(0)
