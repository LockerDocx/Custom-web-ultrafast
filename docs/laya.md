# Laya: el motor de decisión local (y por qué no hay modelos locales)

> Septiembre de 2026. Dos decisiones de producto, juntas porque se explican una a la otra:
>
> 1. **Los LLM locales ya no se soportan.** Ollama, LM Studio, llama.cpp y Jan se retiraron del
>    agente (no están en los presets ni en el catálogo).
> 2. **Laya se queda**, porque no es un modelo sustituto: es un enrutador de decisiones local.

## 1. Por qué fuera los LLM locales

El trabajo de este agente es **conducir una página web viva**. Eso necesita internet, siempre. Un
modelo local no resuelve ningún caso que el producto tenga: no hace que el agente funcione sin
conexión (no hay página que navegar), no mejora la latencia en un PC sin gráfica (3-8 s por paso
frente a ~280 ms de la nube gratis), y añadía a cambio cuatro presets, una sección de catálogo,
documentación de hardware y pruebas que mantener.

Si algún día quieres un endpoint propio, sigue existiendo la vía general: cualquier servidor
OpenAI-compatible **por URL** (`POLICY_PROVIDER=https://mi-gateway/v1`), incluidos gateways
autoalojados en tu máquina, que no necesitan clave.

## 2. Qué es Laya

[Laya](https://github.com/NandhaKishorM/laya) (Convai Innovations, Apache 2.0) es la alternativa
abierta al motor **Jev** de TypeSafe — y no es un LLM:

- Motor de decisión **no-autorregresivo**: lee el estado y responde preguntas tipadas — `choice`
  (elige una opción de una lista), `score` (valora en una escala), `bool` (booleano con P(true)
  calibrada) — en **una sola pasada**, sin generar ni un token. Arquitectónicamente **no puede
  inventar una opción fuera de la lista**: la misma filosofía de validación que el resto del agente.
- 3 checkpoints: `laya` (inglés, 421M, 512 tokens de contexto), **`laya-multilingual`** (322M,
  1024 tokens, 100+ idiomas — el que usa el agente) y `laya-typed-decisions` (fine-tune).
- Entrenado con **RLCD** (el reward solo se maximiza diciendo la verdad), así que su confianza está
  **calibrada de verdad**: ECE 0.081 frente a 0.246 de Jev.
- Apache 2.0, ~1,3 GB de pesos, corre en **CPU**: 32,8 ms p50 en GPU, ~3,7 ms en CoreML y mediciones
  propias de 117 ms por decisión en una CPU de 2 núcleos (GitHub Actions).

### Números publicados vs Jev (T4; las cifras de Jev son de terceros)

| Métrica | Laya | Jev (TypeSafe) |
| --- | --- | --- |
| Latencia p50 | **32,8 ms** (7,2 ms en lote) | 236-276 ms (~7,8× más lento) |
| Calibración (ECE, menos es mejor) | **0.081** | 0.246 |
| Precisión typed-decisions | **0.766** (checkpoint afinado) | 0.727 |
| Coste | **0 €** (autoalojado, air-gapped) | 0,042 $/M tokens |

### ¿Y el Jev original de TypeSafe?

Verificado el 23-sep-2026: **no es open source ni descargable**. API alojada en early access
(waitlist, `console.typesafe.ai`), sin pesos, sin recuento de parámetros y sin opción on-premise
pública. Lo único abierto son sus SDKs.

*(El agente sigue soportándolo si tienes clave: `TYPESAFE_API_KEY` en el `.env` hace que el rol
policy use Jev y se ignore `POLICY_*`.)*

## 3. Las dos letras pequeñas (importantísimas)

1. **Zero-shot flojo**: los checkpoints base sacan ~0.36 en su propio benchmark (el 0.766 es del
   fine-tune). Los autores lo dicen claro: es «una base rápida para especializar», no un oráculo.
2. **`choice` degrada pasadas ~20 opciones** (Banking77, 77 clases: 0.425) y el contexto es de
   512/1024 tokens.

## 4. Qué hace hoy en este agente

**No** sustituye al ejecutor del navegador: elegir entre 30+ elementos de una página real choca de
frente con esas dos letras pequeñas. Donde **ya** gana:

- **Enrutar misiones** (¿navegador u orquestador?) y **elegir skills** en **cualquier idioma**. El
  keyword-matching de siempre solo sabía español e inglés; Laya añade cobertura semántica con
  confianza calibrada. Si duda (<0.75), cae automáticamente al matcher: **nunca rompe una ejecución**.

**Resultados medidos con pesos reales** (GitHub Actions, CPU, sept 2026 — baterías «Laya check» y
«Executor duel»):

| Métrica | Laya | GPT-OSS-20B (Groq) |
| --- | --- | --- |
| Enrutado de misiones (24 casos, 6 idiomas) | 10/24 (42 %) | **24/24 (100 %)** |
| Elegir el elemento de la página (17 casos) | 9/17 (53 %) | **17/17 (100 %)** |
| Páginas «cliff» de 30+ elementos | 0/3 | **3/3** |
| Latencia p50 (CPU local vs API Groq) | 117 ms routing / 447 ms executor | 294 ms / 221 ms |
| Coste por duelo completo | 0 €, 0 tokens | 12.542 tokens (capa gratuita) |

Conclusiones accionadas: (1) el gate de confianza subió de 0.55 a **0.75** — en la batería, toda
decisión de routing de Laya ≥0.75 fue correcta, y el rango 0.55-0.74 contenía errores confiados que
desviaban misiones reales; (2) **GPT-OSS-20B ejecuta y Laya solo clasifica cuando está muy segura**;
(3) el valor de Laya es operar **sin clave, sin red y gratis** para esa decisión concreta.

## 5. Requisitos y coste

| Pregunta | Respuesta |
| --- | --- |
| **¿Self-hosted?** | **Sí, 100 %.** Los pesos (Apache 2.0) se descargan una vez de Hugging Face a `~/.cache/huggingface`. Después: cero red, cero clave, cero coste |
| **Disco** | ~1,3 GB de pesos + torch (200 MB-1 GB; el instalador de Linux usa el build CPU, 10× más pequeño que el de CUDA) |
| **RAM** | **~1 GB** en uso; convive con Firefox en un PC de 8 GB. El cargador **pide 1,6 GB libres** antes de cargar los pesos: en una máquina con menos memoria el proceso moriría por OOM y eso no se puede atrapar, así que se niega y lo dice en el panel |
| **CPU / GPU** | cualquier x86-64 con AVX2 (190 ms/decisión medidos en 2 núcleos); si detecta GPU CUDA o Apple Silicon, la usa sola (32,8 ms) |
| **Instalar** | **Se instala solo** en el primer arranque (en segundo plano, y solo si el arranque lo hace una persona: en CI o dentro de las pruebas no descarga nada). Después tienes `./install-laya.sh` · `.bat` · `.command` o `pip install -e ".[laya]"` |
| **Desactivar** | `JEV_LAYA=off` en el `.env` → vuelve el enrutado por palabras clave |

## 6. El camino al executor 100 % abierto

Cada ejecución del agente ya graba sus **decisiones validadas** (`artifacts/runs.jsonl`: historial
con operation/target por paso). Ese registro es, tal cual, el dataset de fine-tune que Laya
necesitaría para convertirse en el executor local: mismas preguntas `choice` sobre elementos
observados, con las etiquetas correctas incluidas. Ese es el paso natural hacia un agente de
navegador 100 % abierto — y el motivo de mantener Laya integrada aunque hoy solo enrute.

## 7. Licencias y fuentes

- Laya: **Apache 2.0** (Convai Innovations). Pesos y código abiertos.
- Fuentes: repo de Laya, su informe de calibración (sept 2026) y las mediciones propias
  reproducibles en los workflows **Laya check** y **Executor duel** de este repositorio.
