# Modo Dirigente Simulado y Reorganización de Navegación

## Contexto

El "Sistema de Pruebas" (`docs/superpowers/specs/2026-09-06-sistema-de-pruebas-design.md`)
ya le da a un usuario de prueba una cancha demo completa (`ComplejoDeportivo.es_demo=True`)
de la que es `organizador`, con 6 equipos de los que también es `dirigente`. La
implementación original (Tasks 9-10 de su plan) agregó una sección "Dirigente de
Equipo" con vistas y plantillas **nuevas y paralelas**
(`prueba_seleccionar_equipo`, `prueba_ver_como_dirigente`,
`prueba_agregar_jugador`) que solo *simulan* la experiencia de un Dirigente,
en vez de mostrar las pantallas reales que usa un Dirigente de verdad
(`gestionar_jugadores`, `mis_finanzas_equipo`, el `dashboard` en su rama
`DIR`). El usuario probó esa sección en el navegador y pidió explícitamente
que en vez de una réplica, se muestre el panel real del sistema.

Por qué la implementación original no reutilizó las vistas reales: el rol de
un usuario se resuelve con `obtener_rol_principal(user)` /
`Perfil.rol_principal`, que da prioridad absoluta a "soy dueño de una
cancha" (`ComplejoDeportivo.organizador`) sobre "soy dirigente de un
equipo". Como el usuario de prueba siempre es dueño de su propia cancha
demo, su rol resuelve siempre a `'ORG'`, nunca a `'DIR'` — así que visitar
directamente las URLs reales de Dirigente lo llevaría a la experiencia de
Organizador, no a la de Dirigente.

Aparte, al recorrer la UI en vivo el usuario notó que el panel desde donde
se accede a las distintas secciones del sistema está desorganizado: el
bloque "Gestor Administrativo" del dashboard es una fila plana de 10
íconos sin agrupar, la barra de navegación superior del Super Admin se ve
apretada, y el selector "Simular Dirigente de Equipo" mostraba tarjetas con
muy poco contraste/jerarquía visual.

## Decisiones ya acordadas con el usuario

1. **Extender las vistas reales de forma aditiva, en vez de mantener vistas
   paralelas.** Se agrega una noción de "equipo simulado" que, solo para un
   usuario dueño de una cancha demo, fuerza su rol efectivo a `'DIR'` en los
   puntos exactos donde hace falta. Fuera de una cancha demo, cero cambio de
   comportamiento.
2. **La selección de equipo se guarda en la sesión del navegador**, no se
   propaga por parámetro de URL en cada link. El usuario elige un equipo una
   vez y navega libremente por las pantallas reales de Dirigente hasta que
   sale del modo.
3. **Los datos de siembra deben tener nombres realistas**, no genéricos tipo
   "Equipo Demo 1" / "Jugador 3 - Equipo 2" / "Torneo Demo".
4. Se reorganizan tres superficies de navegación: el bloque "Gestor
   Administrativo" del dashboard, la barra de navegación superior (caso
   Super Admin), y el selector de equipo de la sección Dirigente de Equipo.

## Alcance

**Incluye:**
- Nueva función de servicio `obtener_equipo_simulado(request)` que lee
  `request.session['equipo_simulado_id']` y **revalida siempre** contra la
  base de datos (`dirigente=request.user`,
  `torneo__complejo__organizador=request.user`,
  `torneo__complejo__es_demo=True`) antes de confiar en ese valor.
- `dashboard()` y `gestionar_jugadores()`: si hay equipo simulado, tratan el
  rol efectivo como `'DIR'` (en vez de `'ORG'`) y usan ese equipo como
  equipo activo por defecto.
- El *context processor* `configuracion_global` gana una variable de
  contexto (`rol_nav_efectivo`) que vale `user.perfil.rol_principal` para
  cualquier usuario normal, y `'DIR'` para un usuario de prueba con un
  equipo simulado activo. `base.html` usa esta variable en vez de
  `user.perfil.rol_principal` directamente para decidir qué links de nav
  mostrar.
- `prueba_seleccionar_equipo` cambia de propósito: en vez de link a un
  mini-panel propio, cada equipo tiene un botón "Entrar como Dirigente" que
  activa el modo simulado para ese equipo (`POST`) y redirige al dashboard
  real.
- Nueva vista `prueba_salir_modo_dirigente` (`POST`) que limpia la sesión y
  redirige de vuelta al dashboard (como Organizador).
- El banner "🧪 modo prueba" (ya existente) gana un botón "Salir del modo
  Dirigente", visible solo mientras el modo está activo.
- Se **eliminan** `prueba_ver_como_dirigente`, `prueba_agregar_jugador`, sus
  URLs, y sus plantillas (`prueba_dirigente_equipo.html`,
  `prueba_agregar_jugador.html`) — dejan de hacer falta.
- Nombres realistas en `core/services/pruebas.py`: torneo, categoría, 6
  equipos y jugadores con nombres creíbles en vez de placeholders "Demo".
- Reorganización visual del bloque "Gestor Administrativo" en 3 grupos:
  Competición (Torneos, Equipos, Fixture, Jugadores), Fichajes y Cobros
  (Fichar, Finanzas, Caja Diaria), Cancha y Sistema (Ajustes, Medios,
  Usuarios).
- Reorganización de la barra de navegación superior del Super Admin: los 4
  links sueltos (Control SaaS, Canchas, Planes, Roles de Prueba) se agrupan
  en un dropdown "Panel SaaS".
- Rediseño visual del selector "Simular Dirigente de Equipo": nombre de
  equipo legible, cantidad de jugadores, botón de acción claro.

**Explícitamente fuera de alcance:**
- `mis_finanzas_equipo()` no se modifica — ya funciona para el usuario de
  prueba sin cambios, porque filtra solo por `dirigente=request.user`.
- Ningún cambio de comportamiento para usuarios reales (fuera de una cancha
  `es_demo=True`, `rol_nav_efectivo` y el rol efectivo en las vistas dan
  exactamente el mismo resultado que antes).
- No se unifica la duplicación preexistente entre `obtener_rol_principal()`
  (función en `views.py`) y `Perfil.rol_principal` (propiedad del modelo) —
  es una limpieza aparte, no bloquea este trabajo.
- No se reorganiza la barra de navegación de un Organizador real (hoy son
  solo 3-4 links: Panel, Equipos, Finanzas — no está "amontonada").
- No se cambia la plantilla demo para agregar más de 6 equipos ni más
  variedad de eventos — solo los nombres.

## Componentes

### 1. `obtener_equipo_simulado(request)` (nuevo, en `core/services/pruebas.py`)

```python
def obtener_equipo_simulado(request):
    equipo_id = request.session.get('equipo_simulado_id')
    if not equipo_id:
        return None
    return Equipo.objects.filter(
        id=equipo_id,
        dirigente=request.user,
        torneo__complejo__organizador=request.user,
        torneo__complejo__es_demo=True,
    ).select_related('torneo__complejo').first()
```

Revalida las 4 condiciones en cada llamada (nunca solo `dirigente=user`):
así, si el Super Admin le quita el Rol de Prueba a mitad de una sesión con
el navegador abierto, la siguiente request deja de encontrar el equipo y
el usuario vuelve a ver la experiencia de Organizador/normal sin acción
manual.

### 2. Vistas que integran el equipo simulado

- `dashboard()`: después de calcular `rol = obtener_rol_principal(request.user)`,
  agrega:
  ```python
  equipo_simulado = obtener_equipo_simulado(request)
  if equipo_simulado:
      rol = 'DIR'
  ```
  `mis_equipos` sigue siendo `Equipo.objects.filter(dirigente=request.user)`
  sin cambios (para un usuario de prueba, sus 6 equipos demo) — lo único
  que cambia es cuál se destaca por defecto:
  `ctx['mi_equipo'] = equipo_simulado or mis_equipos.first()`. Las deudas
  del widget siguen agregando todos los equipos del usuario, igual que hoy
  para cualquier Dirigente real con más de un equipo.
- `gestionar_jugadores()`: mismo patrón; además el valor por defecto de
  `equipo_id` (cuando no viene `?equipo=` en la URL) pasa a ser
  `equipo_simulado.id` en vez de "el primer equipo del usuario". El
  selector de equipo que ya trae esta vista (para un Dirigente real con
  más de un equipo) sigue funcionando tal cual — el usuario de prueba
  puede cambiar entre sus 6 equipos demo usando ese mismo control real.

### 3. `configuracion_global` (context processor) — `rol_nav_efectivo`

```python
def configuracion_global(request):
    config = Configuracion.objects.first()
    es_entorno_prueba = False
    rol_nav_efectivo = None
    if request.user.is_authenticated:
        es_entorno_prueba = ComplejoDeportivo.objects.filter(
            organizador=request.user, es_demo=True
        ).exists()
        rol_nav_efectivo = request.user.perfil.rol_principal
        if obtener_equipo_simulado(request):
            rol_nav_efectivo = 'DIR'
    return {
        'config_global': config,
        'es_entorno_prueba': es_entorno_prueba,
        'rol_nav_efectivo': rol_nav_efectivo,
    }
```

`base.html` cambia sus 2 condicionales de nav (`user.perfil.rol_principal
== 'ORG'` / `== 'DIR'`) para usar `rol_nav_efectivo` en su lugar. Para
cualquier usuario sin equipo simulado, `rol_nav_efectivo` es idéntico al
valor que ya devolvía `user.perfil.rol_principal` — cero cambio de
comportamiento fuera de este flujo.

`dashboard.html` mantiene sus condicionales existentes tal cual (ya reciben
`mi_rol_principal`/el rol calculado por la vista `dashboard()`, que ya
queda corregido por el punto 2).

### 4. Activar / salir del modo simulado

- `prueba_seleccionar_equipo` (ya existe, guard `es_dueno_de_entorno_prueba`):
  se rediseña la plantilla; cada tarjeta de equipo tiene un `<form
  method="post">` a una nueva URL `prueba_activar_dirigente/<equipo_id>/`.
- `prueba_activar_dirigente(request, equipo_id)` (nueva, `POST`, guard
  `es_dueno_de_entorno_prueba`): valida que el equipo pertenezca a la
  cancha demo del usuario, guarda `request.session['equipo_simulado_id'] =
  equipo.id`, y redirige a `dashboard`.
- `prueba_salir_modo_dirigente(request)` (nueva, `POST`, `@login_required`):
  hace `request.session.pop('equipo_simulado_id', None)` y redirige a
  `dashboard`. No necesita el guard de dueño de entorno de prueba —
  simplemente no hace nada si no había nada que limpiar (idempotente).
- Se eliminan `prueba_ver_como_dirigente`, `prueba_agregar_jugador`, sus
  entradas en `config/urls.py`, y sus plantillas.

### 5. Banner de modo prueba — botón de salida

En `base.html`, dentro del bloque `{% if es_entorno_prueba %}` existente, se
agrega (solo si `rol_nav_efectivo == 'DIR'`, es decir, si el modo está
activo) un botón "Salir del modo Dirigente" con un `<form method="post">` a
`prueba_salir_modo_dirigente`.

### 6. Nombres realistas en la siembra (`core/services/pruebas.py`)

- Torneo: `"Copa Apertura 2026"` (en vez de `"Torneo Demo"`).
- Categoría: `"Segunda Categoría"` (en vez de `"Categoría Demo"`).
- 6 equipos con nombres de liga barrial ecuatoriana: `"Deportivo Chillos"`,
  `"Atlético Valle"`, `"Real San Rafael"`, `"Juventud Amaguaña"`, `"Unión
  Sangolquí"`, `"Estrella del Valle"`.
- 36 jugadores con nombres y apellidos reales variados (lista fija de
  nombres/apellidos combinados de forma determinística para que los tests
  sigan siendo deterministas), en vez de `"Jugador N - Equipo M"`. Las
  cédulas sintéticas (`90########`) no cambian.

### 7. Reorganización visual (dashboard, nav, selector)

- **Dashboard — "Gestor Administrativo":** se agrupan los 10 `admin-btn`
  existentes en 3 `<div>` con encabezado y borde/tarjeta propios
  (Competición / Fichajes y Cobros / Cancha y Sistema), reutilizando la
  clase `.admin-btn` ya existente para cada ícono — solo cambia el
  contenedor/agrupación, no el mecanismo de cada botón individual.
- **Navegación superior (Super Admin):** los 4 `<li class="nav-item">`
  sueltos (Control SaaS, Canchas, Planes, Roles de Prueba) se reemplazan
  por un único `<li class="nav-item dropdown">` "Panel SaaS ▾" con esos 4
  como `dropdown-item`, siguiendo el mismo patrón Bootstrap que ya usa el
  dropdown del usuario (líneas 514-535 de `base.html`).
- **Selector "Simular Dirigente de Equipo"** (`prueba_seleccionar_equipo.html`):
  se corrige el contraste del nombre del equipo (hoy usa una clase que lo
  deja casi invisible), se agrega el conteo de jugadores visible y un
  botón primario "Entrar como Dirigente" por tarjeta.

## Testing

Seguimos el estilo TDD ya establecido en `core/tests.py`:
- `obtener_equipo_simulado`: revalida las 4 condiciones (equipo de otro
  usuario, equipo de cancha real, sesión vacía, caso feliz).
- `dashboard()` con equipo simulado activo: rol efectivo `'DIR'`, contexto
  con el equipo correcto.
- `gestionar_jugadores()` con equipo simulado: el equipo activo por
  defecto es el simulado; fichar un jugador desde ahí funciona igual que
  para un Dirigente real (mismo `JugadorForm`, misma validación de cupos).
- `rol_nav_efectivo` en el context processor: valor igual a
  `user.perfil.rol_principal` sin equipo simulado; `'DIR'` con equipo
  simulado activo; ningún cambio para usuarios sin cancha demo.
- `prueba_activar_dirigente` / `prueba_salir_modo_dirigente`: activa y
  limpia la sesión correctamente; un usuario sin Rol de Prueba no puede
  activar ninguno (`es_dueno_de_entorno_prueba` sigue bloqueando).
- Revocar el Rol de Prueba mientras el modo Dirigente está activo: la
  siguiente request dejar de encontrar el equipo simulado y el usuario cae
  de vuelta a la vista normal sin error.
- Regresión: la suite completa de `core.tests` (88 tests al momento de
  escribir este spec) sigue pasando, incluyendo los tests existentes de
  `PruebaDirigenteEquipoTest` que se reescriben para apuntar a las URLs
  reales en vez de a `prueba_ver_como_dirigente`/`prueba_agregar_jugador`.
