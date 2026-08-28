# Reemplazo del motor de torneos/fixtures y de la vocalía por la versión de gestion_futbol

## Contexto

Al inicio de esta conversación el usuario pidió explícitamente NO tocar la
lógica de organización de torneos (brackets/fixtures) porque "se va a
reemplazar". Ese reemplazo es este sub-proyecto: el usuario confirmó
explícitamente que quiere que la programación de torneos, los fixtures y,
sobre todo, la pantalla de vocalía sean **la misma** que las de
`gestion_futbol`, usando ese proyecto como base de funcionalidades y diseño
de aquí en adelante.

Diferencia clave entre los dos proyectos: comparten origen (mismos nombres de
función), pero `gestion_futbol` es de un solo negocio (sin `ComplejoDeportivo`)
y `Organizador-de-Torneos-por-alquiler` ya tiene todo el aislamiento
multi-tenant corregido en el sub-proyecto 1 de esta misma sesión (16 tests que
no se deben romper). El riesgo central de este trabajo es **reintroducir
fugas entre canchas** al traer lógica que en su origen nunca tuvo el concepto
de "cancha".

## Alcance

**Se reemplaza (vista + plantilla), adaptando cada una para que seguir
filtrando por `complejo`:**

- Vocalía: `gestionar_vocalia`, `registrar_incidencia`, `eliminar_evento`,
  `eliminar_evento_ultimo`, `eliminar_multa`, `toggle_asistencia`,
  `generar_acta_pdf`.
- Calendario: `programar_partidos`, `editar_partido`, `eliminar_partido`,
  `reiniciar_partido`, `registrar_resultado`, `proxima_jornada`.
- Fixtures y llaves: `generar_fixture`, `generar_fase2`,
  `generar_cuartos_directos`, `generar_semis_directas`,
  `generar_cuartos_final`, `generar_semifinales`, `generar_finales`,
  `llaves_eliminatorias`, `revertir_transicion`, `activar_vuelta_f1`,
  `cambiar_formato_fase1`.
- Reportes: `tabla_posiciones`, `tabla_posiciones_f2`, `tabla_goleadores`,
  `reporte_estadisticas`.

**Explícitamente fuera de alcance (sin cambios):** todo lo que no es
organización de torneos — landing, portal público, SaaS/planes,
autenticación, finanzas, galería, carnets, y todo lo del sub-proyecto 3
(caja diaria).

## Regla de oro (no negociable)

Para cada vista de la lista de arriba, el reemplazo NUNCA es un copy-paste
directo del código de `gestion_futbol`. El procedimiento es siempre:

1. Leer la versión de `gestion_futbol` como referencia de comportamiento y
   diseño.
2. Leer la versión actual (ya filtrada por `mi_complejo`/`torneo__complejo`).
3. Portar el comportamiento/diseño nuevo, pero conservando (o agregando
   donde falte) el filtro `complejo` que ya existe en la versión actual.
4. Si `gestion_futbol` agrega un objeto por id de POST/GET sin validar
   pertenencia (patrón que ya causó IDOR en el sub-proyecto 1), esa
   validación se agrega igual en la versión portada — no se copia el bug.

## Componentes

### 1. Vocalía (prioridad más alta, la pidió el usuario explícitamente)

- Plantilla `core/gestionar_vocalia.html`: se reemplaza por una versión
  basada en el HTML/CSS/JS de `gestion_futbol/core/templates/core/gestionar_vocalia.html`
  (896 líneas), adaptada a la marca NEXUS y a los nombres de URL de este
  proyecto (`{% url %}` con los mismos nombres, ya coinciden).
- Vista `gestionar_vocalia`: diff línea por línea contra
  `gestion_futbol/core/views.py::gestionar_vocalia` (224 líneas) vs la actual
  (196 líneas). Cualquier campo/cálculo nuevo se agrega; todo query que en
  gestion_futbol no tiene `torneo__complejo=...`/`equipo__torneo__complejo=...`
  se le agrega antes de portar.
- `registrar_incidencia`, `toggle_asistencia`, `eliminar_evento`,
  `eliminar_evento_ultimo`, `eliminar_multa`: mismo procedimiento. Estas ya
  tienen fixes de aislamiento del sub-proyecto 1 (jugador debe pertenecer al
  partido, etc.) — esos fixes se preservan siempre.
- `generar_acta_pdf`: comparar `acta_partido_pdf.html` de ambos proyectos;
  portar diseño, mantener `verificar_acceso_partido`.

### 2. Calendario y resultados

- `programar_partidos` + `programar_partidos.html`: portar diseño/flujo de
  gestion_futbol; mantener el filtro `complejo_id__in=mis_canchas_ids` /
  `torneo__complejo=mi_complejo` que ya existe.
- `editar_partido`, `eliminar_partido`, `reiniciar_partido`,
  `registrar_resultado`, `proxima_jornada`: mismo procedimiento.

### 3. Fixtures y llaves eliminatorias

- `generar_fixture` + `generar_fixture.html`, `generar_fase2`,
  `generar_cuartos_directos`, `generar_semis_directas`,
  `generar_cuartos_final`, `generar_semifinales`, `generar_finales`,
  `llaves_eliminatorias` + `llaves_eliminatorias.html`,
  `revertir_transicion`, `activar_vuelta_f1`, `cambiar_formato_fase1`.
- Todas ya reciben `torneo = get_object_or_404(Torneo, id=torneo_id, complejo=mi_complejo)`
  al inicio en la versión actual — se preserva en cada una.

### 4. Reportes

- `tabla_posiciones`, `tabla_posiciones_f2`, `tabla_goleadores`,
  `reporte_estadisticas` + sus plantillas. Son de solo lectura y ya son
  públicas por diseño (sin `@login_required` en algunas) — se mantiene así,
  solo cambia el diseño visual.

## Testing

- Antes de tocar cada vista, correr la suite actual (`python manage.py test core`,
  21 tests) para tener una línea base en verde.
- Para las vistas de vocalía y calendario (las que ya tienen tests de
  aislamiento del sub-proyecto 1: `GestionarVocaliaTest`,
  `EliminarMultaTest`, etc.) esos tests **no se pueden romper** — son la red
  de seguridad contra reintroducir IDOR al portar código de un proyecto
  single-tenant.
- Para las piezas nuevas que se porten (ej. algún cálculo de vocalía que hoy
  no existe), se añade un test de aislamiento nuevo con el mismo patrón
  `DosCanchasTestCase` antes de portar el código (TDD).
- Para fixtures/brackets (lógica puramente algorítmica, sin filas de otro
  tenant involucradas en el cálculo en sí), el riesgo de fuga está solo en el
  `get_object_or_404(..., complejo=mi_complejo)` de entrada a la vista — se
  verifica con un test simple por vista: usuario de la Cancha B no puede
  generar/ver fixtures del torneo de la Cancha A.
- Verificación visual: levantar el servidor de desarrollo y revisar en
  navegador cada pantalla reemplazada con los datos de `seed_demo`.

## Orden de ejecución

1. Vocalía completa (vista + plantilla + eventos + acta PDF) — es lo que el
   usuario pidió primero y de forma más explícita.
2. Calendario y resultados.
3. Fixtures y llaves eliminatorias.
4. Reportes.

Cada bloque se implementa, se prueba y se deja funcionando antes de pasar al
siguiente — así el trabajo es útil aunque la sesión se corte antes de llegar
al final de la lista.
