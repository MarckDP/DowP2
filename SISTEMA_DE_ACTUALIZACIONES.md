# Sistema de actualizaciones de DowP — referencia técnica

Este documento describe el sistema de actualizaciones **tal como funciona hoy** (manifiesto
formato `2`, particionado en chunks). Es una referencia de arquitectura, no un diario de
trabajo — para la historia de decisiones, bugs encontrados y por qué se llegó a este diseño
(incluida la v1, abandonada, de "un objeto por archivo"), ver `ACTUALIZACIONES.md`.

## Índice

1. [Resumen](#1-resumen)
2. [Arquitectura general](#2-arquitectura-general)
3. [El manifiesto](#3-el-manifiesto)
4. [Particionado en chunks](#4-particionado-en-chunks)
5. [Firma y verificación (Ed25519)](#5-firma-y-verificación-ed25519)
6. [El publicador (`tools/updater/`)](#6-el-publicador-toolsupdater)
7. [El cliente (`app/src/core/updater/`)](#7-el-cliente-appsrccoreupdater)
8. [El journal y el swap atómico](#8-el-journal-y-el-swap-atómico)
9. [El helper de swap](#9-el-helper-de-swap)
10. [Particularidades por plataforma](#10-particularidades-por-plataforma)
11. [Canales de actualización y fase beta](#11-canales-de-actualización-y-fase-beta)
12. [GitHub como backend](#12-github-como-backend)
13. [Manual operativo: publicar una versión nueva](#13-manual-operativo-publicar-una-versión-nueva)
14. [Rutas y estado en disco del cliente](#14-rutas-y-estado-en-disco-del-cliente)
15. [Qué falta / estado actual](#15-qué-falta--estado-actual)

---

## 1. Resumen

DowP se autoactualiza sin instalador: la app, ya instalada, detecta una versión nueva, baja
solo lo que cambió, y se reemplaza a sí misma en el disco de forma atómica (todo o nada, con
rollback si algo sale mal), reiniciándose sola. No hay servidor propio: **GitHub Releases hace
de backend** — tanto de almacén de archivos como de "última versión disponible".

Piezas, de punta a punta:

```
tools/updater/publish.py          GitHub Releases                app/src/core/updater/
 (maintainer, tras compilar)  --->  (manifest.json firmado    --->  (dentro de la app instalada)
                                     + chunks .tar.zst)
```

1. El maintainer compila y corre `publish.py`: hashea el build, agrupa los archivos en
   ~200 "chunks", comprime y sube solo los chunks que cambiaron, firma el manifiesto con una
   clave Ed25519 privada, y sube todo a un GitHub Release.
2. La app instalada, al arrancar, descarga y verifica la firma del manifiesto (clave pública
   embebida en el propio binario), y compara contra sus archivos locales — chunk por chunk, no
   archivo por archivo.
3. Si hay diferencias, descarga solo los chunks afectados, los verifica por hash, arma un
   "journal" (lista de operaciones: reemplazar este archivo, borrar aquel otro).
4. La app se entrega a un **proceso separado** (`DowP_Updater`, el "helper"), que espera a que
   la app vieja termine, aplica el journal (mueve archivos), y relanza la app nueva. Si algo
   falla a mitad de camino, deshace todo y relanza la versión vieja intacta.

## 2. Arquitectura general

Dos árboles de código, con una frontera estricta:

- **`tools/updater/`** — herramientas de desarrollo, corren en la máquina del maintainer.
  Nunca se empaquetan con la app. Necesitan la clave **privada** y un `GITHUB_TOKEN`.
- **`app/src/core/updater/`** — viaja DENTRO del bundle instalado. Nunca importa nada de
  `tools/`. Lleva la clave **pública** embebida (`updater_public_key.pem`).

Algunos módulos son conceptualmente los mismos en ambos lados (hashear un árbol de archivos,
calcular a qué chunk pertenece una ruta) — como el cliente no puede importar `tools/`, esa
lógica vive en `app/src/core/updater/` y `tools/updater/` la importa por ruta (`sys.path.insert`),
nunca al revés. Esto garantiza que publicador y cliente calculan exactamente lo mismo.

```
app/src/core/updater/
├── chunking.py          # chunk_id_for(), compute_chunk_hash() -- COMPARTIDO (tools la importa)
├── hash_tree.py          # hash_file(), hash_tree() -- duplicado de objectstore.py a proposito
├── platform_key.py       # get_platform_key() -- COMPARTIDO
├── manifest_client.py     # descarga + verifica firma del manifest.json
├── update_checker.py      # compute_diff(): manifiesto vs instalación local -> UpdateInfo
├── downloader.py          # download_update(): baja y extrae los chunks a staging
├── journal.py             # construye/persiste el journal (operaciones replace/delete)
├── swap_executor.py        # aplica/deshace el journal sobre la instalación real
├── launcher.py             # entrega el journal al helper, espera PIDs, relanza
├── macos_sign.py            # firma ad-hoc de macOS (build Y post-swap)
├── update_service.py        # QThread workers: UpdateCheckWorker, UpdateDownloadWorker
└── updater_public_key.pem   # clave pública Ed25519 (commiteada)

tools/updater/
├── objectstore.py         # hash_tree() [dup], stage_chunk() -- empaqueta un chunk a tar.zst
├── github_release.py       # wrapper sobre la API REST de GitHub Releases
├── signing.py               # firma/verifica con la clave Ed25519
├── keygen.py                 # genera el par de claves (se corre UNA vez)
├── publish.py                 # el CLI orquestador -- lo que corre el maintainer
└── secrets/private_key.pem     # clave PRIVADA (gitignored, NUNCA se commitea)

app/updater_helper.py        # el "helper": proceso separado que aplica el swap
```

## 3. El manifiesto

`manifest.json` es el documento central: describe, para cada plataforma soportada, qué
archivos tiene esa versión y en qué chunk vive cada uno, más los chunks en sí (hash, tamaño
comprimido, URL de descarga). Un único `manifest.json` vive por *release* de GitHub (tag
`v{version}`), y agrega plataformas a medida que se van publicando (windows-x64 hoy,
macos-arm64 mañana, sin pisarse).

Formato actual: **`"format": 2`** (particionado en chunks). El `"format": 1` (un objeto por
archivo) existió brevemente y fue abandonado antes de usarse en producción — ver
`ACTUALIZACIONES.md`.

```jsonc
{
  "format": 2,
  "app_version": "1.9.0",
  "min_updatable_version": "1.9.0",
  "platforms": {
    "windows-x64": {
      "files": {
        "DowP.exe": { "hash": "3a8bb0...", "size": 8421376, "chunk": "0107" },
        "_internal/Cryptodome/Cipher/AES.py": { "hash": "fb9123...", "size": 12480, "chunk": "0020" }
        // ... una entrada por cada archivo del build (2667 en el build actual de windows-x64)
      },
      "chunks": {
        "0020": {
          "hash": "8520c146b11a35f09c3d63675ac38099e63bb8fb92d93a340f5d26dc1ee92281",
          "compressed_size": 203015,
          "url": "https://github.com/MarckDP/DowP2/releases/download/v1.9.0/8520c146....tar.zst"
        }
        // ... una entrada por cada uno de los ~200 chunks de esta plataforma
      }
    },
    "macos-arm64": { "files": { /* ... */ }, "chunks": { /* ... */ } }
  }
}
```

Campos clave:

- **`files[relpath].hash`** — blake2b-256 (digest 32 bytes, hex) del archivo **sin comprimir**.
  Es lo que el cliente compara contra sus archivos locales para decidir si algo cambió, y lo
  que verifica tras extraer un chunk.
- **`files[relpath].chunk`** — a qué chunk pertenece este archivo. Viene del manifiesto firmado
  (fuente de verdad), el cliente no necesita recalcularlo con `chunk_id_for()` aunque daría lo
  mismo.
- **`chunks[chunk_id].hash`** — hash combinado de TODOS los archivos de ese chunk (ver sección
  4). Es la señal de "¿cambió algo acá dentro?".
- **`chunks[chunk_id].url`** — URL completa y final de descarga (`browser_download_url` de
  GitHub). El cliente nunca construye URLs por convención, siempre usa la que trae el
  manifiesto.
- **`min_updatable_version`** — versión mínima que puede autoactualizarse incrementalmente.
  Por debajo de esto, el diff ni se calcula: hace falta bajar el instalador completo. Hoy vale
  `"1.9.0"` porque es la primera versión con este sistema — no hay nada anterior con qué
  diffear (ver `core/version.py`).

El manifiesto se firma **completo, como archivo binario** (no se resigna un sub-objeto): un
cambio de un solo byte en cualquier parte lo invalida.

## 4. Particionado en chunks

**Por qué existe esto.** La primera versión de este sistema subía un objeto por archivo
(~2600 objetos en un build de Windows de ~350MB). Eso chocó con un límite duro y documentado de
GitHub: **máximo 1000 assets por release**. Reorganizar en varios releases lo hubiera resuelto
técnicamente, pero a costa de mantener toda una capa de reparto/paginación — mucha complejidad
para una app de este tamaño con un grupo de beta testers chico. La alternativa más simple (un
solo paquete completo por plataforma) resuelve el problema de GitHub de raíz, pero obliga a
bajar los ~150-200MB comprimidos enteros en CADA actualización, aunque cambie un solo archivo.

La solución adoptada es un punto medio: agrupar los ~2600 archivos en un número fijo y chico de
**chunks** (`NUM_CHUNKS = 200`, en `core/updater/chunking.py`), cada uno un `.tar.zst` con un
puñado de archivos adentro (5 a 27 en el build actual, promedio 13). Con 200 assets por
plataforma, un release nunca se acerca al límite de 1000 de GitHub aunque acumule varias
plataformas — y una actualización típica (unos pocos archivos propios cambiados) solo invalida
un puñado de chunks, no el build entero.

**Asignación de contenido a chunk** (`chunk_id_for`):

```python
def chunk_id_for(file_hash: str) -> str:
    return f"{int(file_hash[:8], 16) % NUM_CHUNKS:04d}"
```

Es una función pura del **hash del contenido**, no de la ruta del archivo. Primera versión de
este diseño (misma sesión) usaba el hash de la *ruta* en vez del contenido — se cambió tras
detectar, en el primer publish real de macOS, que los symlinks cruzados entre
`Contents/Frameworks` y `Contents/Resources` (ver sección 10) hacen que el mismo contenido
aparezca bajo dos rutas distintas; agrupando por ruta, esas dos copias caían en chunks
distintos y se subían/bajaban dos veces (**~435MB de puro desperdicio**, medido en un release
real: 785MB reportados contra solo 350MB de contenido único). Agrupando por hash de contenido,
las dos rutas apuntan siempre al mismo chunk, y ese contenido se empaqueta y transfiere una
sola vez sin importar cuántas rutas lo referencien — recupera la deduplicación que ya tenía la
v1 ("un objeto por archivo"), sin volver a pagar el costo del límite de 1000 assets/release.

**Hash combinado de un chunk** (`compute_chunk_hash`): concatenación ordenada de los
**contenidos únicos** (deduplicados) asignados al chunk, hasheada con blake2b-256. Cambia si
cambia el contenido de cualquiera, si se agrega uno nuevo, o si se saca uno — es exactamente
la señal de "hay que volver a bajar este chunk entero".

**Empaquetado** (`objectstore.stage_chunk`): el `.tar` de un chunk guarda cada contenido
nombrado por su **propio hash** (no por relpath) — un mismo miembro del tar puede corresponder
a varias rutas del lado del cliente. `downloader._download_and_extract_chunk` extrae cada
miembro una vez, verifica su hash, y lo copia a **todas** las rutas locales que lo referencian
(`files[relpath].hash` coincidente) antes de darlo por aceptado.

**Caso concreto verificado**: si en el futuro se agregan archivos que hoy no existen (por
ejemplo, más librerías de PySide6), esos `relpath` nuevos caen en algún chunk por el mismo
`chunk_id_for` de siempre. El cliente ve que ese chunk trae un archivo que no tiene localmente
→ lo marca sucio → lo descarga entero. No hace falta ningún caso especial en el código. El único
costo es "colateral": ese chunk trae consigo el resto de sus ~13 archivos, que se vuelven a
bajar aunque ya estuvieran bien — acotado al tamaño de un chunk, nunca al build entero. Esto se
verificó con una prueba real de punta a punta (build real, 2 archivos "nuevos" simulados + 1
modificado, cada uno en un chunk distinto): `compute_diff()` marcó exactamente esos 3 chunks de
200, y la descarga+extracción reprodujo los archivos byte a byte idénticos al build real.

## 5. Firma y verificación (Ed25519)

El manifiesto viaja por HTTP sin cifrar (repo público, sin necesidad de TLS propio más allá del
que ya da GitHub) — lo que garantiza que no fue alterado ni suplantado es la firma.

- **Algoritmo**: Ed25519 vía `pycryptodomex` (`Cryptodome.PublicKey.ECC` + `Cryptodome.Signature.eddsa`,
  modo `rfc8032`). Ya es dependencia de la app, no hace falta `pynacl`.
- **Generación** (una sola vez, `tools/updater/keygen.py`): escribe la privada en
  `tools/updater/secrets/private_key.pem` (gitignored) y la pública directamente dentro de
  `app/src/core/updater/updater_public_key.pem` (se commitea — el cliente la necesita embebida).
  Volver a generar el par invalida cualquier firma que un cliente ya tenga embebida.
- **Firma** (`signing.sign_file`, en `publish.py`): firma los **bytes crudos** del
  `manifest.json` ya escrito en disco — nunca una reserialización del JSON en memoria. Así un
  cambio de formato futuro en una librería (espacios, orden de claves) no puede invalidar una
  firma válida sin que el contenido real haya cambiado.
- **Verificación** (`manifest_client._verify_signature`, en el cliente): descarga
  `manifest.json` y `manifest.json.sig` como dos assets separados del release, y verifica antes
  de tocar el JSON. **Falla cerrado a propósito**: si la firma no verifica,
  `ManifestVerificationError` — nunca se trata silenciosamente como "no hay actualización". Eso
  enmascararía un manifiesto corrupto o manipulado como un simple "estás al día".
- La clave privada **nunca sale de la máquina del maintainer** (decisión explícita: no vive en
  GitHub Secrets, todo publish se corre en local — ver sección 6 y 13).

## 6. El publicador (`tools/updater/`)

Herramientas que corre el maintainer a mano, tras compilar. Ninguna se empaqueta con la app.

- **`objectstore.py`** — `hash_tree()`/`hash_file()` (blake2b-256 por archivo, streaming) y
  `stage_chunk(relpaths, dist_dir, chunk_hash, staging_dir)`: empaqueta un grupo de archivos en
  un tar (streaming, sin cargarlo entero en memoria) comprimido con zstd nivel 19, nombrado por
  el hash combinado del chunk (`<chunk_hash>.tar.zst`). Si el chunk ya está en staging de una
  corrida anterior (interrumpida), no lo vuelve a empaquetar.

- **`github_release.py`** — wrapper fino sobre la API REST de GitHub Releases:
  `get_release_by_tag`, `get_latest_release`, `create_release`, `upload_asset`, `delete_asset`,
  `replace_asset`, `download_asset_content`, `list_release_assets`. Dos detalles importantes,
  aprendidos de fallos reales en producción (ver `ACTUALIZACIONES.md` para el detalle completo):
  - **`_request()`**: TODAS las llamadas pasan por acá, con reintento automático ante un 403/429
    con header `Retry-After` (rate limit *secundario* de GitHub — pedir bajar el ritmo, no un
    error de permisos). Un 403/429 *sin* ese header no se reintenta: ahí sí es un fallo real.
  - **`list_release_assets()`**: pagina de a 100 contra el endpoint dedicado
    (`GET /releases/{id}/assets`). El campo `"assets"` embebido en la respuesta de
    `get_release_by_tag()`/`get_latest_release()` no demostró ser confiable como fuente de "qué
    está subido de verdad" en un release con muchos assets — nunca se usa para eso, en ningún
    punto del código (publicador ni cliente).
  - **`upload_asset()`** trata un 422 con `errors[].code == "already_exists"` como éxito, no
    como error: si el intento original de un POST fue de verdad recibido por GitHub pero la
    respuesta que llegó a este lado fue un 403 de rate limit, el reintento automático vuelve a
    mandar el mismo nombre — y como los chunks son inmutables por contenido (mismo hash =
    mismo contenido), que ya exista es el resultado buscado, no una colisión real.

- **`signing.py` / `keygen.py`** — ver sección 5.

- **`publish.py`** — el CLI orquestador. Uso:

  ```
  python tools/updater/publish.py --dist app/dist/DowP --platform windows-x64 \
      --repo MarckDP/DowP2 --private-key tools/updater/secrets/private_key.pem
  ```

  Flujo interno (`main()`):
  1. Lee `APP_VERSION`/`MIN_UPDATABLE_VERSION` de `app/src/core/version.py` (ejecutándolo
     aislado, sin importarlo — ese archivo no tiene imports a propósito para poder leerse así).
  2. Busca el release `v{version}` (puede ya existir, si otra plataforma la publicó antes) y el
     release `latest` (la versión anterior), y descarga sus `manifest.json` si existen.
  3. Arma un `chunk_reuse_map` (hash de chunk → URL) combinando los chunks ya presentes en el
     manifiesto de esta versión (otra plataforma) y en el de la versión anterior — evita
     recomprimir/resubir un chunk sin cambios.
  4. Hashea `--dist` (`objectstore.hash_tree`), agrupa por chunk (`chunk_id_for`), calcula el
     hash combinado de cada uno. Si coincide con `chunk_reuse_map`, lo referencia sin tocar
     GitHub. Si no, revisa si ya está subido de verdad (`list_release_assets`, idempotencia ante
     un reintento tras un corte a medias). Si no, lo empaqueta (`stage_chunk`) y lo deja
     pendiente de subir.
  5. Sube los chunks pendientes en paralelo (`ThreadPoolExecutor`, `MAX_CONCURRENT_UPLOADS = 15`).
  6. Escribe `manifest.json` local, lo firma, sube manifiesto + firma + chunks nuevos.
  7. **Es idempotente**: volver a correr el mismo comando tras un corte a medias detecta lo que
     ya llegó a GitHub y no lo vuelve a subir. El `manifest.json` final solo se sube al final —
     una publicación a medias es invisible/inofensiva para clientes reales, que solo miran el
     manifiesto ya completo.
  8. `--dry-run` hace todo el trabajo local (hashear, empaquetar, firmar) sin tocar GitHub —
     para validar el flujo sin publicar nada.
  9. `--prerelease` marca el release de GitHub como pre-release (invisible para
     `/releases/latest`, solo lo ven clientes en canal `"beta"` — ver sección 11. **No** es lo
     mismo que `IS_BETA` de la app).

  Simplificación explícita: la reutilización de chunks solo mira la versión inmediatamente
  anterior, no todo el historial — un chunk que cambió y volvió a un valor de hace varias
  versiones se resube (correcto, solo subóptimo).

## 7. El cliente (`app/src/core/updater/`)

Todo lo que corre DENTRO de la app instalada.

- **`manifest_client.fetch_and_verify_manifest(repo, channel)`** — descarga y verifica el
  manifiesto del release más nuevo según el canal (ver sección 11). Sin token (repo público).
  Busca `manifest.json`/`manifest.json.sig` paginando (`_list_assets`), mismo criterio de
  robustez que `list_release_assets` del lado publicador. Lanza `ManifestVerificationError` si
  la firma no verifica.

- **`update_checker.compute_diff(manifest, install_dir=None, current_version=None)`** — el
  corazón del diffing. Sin red a propósito (recibe el manifiesto ya parseado, se puede probar
  con uno fabricado a mano). Devuelve un `UpdateInfo`:

  ```python
  @dataclass
  class UpdateInfo:
      available: bool
      must_full_install: bool       # version.py MIN_UPDATABLE_VERSION o formato no soportado
      current_version: str
      remote_version: str
      platform_key: str
      files_to_download: dict        # relpath -> {"hash", "size", "chunk"}
      chunks_to_download: dict       # chunk_id -> {"hash", "url", "compressed_size"}
      download_size: int             # bytes EN LA RED (suma de compressed_size de los chunks sucios)
      extra_local_files: list        # archivos locales que YA NO estan en el manifiesto (a borrar)
  ```

  Lógica: agrupa los archivos del manifiesto por `chunk` (campo ya firmado), y por cada grupo
  comprueba si **cualquiera** de sus archivos no coincide localmente (falta, o `hash_file()`
  distinto) — si es así, todo el chunk se marca sucio: se agrega a `chunks_to_download` (para
  que `downloader.py` sepa qué URL bajar) y TODOS sus archivos se agregan a `files_to_download`
  (mismo formato `{"hash", "size"}` que ya usa `journal.py` — el journal no necesita saber nada
  de chunks). `extra_local_files` es la diferencia de conjuntos entre lo instalado y lo que
  dice el manifiesto — se usa para borrar archivos que quedaron huérfanos de una versión vieja.

  `install_dir` por defecto usa `launcher.install_dir_from_executable(sys.executable)` — solo
  tiene sentido en modo congelado (`sys.frozen`); en modo fuente hay que pasarlo a mano (útil
  para probar contra un build real sin instalar nada).

- **`downloader.download_update(update_info, staging_dir, progress_callback)`** — descarga cada
  chunk de `chunks_to_download` en streaming, lo descomprime con zstd (`stream_reader`) y
  extrae el `tar` directo a `staging_dir/<relpath>`, verificando el hash de **cada archivo
  extraído** contra `files_to_download` antes de aceptarlo (escribe a `.part` + `os.replace()`
  al final, resistente a cortes). Idempotente a nivel de chunk: si todos los archivos de un
  chunk ya están en staging con el hash correcto (de una corrida anterior interrumpida), no
  vuelve a descargarlo. `progress_callback(bytes_completados, bytes_totales)` usa
  `compressed_size` (bytes de red), no el tamaño descomprimido.

- **`update_service.py`** — dos `QThread` que conectan esto con la interfaz, sin bloquear el
  hilo de UI:
  - `UpdateCheckWorker`: lee `update_channel` de la config, llama a
    `fetch_and_verify_manifest` + `compute_diff`, emite un `UpdateInfo` (o `None` para
    CUALQUIER otro caso — sin releases, sin conexión, firma inválida, nada nuevo — porque "sin
    resultado" es el estado normal y no debe alarmar al usuario).
  - `UpdateDownloadWorker`: corre `download_update`, emite progreso y un resultado final.

## 8. El journal y el swap atómico

El **journal** (`journal.py`) describe, paso a paso, qué tiene que hacer un swap sobre la
instalación real — y cuánto de eso ya se hizo. Es lo que permite reanudar tras un corte de luz
a mitad de camino sin repetir trabajo ni perder de vista qué falta.

```python
def build_journal(update_info, install_dir, staging_dir, state_dir, relaunch_exe) -> dict:
    # cada archivo en files_to_download -> operacion "replace"
    # cada archivo en extra_local_files  -> operacion "delete"
    ...
```

Estructura (persistida en `journal.json` dentro de `state_dir`, con `fsync` antes de devolver
el control — tiene que sobrevivir un corte de luz tanto como los archivos que describe):

```jsonc
{
  "status": "pending",              // pending -> swapping -> done | rolled_back
  "install_dir": "C:\\...\\DowP",
  "relaunch_exe": "C:\\...\\DowP.exe",
  "operations": [
    {
      "relpath": "DowP.exe",
      "action": "replace",          // "replace" | "delete"
      "source": "C:\\...\\update_staging\\DowP.exe",
      "backup": "C:\\...\\updater_state\\backups\\DowP.exe",
      "hash": "3a8bb0...",          // para reanudar: si el destino ya coincide, no repetir
      "done": false
    }
  ]
}
```

**`swap_executor.apply_journal(journal, state_dir)`** — ejecuta las operaciones en orden. Cada
una se marca `"done": true` y se persiste **inmediatamente** tras completarse: la unidad de
trabajo perdible ante un corte es UNA operación, nunca el journal entero. Por operación:
mueve el archivo destino actual a `backup` (si existe), mueve el nuevo desde `source` al
destino, y verifica el hash resultante (`SwapError` si no coincide). Reanudar (llamar de nuevo
sobre un journal a medias) es seguro: las operaciones ya `done` se saltan, y las demás se
comprueban por hash antes de repetir nada.

En macOS, como último paso, vuelve a firmar el `.app` ad-hoc (`macos_sign.adhoc_sign`) — mover
archivos dentro de un bundle rompe la firma anterior, y sin firma válida Apple Silicon rechaza
directamente el arranque.

**`swap_executor.rollback_journal(journal, state_dir)`** — deshace las operaciones ya
aplicadas, en orden inverso: borra lo nuevo, restaura el backup. Igual de idempotente.

**`swap_executor.purge_backups(state_dir)`** — solo se llama tras un swap confirmado con éxito
(la nueva versión arrancó y sigue viva): borra los backups, ya no hacen falta.

## 9. El helper de swap

Un ejecutable **separado** (`app/updater_helper.py`, compilado aparte por
`build_cross_platform.py`, sin PySide6 ni dependencias pesadas — solo stdlib +
`core.updater/.logger/.utils.paths`). Existe porque un proceso no puede sobrescribir su propio
`.exe` ni las DLLs que tiene cargadas, y `DowP.exe` cambia en casi todos los releases.

```
updater_helper.py <journal_path> <wait_pid> <relaunch_exe>
```

Flujo (`main()`):
1. `launcher.wait_for_pid_exit(wait_pid, timeout=60)` — espera a que la app vieja termine de
   verdad (en Windows, `WaitForSingleObject` sobre el handle real, no solo "el PID ya no
   aparece"). Si se agota el timeout, sigue igual — si de verdad tiene archivos abiertos, el
   swap fallará con un error claro más abajo.
2. Lee el journal, llama a `swap_executor.apply_journal`.
3. Si falla, `rollback_journal` — si el rollback TAMBIÉN falla, el journal no se borra (queda
   como evidencia para diagnóstico manual).
4. Relanza la app nueva (`launcher.spawn_detached`).
5. Espera 8 segundos (`STARTUP_CHECK_SECONDS`) y comprueba que el nuevo PID sigue vivo. Si sí:
   swap confirmado, purga backups, borra el journal. Si no: asume fallo de arranque, hace
   rollback, relanza la versión anterior restaurada.

**`launcher.py`** — el pegamento entre la app principal y el helper:
- `hand_off_to_helper(state_dir, install_dir, own_pid, relaunch_exe)`: copia el binario del
  helper a `state_dir` (para que no se autobloquee si el journal también lo reemplaza a él
  mismo) y lo lanza desacoplado (`spawn_detached`) con los tres argumentos. Quien llama debe
  salir inmediatamente después — seguir corriendo con archivos a punto de moverse debajo es
  como se corrompe una instalación.
- `resume_pending_swap()`: se llama al principio de `main.py`, antes de crear la
  `QApplication`. Si hay un journal sin terminar (corte a mitad de camino en la corrida
  anterior), vuelve a entregárselo al helper. No-op en modo fuente.
- `install_dir_from_executable()` / `helper_path_in()`: ver sección 10 (particularidades de
  macOS).
- `is_process_alive()` / `wait_for_pid_exit()`: primitivas multiplataforma, con manejo especial
  en Windows para distinguir un PID reciclado por otro proceso de uno que sigue vivo de verdad.

## 10. Particularidades por plataforma

**macOS — la partición Frameworks/Resources.** El `--onedir` de PyInstaller para un `.app`
NO es un árbol plano: queda partido entre `Contents/Frameworks/` y `Contents/Resources/`, con
symlinks cruzados entre ambas (ni siquiera `Frameworks`, que tiene casi todo, cubre el 100% —
algunos datos, como `_tcl_data`/`_tk_data`, son reales solo en `Resources`). La única raíz que
cubre las dos sin ambigüedad, y que `hash_tree()` recorre completo sin duplicar nada (no sigue
directorios symlink), es **el `.app` entero** — no `Contents/MacOS`, que es donde vive
`sys.executable` pero NO contiene los datos de la app.

Por eso `launcher.install_dir_from_executable()` en macOS sube desde `sys.executable` buscando
la raíz `*.app` (`swap_executor.find_app_bundle_root`, hasta 4 niveles), y
`tools/updater/publish.py --dist` en macOS espera el `.app` completo, nunca
`Contents/MacOS`. Coincide exactamente con lo que hashea `objectstore.hash_tree()` del lado
publicador.

El helper compilado vive dentro de `Contents/MacOS/` (junto al ejecutable principal), no suelto
en la raíz del bundle — `launcher.helper_path_in()` lo sabe.

**Firma ad-hoc** (`macos_sign.py`): `codesign --force --deep --sign - --timestamp=none`, sin
cuenta de Apple ni notarización. No quita el aviso de Gatekeeper (clic derecho > Abrir la
primera vez), pero es lo que hace que el binario ARRANQUE en Apple Silicon — sin firma, el
cargador del sistema lo rechaza directamente. Se aplica tanto al compilar
(`build_cross_platform.py`) como al final de cada swap aplicado (tocar archivos dentro de un
bundle rompe la firma anterior).

**Windows — el bug del hang en compilado.** `TutorialOverlay._load_step()` tenía un
`QApplication.processEvents()` que causaba reentrancia durante la construcción síncrona de
`MainWindow` en el build compilado (no en modo fuente). Ya corregido — ver
`ACTUALIZACIONES.md` para el detalle. Sin relación directa con el updater, pero relevante
porque se descubrió durante la validación de este sistema.

**`is_process_alive`/`wait_for_pid_exit` en Windows**: usan `OpenProcess`/`GetExitCodeProcess`/
`WaitForSingleObject` de la WinAPI directamente (vía `ctypes`), no un simple chequeo de PID —
un PID puede ser reciclado por otro proceso, y `WaitForSingleObject` se entera de cuándo el
proceso de verdad liberó sus DLLs, no solo de que "ya no aparece en la lista".

## 11. Canales de actualización y fase beta

DowP 1.9.0 es la primera versión "real" de la beta pública — deliberadamente por **debajo** de
2.0.0 (`core/version.py`). Así, cuando salga la 2.0.0 oficial, es un número MAYOR que cualquier
beta anterior y el updater SÍ la ofrece a todo el mundo. Si las betas usaran algo como
`2.0.0.3`, la 2.0.0 real quedaría por debajo numéricamente y nunca se ofrecería como update.

- **`IS_BETA`** (`core/version.py`): mientras es `True`, `get_display_version()` muestra la
  palabra `"Beta"` en vez del número interno en la UI (puramente cosmético — todo lo que
  compara o publica versiones sigue usando `APP_VERSION` tal cual). Apagar al compilar/publicar
  la 2.0.0 oficial.
- **Canal de actualización** (`config_manager.py`, clave `"update_channel"`, default `"beta" if
  IS_BETA else "stable"` — mismo patrón que `ytdlp_channel`/`ffmpeg_channel` de `deps_page.py`):
  - `"stable"` — usa `GET /releases/latest` de GitHub. GitHub **excluye** ahí cualquier release
    marcado `prerelease`, por diseño de su propia API.
  - `"beta"` — lista los releases (`GET /releases?per_page=1`, sin ese filtro, más nuevo
    primero) y toma el primero, sea `prerelease` o no. Es la única forma de que un cliente en
    canal beta vea builds marcados `prerelease` en GitHub.
  - UI: tarjeta "Actualizaciones DowP" en Ajustes > General, arriba de "Aspecto" — dos radios
    ("Solo releases oficiales" / "Todas (incluye experimentales)"). Cambiar el canal
    re-dispara el chequeo de actualizaciones si está en reposo.
- **`--prerelease`** de `publish.py` marca el checkbox de GitHub — **no es lo mismo** que
  `IS_BETA` de la app. `IS_BETA` es cosmético (la palabra "Beta" en la UI); `prerelease` de
  GitHub controla literalmente si `/releases/latest` puede encontrar el release. Se pueden
  combinar de las cuatro formas posibles sin conflicto.

## 12. GitHub como backend

Cada versión publicada es un GitHub Release con el tag `v{version}` (ej. `v1.9.0`), conteniendo:

- `manifest.json` + `manifest.json.sig` (se reemplazan en cada publish de esa versión —
  `replace_asset`, borra y resube).
- Un `.tar.zst` por chunk nuevo de cada plataforma publicada (inmutables por contenido — un
  chunk con el mismo hash nunca se vuelve a subir, se referencia).

**Límite duro de GitHub: 1000 assets por release** (documentado en "About releases"). Con
~200 chunks por plataforma, incluso acumulando varias plataformas en el mismo release de
versión, se queda lejos de ese techo — a diferencia de la v1 (un objeto por archivo, ~2600 por
plataforma), que lo superaba de entrada.

**Autenticación**: `tools/updater/` usa un Personal Access Token (`GITHUB_TOKEN` en el entorno,
scope `repo` o `contents: write` fine-grained) — **nunca** el `GITHUB_TOKEN` que GitHub Actions
inyecta solo, son cosas distintas. El cliente (`manifest_client.py`) no usa token: el repo es
público, y tanto listar releases como descargar assets funciona sin autenticar.

**Rate limiting** — dos variantes, distinguibles por el header `Retry-After`:
- *Secundario* (con `Retry-After`): GitHub pidiendo bajar el ritmo tras muchas peticiones
  seguidas de creación de contenido. `github_release._request()` lo reintenta automáticamente
  (hasta 6 veces).
- *Primario* (sin `Retry-After`, `X-RateLimit-Remaining: 0`): cupo de 5000 req/hora agotado.
  No se reintenta solo — hay que esperar al `X-RateLimit-Reset` (se puede consultar sin gastar
  cupo con `GET /rate_limit`).

**CI**: GitHub Actions (`.github/workflows/build-macos.yml`) compila **solo** el `.app` arm64
crudo (el único build que el maintainer no puede producir en su propia máquina Windows) y lo
deja como artifact, listo para `publish.py --dist`. Deliberadamente manual
(`workflow_dispatch`, no en cada push — macOS consume la bolsa de minutos gratis de Actions a
10x contra Linux/Windows). Windows y macOS x64 se compilan y publican enteramente en local (PC
del maintainer / VM Hackintosh) — decisión explícita para que la clave privada nunca salga de
una máquina que el maintainer controla directamente.

## 13. Manual operativo: publicar una versión nueva

1. Subir `APP_VERSION` en `app/src/core/version.py`.
2. Compilar (`python build_cross_platform.py` en `app/`, en cada plataforma que se vaya a
   publicar).
3. Setear `GITHUB_TOKEN` en el entorno (PAT, scope `repo`).
4. Por cada plataforma:
   ```
   python tools/updater/publish.py --dist app/dist/DowP --platform windows-x64 \
       --repo MarckDP/DowP2 --private-key tools/updater/secrets/private_key.pem
   ```
   (en macOS, `--dist app/dist/DowP.app`, `--platform macos-arm64` o `macos-x64`).
5. Confirmar en `https://github.com/MarckDP/DowP2/releases/tag/v{version}` que el release
   tiene `manifest.json`, `manifest.json.sig`, y los chunks de cada plataforma publicada.

Si se corta a medias (ventana cerrada, corte de luz, error de red): **no hay que borrar nada**,
volver a correr el mismo comando — es idempotente por diseño (sección 6, punto 7).

Para una beta que no debe ofrecerse a clientes en canal `"stable"`: agregar `--prerelease`.

## 14. Rutas y estado en disco del cliente

Todo bajo el perfil **local** (no roaming) del usuario, vía `core/utils/paths.py`:

- `get_update_staging_dir()` → `.../DowP2/update_staging/` — chunks ya descargados,
  descomprimidos y verificados por `downloader.py`, listos para que el helper los aplique. Puede
  pesar cientos de MB por actualización pendiente.
- `get_updater_state_dir()` → `.../DowP2/updater_state/` — `journal.json` y `backups/` (lo que
  había antes de cada operación, por si hay que deshacer). Vida separada de `update_staging`
  a propósito: uno es "lo que hay que poner", el otro es "lo que había antes" — se limpian en
  momentos distintos (`purge_backups` solo tras confirmar éxito).

## 15. Qué falta / estado actual

- **Validado con hardware real**: Windows, macOS Intel (Hackintosh VM) y macOS Apple Silicon
  real (hardware de un tercero) — swap, rollback, firma, relanzamiento.
- **No validado todavía**: una publicación real de punta a punta con el esquema de chunks
  (`format: 2`) contra el repo público, ni una actualización incremental real bajando solo un
  par de MB (sección 4 se probó en simulación local, no contra GitHub de verdad todavía).
- **Pendiente antes del próximo publish real**: correr `tools/updater/cleanup_v190_objects.py`
  una vez — el release `v1.9.0` tiene restos de objetos sueltos de la v1 (abandonada) que hay
  que limpiar antes de que los chunks empiecen a compartir ese mismo release.
- **Explícitamente diferido** (no implementar sin pedido explícito): ruta de almacenamiento de
  dependencias/modelos configurable — ver `ACTUALIZACIONES.md`, sección "Lo que falta".

Para el detalle de cada bug encontrado y cómo se diagnosticó (incluida la v1 completa,
abandonada), ver `ACTUALIZACIONES.md`, sección "Trampas encontradas".
