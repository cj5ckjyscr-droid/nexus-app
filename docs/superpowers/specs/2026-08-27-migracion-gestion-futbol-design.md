# Migración de mejoras de gestion_futbol al módulo de gestión de torneos (multi-tenant)

## Contexto

`Organizador-de-Torneos-por-alquiler` es la versión SaaS multi-tenant (varias
`ComplejoDeportivo`, cada una con su propio dueño, plan y datos aislados) de
un sistema de gestión de torneos de fútbol. `gestion_futbol` es una versión
anterior, de un solo negocio (sin multi-tenancy), pero con un módulo de
gestión de torneo más completo y con mejor diseño visual: dashboard, mesa de
vocalía y finanzas más pulidos, y una vista de cierre de caja diaria que no
existe en el proyecto actual.

Este sub-proyecto es el 3° de 4 acordados con el usuario (orden: aislamiento
multi-tenant → límites de plan → branding → esta migración). Los sub-proyectos
1, 2 y 4 ya están implementados y probados.

## Alcance

**Incluye:**
- Cierre de caja diaria (nuevo): reporte de ingresos del día (inscripciones,
  multas, pagos directos) por cancha.
- Rediseño visual (solo plantillas, no lógica) de: dashboard, mesa de
  vocalía (incluyendo fila de jugador "mejorada"), y gestión de finanzas.

**Explícitamente fuera de alcance** (decisión del usuario):
- Alquiler/reserva de cancha por horas (`HorarioCancha`, `ReservaCancha`,
  carrito, checkout) — no se migra nada relacionado.
- Módulo de Publicidad (banners de auspiciantes).
- Cualquier adición nueva a la galería/multimedia (la actual ya quedó
  correctamente aislada por cancha en el sub-proyecto 1 y no se toca).
- Notificaciones automáticas por WhatsApp.
- El landing page (`landing_principal`) y el portal público por cancha
  (`portal_complejo`) — su diseño se queda exactamente como está.
- La lógica de organización de torneos en sí (brackets, fixtures, fases) —
  fuera de alcance de todo este trabajo desde el inicio de la conversación.

## Decisión de estructura

No se crea ninguna app Django nueva. La única pieza que hubiera justificado
una app separada (alquiler) quedó fuera de alcance. Todo el trabajo vive en
la app `core` existente, junto a `Torneo`/`Partido`/`Sancion`/`Equipo`, de
los que depende directamente.

## Componentes

### 1. Cierre de caja diaria (nuevo)

- Vista `cierre_diario_caja(request)` en `core/views.py`, decorada
  `@login_required @user_passes_test(es_organizador)`.
- Recibe `?fecha=YYYY-MM-DD` (default: hoy).
- Agrega, **filtrado siempre por `mi_complejo = obtener_mi_complejo(request.user)`**:
  - Abonos de inscripción del día (`AbonoSancion` cuya `sancion.descripcion`
    contiene "Inscripci", `sancion.torneo.complejo = mi_complejo`).
  - Inscripciones pagadas directamente ese día sin abono previo.
  - Multas cobradas el día (`AbonoSancion` que no sean de inscripción).
  - Pagos directos del día (`Pago` cuyo `equipo.torneo.complejo = mi_complejo`).
  - **Sin sección de alquiler de cancha** (a diferencia del original en
    `gestion_futbol`).
- Devuelve totales por categoría + total del día.
- URL nueva: `path('finanzas/caja-diaria/', views.cierre_diario_caja, name='cierre_diario_caja')`.
- Template nuevo `core/cierre_diario_caja.html`, extiende `core/base.html`
  (así hereda el footer "Desarrollado por Deyvi Rivera" y el resto del
  chrome del sitio).
- Enlace añadido desde `gestionar_finanzas.html` hacia la nueva página.

### 2. Rediseño visual (solo plantillas)

Los siguientes templates se reemplazan por versiones con el HTML/CSS de
`gestion_futbol` como base visual, adaptadas a la paleta/marca ya usada en
`Organizador-de-Torneos-por-alquiler` (no se copian colores/branding de
`gestion_futbol` tal cual):

- `core/dashboard.html`
- `core/gestionar_vocalia.html` (+ nuevo partial `core/_item_jugador_vocalia.html`
  para la fila de jugador, usando las anotaciones que la vista YA calcula:
  `goles_match`, `ta_match`, `tr_match`, `da_match`, `star_match`)
- `core/gestionar_finanzas.html`

**Regla dura: no se toca la lógica de las vistas `dashboard`, `gestionar_vocalia`
ni `gestionar_finanzas`** — ya están correctamente filtradas por `mi_complejo`
desde el sub-proyecto 1. Solo cambian los archivos de plantilla: qué contexto
consumen y cómo lo pintan, no qué contexto se calcula.

Cada plantilla debe seguir extendiendo `core/base.html` para conservar el
footer de atribución y la navegación existente.

## Testing

- **Cierre de caja diaria**: tests con `DosCanchasTestCase` (ya existe en
  `core/tests.py`) verificando que:
  - Los totales de la Cancha A solo incluyen pagos/abonos de la Cancha A.
  - Un pago o abono de la Cancha B no aparece ni suma en la caja de la Cancha A,
    aunque ocurra el mismo día.
  - El filtro por fecha funciona (un pago de otro día no aparece).
- **Rediseño visual**: no es verificable con tests automáticos de contenido
  visual. Se verifica levantando el servidor de desarrollo
  (`python manage.py runserver`) y revisando en navegador que dashboard,
  vocalía y finanzas rendericen sin errores con datos de prueba, para al
  menos un usuario ORG.

## Riesgos / notas

- `gestion_futbol` no es multi-tenant: cualquier query que se traiga de allí
  debe re-filtrarse por `complejo` explícitamente; no copiar consultas tal cual.
- El partial de vocalía mejorado depende de anotaciones ya presentes en la
  vista actual; si en el futuro cambian los nombres de esas anotaciones, el
  partial debe actualizarse junto con la vista.
