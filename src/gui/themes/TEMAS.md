# 🎨 Sistema de Temas — DowP 2.0

## ¿Cómo funciona?

DowP usa un sistema de **template + tokens** para los temas visuales. En lugar de tener archivos de estilos completos para cada tema, se usa:

1. **Un template base** (`_base.qss`) — Define la estructura visual (tamaños, márgenes, bordes redondeados, etc.) usando variables entre llaves dobles como `{{fondo_principal}}`.
2. **Un archivo JSON por tema** (`dark.json`, `light.json`, etc.) — Define únicamente los colores y valores de esas variables.

Al iniciar la app o cambiar de tema, el motor (`styles.py`) combina ambos archivos: lee el template, reemplaza las variables por los colores del JSON, y aplica el resultado.

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────────────┐
│   _base.qss     │  +  │  dark.json   │  =  │  QSS Final (dark)   │
│  (estructura)   │     │  (colores)   │     │  (listo para usar)  │
└─────────────────┘     └──────────────┘     └─────────────────────┘
```

### Ejemplo concreto

Template (`_base.qss`):
```css
QMainWindow {
    background-color: {{fondo_principal}};
}
QLabel#settingsTitle {
    color: {{titulo_settings}};
}
```

Tema oscuro (`dark.json`):
```json
{
    "fondo_principal": "#0a0a0a",
    "titulo_settings": "#1DC038"
}
```

Resultado final aplicado:
```css
QMainWindow {
    background-color: #0a0a0a;
}
QLabel#settingsTitle {
    color: #1DC038;
}
```

---

## Estructura de archivos

```
src/gui/themes/
├── _base.qss        ← Template de estructura (NO tocar colores aquí)
├── dark.json         ← Tema Oscuro (incluido)
├── light.json        ← Tema Claro (incluido)
└── mi_tema.json      ← Tu tema personalizado (tú lo creas)
```

---

## Referencia de Tokens

Cada token controla un aspecto visual específico de la app. Aquí está la lista completa:

### 🖥️ Fondos

| Token | Descripción | Dónde se usa |
|---|---|---|
| `fondo_principal` | Fondo de la ventana principal | `QMainWindow`, thumbnails |
| `fondo_secundario` | Fondo de inputs y contenedores | `QLineEdit`, `QComboBox`, `QListWidget`, `VideoCard` |
| `fondo_terciario` | Fondo del dropdown del ComboBox | Lista desplegable del `QComboBox` |
| `fondo_elemento` | Fondo de cada item en listas | Items dentro de `QListWidget` |

### ✏️ Texto

| Token | Descripción | Dónde se usa |
|---|---|---|
| `texto_principal` | Color de texto general | `QWidget` (hereda a todo), dropdown del ComboBox |
| `texto_secundario` | Texto de menor importancia | Reservado para uso futuro |
| `texto_activo` | Texto destacado o activo | `QLineEdit` input, tab seleccionado, label de resolución |

### 🟢 Acentos

| Token | Descripción | Dónde se usa |
|---|---|---|
| `acento_primario` | Color de acento principal | Borde inferior de tab activo, borde de item seleccionado |
| `acento_secundario` | Color de acento secundario | Reservado para uso futuro |

### 🔲 Bordes

| Token | Descripción | Dónde se usa |
|---|---|---|
| `borde_normal` | Borde estándar de elementos | Inputs, listas, contenedores, thumbnails |
| `borde_sutil` | Borde más suave | Dropdown del ComboBox |

### 🖱️ Selección

| Token | Descripción | Dónde se usa |
|---|---|---|
| `seleccion_fondo` | Fondo del item seleccionado | `QListWidget::item:selected`, `QComboBox` selección |
| `seleccion_texto` | Texto del item seleccionado | Texto en dropdown del ComboBox al seleccionar |

### 🏷️ Badges

| Token | Descripción | Dónde se usa |
|---|---|---|
| `badge_fondo` | Fondo de etiquetas/badges | Label de extensión (MP4, WEBM, etc.) |
| `badge_texto` | Texto de etiquetas/badges | Texto en label de extensión |

### 🔘 Botón principal

| Token | Descripción | Dónde se usa |
|---|---|---|
| `boton_fondo_inicio` | Color inicio del gradiente | Botón "Analizar URL" (arriba) |
| `boton_fondo_fin` | Color fin del gradiente | Botón "Analizar URL" (abajo) |
| `boton_texto` | Color del texto del botón | Texto en botón "Analizar URL" |

> **Tip:** Si quieres un botón de color sólido (sin gradiente), pon el mismo color en `boton_fondo_inicio` y `boton_fondo_fin`.

### 🔘 Botón secundario

| Token | Descripción | Dónde se usa |
|---|---|---|
| `boton_secundario_fondo` | Color de fondo principal | Botones menos destacados (ej. "Descargar miniatura") |
| `boton_secundario_texto` | Color del texto | Texto de botones secundarios |
| `boton_secundario_hover` | Color al pasar el ratón | Efecto hover de botones secundarios |

### ☑️ Casillas (Checkboxes)

| Token | Descripción | Dónde se usa |
|---|---|---|
| `checkbox_fondo` | Fondo de la casilla inactiva | `QCheckBox::indicator` |
| `checkbox_borde` | Borde de la casilla | `QCheckBox::indicator` |
| `checkbox_checked` | Color cuando está activa | `QCheckBox::indicator:checked` |

### 📑 Pestañas (Tabs)

| Token | Descripción | Dónde se usa |
|---|---|---|
| `tab_texto_inactivo` | Color del texto de tabs no seleccionados | Tabs inactivos |
| `tab_fondo_seleccionado` | Fondo del tab activo | Tab seleccionado |
| `divisor` | Línea divisora bajo las pestañas | `QTabWidget::pane` borde superior |

### ⚙️ Ajustes

| Token | Descripción | Dónde se usa |
|---|---|---|
| `titulo_settings` | Color del título "Ajustes Generales" | `QLabel#settingsTitle` |
| `divisor_settings` | Color del divisor en ajustes | `QFrame#settingsDivider` |

### 🚦 Estados

| Token | Descripción | Dónde se usa |
|---|---|---|
| `estado_espera` | Estado neutro/pendiente | Tarjetas de cola en espera, ítems "pendiente"/"en cola" |
| `estado_progreso` | Trabajando activamente (sin fallar) | Tarjetas de cola "Descargando" y "Analizando" |
| `estado_exito` | Operación completada con éxito | Tarjetas "Completado", diálogos de dependencias, verificación de códecs |
| `estado_aviso` | Advertencia, no bloqueante | Tarjetas "Omitido" (archivo ya existía), advertencias de compatibilidad |
| `estado_error` | Fallo o cancelación | Tarjetas "Error"/"Cancelado", errores de dependencias |

### 🔽 Triángulo del ComboBox

El triángulo ▼ que aparece en los menús desplegables se genera **automáticamente** usando el color de `acento_primario`. No necesitas configurarlo — siempre coincide con tu acento.

---

## Cómo crear tu propio tema

### Paso 1: Copiar un tema existente

Copia `dark.json` o `light.json` y renómbralo. Ejemplo: `monokai.json`.

### Paso 2: Editar la metadata

```json
{
    "meta": {
        "nombre": "Mi Tema Custom",
        "autor": "Tu Nombre",
        "version": "1.0"
    },
    "colores": {
        ...
    }
}
```

### Paso 3: Cambiar los colores

Edita los valores hexadecimales en la sección `"colores"`. Usa la referencia de tokens de arriba para saber qué controla cada uno.

```json
"colores": {
    "fondo_principal": "#1e1e2e",
    "fondo_secundario": "#313244",
    "acento_primario": "#cba6f7",
    ...
}
```

### Paso 4: Guardar y seleccionar

Guarda el archivo en `src/gui/themes/` y selecciónalo desde **Ajustes → Tema visual** en la app.

> **Importante:** El archivo debe tener **todos** los tokens listados arriba. Si falta alguno, ese elemento se verá sin estilo.

---

## Ejemplo: Tema "Catppuccin Mocha"

```json
{
    "meta": {
        "nombre": "Catppuccin Mocha",
        "autor": "Comunidad",
        "version": "1.0"
    },
    "colores": {
        "fondo_principal": "#1e1e2e",
        "fondo_secundario": "#313244",
        "fondo_terciario": "#45475a",
        "fondo_elemento": "#313244",
        "texto_principal": "#cdd6f4",
        "texto_secundario": "#6c7086",
        "texto_activo": "#cdd6f4",
        "acento_primario": "#cba6f7",
        "acento_secundario": "#f5c2e7",
        "borde_normal": "#45475a",
        "borde_sutil": "#585b70",
        "seleccion_fondo": "#45475a",
        "seleccion_texto": "#cba6f7",
        "badge_fondo": "#45475a",
        "badge_texto": "#cba6f7",
        "boton_fondo_inicio": "#cba6f7",
        "boton_fondo_fin": "#f5c2e7",
        "boton_texto": "#1e1e2e",
        "tab_texto_inactivo": "#6c7086",
        "tab_fondo_seleccionado": "#313244",
        "divisor": "#45475a",
        "titulo_settings": "#cba6f7",
        "divisor_settings": "#f5c2e7"
    }
}
```

---

## Notas para desarrolladores

### Agregar un nuevo token

Si necesitas un color nuevo que no existe en la lista actual:

1. **Agrégalo al template** `_base.qss` usando la sintaxis `{{mi_nuevo_token}}`
2. **Agrégalo a todos los JSON** existentes (`dark.json`, `light.json`) con un valor apropiado
3. **Documéntalo** en este archivo

### Cómo se genera el QSS

El motor en `styles.py` hace esto:

```python
# 1. Lee el template
template = open("_base.qss").read()

# 2. Lee los tokens del tema
tokens = json.load(open("dark.json"))["colores"]

# 3. Genera el SVG del triángulo con el color de acento
triangle_svg = generate_triangle(tokens["acento_primario"])
tokens["icono_triangulo"] = triangle_svg

# 4. Reemplaza todas las variables
for key, value in tokens.items():
    template = template.replace("{{" + key + "}}", value)

# 5. Resultado = QSS listo para aplicar
return template
```

### Archivos temporales

Los SVGs del triángulo se generan en `%TEMP%/dowp_theme_assets/` y se cachean por color. No se incluyen en el proyecto.
