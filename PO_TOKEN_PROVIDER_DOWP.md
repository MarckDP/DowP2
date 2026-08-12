# PO Token Provider para DowP — Documentación técnica

Fecha de investigación: agosto 2026
Alcance: `analyzer.py`, `downloader_master.py`, `setup_manager.py`, `ytdlp_setup.py`, `deno_setup.py`

---

## 1. Diagnóstico de tu situación actual

Tu arquitectura ya resuelve **una** de las dos capas de protección de YouTube:

| Capa | Qué hace | ¿La tienes? |
|---|---|---|
| **JS Challenge (EJS)** | Resuelve firmas y el parámetro `n` del reproductor. Requiere un runtime JS (Deno). | ✅ Sí — `deno_setup.py` + `js_runtimes` en `analyzer.py` |
| **PO Token (Proof of Origin)** | Certifica ante YouTube que la petición viene de un cliente "real" (BotGuard). Se exige para GVS (el streaming en sí) y subtítulos. | ❌ No — no hay ningún provider configurado |

Esto explica el síntoma exacto que describiste: Deno está instalado el 100% de las veces, pero los videos públicos sin cookies siguen fallando con 429 / "sign in to confirm you're not a bot". Deno resuelve el challenge de JavaScript, pero sin PO Token, la petición de streaming igual se rechaza.

**Sobre el impersonate lento (confirmado):** el usuario confirmó que `curl_cffi==0.14.0` está pineado explícitamente en su `requirements.txt`, siendo la única versión que le funciona sin errores (versiones más nuevas o más antiguas fallaban). Esto descarta la hipótesis de "curl_cffi no disponible" — sí está activo y siendo usado. Con esto, hay dos causas reales de la lentitud, y probablemente se combinan:

1. **Overhead inherente de la impersonación TLS.** `curl_cffi` no hace un handshake TLS normal: reconstruye byte a byte el ClientHello, el orden de extensiones, las cifras soportadas y los ajustes HTTP/2 de un navegador real (vía `libcurl-impersonate`, compilado sobre BoringSSL). Esto es sustancialmente más costoso en CPU que el handshake estándar de `urllib`/`requests`, y ese costo se paga en **cada** conexión nueva, no solo una vez.
2. **Riesgo de versión pineada y frágil.** yt-dlp declara rangos de compatibilidad estrictos con `curl_cffi` en su `pyproject.toml` (por ejemplo, hubo un momento donde el rango válido era `!=0.6.*,!=0.7.*,!=0.8.*,!=0.9.*,<0.14,>=0.5.10` — es decir, **0.14.0 quedaba fuera de rango** en esa versión de yt-dlp). Que 0.14.0 sea "la única que funciona" en tu entorno sugiere que estás en una versión de yt-dlp cuyo rango soportado ya subió para incluirla, pero este acoplamiento es frágil: cada vez que actualices yt-dlp (o vuelvas a fijar versión de yt-dlp), el rango compatible de `curl_cffi` puede cambiar de nuevo y romper silenciosamente el impersonate (quedando "unavailable" sin error visible, como viste antes). **Recomendación:** cuando automatices la descarga/actualización de yt-dlp, valida contra el `curl_cffi` que tienes pineado, o considera desacoplar leyendo el rango soportado desde el propio yt-dlp en tiempo de ejecución en vez de confiar en que 0.14.0 seguirá siendo válido para siempre.

Con el PO Token Provider activo (sección 2), la necesidad de mantener impersonate como algo obligatorio baja: el PO Token ya resuelve la parte de "autenticidad" a nivel de aplicación, mientras que impersonate resuelve la parte de "huella TLS" — son complementarios, no sustitutos, pero dado el costo en velocidad que describes, tiene sentido bajarlo a opción avanzada/opcional en vez de dejarlo en el camino crítico del modo rápido.

---

## 2. ¿Qué es un PO Token Provider y por qué lo necesitas ahora?

Es un componente que genera el token BotGuard que YouTube exige. No es opcional para descargas confiables desde mediados de 2026 — es la pieza que actualmente más está causando los 429/bloqueos que reportaste, con o sin cookies.

Hay dos implementaciones "de facto" en el ecosistema yt-dlp:

### Opción A — `Brainicism/bgutil-ytdlp-pot-provider` (original, TypeScript/Node)
- Requiere **Node.js ≥ 20** o Deno ≥ 2.0 para el servidor.
- Dos modos: servidor HTTP persistente (puerto 4416 por defecto) o script invocado bajo demanda.
- Es el más usado y con más tiempo en producción, pero varios issues recientes reportan timeouts, problemas de bind IPv6/IPv4, y que se "queda pegado" tras un tiempo corriendo como servicio.
- Requiere clonar el repo + `npm ci` — no es un binario único, lo que complica empaquetarlo dentro de tu carpeta `bin/dependences/`.

### Opción B — `jim60105/bgutil-ytdlp-pot-provider-rs` (reescritura en Rust) — **recomendada para tu caso**
- Se distribuye como **binario standalone precompilado** por plataforma (Windows/Linux/macOS, x86_64/aarch64), descargable directo desde GitHub Releases — exactamente el mismo patrón que ya usas para Deno y ffmpeg.
- No requiere Node.js en absoluto.
- Mismos dos modos: servidor HTTP (`bgutil-pot server`) o script/CLI bajo demanda.
- Plugin Python separado (`bgutil-ytdlp-pot-provider-rs` para yt-dlp) que se instala como carpeta de plugin, no como paquete pip — compatible con tu esquema de ZIP.
- Más rápido en frío que la versión Node porque es un binario compilado, no un runtime interpretado arrancando cada vez.

**Recomendación: usa la Opción B.** Encaja con tu filosofía de "todo se descarga solo a la misma carpeta" sin añadir Node.js como dependencia nueva.

---

## 2 bis. ¿Qué es físicamente un plugin de yt-dlp? (anatomía)

Antes de tocar carpetas y `sys.path`, vale aclarar qué es un plugin en términos concretos, porque el término es ambiguo y mezcla dos cosas distintas.

**Un plugin de yt-dlp NO es un `.exe`, NO es un script JS, y NO vive en ningún servidor remoto.** Es código Python plano: una carpeta con archivos `.py` que sigue una convención de nombres fija, y que yt-dlp **importa dentro de su propio proceso** al arrancar — exactamente igual que tu `analyzer.py` hace `import yt_dlp`. No hay "instalación" real, no hay ejecución independiente; es Python cargando más Python en el mismo proceso.

La estructura mínima es siempre así:

```
cualquier_carpeta/
└── yt_dlp_plugins/          <- nombre de carpeta fijo, obligatorio, no se puede renombrar
    ├── extractor/            <- soporte a un sitio nuevo, o PO Token Providers
    │   └── mi_modulo.py
    └── postprocessor/        <- procesamiento post-descarga
        └── otro_modulo.py
```

Cada archivo `.py` ahí dentro define una clase Python que se auto-registra en las listas internas de yt-dlp (extractores, post-procesadores, proveedores de PO Token, etc.) cuando el intérprete lo importa. Un plugin de PO Token Provider simplificado, solo para ilustrar que no hay magia:

```python
# yt_dlp_plugins/extractor/getpot_ejemplo.py
from yt_dlp.extractor.youtube.pot._provider import PoTokenProvider

class MiProveedorDePOT(PoTokenProvider):
    def _real_request_pot(self, request):
        return token_generado  # aquí consigue el token
```

**Entonces, ¿por qué el PO Token Provider sí trae un `.exe`?** Porque en ese caso concreto hay **dos capas separadas** que es fácil confundir:

| Capa | Qué es | Formato |
|---|---|---|
| El plugin (`getpot_bgutil.py`, etc.) | El "conector" que yt-dlp entiende | Código fuente `.py`, puro Python |
| El motor generador de tokens (`bgutil-pot`) | El programa que resuelve de verdad el desafío BotGuard, algo que requiere ejecutar JavaScript real (Python solo no puede) | Binario compilado standalone (`.exe` en Windows) o script Node/Deno |

El plugin Python **no genera el token él mismo** — delega el trabajo hablando con el motor generador, ya sea lanzándolo como subproceso puntual (modo script) o haciéndole una petición HTTP a `localhost:4416` si lo dejas corriendo como servidor. Esa dirección es **local, en tu propia máquina** — nunca sale a internet, no es un servidor en el sentido de nube, es un proceso hijo de tu propia app hablando consigo mismo por loopback.

Este patrón "plugin Python liviano + binario externo que hace el trabajo pesado" es específico de los PO Token Providers, porque necesitan ejecutar JS real. La mayoría de los demás plugins de yt-dlp (soporte para un sitio nuevo, un post-procesador) son 100% Python sin ningún binario externo — ahí sí es solo "carpeta de código que se importa" y nada más.

**Sobre `yt_dlp_plugins` como namespace package:** esto significa que puedes tener *varios* plugins distintos apuntando a la misma carpeta padre, y Python los combina automáticamente sin que se pisen entre sí — siempre que cada uno traiga su propia subcarpeta (`extractor/`, `postprocessor/`) con nombres de archivo distintos entre sí. Por eso tu idea de una carpeta fija `dependences/ytdlp/plugins/` funciona bien: hoy cae ahí el PO Token Provider, mañana podría caer cualquier otro plugin, y todos conviven en la misma carpeta `yt_dlp_plugins/` sin conflicto.

---

## 3. Modo servidor vs modo script — cuál usar dónde

| | Modo servidor (`bgutil-pot server`) | Modo script (CLI por request) |
|---|---|---|
| Latencia | Baja (~decenas de ms tras el arranque) | Alta (~1-3s por token, arranca proceso cada vez) |
| Uso de recursos | Un proceso persistente en background | Cero en reposo, gasta CPU solo al pedir token |
| Complejidad de gestión | Necesitas arrancarlo/pararlo con el ciclo de vida de tu app | Ninguna gestión — yt-dlp lo invoca solo |
| Encaja mejor en | **Modo rápido** (pegar URL y descargar ya) | **Modo avanzado** / uso esporádico |

**Recomendación concreta para DowP:**
- **Modo rápido:** arranca el servidor `bgutil-pot` como proceso hijo cuando la app inicia (mismo momento en que verificas Deno/ffmpeg/yt-dlp), y lo detienes al cerrar la app. Esto evita el overhead de 1-3s por video que tendrías con modo script, algo crítico si el usuario va a descargar varios videos seguidos.
- **Modo avanzado:** deja también la opción de modo script como fallback configurable, por si el usuario prefiere no tener un proceso corriendo en background o tiene problemas de puertos ocupados.

---

## 4. El "gotcha" de tu arquitectura: carga de yt-dlp vía ZIP + `sys.path`

Este es el punto técnico más delicado y por eso vale la pena documentarlo bien antes de tocar código.

yt-dlp normalmente descubre plugins buscando carpetas `yt_dlp_plugins` en varias ubicaciones estándar (config del usuario, `%APPDATA%/yt-dlp/plugins`, o una carpeta `yt-dlp-plugins/` junto al ejecutable/`yt_dlp/__main__.py`). El problema: en tu caso, `yt_dlp` no vive en disco como carpeta — vive **dentro del ZIP** (`yt-dlp.zip`) y lo cargas insertando el path del zip en `sys.path`. La detección "carpeta junto al ejecutable" puede no resolver correctamente el `root-dir` en este escenario porque no hay un `yt_dlp/__main__.py` real en disco, sino un import vía `zipimport`.

**Camino más robusto para tu setup (y el que recomiendo):** en vez de depender de la convención de carpetas que busca yt-dlp automáticamente, agrega tú mismo la carpeta del plugin a `sys.path` **antes** de importar `yt_dlp`, igual que ya haces con el ZIP:

```python
sys.path.insert(0, ytdlp_path)                 # tu línea actual
sys.path.insert(0, pot_provider_plugin_dir)     # nueva línea, apuntando a la carpeta
                                                 # que contiene directamente "yt_dlp_plugins/"
```

Esto funciona porque `yt_dlp_plugins` es un *namespace package* — Python lo ensambla desde **todas** las ubicaciones en `sys.path` que lo contengan, sin importar si son carpetas normales o entradas de zip. Es el mismo mecanismo por el cual pip-instalando el plugin normalmente funciona (pip lo deja en site-packages, que está en sys.path).

No necesitas tocar código todavía, pero cuando llegue el momento, esta es la forma más confiable de integrarlo — evita depender de que yt-dlp adivine correctamente el "root-dir" de un ZIP.

---

## 5. Estructura de carpetas propuesta

Siguiendo tu convención actual (`bin/dependences/<nombre>/`), con el ajuste que propusiste: una carpeta `plugins/` fija **dentro** de `dependences/ytdlp/`, para que cualquier plugin (presente o futuro) se apunte siempre al mismo lugar en `sys.path`, separada del binario generador de tokens (que sigue el patrón normal de dependencia standalone, como Deno):

```
bin/dependences/
├── ytdlp/
│   ├── yt-dlp.zip
│   └── plugins/                          <- NUEVO, carpeta fija de plugins
│       └── yt_dlp_plugins/               <- esto es lo que agregas a sys.path
│           └── extractor/
│               ├── getpot_bgutil.py
│               ├── getpot_bgutil_http.py
│               └── getpot_bgutil_cli.py
├── ffmpeg/
├── deno/
│   └── deno.exe
└── potprovider/                          <- NUEVO, el motor generador (binario)
    └── bgutil-pot.exe                    <- descargado igual que deno.exe
```

Nota importante siguiendo la sección 2 bis: `dependences/ytdlp/plugins/` es la carpeta que agregas a `sys.path` (la que *contiene* a `yt_dlp_plugins/`), no `yt_dlp_plugins/` en sí. Cualquier plugin nuevo que quieras agregar en el futuro (no solo el PO Token Provider) cae dentro de esa misma carpeta `plugins/yt_dlp_plugins/extractor/` sin necesitar tocar la lógica de carga — solo el contenido crece.

Un futuro `potprovider_setup.py` sería estructuralmente casi idéntico a `deno_setup.py`: mismo patrón de `get_platform_info()`, `get_potprovider_dir()`, `check_potprovider()`, `download_potprovider()` — descargando el asset correcto desde `https://api.github.com/repos/jim60105/bgutil-ytdlp-pot-provider-rs/releases/latest`, más un segundo paso para bajar y descomprimir el ZIP del plugin Python directamente dentro de `dependences/ytdlp/plugins/`.

---

## 6. Checklist de implementación (para cuando quieras que lo codifiquemos)

1. **Crear `potprovider_setup.py`** (mismo patrón que `deno_setup.py`): descarga binario `bgutil-pot` + carpeta del plugin, verifica existencia, expone `check_potprovider()` / `download_potprovider()`.
2. **Registrar en `setup_manager.py`**: agregar a `verify_all_dependencies()` y `download_missing_dependencies()`, igual que ffmpeg/deno. Esto respeta tu regla de "la app no inicia si faltan dependencias".
3. **Gestión del ciclo de vida del servidor**: arrancar `bgutil-pot server --port 4416` (o puerto configurable) como subprocess al iniciar la app; verificar que responde antes de habilitar descargas; terminarlo limpio al cerrar.
4. **Modificar `analyzer.py` → `get_base_ydl_opts()`**: agregar el path del plugin a `sys.path` antes del import de `yt_dlp`, y setear `extractor_args['youtube']['getpot_bgutil_http']` o `pot_trace` según corresponda si necesitas apuntar a un puerto no estándar.
5. **Decidir si eliminar o condicionar `impersonate`**: una vez el PO Token Provider esté activo, la necesidad de impersonate baja bastante — su función principal (parecer un navegador real a nivel TLS) se solapa parcialmente con lo que resuelve el PO Token a nivel de aplicación. Te recomiendo dejarlo como opción avanzada desactivada por defecto, y solo forzarlo si el análisis vuelve a fallar (ver sección 3 del mensaje anterior sobre fallback de clientes).
6. **Agregar versión del PO provider al sistema de versiones** que ya tienes en `config.json` (`dependency_versions`), igual que haces con `ytdlp`/`deno`, para poder mostrarlo en tu UI de diagnóstico.
7. **Probar primero en modo avanzado** con un toggle visible ("PO Token Provider: activo/inactivo") antes de hacerlo obligatorio en modo rápido, para que puedas comparar tasas de éxito con logs reales de tus usuarios.

---

## 7. Mantenimiento a futuro (esto no es "instalar y olvidar")

- YouTube cambia el algoritmo de BotGuard con cierta frecuencia. Cuando eso pasa, **tanto** el PO Token Provider **como** yt-dlp mismo necesitan actualizarse — no basta con actualizar solo uno. Tu sistema de auto-actualización ya cubre yt-dlp; deberías replicar la misma lógica de "chequear última versión en GitHub Releases" para el PO provider.
- Si en algún punto el binario Rust deja de mantenerse o rompe compatibilidad, el fallback documentado es volver a la versión Node original (Opción A) — mantén esto en mente al diseñar la abstracción para no acoplarte 100% a un solo proveedor.
- Vigila los logs por el mensaje `PO Token Providers: bgutil:... (external, unavailable)` — indica que el plugin se detectó pero el binario/servidor no está corriendo o no fue encontrado, y es la forma más rápida de diagnosticar problemas de integración.
- **`curl_cffi` pineado a 0.14.0:** trátalo como una dependencia acoplada a tu versión actual de yt-dlp, no como algo "fijado y listo". Cada vez que subas de versión el ZIP de yt-dlp, corre `yt-dlp --list-impersonate-targets` (o el equivalente vía API) para confirmar que sigue reportando los targets como disponibles y no "unavailable" — ese es el chequeo más rápido para detectar que el rango de compatibilidad cambió por debajo tuyo.

---

## 8. Configuración final recomendada (referencia, no código a aplicar aún)

Combinando todo lo discutido — Deno (JS challenge) + PO Token Provider (BotGuard) + fallback de cliente ante 429 — la receta completa para el modo rápido sería:

- `js_runtimes`: Deno (ya lo tienes)
- `remote_components`: `ejs:github`, con `ejs:npm` como fallback si GitHub falla (mencionado en la respuesta anterior)
- PO Token Provider en modo servidor, arrancado con la app
- `extractor_args` sin forzar cliente por defecto (dejar que yt-dlp decida) — el PO Token Provider hace que el cliente por defecto vuelva a ser confiable
- Fallback automático a `player_client=android` solo si el intento con default falla con 429/bot-check
- `impersonate` como opción avanzada, no activada por defecto

---

## Referencias

- https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide
- https://github.com/jim60105/bgutil-ytdlp-pot-provider-rs
- https://github.com/Brainicism/bgutil-ytdlp-pot-provider
- https://github.com/yt-dlp/yt-dlp/wiki/EJS
- https://github.com/yt-dlp/yt-dlp#plugins (sección de ubicaciones de plugins)
