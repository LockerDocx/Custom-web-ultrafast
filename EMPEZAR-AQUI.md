# 🚀 EMPEZAR AQUÍ — Manual súper sencillo (paso a paso, sin consola)

Esto te instala un **asistente IA que maneja tu Firefox**: le escribes lo que quieres hacer ("busca vuelos de Madrid a Roma el 20 de junio") y él navega, hace clic y escribe por ti, en tu propia pestaña.

**Tiempo total: unos 10 minutos. Gratis. Sin escribir comandos.**

Si algo falla, mira la tabla de [problemas comunes](#-problemas-comunes) al final.

---

## 📋 Antes de empezar: necesitas 3 cosas

| # | Qué | Cómo comprobarlo |
|---|-----|------------------|
| 1 | **Firefox** → [mozilla.org/firefox](https://www.mozilla.org/firefox/) | Si ya lo usas, hecho ✓ |
| 2 | **Python 3.12 o más nuevo** → [python.org/downloads](https://www.python.org/downloads/) | Abre el instalador; en el primer paso marca la casilla **"Add python.exe to PATH"** (solo Windows) y pulsa Install |
| 3 | **Una clave API gratuita** | La conseguimos en el PASO 2 de esta guía (2 minutos) |

---

## 🟦 PASO 1 — Descargar el proyecto (1 minuto)

1. Abre en Firefox: **https://github.com/LockerDocx/Custom-web-ultrafast**
2. Pulsa el **botón verde "Code"** → **"Download ZIP"**
3. El ZIP baja a tu carpeta de *Descargas*. Descomprímelo:
   - **Windows**: clic derecho sobre el ZIP → **"Extraer todo…"** → Extraer
   - **macOS**: doble clic sobre el ZIP
4. ✓ Comprobación: tienes una carpeta que contiene archivos como `start-host.bat` y una carpeta `extension`.

> 💡 También puedes descargar el ZIP desde la página de **Releases** del repo (mismo resultado).

---

## 🟦 PASO 2 — Conseguir tu clave API gratuita (2 minutos)

La clave es como una contraseña para que el asistente use una IA. La más fácil de conseguir es la de **Groq** (gratis):

1. Abre **https://console.groq.com/keys**
2. Inicia sesión (puedes usar tu cuenta de **Google**: botón "Continue with Google")
3. Pulsa **"Create API Key"** → dale un nombre cualquiera (por ejemplo `jev`) → **Create API Key**
4. Aparece un texto que empieza por `gsk_...` → **cópialo** con el botón de copiar 📋
5. ⚠️ Guárdala en un sitio seguro. **Nunca la compartas ni la pegues en webs raras.**

> 🧠 **Opcional (recomendado más adelante):** la clave de **NVIDIA** (también gratis) activa el "cerebro planificador" que descompone tu misión en pasos. Se consigue en **https://build.nvidia.com** → botón *Login* → icono de tu perfil → **Get API Key**. Si no la pones ahora, todo funciona igual (sin planificador).

---

## 🟦 PASO 3 — Pegar tu clave y encender el agente (2 minutos)

1. Entra en la carpeta que descomprimiste en el PASO 1
2. **Doble clic** en el arranque de tu sistema:
   - **Windows** → `start-host.bat`
   - **macOS** → `start-host.command` *(la primera vez: clic derecho → **Abrir** → **Abrir**)*
   - **Linux** → `start-host.sh`
3. **La primera vez** se prepara todo solo (verás que instala cosas, ~1 minuto). Al terminar **se abre el Bloc de notas** con el archivo de configuración (`.env`)
4. En el Bloc de notas, **busca esta línea**:
   ```
   GROQ_API_KEY=PASTE-YOUR-GROQ-KEY-HERE
   ```
5. **Borra** `PASTE-YOUR-GROQ-KEY-HERE` y **pega tu clave** (Ctrl+V). Tiene que quedar así (con TU clave):
   ```
   GROQ_API_KEY=gsk_AbCdEf123456...
   ```
6. *(Opcional)* Haz lo mismo con la línea `NVIDIA_API_KEY=...` si conseguiste la clave de NVIDIA
7. **Guarda**: Ctrl+S (Windows) o Cmd+S (macOS). Cierra el Bloc de notas
8. **Doble clic otra vez** en el arranque → se abre una **ventana negra** que dice:
   ```
   Jev Ultrafast Firefox bridge: ws://127.0.0.1:8767
   Policy model: groq:openai/gpt-oss-20b
   ```
   ✓ **¡El agente está encendido!** ⚠️ **NO CIERRES ESA VENTANA** mientras uses el asistente (puedes minimizarla).

**❌ Si algo sale mal aquí:**
- *Dice "Python 3.12 or newer is required"* → instala Python (ver 📋) y repite el PASO 3
- *Dice "No API key configured yet"* → la clave no se pegó bien: repite los puntos 4-7
- *La ventana se cierra al instante* → instala Python marcando **"Add python.exe to PATH"** y repite

---

## 🟦 PASO 4 — Instalar el add-on en Firefox (1 minuto)

1. En Firefox, escribe en la **barra de direcciones**: `about:debugging` y pulsa **Enter**
2. Clic en **"This Firefox"** (o **"Este Firefox"** si lo tienes en español), en el menú de la izquierda
3. Pulsa el botón **"Load Temporary Add-on…"** (o **"Cargar complemento temporal…"**)
4. Se abre una ventana para elegir archivo:
   1. Entra en **la carpeta del proyecto** (la del PASO 1)
   2. Entra en la carpeta **`extension`**
   3. Selecciona el archivo **`manifest.json`** → **Abrir**
5. ✓ Comprobación: en la lista aparece **"Jev Ultrafast · Firefox Agent"**

> ℹ️ **"Temporal" significa que al reiniciar Firefox desaparece.** Es normal (aún no está firmado). Cada vez que reinicies Firefox, repite este PASO 4 (30 segundos). La ventana negra del PASO 3 también debe estar abierta.

---

## 🟦 PASO 5 — Abrir el panel y ¡probarlo! (1 minuto)

1. Arriba a la derecha en Firefox, pulsa el **icono de Jev** en la barra de herramientas.
   - ¿No lo ves? Pulsa la **pieza de puzzle 🧩** de la barra → Jev Agent. O menú **☰ → Panel lateral → Jev Agent**
2. Se abre el **panel lateral** del agente. Mira el puntito de arriba a la derecha del panel:
   - 🟢 **Verde "host online"** = todo conectado ✓
   - 🔴 Rojo "offline" = la ventana negra está cerrada → vuelve al PASO 3
3. **Revisa la conexión de las IAs**: al abrir el panel, debajo del cuadro de texto verás el estado de cada modelo:
   - 🟢 `Executor · groq:openai/gpt-oss-20b` = tu clave Groq funciona ✓
   - 🟢 `Planner · nvidia:z-ai/glm-5.3` y `Text writer` = tu clave NVIDIA funciona ✓
   - 🔴 **algo rojo** = pulsa el botón **"Test setup"** y lee el mensaje: te dice EXACTAMENTE qué falla (clave mal pegada, modelo que no existe…). Arregla el `.env` (PASO 3) y reinicia el starter.
4. Escribe una misión de prueba y pulsa **Run**:
   > Busca el artículo de la Wikipedia sobre la Torre Eiffel y ábrelo.
   - ¿Estás en una pestaña vacía o en la página de inicio? **No pasa nada**: el agente abre solo DuckDuckGo y trabaja allí. Si quieres que trabaje en una web concreta, navega a ella antes de pulsar Run.
5. 🍿 **Mira tu Firefox**: aparece el **PLAN con pasos que se van marcando ✓**, la página se mueve sola, clickea, escribe… y el historial de acciones va apareciendo en el panel
6. Botón **Stop** para pararlo cuando quieras (termina la acción en curso y se detiene)

**❌ Si algo falla aquí:** el error queda **escrito en rojo en el panel** (ya no desaparece) y el estado de cada modelo está siempre visible. Con ese mensaje y la tabla de abajo se resuelve casi todo.

---

## 🎉 ¡Listo!

Acabas de ver las dos IAs trabajando: el **planificador** (si pusiste clave NVIDIA) parte tu misión en pasos, y el **ejecutor rápido** (Groq) elige cada acción. Todo dentro de **tu Firefox real**.

**Ideas para probar:**
- *Encuentra vuelos de ida de Barcelona a Roma el 20 de junio para 1 adulto y para cuando se vean los resultados*
- *Busca en la Wikipedia el artículo sobre los gatos y dime cuántas razas hay*
- *En esta página, pon el idioma en inglés* (en webs con selector de idioma)

---

## 🔧 Problemas comunes

| Veo esto… | Solución |
|---|---|
| El puntito del panel está **rojo "offline"** | La ventana negra del host está cerrada → doble clic en el starter (PASO 3, punto 8) |
| **Planner o Text writer en 🔴 con error 404 / "not found"** | El id del modelo estaba mal en versiones anteriores (`zai/glm-5.3` en vez de `z-ai/glm-5.3`). **Los starters nuevos lo corrigen solos** al arrancar (verás "Fixed an outdated model id") — o edita `.env` a mano: cambia `zai/` por `z-ai/` en las líneas PLANNER_MODEL y TEXT_MODEL |
| Un modelo está en **🔴 en el panel** | Pulsa **"Test setup"** y lee el mensaje exacto: `401` = clave mal pegada (repite PASO 3); `404` o `not found` = el nombre del modelo no existe en ese proveedor → córregelo en `.env` (el enlace correcto: Groq en console.groq.com/models, NVIDIA en build.nvidia.com/models) y reinicia el starter |
| Sale un **error rojo en el panel** al pulsar Run | Léelo: ahora incluye la causa real (`HTTP 401: invalid key`, `HTTP 404: model ... does not exist`...). Cada caso está en esta tabla |
| No encuentro `manifest.json` al cargar el add-on | Está DENTRO de la carpeta `extension` del proyecto (PASO 4, punto 4) |
| Reinicié Firefox y el add-on desapareció | Normal, es "temporal" → repite el PASO 4 |
| El agente no mueve la página | Debe ser una web normal (no vale `about:...`); si estabas en una pestaña vacía, él abre DuckDuckGo solo. La pestaña debe estar **visible** (no minimizada) |
| Estaba en la pestaña de inicio y di Run | No pasa nada: abre DuckDuckGo automáticamente y trabaja allí |
| `Python 3.12 or newer is required` | Instala Python desde python.org y repite el PASO 3 |
| La ventana negra se cierra al instante | En el instalador de Python marca **"Add python.exe a PATH"**, reinstala y repite |
| Solo tengo clave de NVIDIA, no de Groq | Abre `.env` con el Bloc de notas y cambia la línea `POLICY_PROVIDER=groq` por `POLICY_PROVIDER=nvidia` y `POLICY_MODEL=openai/gpt-oss-20b` por un modelo de NVIDIA (míralos en build.nvidia.com/models). Guarda y arranca |
| Quiero cambiar el modelo | Todo está explicado en `docs/providers.md` |

## ❓ Preguntas rápidas

- **¿Cuesta dinero?** No. Groq y NVIDIA tienen capas gratuitas generosas para este uso.
- **¿Mi clave está segura?** Sí: se guarda solo en TU ordenador (el archivo `.env`) y solo viaja a Groq/NVIDIA cuando el agente piensa. Nunca llega a las webs que visitas ni a la extensión.
- **¿Puede descontrolarse mi navegador?** No: solo actúa en la pestaña donde lo lanzaste, hay botón Stop, y un máximo de acciones por tarea.
- **¿Funciona en todas las webs?** En la mayoría. Algunas con protecciones anti-bot muy agresivas pueden resistirse.
- **¿En Chrome?** Este manual es para Firefox. El proyecto también funciona con Chrome para usuarios avanzados (`README.md`).

## ➕ Siguiente nivel

- **Todas las opciones de modelos y proveedores** → `docs/providers.md`
- **Cómo funciona por dentro (arquitectura, seguridad)** → `docs/firefox-extension.md`
- **Guía equivalente en inglés** → `docs/getting-started-gui.md`
