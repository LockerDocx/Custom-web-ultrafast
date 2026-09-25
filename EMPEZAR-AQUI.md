# 🚀 EMPEZAR AQUÍ — Manual súper sencillo (paso a paso, sin consola)

Esto te instala un **asistente IA que maneja tu Firefox**: le escribes lo que quieres hacer ("busca vuelos de Madrid a Roma el 20 de junio") y él navega, hace clic y escribe por ti, en tu propia pestaña.

**Tiempo total: unos 10 minutos. Gratis. Sin escribir comandos.**

Si algo falla, mira la tabla de [problemas comunes](#-problemas-comunes) al final.

---

## 📋 Antes de empezar: necesitas 3 cosas

| # | Qué | Cómo comprobarlo |
|---|-----|------------------|
| 1 | **Firefox** → [mozilla.org/firefox](https://www.mozilla.org/firefox/) | Si ya lo usas, hecho ✓ |
| 2 | **Python 3.11 o más nuevo** → [python.org/downloads](https://www.python.org/downloads/) | En Windows marca la casilla **"Add python.exe to PATH"** al instalar. **En Linux puede que ya lo tengas**: el arranque te dice el comando exacto si no |
| 3 | **Una clave API gratuita** | La conseguimos en el PASO 2 de esta guía (2 minutos) |

> 🐧 **¿Linux?** El doble clic te dirá el comando exacto si te falta Python. Para adelantarte:
>
> | Sistema | Comando |
> | --- | --- |
> | **openSUSE / SUSE (Leap y Tumbleweed)** | `sudo zypper install python312 python312-pip` |
> | **Ubuntu / Debian / Linux Mint** | `sudo apt update && sudo apt install python3 python3-pip python3-venv` |
> | **Fedora / RHEL / Rocky** | `sudo dnf install python3.12 python3-pip` |
> | **Arch / Manjaro / EndeavourOS** | `sudo pacman -S python` |
>

> ⚠️ **En openSUSE Leap 15.6 el `python3` del sistema es Python 3.6** (el que usa YaST), así que no sirve: hay que instalar el 3.12 con el comando de arriba (`zypper`). El arranque lo detecta solo y usa `python3.12` sin que toques nada — y si te falta, te lo dice con ese mismo comando.
>
> En **Tumbleweed** no hay que instalar nada: su `python3` ya es 3.13.
>
> 📚 **Guía completa sistema por sistema** (comandos, cómo abrir la terminal en cada uno, comprobaciones y desinstalación): **[docs/setup-por-sistema.md](docs/setup-por-sistema.md)**.

---

## 🟦 PASO 1 — Descargar el proyecto (1 minuto)

1. Abre en Firefox: **https://github.com/LockerDocx/firefox-ai-agent**
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

> 🧠 **Opcional:** con la clave de **NVIDIA** (también gratis) el "cerebro planificador" pasa a ser un modelo más profundo (`z-ai/glm-5.3`). Se consigue en **https://build.nvidia.com** → botón *Login* → icono de tu perfil → **Get API Key**. **Si no la pones, no pasa nada: con tu clave de Groq ya funciona todo**, planificador incluido.

---

## 🟦 PASO 3 — Encender el agente (1 minuto, y solo esta vez)

1. Entra en la carpeta que descomprimiste en el PASO 1
2. **Doble clic** en el arranque de tu sistema:
   - **Windows** → `start-host.bat`
   - **macOS** → `start-host.command` *(la primera vez: clic derecho → **Abrir** → **Abrir**)*
   - **Linux** → `start-host.sh`
3. **La primera vez** se prepara todo solo (instala lo necesario, ~1 minuto) y deja el agente **registrado en Firefox**:
   ```
   Registering the host with Firefox...
     Done: from now on the sidebar starts Jev by itself - you will not need this window again.
   ```
4. 🎉 **A partir de aquí este doble clic ya no hace falta.** En Firefox, al abrir el panel, el agente arranca **solo** (no verás ninguna ventana). La ventana que se ha abierto ahora queda como **respaldo**: puedes dejarla o cerrarla, tú decides.
   - Si el panel dijera **🔴 offline**, es que Firefox no dejó arrancarlo solo: deja esa ventana abierta y **todo funciona igual**. Si tu Firefox es el *snap* de Ubuntu o un *Flatpak*, el navegador lanza los programas locales a través de un permiso del sistema y puede pedírtelo la primera vez; si nunca conecta, usa la ventana.
   - Si mueves la carpeta de sitio, vuelve a hacer doble clic una vez (se registra de nuevo).

**❌ Si algo sale mal aquí:**
- *Dice "Python 3.11 or newer is required"* → el mensaje incluye **el comando para tu sistema** (zypper en openSUSE, apt en Debian/Ubuntu, dnf en Fedora, pacman en Arch); instálalo y repite
- *La ventana se cierra al instante* → instala Python marcando **"Add python.exe to PATH"** y repite
- *El panel dice "offline"* → deja abierta la ventana del PASO 3 (es el modo respaldo)

---

## 🟦 PASO 4 — Instalar el add-on en Firefox (1 minuto)

1. En Firefox, escribe en la **barra de direcciones**: `about:debugging` y pulsa **Enter**
2. Clic en **"This Firefox"** (o **"Este Firefox"** si lo tienes en español), en el menú de la izquierda
3. Pulsa el botón **"Load Temporary Add-on…"** (o **"Cargar complemento temporal…"**)
4. Se abre una ventana para elegir archivo. Dos formas, la que te resulte más cómoda:
   - **Un solo archivo** ⭐: descarga `jev-agent-firefox-….xpi` de la página **Releases** del proyecto (la misma de donde bajaste el ZIP) y selecciónalo tal cual
   - **Desde la carpeta**: entra en **la carpeta del proyecto** (la del PASO 1) → subcarpeta **`extension`** → selecciona **`manifest.json`** → **Abrir**
5. ✓ Comprobación: en la lista aparece **"Jev Ultrafast · Firefox Agent"**

> ℹ️ **"Temporal" significa que al reiniciar Firefox desaparece.** Es normal (aún no está firmado). Cada vez que reinicies Firefox, repite este PASO 4 (30 segundos). **La ventana del PASO 3 no hace falta**: el panel arranca el agente por su cuenta.

---

## 🟦 PASO 5 — Pegar la clave EN FIREFOX y probarlo (2 minutos)

1. Arriba a la derecha en Firefox, pulsa el **icono de Jev** en la barra de herramientas.
   - ¿No lo ves? Pulsa la **pieza de puzzle 🧩** de la barra → Jev Agent. O menú **☰ → Panel lateral → Jev Agent**
2. Se abre el **panel lateral** del agente. Mira el puntito de arriba a la derecha del panel:
   - 🟢 **Verde "host online"** = todo conectado ✓
   - 🔴 Rojo "offline" = Firefox no ha podido arrancar el agente → **doble clic en el starter (PASO 3) una vez** y deja esa ventana abierta. (Suele pasar solo si moviste la carpeta, o en Firefox *snap*/*Flatpak*, donde el sistema pide permiso para lanzar programas locales.)
3. **Pega aquí la clave** (esto es todo el setup): el panel te pide la clave en una tarjeta con un enlace para conseguirla gratis:
   ```
   🔑 One free key starts the agent
   Groq · fast executor (recommended)        get one ↗
   [ pega aquí la clave........... ]         [ Save ]
   ```
   Pega la del PASO 2 y pulsa **Save**. Nada más: **no hay que abrir ni editar ningún archivo**, ni tocar la ventana del host.
   Debajo verás qué queda configurado —con una clave de Groq, todo funciona, planificador incluido:
   ```
   Ready — planner groq:openai/gpt-oss-120b · policy groq:openai/gpt-oss-20b · text groq:openai/gpt-oss-20b
   ```
   *(¿Tienes también la clave de NVIDIA del PASO 2? Pégala en su casilla: el planificador pasará a `nvidia:z-ai/glm-5.3`.)*
4. **Revisa la conexión de las IAs**: el panel prueba cada modelo y te dice el resultado exacto:
   - 🟢 `Executor · groq:openai/gpt-oss-20b 267 ms` = tu clave funciona ✓
   - 🔴 **algo rojo** = pulsa **"Test setup"** y lee el mensaje: dice EXACTAMENTE qué falla (clave mal pegada, sin saldo, modelo inexistente…). Si el problema es la clave, la tarjeta del punto 3 se abre sola para que pegues otra.
5. Escribe una misión de prueba y pulsa **Run**:
   > Busca el artículo de la Wikipedia sobre la Torre Eiffel y ábrelo.
   - ¿Estás en una pestaña vacía o en la página de inicio? **No pasa nada**: el agente abre solo DuckDuckGo y trabaja allí. Si quieres que trabaje en una web concreta, navega a ella antes de pulsar Run.
6. 🍿 **Mira tu Firefox**: aparece el **PLAN con pasos que se van marcando ✓**, la página se mueve sola, clickea, escribe… y el historial de acciones va apareciendo en el panel
7. Botón **Stop** para pararlo cuando quieras (termina la acción en curso y se detiene)

**❌ Si algo falla aquí:** el error queda **escrito en rojo en el panel** (ya no desaparece) y el estado de cada modelo está siempre visible. Con ese mensaje y la tabla de abajo se resuelve casi todo.

---

## 🎉 ¡Listo!

Acabas de ver las dos IAs trabajando: el **planificador** (si pusiste clave NVIDIA) parte tu misión en pasos, y el **ejecutor rápido** (Groq) elige cada acción. Todo dentro de **tu Firefox real**.

**Ideas para probar:**
- *Encuentra vuelos de ida de Barcelona a Roma el 20 de junio para 1 adulto y para cuando se vean los resultados*
- *Busca en la Wikipedia el artículo sobre los gatos y dime cuántas razas hay*
- *En esta página, pon el idioma en inglés* (en webs con selector de idioma)

---

## 🆕 NUEVO: el agente también busca, crea archivos y usa la terminal

El panel ya no solo mueve la página. Ahora hay 5 funciones nuevas:

### 1️⃣ Cambiar de modelo SIN tocar el `.env` (panel "⚙️ Models & parameters")

1. En el panel, haz clic en la línea **"⚙️ Models & parameters"** → se despliega.
2. Verás: botones redondos (*Fast*, *Balanced*…) y 3 desplegables: **Planner**, **Executor**, **Text writer**.
3. Haz clic en el desplegable de **Planner** → verás la lista de modelos del proveedor (la primera vez tarda unos segundos en cargarla; si no sale nada, pulsa **"Refresh catalogue"**).
4. Elige otro modelo → verás que el panel parpadea y abajo los chips se ponen 🟢 (o 🔴 si el modelo no vale: prueba otro).
5. Listo: el cambio **se guarda solo** (en `artifacts/model-config.json`) y se mantiene al reiniciar.

> Los botones *Fast / Balanced / Deep / Browser / Coding* son "ajustes rápidos" para todo el conjunto: Fast = respuestas más veloces, Deep = más pensamiento para misiones difíciles. Dentro de cada rol, **"advanced parameters"** muestra solo los controles que **ese modelo concreto** acepta: si cambias a un modelo sin modo razonamiento, el control desaparece (y si algo no lo admite, el panel te lo dice en vez de enviarlo). También aparece un control de *stream* (respuesta en vivo on/off) y, en modelos que lo permiten, `max_tokens`, `top_p`, `seed`, `stop`…

### 2️⃣ Misiones con herramientas: búsqueda, archivos, PDF y terminal

Ya NO hace falta que la misión sea solo "en esta página". Escribe en el mismo cuadro de siempre, por ejemplo:

- *"Busca en la web el precio del euro hoy y guárdalo en un archivo llamado euro.txt"*
- *"Descarga un PDF sobre cambio climático y resúmelo"* (necesita la instalación del PASO 3 ya hecha con el starter nuevo)
- *"Crea un script de python que diga hola y ejecútalo"*

Qué verás: en vez de la captura de la página, aparece la sección **"Steps"** con el paso a paso (🔧 la herramienta usada, 🏁 la respuesta final). Si el agente necesita navegar, verás también la vista del navegador en directo.

### 3️⃣ El candado 🔐: aprobación de comandos

Cuando el agente quiera ejecutar un comando de terminal "con efectos" (instalar algo, crear, ejecutar), aparecerá un aviso amarillo arriba del panel con el comando exacto y dos botones:

- **Approve** = permitir (se ejecuta solo eso)
- **Deny** = no permitir

Si no respondes en 2 minutos, se considera **Deny** (máxima seguridad). Los comandos de solo lectura (`ls`, `git status`…) no preguntan, y los peligrosos (`sudo`, borrar carpetas…) se bloquean solos.

### 4️⃣ 🔐 Centro de permisos: tú decides qué puede tocar el agente

Debajo del candado de aprobaciones ahora hay un panel **"🔐 Permissions"** con 6 interruptores, cada uno con 3 niveles:

| Ámbito | Qué controla |
|---|---|
| **Browser** | misiones en tu pestaña y el paso de navegación del orquestador |
| **Terminal** | comandos de terminal (`allow` = política normal, `ask` = pregunta siempre, `deny` = nada) |
| **Files** | escribir archivos en la carpeta de trabajo |
| **Network** | buscar en la web y leer páginas |
| **Clipboard** | leer/escribir el portapapeles (por defecto: *ask*) |
| **Downloads** | descargar archivos (por defecto: *allow*, tope 25 MB) |

Reglas que **ningún** nivel puede saltarse: los comandos destructivos (`sudo`, `rm -rf`…) siguen bloqueados y leer secretos sigue estando prohibido, aunque pongas `allow`. Todo cambio de nivel y cada aprobación queda registrado en `artifacts/audit.jsonl`.

### 5️⃣ 🧪 Navegador aislado (modo Neko): que no toque tu sesión

Arriba del panel verás **"Browser target"** con dos botones:

- **My current tab** = lo de siempre: el agente trabaja en tu pestaña actual.
- **Isolated browser** = el agente trabaja dentro de un navegador **Neko** en Docker (aislado de tus cuentas y cookies). Pulsa **Start session** (necesitas Docker instalado) y luego **Watch it** para ver la sesión en directo por WebRTC mientras el agente trabaja. **Stop session** apaga el contenedor.

> Si el contenedor no expone el puerto de control (CDP), el panel lo dice: *"session is manual"* = puedes verlo, pero el agente no puede pilotarlo. Se ajusta con `NEKO_IMAGE` / `NEKO_BROWSER_ARGS` / `NEKO_CDP_PORT` en el `.env`.

> Todo lo que el agente crea o descarga va a la carpeta `workspace/` dentro del proyecto. No puede salir de ahí ni borrar nada fuera.

---

## 🥔 ¿Y si mi PC es modesto? No pasa nada: no instalas nada

El agente **no necesita gráfica ni modelos en tu ordenador**: pensar ocurre en la nube gratis
(Groq + NVIDIA), y en tu PC solo corren Firefox y un proceso de ~40 MB. Un PC de 8 GB va sobrado.

> Los modelos locales (Ollama y compañía) se retiraron a propósito en septiembre de 2026: como el
> agente navega por internet de todas formas, tener el modelo en casa no te salvaba de nada y solo
> añadía instalaciones y lentitud (3-8 s por paso, frente a ~280 ms en la nube).

## 🧠 Extra para curiosos: Laya, el «Jev» abierto (opcional)

Existe un motor de decisión **gratis y de código abierto** (Laya, de Convai — la alternativa abierta al modelo Jev de pago) que este agente ya sabe usar: **clasifica tu misión en cualquier idioma** (¿va al navegador, o necesita búsqueda/archivos/terminal?) en milisegundos y en tu propio PC. Es opcional: sin él todo funciona igual (con las palabras clave de siempre).

1. Descarga los últimos cambios del proyecto (`git pull`) — verás 3 archivos nuevos: `install-laya.bat`, `install-laya.command`, `install-laya.sh`.
2. **Haz doble clic en el de tu sistema** (Windows → `.bat` · macOS → `.command` · Linux → `.sh`). La primera vez hay que haber arrancado el starter al menos una vez.
3. Espera: descarga ~1,3 GB (una sola vez) y verás "Done".
4. **Reinicia el starter.** A partir de aquí, si escribes la misión en alemán, francés… también se enruta bien.

> Para desactivarlo: añade `JEV_LAYA=off` al `.env`. Análisis completo (números, límites, por qué aún no sustituye al navegador): `docs/laya.md`.

## 🔧 Problemas comunes

| Veo esto… | Solución |
|---|---|
| El puntito del panel está **rojo "offline"** | Firefox no arrancó el agente: haz **doble clic en el starter** (PASO 3) y deja esa ventana abierta → todo sigue funcionando igual. Si acabas de mover la carpeta del proyecto, ese doble clic también la vuelve a registrar. En Firefox *snap*/*Flatpak* el sistema puede pedir permiso la primera vez (o denegarlo): con la ventana abierta va igual |
| **Planner o Text writer en 🔴 con error 404 / "not found"** | El id del modelo estaba mal en versiones anteriores (`zai/glm-5.3` en vez de `z-ai/glm-5.3`). **Los starters nuevos lo corrigen solos** al arrancar (verás "Fixed an outdated model id") — o edita `.env` a mano: cambia `zai/` por `z-ai/` en las líneas PLANNER_MODEL y TEXT_MODEL |
| **🔴 con error 401/403 "Authorization failed"** | El proveedor **rechazó tu clave** (mal pegada, incompleta o revocada). Genera una nueva (Groq en **console.groq.com/keys**, NVIDIA en **build.nvidia.com** → perfil → *API Keys*) y **pégala en el propio panel**: botón **🔑 API keys** → Save. Se guarda y se aplica al momento, sin reiniciar nada |
| Un modelo está en **🔴 en el panel** | Pulsa **"Test setup"** y lee el mensaje exacto: `401/403` = clave mal pegada → pégala otra vez con **🔑 API keys**; `404` o `not found` = ese nombre de modelo no existe en el proveedor → elige otro en el desplegable del panel **⚙️ Models & parameters** |
| Sale un **error rojo en el panel** al pulsar Run | Léelo: ahora incluye la causa real (`HTTP 401: invalid key`, `HTTP 404: model ... does not exist`...). Cada caso está en esta tabla |
| No encuentro `manifest.json` al cargar el add-on | Está DENTRO de la carpeta `extension` del proyecto (PASO 4, punto 4) |
| Reinicié Firefox y el add-on desapareció | Normal, es "temporal" → repite el PASO 4 |
| El agente no mueve la página | Debe ser una web normal (no vale `about:...`); si estabas en una pestaña vacía, él abre DuckDuckGo solo. La pestaña debe estar **visible** (no minimizada) |
| Estaba en la pestaña de inicio y di Run | No pasa nada: abre DuckDuckGo automáticamente y trabaja allí |
| `Python 3.11 or newer is required` | El mensaje ya te da el comando de tu sistema (zypper/apt/dnf/pacman) o el enlace de python.org |
| La ventana negra se cierra al instante | En el instalador de Python marca **"Add python.exe a PATH"**, reinstala y repite |
| Solo tengo clave de NVIDIA, no de Groq | **No hay que hacer nada**: pégala y el agente se configura solo para usarla en los tres papeles (`nvidia:z-ai/glm-5.3` planifica) |
| Quiero cambiar el modelo | Panel **⚙️ Models & parameters** → desplegable → elegir (se guarda solo). Sin panel: `docs/providers.md` |
| El desplegable de modelos sale **vacío** | Pulsa **"Refresh catalogue"**. Si sigue vacío: falta la clave de ese proveedor en `.env` (cada desplegable solo lista proveedores con clave) |
| *"Missing library for .pdf files"* al analizar un PDF | Cierra la ventana negra y vuelve a arrancar con el **starter nuevo** (instala el soporte de PDF/Word/Excel solo). Si persiste: en la carpeta del proyecto ejecuta `pip install -e ".[documents]"` y reinicia |
| No aparece el aviso 🔐 pero el comando no se ejecuta | Es lo esperado: sin respuesta en 2 minutos se considera "Deny". Vuelve a lanzar la misión y pulsa **Approve** cuando aparezca |
| La sección **Steps** se queda mucho en "working…" | Las misiones con búsqueda web tardan más (varias llamadas al modelo). El botón **Stop** funciona igual |
| Instalé Laya y va igual que antes | Laya no cambia lo que ves: enruta misiones y elige skills por dentro (en cualquier idioma). Comprueba que reiniciaste el starter tras instalarlo; para desactivarlo: `JEV_LAYA=off` |

## ❓ Preguntas rápidas

- **¿Cuesta dinero?** No. Groq y NVIDIA tienen capas gratuitas generosas para este uso.
- **¿Necesito una gráfica o instalar un modelo local?** No. El agente ya viene configurado para
  pensar en la nube gratis (Groq + NVIDIA): en tu PC solo corren Firefox y un proceso de ~40 MB.
  Los modelos locales se retiraron en septiembre de 2026 (el agente navega por internet igual, así
  que no servían para funcionar sin conexión). Lo único que corre en tu PC es el enrutador de
  decisiones opcional: `docs/laya.md`.
- **Solo tengo una clave, ¿vale?** Sí: con la de Groq o con la de NVIDIA funciona todo
  (`docs/providers.md` → *Zero configuration: one key is enough*). Con las dos se reparte: NVIDIA para el
  planificador y Groq para el ejecutor, que es lo más rápido.
- **¿Mi clave está segura?** Sí: se guarda solo en TU ordenador (el archivo `.env`) y solo viaja a Groq/NVIDIA cuando el agente piensa. Nunca llega a las webs que visitas ni a la extensión.
- **¿Puede descontrolarse mi navegador?** No: solo actúa en la pestaña donde lo lanzaste, hay botón Stop, y un máximo de acciones por tarea.
- **¿Funciona en todas las webs?** En la mayoría. Algunas con protecciones anti-bot muy agresivas pueden resistirse.
- **¿En Chrome?** Este manual es para Firefox. El proyecto también funciona con Chrome para usuarios avanzados (`README.md`).

## ➕ Siguiente nivel

- **Todas las opciones de modelos y proveedores** → `docs/providers.md`
- **Cómo funciona por dentro (arquitectura, seguridad)** → `docs/firefox-extension.md`
- **Guía equivalente en inglés** → `docs/getting-started-gui.md`
