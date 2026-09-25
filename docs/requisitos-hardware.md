# Requisitos de hardware

La pregunta correcta no es «cuánto pide el programa» sino **qué modo usas**, porque el
programa en sí es minúsculo: el trabajo pesado lo hacen los proveedores en la nube. Hay
cuatro cosas que sí consumen, y solo una es obligatoria:

| # | Qué consume | ¿Obligatorio? | Cuánto |
| --- | --- | --- | --- |
| 1 | **El navegador** (Firefox con la extensión) | Sí | el navegador que ya tienes abierto |
| 2 | **El host del agente** (Python) | Sí | **38,6 MB de RAM** · ~2 % de un núcleo |
| 3 | **Laya** (motor de decisión local) | No | ~1 GB RAM + ~1,2 GB disco |
| 4 | **Sandbox Neko** (navegador aislado en Docker) | No | ~2 GB disco + ~1-2 GB RAM del contenedor |
| 5 | ~~Modelos locales~~ | **No existen** | retirados en sept 2026: ver §4 |
| 6 | **Tarjeta gráfica** | No, nunca | solo acelera modelos locales y Laya |

## La medición del host, hecha aquí mismo

No es una estimación: se ejecutó la aplicación completa (clon de `main`) y se midió el proceso
mientras hacía el circuito entero (catálogo real + sonda en vivo + 3 llamadas por rol):

```
ENTORNO DE MEDICIÓN (peor que cualquier PC real): contenedor de 2 núcleos y 2 GB de RAM, sin GPU

Host del agente (jev-firefox)   RAM: 38,6 MB constante   ·   CPU pico: 2,2 % de un núcleo
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

Números del propio proyecto (`docs/laya.md`), medidos con pesos reales en la
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

## 4. ¿Y modelos locales en mi PC? No: no se soportan

Los runtimes locales (Ollama, LM Studio, llama.cpp, Jan) se retiraron en septiembre de 2026. El
motivo es de producto: el agente conduce una página web viva, así que **necesita internet de todas
formas** — un modelo en casa no habilitaba ningún caso de uso real y a cambio añadía instalación,
GB de disco y 3-8 s por paso (frente a ~280 ms de la nube gratis).

Lo único que se ejecuta en tu equipo, y **opcional**, es **Laya** (§2). Cualquier endpoint
OpenAI-compatible sigue siendo alcanzable por URL, si algún día montas un gateway propio.

## 5. Red

Con proveedores en la nube cada acción es **una petición pequeña** (~1-3 KB de ida, 100-300
tokens de vuelta): ancho de banda irrelevante, la **latencia** es lo que se nota. Lo único
que consume ancho de banda de verdad es el vídeo del sandbox Neko.

## 6. Resumen por perfil

**Regla general: si tienes internet, la vía recomendada es la nube gratis (Groq + NVIDIA NIM)
y no necesitas ninguno de los extras de esta tabla.** Los modelos locales son para quien quiera
cero claves, funcionar sin internet o que su misión no salga de su PC (y en un PC sin gráfica
cuestan 3-8 s por paso, frente a ~280 ms en la nube).

| Perfil | Hardware | Qué obtienes |
| --- | --- | --- |
| **PC normal, con internet** (4-8 GB RAM, sin GPU) ← *el caso típico* | **nada extra** | agente completo con Groq + NVIDIA NIM gratis: solo tu Firefox + ~40 MB de host |
| **Solo quieres una clave** (NVIDIA NIM para todo) | **nada extra** | lo mismo, con menos latencia que NVIDIA por llamada que Groq |
| Quieres decisiones internas sin nube (opcional) | + Laya (+1 GB RAM) | enrutado de misiones local; sin clave y en cualquier idioma |
| Quieres aislar el navegador (opcional) | + Docker y la imagen Neko (§3) | el agente navega en un navegador aparte, sin tus cookies |

## 7. Evidencia de que el host es ligero

Toda la batería del proyecto (367 pruebas, la "Laya check" con pesos reales, la batería de
routing de 241 misiones) corre en los **runners estándar de GitHub Actions: 2 núcleos, 7 GB
de RAM, sin GPU**. Es el mismo entorno donde hoy pasaron las pruebas reales contra Groq y
NVIDIA. Si el host pidiera hardware, no cabría ahí.
