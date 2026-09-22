# ⚡ Ultrafast Web Agent · Extensión para Firefox

Extensión nativa para Mozilla Firefox del agente web autónomo ultrarrápido con **espacio de acciones indexadas**, extracción DOM en milisegundos y **soporte multi-proveedor de modelos de lenguaje**.

---

## 🚀 ¿Por qué es ultrarrápido?

Los agentes web tradicionales basados en capturas de pantalla (visión) y protocolos CDP/Playwright sufren de una latencia enorme:
1. Capturar pantalla completa a alta resolución: ~500ms - 1.5s
2. Codificar y transferir imagen por red a un modelo multimodal: ~1.5s - 4s
3. Inferencia multimodal pesada: ~2s - 5s
4. Latencia IPC entre el proceso del agente y el navegador: ~100ms - 300ms
**Total por paso en agentes tradicionales: 4 a 10 segundos.**

### La arquitectura Ultrafast en Firefox:
- **0ms de retardo IPC**: La extensión se ejecuta **directamente dentro del proceso de Firefox**.
- **Snapshot DOM en ~2 milisegundos**: `snapshot.js` analiza los elementos interactivos visibles (`button`, `input`, `select`, enlaces), les asigna índices compactos (`[1]`, `[2]`, `[3]`) y descarta el árbol DOM innecesario.
- **Inferencia LLM de texto puro en ~200-400ms**: El modelo recibe una tabla compacta de sólo unos cientos de tokens y responde en un único paso con la acción, el objetivo y el texto a escribir en JSON.
- **Ejecución directa en el DOM en ~1ms**: Clics, escritura de texto (`input`/`change`), scrolls y selecciones se ejecutan directamente en la página con feedback visual inmediato.
**Total por paso: ¡menos de 400 milisegundos!**

---

## 📦 Instalación rápida en Firefox

1. Abre Mozilla Firefox.
2. En la barra de direcciones escribe:
   ```text
   about:debugging#/runtime/this-firefox
   ```
   (o ve a Menú ☰ → *Herramientas* → *Depuración de extensiones* → *Este Firefox*).
3. Haz clic en el botón **"Cargar complemento temporal..."** (*Load Temporary Add-on...*).
4. Selecciona el archivo `manifest.json` dentro de la carpeta `firefox-extension/`.
5. ¡Listo! Verás el icono del rayo ⚡ en la barra de herramientas de Firefox.

---

## 🤖 Proveedores LLM soportados

Puedes alternar entre los siguientes proveedores desde el desplegable del popup:

### 1. OpenRouter (`openrouter`)
- **Base URL predeterminada:** `https://openrouter.ai/api/v1`
- **Modelos recomendados:**
  - `deepseek/deepseek-chat` (ultrarrápido y económico)
  - `meta-llama/llama-3.3-70b-instruct`
  - `anthropic/claude-3.5-haiku`
  - `openai/gpt-4o-mini`
- **Configuración:** Introduce tu API Key de OpenRouter (`sk-or-...`).

### 2. OmniRoute (`omniroute`)
- **Base URL predeterminada:** `http://localhost:20128/v1` (o tu instancia remota de OmniRoute)
- **Modelos recomendados:** Cualquier modelo configurado en tu pasarela OmniRoute (ej. `gpt-4o-mini`, `cc/claude-3-5-haiku`, `glm/glm-4`).
- **Configuración:** Si ejecutas OmniRoute localmente (`npm install -g omniroute && omniroute start`), no necesitas API key o puedes ingresar la configurada en tu panel.

### 3. NVIDIA NIM (`nvidia`)
- **Base URL predeterminada:** `https://integrate.api.nvidia.com/v1`
- **Modelos recomendados:**
  - `meta/llama-3.1-70b-instruct`
  - `meta/llama-3.3-70b-instruct`
  - `mistralai/mistral-large-2-instruct`
- **Configuración:** Introduce tu API Key de NVIDIA NGC / NIM (`nvapi-...`).

### 4. Anthropic Claude (`anthropic`)
- **Base URL predeterminada:** `https://api.anthropic.com/v1`
- **Modelos recomendados:**
  - `claude-3-5-haiku-20241022` (máxima velocidad)
  - `claude-3-7-sonnet-20250219`
- **Configuración:** Introduce tu API Key de Anthropic (`sk-ant-...`). La extensión incluye automáticamente el encabezado de acceso directo para extensiones de navegador (`anthropic-dangerous-direct-browser-access: true`).

### 5. OpenAI (`openai`)
- **Base URL predeterminada:** `https://api.openai.com/v1`
- **Modelos recomendados:**
  - `gpt-4o-mini` (rápido y económico)
  - `gpt-4o`
- **Configuración:** Introduce tu API Key de OpenAI (`sk-...`).

---

## 🎮 Cómo utilizar la extensión

1. Navega a cualquier página web donde quieras que actúe el agente (por ejemplo: Google Flights, una tienda online, una wiki, etc.).
2. Haz clic en el icono ⚡ de la extensión en la barra de herramientas.
3. Elige tu proveedor favorito e introduce tu API Key (se guarda automáticamente de forma segura en `browser.storage.local`).
4. Escribe el objetivo en el campo **Objetivo / Tarea**:
   > *Ejemplo:* `"Buscar vuelos de Madrid a París el 12 de noviembre para un adulto en clase turista y detenerte cuando se vean los precios."*
5. Opciones de ejecución:
   - **▶ Iniciar Agente:** El agente analizará la página, razonará el siguiente paso y ejecutará las acciones en bucle hasta completar el objetivo o alcanzar el límite de pasos.
   - **⏭ Paso:** Ejecuta exactamente 1 paso (útil para inspeccionar o depurar).
   - **⏹ Detener:** Pausa la ejecución en cualquier momento.
   - **👁 Ver etiquetas [1], [2]:** Dibuja sobre la página etiquetas numéricas en cada elemento interactivo para que veas exactamente qué ve el agente.

---

## 📂 Estructura de archivos de la extensión

```text
firefox-extension/
├── manifest.json            # Manifiesto WebExtension compatible con Firefox
├── popup/
│   ├── popup.html          # Interfaz visual de control y configuración
│   ├── popup.css           # Estilos modernos y modo oscuro de alto rendimiento
│   └── popup.js            # Controlador de eventos, almacenamiento y comunicación
├── content/
│   ├── snapshot.js         # Extractor DOM ultrarrápido (~2ms)
│   └── executor.js         # Ejecutor de clics, escritura y resaltado visual en página
├── background/
│   ├── background.js       # Máquina de estados y bucle de control del agente
│   └── providers.js        # Cliente unificado de APIs LLM (OpenRouter, OmniRoute, etc.)
└── icons/
    ├── icon-16.png
    ├── icon-48.png
    ├── icon-96.png
    └── icon-128.png
```
