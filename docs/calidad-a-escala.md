# Calidad a escala (v0.4.0)

La 0.2.0 demostró que la arquitectura funciona; la 0.3.0 puso seguridad, trazas y
límites. La 0.4.0 responde a la única pregunta que faltaba: **¿sigue siendo cierto a
escala, medido con recursos reales y en cada PR?**

Tres piezas, cada una con su workflow:

| Pieza | Qué mide | Dónde corre |
|---|---|---|
| `scripts/bench_routing.py` + `scripts/routing_cases.py` | Routing: Laya crudo vs el stack real, y **confusión peligrosa** | `Routing battery` (pesos reales de Laya) |
| `scripts/bench_providers.py` | Latencia y tokens por rol y **por operación real** (route/choose/plan/text) | Local o Actions con los secretos |
| `scripts/e2e_flights.py` | La misión completa sobre Google Flights real, con verificación de página | `E2E flights` (Chrome + proveedores reales) |

## 1. La batería de routing: 241 misiones etiquetadas

```
python scripts/bench_routing.py            # con pesos reales de Laya
python scripts/bench_routing.py --selftest # offline: solo la capa de keywords
python scripts/bench_routing.py --sample 24 --json artifacts/routing.json
```

Composición: **6 idiomas × 36 misiones core** (18 de navegador + 18 de herramientas,
la misma carga en cada idioma) **+ 25 adversariales** = 241. Los adversariales son
las formas que la gente escribe de verdad: intención mixta, multi-frase, bilingües,
telegráficas y con erratas.

### La etiqueta es la verdad del producto, no un gusto

- **`browser`** — la misión se termina interactuando con la página actual (clic,
  teclear, seleccionar, desplazar, navegar ese sitio, leer lo que muestra).
- **`orchestrated`** — necesita al menos una capacidad que el bucle de navegador no
  tiene: buscar en la web, abrir otros sitios, descargar un archivo, leer o crear un
  documento (PDF/DOCX/XLSX/CSV) o ejecutar comandos y código.

Las misiones mixtas van en la dirección segura: si **alguna** parte necesita
herramientas, la etiqueta es `orchestrated`. La métrica titular es la **confusión
peligrosa**: una misión de herramientas enviada al bucle de navegador, que no puede
autorrecuperarse. El error contrario (página enviada al bucle de herramientas) es más
lento pero **termina**, y se cuenta aparte como *sobre-enrutado seguro*.

Escalar a 500 casos no requiere tocar Python: `--cases extra.jsonl` añade misiones
etiquetadas (`{"lang": "de", "mission": "...", "expected": "orchestrated"}`).

## 2. Lo que cambió la 0.4.0 (medido, no opinado)

Dos capas de keywords medidas sobre la misma batería, a través del `route_task` real:

| Capa | Acierto | Confusión peligrosa | Sobre-enrutado | p50/p95 |
|---|---|---|---|---|
| 0.3.0: ES/EN, 34 keywords, regla de subcadena | 77% (186/241) | **54** | 1 | 0.01/0.01 ms |
| 0.4.0: 6 idiomas, 129 keywords, regla de inicio de palabra | **100% (241/241)** | **0** | **0** | 0.11/0.21 ms |

*(medido offline, sin pesos: es exactamente lo que decide cuando Laya se abstiene;
el workflow `Routing battery` añade la columna de Laya crudo con los pesos reales.)*

Dos defectos reales que la batería encontró y que ya no existen:

1. **El hueco de idiomas.** El fallback solo cubría ES/EN, así que en DE/FR/IT/PT toda
   abstención de Laya acababa en el bucle de navegador: 54 misiones de herramientas
   mal enrutadas. La lista ahora cubre los seis idiomas.
2. **La subcadena.** `inscription` contiene `script` e `iscrivimi` contiene `scrivi`,
   así que un formulario normal se enviaba al bucle de herramientas. La coincidencia
   ahora se ancla al inicio de palabra, y el `*` final marca prefijos explícitos
   (`descarg*` → descarga/descargar) sin dejar entrar compuestos (`profile` no es
   `file`).

La regla antigua se conserva como `orchestrator.legacy_keyword_match` **solo para que
el benchmark pueda medir el antes y el después**, nunca en el camino de ejecución.

### Por qué Laya sigue importando

Laya no decide sola: decide **por encima de la puerta de confianza 0.75**, y en el
duelo medido (24 casos, pesos reales) todas sus decisiones ≥0.75 fueron correctas,
mientras que Laya crudo acierta ~42%. La puerta es lo que convierte un motor abierto
rápido y local en algo que se puede dejar delante de un usuario: cuando duda, el
router multilingüe responde, y ahora responde bien en seis idiomas.

## 3. Bench de proveedores por operación real

```
python scripts/bench_providers.py --samples 3
python scripts/bench_providers.py --operations choose,route --prices prices.json
```

Mide las **operaciones del producto** por sus rutas de código reales, no un ping:
`route` (política: navegador vs herramientas), `choose` (la ruta caliente: elegir la
siguiente acción), `plan` (planner: descomponer la misión) y `text` (escribir el valor
de un campo). Para cada una: min/p50/p95/max, tokens de entrada y salida facturados, y
opcionalmente **coste proyectado por 1.000 llamadas**.

El coste solo se imprime si aportas precios (`--prices prices.json`, USD por millón de
tokens); un precio inventado es peor que ningún precio.

```json
{"groq:openai/gpt-oss-20b": {"input": 0.15, "output": 0.75}}
```

## 4. E2E real: vuelos Zúrich → Londres

```
python scripts/e2e_flights.py --selftest                  # offline, 18 comprobaciones
xvfb-run -a python scripts/e2e_flights.py --max-seconds 600
```

La misión del demo (solo ida, Zúrich–Londres, 20 de septiembre de 2026, un adulto,
economía; nunca selecciona ni reserva) sobre Google Flights real, con cinco decisiones
de diseño que importan en un runner:

- **Pacing**: cada llamada al modelo se separa `--pacing` segundos (2.4 por defecto)
  parcheando `model.post_json`/`model.post_stream`, la única costura HTTP del producto,
  así que ningún camino de llamada nuevo puede saltarse el espaciado.
- **Presupuesto de tokens**: el primer run real murió con `HTTP 429 … TPM: Limit 8000`.
  El tier gratuito rechaza por **tokens**, no por peticiones, así que cada llamada
  reserva su coste estimado en una ventana deslizante (`--tpm 6000`, `--window 60`) y
  se corrige con el `usage` real que devuelve el proveedor; una respuesta limitada se
  reintenta esperando lo que el proveedor pide («try again in 4.5s»). El workflow
  ejecuta una sola misión por commit (`concurrency` por PR/rama) porque todo comparte
  el mismo presupuesto.
- **Página lista antes de decidir**: un Chrome frío navega y la primera observación
  puede pillar Google Flights sin renderizar; el modelo ve una página vacía, contesta
  `BLOCKED` y la misión muere en 1.8 s (pasó en CI). El driver espera a que el
  formulario esté en pantalla y descarta el muro de cookies con el propio
  `Browser.act`; si aun así una corrida termina sin ejecutar ninguna acción, se
  reintenta una vez con el presupuesto que quede y el informe dice cuántos intentos hubo.
- **Verificación**: el veredicto sale de `examples.flights.verify`, **siete
  comprobaciones sobre la página final** (página de búsqueda, solo ida, origen,
  destino, fecha, año, resultados que coinciden), nunca del `DONE` del modelo.
- **Veredictos honestos**: `passed`; `site_blocked` (muro de consentimiento, CAPTCHA o
  host inesperado: es infraestructura, avisa y sale 0); o `failed` (el agente corrió y
  la página no cumple las comprobaciones: sale 1). Un fallo nunca se disfraza de verde.

## 5. Los workflows

| Workflow | Recurso real | Qué publica |
|---|---|---|
| `Routing battery` | pesos abiertos de Laya (caché de HF) + Groq para la muestra | tabla por idioma, confusión peligrosa, antes/después de la capa de keywords |
| `E2E flights` | Chrome headless + CDP + Groq/NVIDIA + Google Flights | las 7 comprobaciones, warm-up, presupuesto de tokens por modelo, reintentos, URL final, artefactos |
| `Provider check`, `Laya check`, `Executor duel` (0.2.0/0.3.0) | claves reales del repo | ya existían; ahora comentan en **el PR de la rama**, no en el PR #1 |

Los cuatro workflows que comentan usan `scripts/comment_on_pr.sh`, que resuelve el PR
del evento (`pull_request`) o por rama (`push`) y nunca tumba el job por un comentario.

Puertas reales, no decorativas: la batería falla por debajo del 85% de acierto o por
más de 5 confusiones peligrosas; el E2E falla si la misión corrió y no verificó.

## 6. Resultados medidos (23 de septiembre de 2026, CI con recursos reales)

| Medición | Resultado |
|---|---|
| Batería de routing, pesos reales de Laya | **241/241 (100 %)** efectivo · **0** confusiones peligrosas · 0 sobre-enrutado |
| Laya crudo (pesos solos, sin puerta ni keywords) | **140/241 (58 %)** de las misiones decididas |
| Capa de keywords, medida con el mismo `route_task` | 0.3.0: 77 % y **54** peligrosas · 0.4.0: 100 % y **0** |
| Latencia de decisión | Laya p50/p95 190/206 ms · stack 0/198 ms |
| Cross-check del modelo de política (muestra de 23) | 20/23 (87 %) |
| Provider check (roles reales) | planner y policy 🟢 · text 🟢 tras corregir el presupuesto de tokens |
| **E2E de vuelos en vivo** | **✅ passed — 7/7 comprobaciones**, 369 s, 16 llamadas al modelo, 9 acciones, resultados reales (easyJet 78 USD ZRH→LTN) |

El E2E no se conforma con que el modelo diga `DONE`: el veredicto sale de la página
final. Ese primer verde costó siete correcciones reales que solo aparecen con recursos
de verdad: la fecha del demo había caducado, el daemon de Chrome no arranca en un runner
limpio, `| tee` escondía el código de salida, el ritmo reventaba el cupo de tokens, el
*helper* de texto devolvía `null`, el presupuesto se contaba por host y no por modelo, y
el agente repetía un `fill` sobre un campo que ya tenía el valor en lugar de pulsar la
sugerencia que lo confirma (esa última recuperación es ahora parte del agente).

## 7. Límites conocidos

- Laya crudo ~42%: el routing depende de la puerta + el router multilingüe. El
  backlog #1 (router híbrido: el modelo de política cuando hay red, Laya offline) es
  el siguiente salto natural.
- Los E2E contra terceros son frágiles por naturaleza: por eso la clasificación
  distingue «el sitio nos bloqueó» y «el proveedor se cayó» (infraestructura, avisa y
  sale 0) de «nuestra misión falló» (sale 1).
- Los tiers gratuitos se agotan **por modelo y por día** (`TPD: Limit 200000`, medido):
  una misión completa consume alrededor de medio cupo, así que los reintentos del E2E
  hay que racionarlos o subir de tier.
- La batería mide routing y verificación de página, no *task completion* completo:
  métricas de completion, reintentos y coste por tarea siguen en el backlog.
- Los 241 casos son el suelo, no el techo: el formato JSONL permite llegar a 500 sin
  tocar código.
