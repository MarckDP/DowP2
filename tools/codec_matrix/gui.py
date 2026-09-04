# tools/codec_matrix/gui.py
"""
Interfaz simple para correr la matriz de compatibilidad codec<->contenedor contra
un ffmpeg elegido a mano, en vez de depender de una ruta hardcodeada o de escribir
el comando en consola.

Herramienta de mantenedor: no es parte de la app DowP, no se empaqueta ni se
distribuye. Por eso usa Tkinter (viene con Python) en vez de PySide6 - cero
dependencias nuevas, y no se mezcla con el stack de la app.

A proposito NO hay ningun ffmpeg por defecto: hay que elegir el ejecutable a
mano cada vez que se corre, para no correr la matriz sin querer contra el
ffmpeg equivocado.

Uso:
    python tools/codec_matrix/gui.py
"""
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

HERE = os.path.dirname(os.path.abspath(__file__))
RUN_MATRIX = os.path.join(HERE, "run_matrix.py")
BUILD_RUNTIME = os.path.join(HERE, "build_runtime_json.py")


class CodecMatrixGUI:
    def __init__(self, root):
        self.root = root
        root.title("DowP - Codec Matrix Runner")
        root.geometry("760x520")
        root.minsize(600, 400)

        self.ffmpeg_path = tk.StringVar()

        top = tk.Frame(root, padx=10, pady=10)
        top.pack(fill=tk.X)

        tk.Label(top, text="ffmpeg a probar (elegir a mano, sin default):").pack(anchor="w")
        row = tk.Frame(top)
        row.pack(fill=tk.X, pady=(2, 8))
        self.entry = tk.Entry(row, textvariable=self.ffmpeg_path, state="readonly")
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(row, text="Elegir...", command=self._pick_ffmpeg).pack(side=tk.LEFT, padx=(6, 0))

        btn_row = tk.Frame(top)
        btn_row.pack(fill=tk.X)
        self.run_btn = tk.Button(btn_row, text="Correr matriz", command=self._run_matrix, state=tk.DISABLED)
        self.run_btn.pack(side=tk.LEFT)
        self.build_btn = tk.Button(
            btn_row, text="Generar ffmpeg_codec_matrix.json para la app",
            command=self._build_runtime, state=tk.DISABLED,
        )
        self.build_btn.pack(side=tk.LEFT, padx=(6, 0))

        tk.Label(root, text="Progreso:", padx=10).pack(anchor="w")
        self.log = scrolledtext.ScrolledText(root, state=tk.DISABLED, font=("Consolas", 9))
        self.log.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

    def _pick_ffmpeg(self):
        filetypes = [("ffmpeg", "ffmpeg.exe")] if sys.platform == "win32" else [("ffmpeg", "ffmpeg")]
        filetypes.append(("Todos los archivos", "*.*"))
        path = filedialog.askopenfilename(title="Seleccionar ejecutable de ffmpeg", filetypes=filetypes)
        if not path:
            return
        self.ffmpeg_path.set(path)
        self.run_btn.config(state=tk.NORMAL)
        self.build_btn.config(state=tk.DISABLED)
        self._log(f"ffmpeg seleccionado: {path}\n")

    def _log(self, text):
        self.log.config(state=tk.NORMAL)
        self.log.insert(tk.END, text)
        self.log.see(tk.END)
        self.log.config(state=tk.DISABLED)

    def _set_running(self, running):
        state = tk.DISABLED if running else tk.NORMAL
        self.run_btn.config(state=state if self.ffmpeg_path.get() else tk.DISABLED)

    def _run_matrix(self):
        path = self.ffmpeg_path.get()
        if not path or not os.path.exists(path):
            messagebox.showerror("Error", "Elige un ejecutable de ffmpeg válido primero.")
            return
        self.run_btn.config(state=tk.DISABLED)
        self.build_btn.config(state=tk.DISABLED)
        self._log(f"\n=== Corriendo matriz contra: {path} ===\n")
        threading.Thread(target=self._run_matrix_worker, args=(path,), daemon=True).start()

    def _run_matrix_worker(self, ffmpeg_path):
        try:
            proc = subprocess.Popen(
                [sys.executable, RUN_MATRIX, "--ffmpeg", ffmpeg_path],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", cwd=HERE,
            )
            for line in proc.stdout:
                self.root.after(0, self._log, line)
            proc.wait()
            ok = proc.returncode == 0
        except Exception as e:
            ok = False
            self.root.after(0, self._log, f"\nError al correr run_matrix.py: {e}\n")

        self.root.after(0, self._on_run_done, ok)

    def _on_run_done(self, ok):
        self.run_btn.config(state=tk.NORMAL)
        if ok:
            self._log("\n=== Listo. tools/codec_matrix/runs/latest.json actualizado. ===\n")
            self.build_btn.config(state=tk.NORMAL)
        else:
            self._log("\n=== Termino con errores, revisa el log arriba. ===\n")

    def _build_runtime(self):
        self.build_btn.config(state=tk.DISABLED)
        self._log("\n=== Generando src/assets/data/ffmpeg_codec_matrix.json ===\n")
        threading.Thread(target=self._build_runtime_worker, daemon=True).start()

    def _build_runtime_worker(self):
        try:
            proc = subprocess.run(
                [sys.executable, BUILD_RUNTIME],
                capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=HERE,
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            ok = proc.returncode == 0
        except Exception as e:
            out = str(e)
            ok = False
        self.root.after(0, self._log, out + "\n")
        self.root.after(0, lambda: self.build_btn.config(state=tk.NORMAL))
        if ok:
            self.root.after(0, self._log, "=== Listo. ===\n")
        else:
            self.root.after(0, self._log, "=== Termino con errores. ===\n")


def main():
    root = tk.Tk()
    CodecMatrixGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
