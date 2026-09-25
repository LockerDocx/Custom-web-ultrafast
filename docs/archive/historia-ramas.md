# Historia de ramas: dónde acabó cada línea de trabajo

`main` es la única rama de la aplicación. Todo lo construido en las distintas
sesiones (y por distintos agentes) vive aquí; las ramas que siguen existiendo en
el remoto son **puntos de partida ya contenidos en `main`**, no trabajo paralelo
pendiente.

| Rama | Estado | Contenido |
| --- | --- | --- |
| `main` | **la app** | MVP-0 → MVP-6 (ver `docs/evaluacion-a-produccion.md`) |
| `mvp1-per-model-parameters` | contenida en `main` (merge `36a540f`) | motor de parámetros por modelo: `jev_ultrafast/schemas.py`, registro v2, sonda en vivo, evidencia en `artifacts/model-runtime.json` |
| `arena/01a0ce34-…` | contenida en `main` | `feat(check)`: una cuota agotada es un estado propio, no un modelo roto |
| `arena/01a0c8b2-…` | contenida en `main` | trabajo anterior de provider-check / defaults documentados |
| `arena/01a0c8af-…` (`082d25f`) | **no fusionada, por diseño** | prototipo temprano de la extensión (`firefox-extension/`, popup) y primera versión de `jev_ultrafast/providers.py` |

## Por qué `082d25f` no está en `main`

No se dejó fuera por falta de tiempo: es una implementación **anterior y
superada** del mismo producto, con otra forma.

- Su extensión (`firefox-extension/`) nunca llegó a `main`: la extensión real,
  con barra lateral, se construyó y evolucionó después en `extension/`. El
  código de `082d25f` fue su punto de partida (snapshot.js 259 líneas frente a
  las 112 de aquella versión, popup en lugar de sidebar).
- Los cambios de `jev_ultrafast/` que aporta (providers.py, model.py, agent.py,
  demo.py) fueron la primera versión de módulos que hoy existen, más completos y
  con tests, en `main`.
- Fusionarla introduciría un segundo árbol de extensión duplicado y sin
  mantenimiento, además de revertir ficheros que ya evolucionaron.

Se conserva íntegra en el remoto como referencia histórica. Si alguna vez hace
falta una parte concreta, se puede consultar ahí o con
`git show 082d25f:<ruta>`.
