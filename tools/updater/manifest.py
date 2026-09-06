"""Genera o compara manifiestos de un arbol de build: ruta -> (blake2b, tamano).

Es el prototipo minimo del manifiesto que usaria el updater, y sirve para medir cuanto
pesa de verdad un release antes de decidir si hace falta bsdiff.

    python manifest.py hash  <dir> <salida.json>
    python manifest.py diff  <a.json> <b.json>
"""
import hashlib, json, os, sys


def hash_tree(root):
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace("\\", "/")
            h = hashlib.blake2b(digest_size=32)
            with open(full, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            out[rel] = {"hash": h.hexdigest(), "size": os.path.getsize(full)}
    return out


def mb(n):
    return f"{n / 1048576:.1f} MB"


def diff(a, b):
    ka, kb = set(a), set(b)
    nuevos = sorted(kb - ka)
    borrados = sorted(ka - kb)
    cambiados = sorted(k for k in ka & kb if a[k]["hash"] != b[k]["hash"])
    iguales = sorted(k for k in ka & kb if a[k]["hash"] == b[k]["hash"])

    total_b = sum(v["size"] for v in b.values())
    descarga = sum(b[k]["size"] for k in nuevos + cambiados)

    print(f"  build anterior : {len(a):>5} archivos, {mb(sum(v['size'] for v in a.values())):>9}")
    print(f"  build nuevo    : {len(b):>5} archivos, {mb(total_b):>9}")
    print()
    print(f"  sin cambios    : {len(iguales):>5} archivos  <- no se descargan")
    print(f"  modificados    : {len(cambiados):>5} archivos")
    print(f"  nuevos         : {len(nuevos):>5} archivos")
    print(f"  eliminados     : {len(borrados):>5} archivos")
    print()
    print(f"  ==> DESCARGA   : {mb(descarga)}  de {mb(total_b)}  "
          f"({descarga / total_b * 100:.1f}% del total)")
    if descarga:
        print(f"  ==> AHORRO     : {mb(total_b - descarga)}  "
              f"({(total_b - descarga) / total_b * 100:.1f}%)")

    detalle = sorted(((b[k]["size"], k) for k in nuevos + cambiados), reverse=True)
    if detalle:
        print("\n  Lo que habria que descargar (mayores primero):")
        for size, k in detalle[:20]:
            marca = "NUEVO " if k in set(nuevos) else "cambio"
            print(f"    {marca} {mb(size):>9}  {k}")
        if len(detalle) > 20:
            resto = sum(s for s, _ in detalle[20:])
            print(f"    ... y {len(detalle) - 20} archivos mas, {mb(resto)} en total")
    if borrados:
        print(f"\n  Eliminados: {', '.join(borrados[:10])}"
              + (f" ... (+{len(borrados) - 10})" if len(borrados) > 10 else ""))


if __name__ == "__main__":
    if sys.argv[1] == "hash":
        m = hash_tree(sys.argv[2])
        with open(sys.argv[3], "w", encoding="utf-8") as f:
            json.dump(m, f)
        print(f"{len(m)} archivos, {mb(sum(v['size'] for v in m.values()))} -> {sys.argv[3]}")
    else:
        a = json.load(open(sys.argv[2], encoding="utf-8"))
        b = json.load(open(sys.argv[3], encoding="utf-8"))
        diff(a, b)
