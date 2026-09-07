# Sistema de Pruebas (Rol de Prueba / entorno demo aislado)

## Contexto

`nexus-app` ya es un SaaS multi-tenant real: cada `ComplejoDeportivo` (cancha)
tiene su propio dueño (`organizador`, `OneToOneField` a `User`), su propio
plan, y todos los datos deportivos (`Torneo`, `Equipo`, `Jugador`, `Partido`,
`Sancion`, etc.) cuelgan de esa cancha por FK, directa o transitivamente.
Casi todas las vistas del sistema ya resuelven "mi cancha" a través de
`obtener_mi_complejo(request.user)` / `es_organizador` / `obtener_rol_principal`
(definidas en `core/views.py`), que priorizan `ComplejoDeportivo.organizador`
y caen a `RolComplejo` como respaldo. `request.user.is_superuser` ya es, en
la práctica, el "Super Administrador": tiene su propio panel (`dashboard_saas`,
bajo `/nexus-admin/`) separado de la experiencia normal de un organizador.

El usuario (dueño del sistema, Super Admin) quiere poder darle a cualquier
usuario un "Rol de Prueba": un entorno de demostración con datos precargados
(6 equipos, 6 jugadores por equipo, partidos jugados y futuros, tarjetas,
estadísticas) donde puede operar casi como un organizador real, sin que sus
cambios afecten jamás los datos reales del sistema ni los de otros usuarios
de prueba. Al quitarle el rol, todo lo que hizo se descarta; si se lo vuelve
a dar, empieza de cero.

## Decisiones ya acordadas con el usuario

1. **Snapshot al asignar, no sincronización en vivo.** Cada entorno de
   prueba es una copia independiente generada en el momento en que se
   asigna (o reasigna) el Rol de Prueba. No hay overlay/fusión en tiempo
   real entre datos reales y datos de prueba. El contenido de la
   "plantilla demo" vive en código (una función de siembra), así que
   mejoras futuras a esa plantilla se reflejan automáticamente en cada
   nueva asignación — no en entornos ya activos.
2. **El Rol de Prueba solo se puede asignar a usuarios que HOY NO sean ya
   dueños (`organizador`) de una cancha real.** Esto permite implementar
   el aislamiento reutilizando `ComplejoDeportivo.organizador` tal cual,
   sin tocar ninguna función central de permisos. Si el Super Admin
   intenta asignarlo a un dueño real, el sistema lo bloquea con un
   mensaje explicando por qué.
3. **La vista "Dirigente de Equipo" del entorno de prueba se implementa
   con vistas y plantillas nuevas e independientes**, no reutilizando ni
   modificando las vistas reales de Dirigente (`mis_finanzas_equipo`, la
   rama `DIR` de `gestionar_jugadores`, etc.). Cero riesgo para la
   experiencia real de un Dirigente.

## Alcance

**Incluye:**
- Modelo: dos campos nuevos en `ComplejoDeportivo` (`es_demo`,
  `fecha_asignacion_prueba`). Ninguna tabla nueva.
- Panel del Super Admin (`/nexus-admin/pruebas/`) para asignar/quitar el
  Rol de Prueba a un usuario.
- Función de siembra que genera un entorno demo completo: 1 Torneo,
  6 Equipos, 6 Jugadores por equipo, partidos jugados (con goles y
  tarjetas) y partidos futuros programados, con las multas (`Sancion`)
  y contadores de jugador que la lógica real generaría, para que las
  pantallas de estadísticas, finanzas y vocalía se vean consistentes.
- Borrado en cascada del entorno al quitar el rol (usa el `CASCADE` que
  ya existe en las FKs — no requiere lógica de limpieza nueva).
- Sección nueva "Dirigente de Equipo" (solo dentro de un entorno demo):
  elegir uno de los 6 equipos y ver/editar lo que un Dirigente real
  vería para ese equipo.
- Banner "Estás en un entorno de PRUEBA" visible en todo el sitio
  cuando el usuario logueado es dueño de una cancha `es_demo=True`.
- Un ajuste mínimo y aditivo a `dashboard_saas` (la vista real de
  Control SaaS del Super Admin): excluir `es_demo=True` de la lista de
  canchas / contabilidad, para que los entornos de prueba no ensucien
  las cifras reales del negocio.

**Explícitamente fuera de alcance:**
- Sincronización en vivo entre datos reales y entornos de prueba activos.
- Permitir el Rol de Prueba a usuarios que ya son dueños reales de una
  cancha (ver decisión #2).
- Editar la plantilla demo desde la UI (por ahora vive en código; ver
  "Extensiones futuras").
- Cualquier cambio a las vistas/plantillas reales de Dirigente, Vocal u
  Organizador — el sistema de permisos existente no se toca.
- Corregir el bug preexistente de `Configuracion.objects.first()` en el
  context processor (no está scopeado por cancha) — no forma parte de
  este trabajo.

## Decisión de estructura

No se crea ninguna app Django nueva. Todo vive en `core`, junto al resto
del dominio del que depende directamente (`ComplejoDeportivo`, `Torneo`,
`Equipo`, `Jugador`, `Partido`). La función de siembra vive en un módulo
nuevo, `core/services/pruebas.py`, separada de `views.py` porque es lógica
de negocio reutilizable (se llama tanto al asignar como al reasignar) y no
una vista.

## Componentes

### 1. Modelo (migración aditiva)

En `ComplejoDeportivo`:
- `es_demo = models.BooleanField(default=False, verbose_name="Es entorno de prueba")`
- `fecha_asignacion_prueba = models.DateTimeField(null=True, blank=True)`

Ambos con default seguro; migración no afecta ninguna fila existente.

Se reutiliza el `PlanSuscripcion` existente para las canchas demo, pero se
crea (una sola vez, `get_or_create`) un plan dedicado **"Plan Demo (Prueba)"**
con límites generosos (`max_torneos=5`, `max_categorias_por_torneo=5`,
`max_jugadores=100`). Es necesario: `limite_jugadores_alcanzado()` calcula
el límite como `complejo.plan.max_jugadores if complejo.plan else 1` — sin
un plan con límite alto, el propio usuario de prueba se vería bloqueado
para agregar jugadores nuevos casi de inmediato.

### 2. Función de siembra (`core/services/pruebas.py`)

`crear_entorno_prueba(usuario) -> ComplejoDeportivo`:
1. Crea `ComplejoDeportivo` (`organizador=usuario`, `es_demo=True`,
   `activo=True`, `fecha_vencimiento=None` — nunca vence,
   `plan=<Plan Demo>`, `nombre`/`slug` derivados del username y únicos).
2. Crea `RolComplejo(usuario, complejo, rol='ORG')` — mismo patrón que
   usa hoy `gestionar_canchas_saas` al registrar una cancha real.
3. Crea una `Categoria` y un `Torneo` demo dentro de esa cancha.
4. Crea 6 `Equipo` (dirigente=usuario, `estado_inscripcion='APROBADO'`,
   `pagado=True`, `cupos_pagados` suficiente).
5. Crea 6 `Jugador` por equipo (36 en total) con nombres y cédulas
   sintéticas únicas (se insertan por ORM directo, sin pasar por
   `full_clean()`, así que no necesitan satisfacer el checksum de cédula
   ecuatoriana — igual que cualquier otro dato de fixture).
6. Crea partidos ya jugados (`estado='JUG'`, resultado, algunos `DetallePartido`
   de gol/asistencia/tarjeta) y partidos futuros (`estado='PROG'`,
   `fecha_hora` futura, sin resultado).
7. Para cada tarjeta amarilla/roja sembrada, crea también el `Sancion`
   correspondiente (usando `torneo.costo_amarilla`/`costo_roja`, igual
   que la lógica real de vocalía) y actualiza
   `jugador.rojas_directas_acumuladas` cuando aplica — así las pantallas
   de finanzas, sanciones y estadísticas del entorno demo son
   internamente consistentes, no solo partidos con cartelitos sueltos.
8. Guarda `fecha_asignacion_prueba = timezone.now()` en el complejo.

`eliminar_entorno_prueba(usuario)`:
- Busca `ComplejoDeportivo.objects.get(organizador=usuario, es_demo=True)`
  y lo borra. El `CASCADE` ya declarado en el modelo (`Torneo`, `Equipo`,
  `Jugador`, `Partido`, `Sancion`, `DetallePartido`, `Pago`, `AbonoSancion`,
  `Configuracion`, `Categoria`, `FotoGaleria`, `Cupon` — todos cuelgan de
  `ComplejoDeportivo` o de algo que cuelga de él) se encarga de borrar
  absolutamente todo lo que el usuario haya creado o modificado durante
  la prueba. También borra el `RolComplejo` asociado (cascade).
- Si el usuario no tiene un complejo `es_demo=True`, no hace nada (idempotente).

### 3. Panel del Super Admin

Vista nueva `gestionar_roles_prueba(request)` en `core/views.py`,
`@login_required @user_passes_test(lambda u: u.is_superuser)`, URL
`/nexus-admin/pruebas/` (`name='gestionar_roles_prueba'`).

- Lista `User.objects.exclude(is_superuser=True)`, mostrando para cada uno:
  si ya tiene Rol de Prueba (`es_demo=True`), o si es dueño de una cancha
  real (`organizador` de una cancha con `es_demo=False`) — en cuyo caso el
  botón de asignar aparece deshabilitado con un texto explicando por qué.
- Botón **Asignar**: llama `crear_entorno_prueba(usuario)`, mensaje de éxito.
- Botón **Quitar**: pide confirmación (acción destructiva — borra datos),
  llama `eliminar_entorno_prueba(usuario)`, mensaje de éxito.
- Enlace nuevo "Roles de Prueba" en el nav del Super Admin en `base.html`
  (junto a "Control SaaS" y "Planes").
- Template nuevo `core/templates/core/gestionar_roles_prueba.html`,
  extiende `core/base.html`, reutiliza los estilos de tabla ya usados en
  `saas_gestionar_canchas.html`.

**Ajuste aditivo a `dashboard_saas`** (única vista existente que se toca):
su queryset base `ComplejoDeportivo.objects.select_related(...).all()`
pasa a `...filter(es_demo=False)`, para que canchas demo no aparezcan en
la lista paginada del Control SaaS ni en `total_ingresos`/`canchas_activas`/
`canchas_por_vencer`/`canchas_vencidas`. Es un filtro adicional, no cambia
ningún comportamiento para canchas reales.

### 4. Sección "Dirigente de Equipo" (dentro del entorno de prueba)

Solo accesible por un usuario cuyo `obtener_mi_complejo(request.user)`
tenga `es_demo=True` (guard nuevo, reutilizable:
`es_dueno_de_entorno_prueba(user)`).

- `GET /prueba/dirigente/` → `prueba_seleccionar_equipo(request)`: lista
  los 6 equipos de su cancha demo, elige uno.
- `GET /prueba/dirigente/<equipo_id>/` → `prueba_ver_como_dirigente(request, equipo_id)`:
  valida que `equipo.torneo.complejo == mi_complejo_demo` (evita que edite
  cualquier ID ajeno vía URL), y muestra plantilla propia
  (`core/templates/core/prueba_dirigente_equipo.html`) con: plantel,
  próximos partidos, historial de partidos jugados con resultado, tarjetas
  acumuladas por jugador, resumen de multas/deudas del equipo.
- Acciones de edición (agregar/editar jugador del equipo elegido) usan
  vistas nuevas y pequeñas que reutilizan `JugadorForm` ya existente en
  `core/forms.py` (el formulario en sí no se toca — se reutiliza tal cual,
  que es distinto a reutilizar las *vistas* de Dirigente), pero con su
  propio guard de "pertenece a mi cancha demo".
- Nada de esto toca `mis_finanzas_equipo`, la rama `DIR` de
  `gestionar_jugadores`, ni ninguna otra vista real de Dirigente.

### 5. Banner de entorno de prueba

Se añade `es_entorno_prueba` al contexto global (extensión pequeña y
aditiva del context processor `configuracion_global` en
`core/context_processors.py`, o uno nuevo si se prefiere no tocar el
existente — a decidir en el plan): `True` si
`ComplejoDeportivo.objects.filter(organizador=request.user, es_demo=True).exists()`.
`base.html` muestra una franja fija (ej. amarilla, "🧪 Estás en un entorno
de PRUEBA — nada de esto afecta datos reales") cuando esa bandera es `True`.

### 6. Seguridad / aislamiento

- La garantía de aislamiento **no es código nuevo**: es una consecuencia
  directa de que todas las vistas existentes (`gestionar_torneos`,
  `gestionar_equipos`, `gestionar_jugadores`, `programar_partidos`,
  `registrar_resultado`, `gestionar_vocalia`, `gestionar_finanzas`, etc.)
  ya filtran estrictamente por `obtener_mi_complejo(request.user)`. Un
  usuario de prueba, al ser `organizador` de su propia cancha demo, pasa
  por exactamente el mismo camino de código que un organizador real —
  nunca ve ni puede tocar otra cancha, real o demo de otro usuario.
- Único código de aislamiento genuinamente nuevo: los guards de la
  sección "Dirigente de Equipo" (punto 4), que deben validar pertenencia
  a la cancha demo del usuario logueado.
- Revocar el rol es un `DELETE` en cascada sobre una jerarquía de FKs que
  ya existía — no hay estado "fantasma" posible.

## Testing

- Tests unitarios para `crear_entorno_prueba` / `eliminar_entorno_prueba`:
  cascada borra todo, reasignar tras revocar genera datos frescos con IDs
  nuevos, un usuario que ya es `organizador` real no puede recibir el rol.
- Test de que las vistas normales (`gestionar_equipos`, `dashboard`, etc.)
  funcionan igual para un usuario de prueba que para uno real, y que
  jamás devuelven datos de otra cancha.
- Test de que `dashboard_saas` no cuenta canchas demo en sus totales.
- Test manual en navegador: asignar rol, operar como si fuera admin real,
  entrar a "Dirigente de Equipo", quitar el rol, verificar que no queda
  ni una fila en la base de datos asociada a esa cancha demo.

## Extensiones futuras (fuera de alcance ahora)

- Plantilla demo editable por el Super Admin desde la UI (en vez de
  vivir en código), clonando una cancha "plantilla" real en lugar de
  generar datos sintéticos.
- Permitir el Rol de Prueba a usuarios que ya son organizadores reales
  (requeriría dejar de depender de `ComplejoDeportivo.organizador` como
  único mecanismo de "mi cancha", tocando funciones centrales de permisos).
