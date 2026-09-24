# Requisitos de hardware

La pregunta correcta no es «cuánto pide el programa» sino **qué modo usas**, porque el
programa en sí es minúsculo: el trabajo pesado lo hacen los proveedores en la nube. Hay
cuatro cosas que sí consumen, y solo una es obligatoria:

| # | Qué consume | ¿Obligatorio? | Cuánto |
| --- | --- | --- | --- |
| 1 | **El navegador** (Firefox con la extensión) | Sí | el navegador que ya tienes abierto |
| 2 | **El host de Jev** (Python) | Sí | **38,6 MB de RAM** · ~2 % de un núcleo |
| 3 | **Laya** (motor de decisión local) | No | ~1 GB RAM + ~1,2 GB disco |
| 4 | **Sandbox Neko** (navegador aislado en Docker) | No | ~2 GB disco + ~1-2 GB RAM del contenedor |
| 5 | **Modelos locales** (Ollama/LM Studio…) | No | el rango más amplio: 1,3 → 8 GB de RAM |
| 6 | **Tarjeta gráfica** | No, nunca | solo acelera modelos locales y Laya |

## La medición del host, hecha aquí mismo

No es una estimación: se ejecutó la aplicación completa (clon de `main`) y se midió el proceso
mientras hacía el circuito entero (catálogo real + sonda en vivo + 3 llamadas por rol):

```
ENTORNO DE MEDICIÓN (peor que cualquier PC real): contenedor de 2 núcleos y 2 GB de RAM, sin GPU

Host de Jev (jev-firefox)   RAM: 38,6 MB constante   ·   CPU pico: 2,2 % de un núcleo
Proveedor simulado          RAM: 18 MB
Disco: repositorio 8,6 MB + entorno virtual 46 MB  (sin torch)
```

Es decir: **el host cabe 50 veces en un Chrome con dos pestañas**. Por eso los requisitos
reales son los del navegador y, si los usas, los de los componentes opcionales.

## 1. Navegador (imprescindible)

- **Vía principal: Firefox 109+.** El agente lee y acciona la página **desde la propia
  extensión**, así que no necesita nada más. RAM: la que tu Firefox ya usa
  (típico 500 MB–1,5 GB según pestañas).
- **Vía suelta `jev` (opcional): Chrome/Chromium** con depuración remota. Mismo rango de RAM.
- Arquitectura: x86-64 y ARM64 funcionan (la imagen Neko tiene capa `arm64` nativa, así que
  Apple Silicon no emula).

## 2. Laya, el motor de decisión local (opcional)

Números del propio proyecto (`docs/modelos-locales.md`), medidos con pesos reales en la
CPU de CI (2 núcleos):

| Concepto | Valor |
| --- | --- |
| Pesos | ~1 GB (`multilingual`, 322M parámetros) |
| RAM en uso | **~1 GB** (fp16); convive con Firefox en un PC de **8 GB** |
| Disco | ~1 GB pesos + torch (200 MB–1 GB; el instalador Linux usa el build CPU ligero) |
| CPU | cualquier x86-64 moderna con **AVX2**: 190 ms por decisión en 2 núcleos |
| GPU | opcional: 32,8 ms en GPU, 3,7 ms en CoreML (Apple) |

Apagarlo: `JEV_LAYA=off` (cae al enrutado por palabras clave, sin coste de hardware).

## 3. Sandbox Neko, navegador aislado (opcional — Docker)

| Concepto | Valor real |
| --- | --- |
| Descarga de imagen | **629 MB comprimidos** (`ghcr.io/m1k1o/neko/chromium:latest`, 24 capas) |
| Disco tras instalar | ~1,5–2 GB |
| Memoria compartida | `--shm-size 2g` (lo pide el propio código) |
| RAM del contenedor | ~1–2 GB (Chromium + codificador WebRTC) |
| CPU | 2 núcleos cómodos si la codificación es por software |
| Red | aquí sí pesa: el vídeo WebRTC para que **veas** la sesión consume ancho de banda |
| Plataformas | amd64 y arm64 nativos |

Sin Docker, la app lo dice y sigue funcionando en modo pestaña real.

## 4. Modelos locales (opcional — el rango más amplio)

Tabla del proyecto, cuantizada en Q4_K_M. **Regla práctica: tu memoria libre (RAM+VRAM) debe
superar el tamaño del archivo GGUF.**

| Modelo | RAM (Q4) | CPU típica |
| --- | --- | --- |
| Llama 3.2 1B | ~1,3 GB | 60-90 tok/s |
| Gemma 4 E2B | ~2 GB | 20-30 tok/s |
| Phi-4-mini 3.8B | ~2,5 GB | 15-25 tok/s |
| **Qwen3.5 4B** ⭐ (recomendado) | ~4,5 GB | 12-25 tok/s |
| Qwen3.5 9B (planner) | ~7-8 GB | 6-12 tok/s (pide 16 GB de equipo) |

| VRAM | Qué corre cómodo |
| --- | --- |
| 2-4 GB | 2B / Phi-4-mini / Gemma 4 E2B |
| 4-6 GB | Qwen3.5 4B entero en GPU (40-80 tok/s) |
| 6-8 GB | Qwen3.5 4B/9B, Llama 3.1 8B |
| 12 GB+ | Qwen3.5 9B holgado, 12B-14B |

Con **menos VRAM que el modelo**, el reparto 70/30 GPU/CPU da 10-15 tok/s (frente a 3-6 en
CPU puro). Y una **configuración 100 % offline** (los tres roles en local) pide **~16 GB de RAM**
para ir bien.

## 5. Red

Con proveedores en la nube cada acción es **una petición pequeña** (~1-3 KB de ida, 100-300
tokens de vuelta): ancho de banda irrelevante, la **latencia** es lo que se nota. Lo único
que consume ancho de banda de verdad es el vídeo del sandbox Neko.

## 6. Resumen por perfil

| Perfil | Hardware | Qué obtienes |
| --- | --- | --- |
| **Portátil modesto** (4-8 GB RAM, sin GPU) | nada extra | agente completo con Groq/NVIDIA gratis (hardware: solo tu Firefox + 40 MB) |
| **PC de 8 GB** | + Laya (+1 GB RAM) | decisiones locales, más rápido y sin depender de la nube para enrutar |
| **PC de 8-16 GB** | + Ollama con Qwen3.5 4B | ejecutor local; puede combinarse con planner en la nube |
| **Con GPU 6-8 GB** | + modelos 4B-8B en VRAM | todo local y a 40+ tok/s |
| **16 GB+ / GPU 12 GB** | + Neko + 9B local | modo 100 % offline **y** navegador aislado |

## 7. Evidencia de que el host es ligero

Toda la batería del proyecto (367 pruebas, la "Laya check" con pesos reales, la batería de
routing de 241 misiones) corre en los **runners estándar de GitHub Actions: 2 núcleos, 7 GB
de RAM, sin GPU**. Es el mismo entorno donde hoy pasaron las pruebas reales contra Groq y
NVIDIA. Si el host pidiera hardware, no cabría ahí.
