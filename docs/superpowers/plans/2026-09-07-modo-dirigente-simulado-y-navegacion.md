# Modo Dirigente Simulado y Reorganización de Navegación Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar la réplica simulada de "Dirigente de Equipo" del Sistema de Pruebas por un mecanismo aditivo que muestra las pantallas REALES de Dirigente (`dashboard`, `gestionar_jugadores`) a un usuario de prueba, y reorganizar tres superficies de navegación que hoy están amontonadas.

**Architecture:** Un "equipo simulado" se guarda en `request.session` y se revalida en cada request contra la base de datos (`core/services/pruebas.py::obtener_equipo_simulado`). Cuando hay un equipo simulado activo, el rol efectivo del usuario pasa a `'DIR'` en exactamente 3 puntos: `dashboard()`, `gestionar_jugadores()`, y el *context processor* `configuracion_global` (de donde toman `rol_nav_efectivo` `base.html` y `dashboard.html` para decidir qué mostrar). Fuera de una cancha `es_demo=True`, `rol_nav_efectivo` es siempre idéntico a `user.perfil.rol_principal` — cero cambio de comportamiento real.

**Tech Stack:** Django 6.0.1, `python3 manage.py test` (Django `TestCase` + `self.client`, estilo ya usado en `core/tests.py`), Bootstrap 5 + Bootstrap Icons.

**Spec:** `docs/superpowers/specs/2026-09-07-modo-dirigente-simulado-y-navegacion-design.md`

## Global Constraints

- `obtener_equipo_simulado(request)` **nunca** confía ciegamente en `request.session['equipo_simulado_id']`: revalida `dirigente=request.user`, `torneo__complejo__organizador=request.user`, `torneo__complejo__es_demo=True` en cada llamada.
- Cero cambio de comportamiento para cualquier usuario fuera de una cancha `es_demo=True` — `rol_nav_efectivo` debe ser exactamente igual a lo que ya devolvía `user.perfil.rol_principal` cuando no hay equipo simulado.
- `mis_finanzas_equipo()` **no se modifica** — ya funciona sin cambios para el usuario de prueba.
- `programar_partidos.html` y `ver_torneos_activos.html` (los otros 2 templates que usan `user.perfil.rol_principal`) **no se tocan** — fuera de alcance.
- Todo dato demo se sigue creando con ORM directo (`Model.objects.create(...)`), nunca vía `ModelForm`/`full_clean()`.
- Comandos de test siempre con `python3` (no `python`).
- Los nombres de equipos/jugadores/torneo de la siembra deben ser realistas, no genéricos tipo "Demo N".

---

## Task 1: Nombres realistas en la siembra de datos

**Files:**
- Modify: `core/services/pruebas.py`
- Test: `core/tests.py`

**Interfaces:**
- Ninguna nueva — cambia solo el contenido de `nombre`/`nombres` en `crear_entorno_prueba` y `_sembrar_equipos_y_jugadores`. Ninguna tarea futura depende de nombres específicos.

- [ ] **Step 1: Escribir el test que falla**

Añade al final de `core/tests.py`:

```python
class SiembraDemoNombresRealistasTest(TestCase):
    def test_el_torneo_y_la_categoria_tienen_nombres_realistas(self):
        usuario = User.objects.create_user("nombres1", password="pass12345")

        complejo = crear_entorno_prueba(usuario)

        torneo = Torneo.objects.get(complejo=complejo)
        self.assertEqual(torneo.nombre, "Copa Apertura 2026")
        self.assertEqual(torneo.categoria.nombre, "Segunda Categoría")

    def test_los_seis_equipos_tienen_nombres_de_liga_barrial_no_genericos(self):
        usuario = User.objects.create_user("nombres2", password="pass12345")

        complejo = crear_entorno_prueba(usuario)

        nombres_equipos = list(
            Equipo.objects.filter(torneo__complejo=complejo).order_by('id').values_list('nombre', flat=True)
        )
        self.assertEqual(nombres_equipos, [
            "Deportivo Chillos", "Atlético Valle", "Real San Rafael",
            "Juventud Amaguaña", "Unión Sangolquí", "Estrella del Valle",
        ])
        for nombre in nombres_equipos:
            self.assertNotIn("Demo", nombre)

    def test_los_36_jugadores_tienen_nombre_y_apellido_reales_y_unicos(self):
        usuario = User.objects.create_user("nombres3", password="pass12345")

        complejo = crear_entorno_prueba(usuario)

        nombres = list(
            Jugador.objects.filter(equipo__torneo__complejo=complejo).values_list('nombres', flat=True)
        )
        self.assertEqual(len(nombres), 36)
        self.assertEqual(len(set(nombres)), 36)
        for nombre in nombres:
            self.assertNotIn("Demo", nombre)
            self.assertNotIn("Jugador ", nombre)
            self.assertEqual(len(nombre.split()), 2)
```

- [ ] **Step 2: Confirmar que falla**

Run: `python3 manage.py test core.tests.SiembraDemoNombresRealistasTest -v 1`
Expected: `FAIL` — los nombres actuales son `"Torneo Demo"` / `"Equipo Demo N"` / `"Jugador N - Equipo M"`.

- [ ] **Step 3: Implementar**

En `core/services/pruebas.py`, agrega estas dos listas justo después de `NOMBRE_PLAN_DEMO = "Plan Demo (Prueba)"`:

```python
NOMBRES_EQUIPOS_DEMO = [
    "Deportivo Chillos", "Atlético Valle", "Real San Rafael",
    "Juventud Amaguaña", "Unión Sangolquí", "Estrella del Valle",
]

NOMBRES_JUGADORES_DEMO = [
    "Carlos Vera", "Andrés Suárez", "Luis Chasi", "Diego Toapanta", "Miguel Quishpe", "José Chicaiza",
    "Fernando Simbaña", "Pablo Pilamunga", "Iván Cofre", "Marco Salazar", "Esteban Bonilla", "Ricardo Andrade",
    "Alexander Mora", "Freddy Villacís", "Wilmer Cabezas", "Bryan Pazmiño", "Kevin Rosero", "Cristian Cevallos",
    "Daniel Naranjo", "Jorge Guamán", "Santiago Tipán", "Xavier Yépez", "Patricio Zambrano", "Vinicio Cárdenas",
    "Gonzalo Loachamín", "Fabián Puco", "Edwin Sailema", "Byron Guacho", "Franklin Chamorro", "Rodrigo Falconí",
    "Nelson Espín", "Milton Barreno", "Segundo Tacuri", "Klever Quinatoa", "Washington Segovia", "Hernán Herrera",
]
```

Cambia la línea `categoria = Categoria.objects.create(complejo=complejo, nombre="Categoría Demo")` por:

```python
    categoria = Categoria.objects.create(complejo=complejo, nombre="Segunda Categoría")
```

Cambia `nombre="Torneo Demo",` (dentro de `Torneo.objects.create(...)`) por:

```python
        nombre="Copa Apertura 2026",
```

Reemplaza toda la función `_sembrar_equipos_y_jugadores` por:

```python
def _sembrar_equipos_y_jugadores(torneo, usuario):
    equipos = []
    contador_jugador = 0
    for i in range(6):
        equipo = Equipo.objects.create(
            torneo=torneo,
            dirigente=usuario,
            nombre=NOMBRES_EQUIPOS_DEMO[i],
            estado_inscripcion="APROBADO",
            pagado=True,
            cupos_pagados=10,
        )
        for dorsal in range(1, 7):
            nombre_jugador = NOMBRES_JUGADORES_DEMO[contador_jugador]
            contador_jugador += 1
            Jugador.objects.create(
                equipo=equipo,
                nombres=nombre_jugador,
                dorsal=dorsal,
                cedula=f"90{contador_jugador:08d}",
            )
        equipos.append(equipo)
    return equipos
```

- [ ] **Step 4: Confirmar que pasa**

Run: `python3 manage.py test core.tests.SiembraDemoNombresRealistasTest -v 1`
Expected: `OK` (3 tests)

También vuelve a correr las tareas estructurales previas para confirmar que nada se rompió:
Run: `python3 manage.py test core.tests.CrearEntornoPruebaBaseTest core.tests.CrearEntornoPruebaEquiposYJugadoresTest core.tests.CrearEntornoPruebaPartidosTest -v 1`
Expected: `OK` (14 tests)

- [ ] **Step 5: Commit**

```bash
git add core/services/pruebas.py core/tests.py
git commit -m "$(cat <<'EOF'
Usa nombres realistas en la siembra del entorno de prueba

Torneo, categoría, los 6 equipos y los 36 jugadores demo ahora tienen
nombres creíbles (equipos de liga barrial, nombres y apellidos
reales) en vez de placeholders genéricos "Demo N".

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RHn9nvU9sj2GA39FdVhWbb
EOF
)"
```

---

## Task 2: `obtener_equipo_simulado(request)` con revalidación completa

**Files:**
- Modify: `core/services/pruebas.py`
- Test: `core/tests.py`

**Interfaces:**
- Consumes: `Equipo`, `ComplejoDeportivo` (ya importados en `pruebas.py`).
- Produces: `obtener_equipo_simulado(request) -> Equipo | None`. Las Tasks 3, 4, 5 y 6 la usan.

- [ ] **Step 1: Escribir el test que falla**

En `core/tests.py`, agrega estos imports al inicio del archivo (junto a los demás imports de `django.test`/`django.contrib`):

```python
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory
```

Añade al final de `core/tests.py`:

```python
class ObtenerEquipoSimuladoTest(TestCase):
    def _request_con_sesion(self, usuario, equipo_id=None):
        request = RequestFactory().get('/')
        request.user = usuario
        request.session = SessionStore()
        if equipo_id is not None:
            request.session['equipo_simulado_id'] = equipo_id
        return request

    def test_sin_nada_en_sesion_devuelve_none(self):
        usuario = User.objects.create_user("simulador1", password="pass12345")

        request = self._request_con_sesion(usuario)

        self.assertIsNone(obtener_equipo_simulado(request))

    def test_devuelve_el_equipo_si_es_dirigente_de_su_propia_cancha_demo(self):
        usuario = User.objects.create_user("simulador2", password="pass12345")
        complejo = crear_entorno_prueba(usuario)
        mi_equipo = Equipo.objects.filter(torneo__complejo=complejo).first()

        request = self._request_con_sesion(usuario, equipo_id=mi_equipo.id)

        self.assertEqual(obtener_equipo_simulado(request), mi_equipo)

    def test_no_confia_en_un_equipo_de_otro_usuario_de_prueba(self):
        usuario = User.objects.create_user("simulador3", password="pass12345")
        crear_entorno_prueba(usuario)
        otro_usuario = User.objects.create_user("simulador4", password="pass12345")
        otro_complejo = crear_entorno_prueba(otro_usuario)
        equipo_ajeno = Equipo.objects.filter(torneo__complejo=otro_complejo).first()

        request = self._request_con_sesion(usuario, equipo_id=equipo_ajeno.id)

        self.assertIsNone(obtener_equipo_simulado(request))

    def test_no_confia_en_un_equipo_de_una_cancha_real(self):
        plan = PlanSuscripcion.objects.create(nombre="Plan RS", precio_mensual=Decimal("10.00"))
        usuario = User.objects.create_user("simulador5", password="pass12345")
        complejo_real = ComplejoDeportivo.objects.create(
            nombre="Cancha Real RS", slug="cancha-real-rs", organizador=usuario, plan=plan,
        )
        torneo_real = Torneo.objects.create(complejo=complejo_real, nombre="Torneo Real RS", organizador=usuario)
        equipo_real = Equipo.objects.create(
            torneo=torneo_real, dirigente=usuario, nombre="Equipo Real RS", estado_inscripcion="APROBADO",
        )

        request = self._request_con_sesion(usuario, equipo_id=equipo_real.id)

        self.assertIsNone(obtener_equipo_simulado(request))

    def test_deja_de_encontrar_el_equipo_si_le_revocan_el_rol_de_prueba_a_mitad_de_sesion(self):
        usuario = User.objects.create_user("simulador6", password="pass12345")
        complejo = crear_entorno_prueba(usuario)
        mi_equipo = Equipo.objects.filter(torneo__complejo=complejo).first()
        request = self._request_con_sesion(usuario, equipo_id=mi_equipo.id)
        self.assertIsNotNone(obtener_equipo_simulado(request))

        eliminar_entorno_prueba(usuario)

        self.assertIsNone(obtener_equipo_simulado(request))
```

- [ ] **Step 2: Confirmar que falla**

Run: `python3 manage.py test core.tests.ObtenerEquipoSimuladoTest -v 1`
Expected: `FAIL` — `ImportError: cannot import name 'obtener_equipo_simulado'`

- [ ] **Step 3: Implementar**

Actualiza el import de `core/tests.py` (la línea `from .services.pruebas import (...)` a mitad del archivo) para incluir la nueva función:

```python
from .services.pruebas import (
    NOMBRE_PLAN_DEMO, crear_entorno_prueba, eliminar_entorno_prueba,
    obtener_equipo_simulado, obtener_o_crear_plan_demo,
)
```

Agrega al final de `core/services/pruebas.py`:

```python
def obtener_equipo_simulado(request):
    """Devuelve el Equipo que el usuario está "simulando" dirigir dentro de
    su propio entorno de prueba, o None. Revalida SIEMPRE contra la base de
    datos — nunca confía ciegamente en request.session — así que si el
    Super Admin le revoca el Rol de Prueba a mitad de sesión, la siguiente
    llamada deja de encontrar el equipo automáticamente."""
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

- [ ] **Step 4: Confirmar que pasa**

Run: `python3 manage.py test core.tests.ObtenerEquipoSimuladoTest -v 1`
Expected: `OK` (5 tests)

- [ ] **Step 5: Commit**

```bash
git add core/services/pruebas.py core/tests.py
git commit -m "$(cat <<'EOF'
Agrega obtener_equipo_simulado con revalidación completa en cada request

Base del modo "Dirigente simulado": lee request.session pero nunca
confía en ella — revalida dirigente, organizador y es_demo=True
contra la base de datos en cada llamada, así que revocar el Rol de
Prueba a mitad de sesión desactiva la simulación automáticamente.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RHn9nvU9sj2GA39FdVhWbb
EOF
)"
```

---

## Task 3: `dashboard()` integra el equipo simulado

**Files:**
- Modify: `core/views.py:95-161` (función `dashboard`)
- Test: `core/tests.py`

**Interfaces:**
- Consumes: `obtener_equipo_simulado` (Task 2).
- Produces: `dashboard()` trata el rol como `'DIR'` cuando hay equipo simulado. Ninguna tarea posterior depende de detalles internos, solo de que `ctx['mi_rol_principal']` y `ctx['mi_equipo']` queden correctos.

- [ ] **Step 1: Escribir el test que falla**

Añade al final de `core/tests.py`:

```python
class DashboardConEquipoSimuladoTest(TestCase):
    def test_dashboard_trata_al_organizador_demo_como_dirigente_del_equipo_elegido(self):
        usuario = User.objects.create_user("dashsim1", password="pass12345")
        complejo = crear_entorno_prueba(usuario)
        mi_equipo = Equipo.objects.filter(torneo__complejo=complejo).order_by('id').first()
        self.client.login(username="dashsim1", password="pass12345")
        session = self.client.session
        session['equipo_simulado_id'] = mi_equipo.id
        session.save()

        response = self.client.get("/dashboard/")

        self.assertEqual(response.context["mi_rol_principal"], "DIR")
        self.assertEqual(response.context["mi_equipo"], mi_equipo)

    def test_sin_equipo_simulado_el_organizador_demo_sigue_viendo_su_propio_panel_org(self):
        usuario = User.objects.create_user("dashsim2", password="pass12345")
        crear_entorno_prueba(usuario)
        self.client.login(username="dashsim2", password="pass12345")

        response = self.client.get("/dashboard/")

        self.assertEqual(response.context["mi_rol_principal"], "ORG")
```

- [ ] **Step 2: Confirmar que falla**

Run: `python3 manage.py test core.tests.DashboardConEquipoSimuladoTest -v 1`
Expected: `FAIL` — `mi_rol_principal` sigue siendo `'ORG'` aunque haya equipo simulado en sesión.

- [ ] **Step 3: Implementar**

En `core/views.py`, agrega `obtener_equipo_simulado` al import existente de `core/services/pruebas` (línea 41):

```python
from .services.pruebas import crear_entorno_prueba, eliminar_entorno_prueba, obtener_equipo_simulado, NOMBRE_PLAN_DEMO
```

Dentro de `dashboard()`, reemplaza:

```python
    if request.user.is_authenticated:
        rol = obtener_rol_principal(request.user)
        ctx['mi_rol_principal'] = rol # Pasamos el rol a la plantilla

        if rol == 'ORG':
```

por:

```python
    if request.user.is_authenticated:
        rol = obtener_rol_principal(request.user)
        equipo_simulado = obtener_equipo_simulado(request)
        if equipo_simulado:
            rol = 'DIR'
        ctx['mi_rol_principal'] = rol # Pasamos el rol a la plantilla

        if rol == 'ORG':
```

Y reemplaza:

```python
        elif rol == 'DIR':
            mis_equipos = Equipo.objects.filter(dirigente=request.user)
            if mis_equipos.exists():
                ctx['mi_equipo'] = mis_equipos.first() 
```

por:

```python
        elif rol == 'DIR':
            mis_equipos = Equipo.objects.filter(dirigente=request.user)
            if mis_equipos.exists():
                ctx['mi_equipo'] = equipo_simulado or mis_equipos.first()
```

- [ ] **Step 4: Confirmar que pasa**

Run: `python3 manage.py test core.tests.DashboardConEquipoSimuladoTest -v 1`
Expected: `OK` (2 tests)

- [ ] **Step 5: Commit**

```bash
git add core/views.py core/tests.py
git commit -m "$(cat <<'EOF'
dashboard() trata al usuario de prueba como Dirigente del equipo elegido

Cuando hay un equipo simulado activo en sesión, el rol efectivo pasa
a 'DIR' y ctx['mi_equipo'] apunta a ese equipo — el usuario de prueba
ve exactamente el mismo contexto que vería un Dirigente real.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RHn9nvU9sj2GA39FdVhWbb
EOF
)"
```

---

## Task 4: `gestionar_jugadores()` integra el equipo simulado

**Files:**
- Modify: `core/views.py:409-614` (función `gestionar_jugadores`)
- Test: `core/tests.py`

**Interfaces:**
- Consumes: `obtener_equipo_simulado` (Task 2).
- Produces: `gestionar_jugadores()` usa el equipo simulado como equipo activo por defecto cuando no viene `?equipo=` en la URL, y trata el rol como `'DIR'`.

- [ ] **Step 1: Escribir el test que falla**

Añade al final de `core/tests.py`:

```python
class GestionarJugadoresConEquipoSimuladoTest(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user("fichsim1", password="pass12345")
        self.complejo = crear_entorno_prueba(self.usuario)
        self.mi_equipo = Equipo.objects.filter(torneo__complejo=self.complejo).order_by('id').first()
        self.client.login(username="fichsim1", password="pass12345")
        session = self.client.session
        session['equipo_simulado_id'] = self.mi_equipo.id
        session.save()

    def test_sin_parametro_equipo_en_la_url_usa_el_equipo_simulado_por_defecto(self):
        response = self.client.get("/jugadores/")

        self.assertEqual(response.context["equipo_obj"], self.mi_equipo)
        self.assertTrue(response.context["es_dirigente"])

    def test_puede_fichar_un_jugador_nuevo_en_el_equipo_simulado(self):
        jugadores_antes = self.mi_equipo.jugadores.count()

        response = self.client.post("/jugadores/", {
            "equipo": self.mi_equipo.id,
            "nombres": "Jugador De Prueba Fichado",
            "dorsal": "88",
            "cedula": "1710000088",
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.mi_equipo.jugadores.count(), jugadores_antes + 1)

    def test_puede_cambiar_a_otro_de_sus_seis_equipos_demo_con_el_selector_real(self):
        otro_equipo = Equipo.objects.filter(torneo__complejo=self.complejo).exclude(id=self.mi_equipo.id).first()

        response = self.client.get(f"/jugadores/?equipo={otro_equipo.id}")

        self.assertEqual(response.context["equipo_obj"], otro_equipo)
```

- [ ] **Step 2: Confirmar que falla**

Run: `python3 manage.py test core.tests.GestionarJugadoresConEquipoSimuladoTest -v 1`
Expected: `FAIL` — sin `?equipo=` en la URL, `equipo_obj` es el primer equipo del usuario (por orden de `equipos_activos`), no necesariamente `self.mi_equipo`, y `es_dirigente`/rol no están forzados a DIR (aunque en este caso ya resuelve ORG y la vista real de fichaje no se comporta igual).

- [ ] **Step 3: Implementar**

Dentro de `gestionar_jugadores()`, reemplaza:

```python
    rol_principal = obtener_rol_principal(request.user)
    puede_fichar = True
    query = request.GET.get('q', '').strip()

    if rol_principal == 'DIR':
        mis_equipos = Equipo.objects.filter(dirigente=request.user)
        if not mis_equipos.exists():
            messages.error(request, 'No tienes un equipo inscrito. Inscríbete a un torneo primero.')
            return redirect('ver_torneos_activos')

        equipos_activos = mis_equipos.filter(torneo__activo=True).order_by('torneo__categoria__nombre', 'torneo__nombre', 'nombre')
        equipo_id = request.GET.get('equipo')
        mi_equipo = mis_equipos.filter(id=equipo_id).first() if equipo_id else (equipos_activos.first() or mis_equipos.first())
```

por:

```python
    rol_principal = obtener_rol_principal(request.user)
    equipo_simulado = obtener_equipo_simulado(request)
    if equipo_simulado:
        rol_principal = 'DIR'
    puede_fichar = True
    query = request.GET.get('q', '').strip()

    if rol_principal == 'DIR':
        mis_equipos = Equipo.objects.filter(dirigente=request.user)
        if not mis_equipos.exists():
            messages.error(request, 'No tienes un equipo inscrito. Inscríbete a un torneo primero.')
            return redirect('ver_torneos_activos')

        equipos_activos = mis_equipos.filter(torneo__activo=True).order_by('torneo__categoria__nombre', 'torneo__nombre', 'nombre')
        equipo_id = request.GET.get('equipo') or (equipo_simulado.id if equipo_simulado else None)
        mi_equipo = mis_equipos.filter(id=equipo_id).first() if equipo_id else (equipos_activos.first() or mis_equipos.first())
```

- [ ] **Step 4: Confirmar que pasa**

Run: `python3 manage.py test core.tests.GestionarJugadoresConEquipoSimuladoTest -v 1`
Expected: `OK` (3 tests)

También corre de nuevo la Task 3 para confirmar que no se rompió:
Run: `python3 manage.py test core.tests.DashboardConEquipoSimuladoTest -v 1`
Expected: `OK` (2 tests)

- [ ] **Step 5: Commit**

```bash
git add core/views.py core/tests.py
git commit -m "$(cat <<'EOF'
gestionar_jugadores() usa el equipo simulado como equipo activo

Sin ?equipo= explícito en la URL, el usuario de prueba en modo
Dirigente simulado ve y ficha jugadores en el equipo que eligió — la
misma pantalla y el mismo formulario (JugadorForm) que usa un
Dirigente real, incluyendo el selector real de equipo si tiene más
de uno.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RHn9nvU9sj2GA39FdVhWbb
EOF
)"
```

---

## Task 5: `rol_nav_efectivo` en el context processor + plantillas

**Files:**
- Modify: `core/context_processors.py`
- Modify: `core/templates/core/base.html` (3 apariciones de `user.perfil.rol_principal`)
- Modify: `core/templates/core/dashboard.html` (9 apariciones de `user.perfil.rol_principal`)
- Test: `core/tests.py`

**Interfaces:**
- Consumes: `obtener_equipo_simulado` (Task 2).
- Produces: contexto global `rol_nav_efectivo`, disponible en toda plantilla que extienda `base.html`. Ninguna tarea posterior depende de esto salvo la Task 6 (banner).

**Corrección importante (ver spec):** `dashboard.html` NO usa el `mi_rol_principal` que ya calcula `dashboard()` — es una variable muerta. Las 9 secciones de `dashboard.html` que deciden qué mostrar leen `user.perfil.rol_principal` directamente, igual que `base.html`. Por eso esta tarea reemplaza esa expresión en AMBOS archivos.

- [ ] **Step 1: Escribir el test que falla**

Añade al final de `core/tests.py`:

```python
class RolNavEfectivoContextProcessorTest(TestCase):
    def test_usuario_normal_sin_simulacion_tiene_el_mismo_rol_de_siempre(self):
        plan = PlanSuscripcion.objects.create(nombre="Plan Nav", precio_mensual=Decimal("10.00"))
        organizador = User.objects.create_user("navctx1", password="pass12345")
        ComplejoDeportivo.objects.create(
            nombre="Cancha Nav", slug="cancha-nav", organizador=organizador, plan=plan,
        )
        self.client.login(username="navctx1", password="pass12345")

        response = self.client.get("/dashboard/")

        self.assertEqual(response.context["rol_nav_efectivo"], "ORG")
        self.assertContains(response, "Gestor Administrativo")

    def test_usuario_de_prueba_con_equipo_simulado_activo_ve_el_panel_real_de_dirigente(self):
        usuario = User.objects.create_user("navctx2", password="pass12345")
        complejo = crear_entorno_prueba(usuario)
        mi_equipo = Equipo.objects.filter(torneo__complejo=complejo).first()
        self.client.login(username="navctx2", password="pass12345")
        session = self.client.session
        session['equipo_simulado_id'] = mi_equipo.id
        session.save()

        response = self.client.get("/dashboard/")

        self.assertEqual(response.context["rol_nav_efectivo"], "DIR")
        self.assertContains(response, 'href="/jugadores/"')
        self.assertContains(response, 'href="/mis-finanzas-equipo/"')
        self.assertNotContains(response, "Gestor Administrativo")
        self.assertNotContains(response, 'href="/equipos/"')
```

- [ ] **Step 2: Confirmar que falla**

Run: `python3 manage.py test core.tests.RolNavEfectivoContextProcessorTest -v 1`
Expected: `FAIL` — `KeyError: 'rol_nav_efectivo'` en el primer test; en el segundo, el dashboard sigue mostrando "Gestor Administrativo" (contenido de Organizador) porque las plantillas ignoran el equipo simulado.

- [ ] **Step 3: Implementar**

Reemplaza el contenido completo de `core/context_processors.py`:

```python
# core/context_processors.py
from .models import ComplejoDeportivo, Configuracion
from .services.pruebas import obtener_equipo_simulado

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

En `core/templates/core/base.html`, reemplaza **todas** las apariciones de `user.perfil.rol_principal` por `rol_nav_efectivo` (son 3, en las líneas donde decide el destino del logo/marca y el bloque de nav de Organizador/Dirigente).

En `core/templates/core/dashboard.html`, reemplaza **todas** las apariciones de `user.perfil.rol_principal` por `rol_nav_efectivo` (son 9: la alerta de cobros ORG, el botón "Generar Imagen", el bloque "Mi Panel", los botones "Mi Equipo"/"Finanzas", el panel de Vocal, "Gestor Administrativo", y los dos modales de deudas).

- [ ] **Step 4: Confirmar que pasa**

Run: `python3 manage.py test core.tests.RolNavEfectivoContextProcessorTest -v 1`
Expected: `OK` (2 tests)

Corre también toda la suite para descartar una regresión de nav en otras vistas:
Run: `python3 manage.py test core.tests -v 1`
Expected: `OK` (todos los tests existentes siguen pasando)

- [ ] **Step 5: Commit**

```bash
git add core/context_processors.py core/templates/core/base.html core/templates/core/dashboard.html core/tests.py
git commit -m "$(cat <<'EOF'
Agrega rol_nav_efectivo: nav y dashboard reflejan el modo Dirigente simulado

base.html y dashboard.html usaban user.perfil.rol_principal
directamente (ignorando el equipo simulado que ya calculan
dashboard() y gestionar_jugadores()). rol_nav_efectivo, calculado en
el context processor, es idéntico a esa propiedad para cualquier
usuario real y solo cambia a 'DIR' cuando hay un equipo simulado
activo — así el usuario de prueba ve el nav y el dashboard reales de
un Dirigente.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RHn9nvU9sj2GA39FdVhWbb
EOF
)"
```

---

## Task 6: Activar y salir del modo Dirigente simulado

**Files:**
- Modify: `core/views.py` (agrega 2 vistas nuevas, cerca de `prueba_seleccionar_equipo`)
- Modify: `config/urls.py:128-130`
- Modify: `core/templates/core/base.html` (banner de modo prueba)
- Test: `core/tests.py`

**Interfaces:**
- Consumes: `es_dueno_de_entorno_prueba`, `obtener_mi_complejo_demo` (ya existen en `views.py`); `rol_nav_efectivo` (Task 5).
- Produces: URLs `prueba_activar_dirigente` (POST) y `prueba_salir_modo_dirigente` (POST). La Task 7 (rediseño del selector) las consume.

- [ ] **Step 1: Escribir el test que falla**

Añade al final de `core/tests.py`:

```python
class ActivarYSalirModoDirigenteTest(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user("activar1", password="pass12345")
        self.complejo = crear_entorno_prueba(self.usuario)
        self.mi_equipo = Equipo.objects.filter(torneo__complejo=self.complejo).order_by('id').first()
        self.client.login(username="activar1", password="pass12345")

    def test_activar_redirige_al_dashboard_y_este_muestra_el_panel_real_de_dirigente(self):
        response = self.client.post(f"/prueba/dirigente/activar/{self.mi_equipo.id}/", follow=True)

        self.assertRedirects(response, "/dashboard/")
        self.assertEqual(response.context["mi_rol_principal"], "DIR")
        self.assertEqual(response.context["mi_equipo"], self.mi_equipo)

    def test_no_puede_activar_un_equipo_que_no_es_suyo(self):
        otro_usuario = User.objects.create_user("activar2", password="pass12345")
        otro_complejo = crear_entorno_prueba(otro_usuario)
        equipo_ajeno = Equipo.objects.filter(torneo__complejo=otro_complejo).first()

        response = self.client.post(f"/prueba/dirigente/activar/{equipo_ajeno.id}/")

        self.assertEqual(response.status_code, 404)

    def test_un_usuario_sin_rol_de_prueba_no_puede_activar_nada(self):
        self.client.logout()
        User.objects.create_user("activar3", password="pass12345")
        self.client.login(username="activar3", password="pass12345")

        response = self.client.post(f"/prueba/dirigente/activar/{self.mi_equipo.id}/")

        self.assertNotEqual(response.status_code, 200)

    def test_salir_del_modo_dirigente_vuelve_a_la_vista_de_organizador(self):
        self.client.post(f"/prueba/dirigente/activar/{self.mi_equipo.id}/")

        response = self.client.post("/prueba/dirigente/salir/", follow=True)

        self.assertEqual(response.context["mi_rol_principal"], "ORG")

    def test_el_banner_de_modo_prueba_muestra_el_boton_salir_solo_si_esta_activo(self):
        response_antes = self.client.get("/dashboard/")
        self.assertNotContains(response_antes, "Salir del modo Dirigente")

        self.client.post(f"/prueba/dirigente/activar/{self.mi_equipo.id}/")
        response_activo = self.client.get("/dashboard/")

        self.assertContains(response_activo, "Salir del modo Dirigente")
```

- [ ] **Step 2: Confirmar que falla**

Run: `python3 manage.py test core.tests.ActivarYSalirModoDirigenteTest -v 1`
Expected: `FAIL` — `django.urls.exceptions.NoReverseMatch`/404 (las URLs no existen todavía).

- [ ] **Step 3: Implementar**

En `core/views.py`, agrega estas 2 vistas justo después de la definición de `prueba_seleccionar_equipo` (no reemplaces `prueba_ver_como_dirigente`/`prueba_agregar_jugador` todavía, eso es la Task 8):

```python
@login_required
@user_passes_test(es_dueno_de_entorno_prueba)
def prueba_activar_dirigente(request, equipo_id):
    mi_complejo_demo = obtener_mi_complejo_demo(request.user)
    equipo = get_object_or_404(
        Equipo, id=equipo_id, dirigente=request.user, torneo__complejo=mi_complejo_demo,
    )
    if request.method == 'POST':
        request.session['equipo_simulado_id'] = equipo.id
        messages.success(request, f"🧪 Ahora estás viendo el sistema como el Dirigente de {equipo.nombre}.")
    return redirect('dashboard')


@login_required
def prueba_salir_modo_dirigente(request):
    if request.method == 'POST':
        request.session.pop('equipo_simulado_id', None)
    return redirect('dashboard')
```

En `config/urls.py`, reemplaza las líneas:

```python
    path('prueba/dirigente/', views.prueba_seleccionar_equipo, name='prueba_seleccionar_equipo'),
    path('prueba/dirigente/<int:equipo_id>/', views.prueba_ver_como_dirigente, name='prueba_ver_como_dirigente'),
    path('prueba/dirigente/<int:equipo_id>/agregar-jugador/', views.prueba_agregar_jugador, name='prueba_agregar_jugador'),
```

por:

```python
    path('prueba/dirigente/', views.prueba_seleccionar_equipo, name='prueba_seleccionar_equipo'),
    path('prueba/dirigente/activar/<int:equipo_id>/', views.prueba_activar_dirigente, name='prueba_activar_dirigente'),
    path('prueba/dirigente/salir/', views.prueba_salir_modo_dirigente, name='prueba_salir_modo_dirigente'),
    path('prueba/dirigente/<int:equipo_id>/', views.prueba_ver_como_dirigente, name='prueba_ver_como_dirigente'),
    path('prueba/dirigente/<int:equipo_id>/agregar-jugador/', views.prueba_agregar_jugador, name='prueba_agregar_jugador'),
```

(Las 2 últimas líneas se eliminan en la Task 8, junto con las vistas. Se dejan por ahora para no romper nada a mitad de tarea.)

En `core/templates/core/base.html`, reemplaza el bloque del banner de modo prueba:

```html
    {% if es_entorno_prueba %}
    <div class="bg-warning bg-opacity-25 border-bottom border-warning text-center py-2 fw-bold small">
        🧪 Estás en un entorno de PRUEBA — nada de lo que hagas aquí afecta datos reales.
    </div>
    {% endif %}
```

por:

```html
    {% if es_entorno_prueba %}
    <div class="bg-warning bg-opacity-25 border-bottom border-warning text-center py-2 fw-bold small d-flex align-items-center justify-content-center gap-3 flex-wrap">
        <span>🧪 Estás en un entorno de PRUEBA — nada de lo que hagas aquí afecta datos reales.</span>
        {% if rol_nav_efectivo == 'DIR' %}
        <form method="post" action="{% url 'prueba_salir_modo_dirigente' %}" class="m-0">
            {% csrf_token %}
            <button type="submit" class="btn btn-sm btn-outline-dark rounded-pill fw-bold py-0 px-2">Salir del modo Dirigente</button>
        </form>
        {% endif %}
    </div>
    {% endif %}
```

- [ ] **Step 4: Confirmar que pasa**

Run: `python3 manage.py test core.tests.ActivarYSalirModoDirigenteTest -v 1`
Expected: `OK` (5 tests)

- [ ] **Step 5: Commit**

```bash
git add core/views.py config/urls.py core/templates/core/base.html core/tests.py
git commit -m "$(cat <<'EOF'
Agrega activar/salir del modo Dirigente simulado + botón en el banner

prueba_activar_dirigente guarda el equipo elegido en sesión y manda
al dashboard real; prueba_salir_modo_dirigente la limpia. El banner
"modo prueba" gana un botón "Salir del modo Dirigente" visible solo
mientras la simulación está activa.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RHn9nvU9sj2GA39FdVhWbb
EOF
)"
```

---

## Task 7: Rediseña el selector "Dirigente de Equipo"

**Files:**
- Modify: `core/templates/core/prueba_seleccionar_equipo.html`
- Test: `core/tests.py`

**Interfaces:**
- Consumes: `prueba_activar_dirigente` (Task 6).
- Ninguna tarea posterior depende de esta plantilla.

- [ ] **Step 1: Escribir el test que falla**

Añade al final de `core/tests.py`:

```python
class SelectorDirigenteRediseniadoTest(TestCase):
    def test_cada_tarjeta_de_equipo_tiene_boton_para_entrar_como_dirigente(self):
        usuario = User.objects.create_user("selector1", password="pass12345")
        complejo = crear_entorno_prueba(usuario)
        un_equipo = Equipo.objects.filter(torneo__complejo=complejo).first()
        self.client.login(username="selector1", password="pass12345")

        response = self.client.get("/prueba/dirigente/")

        self.assertContains(response, un_equipo.nombre)
        self.assertContains(response, f'action="/prueba/dirigente/activar/{un_equipo.id}/"')
        self.assertContains(response, "Entrar como Dirigente")
```

- [ ] **Step 2: Confirmar que falla**

Run: `python3 manage.py test core.tests.SelectorDirigenteRediseniadoTest -v 1`
Expected: `FAIL` — la plantilla actual enlaza a `prueba_ver_como_dirigente`, no tiene un `<form>` a `prueba_activar_dirigente` ni el texto "Entrar como Dirigente".

- [ ] **Step 3: Implementar**

Reemplaza el contenido completo de `core/templates/core/prueba_seleccionar_equipo.html`:

```html
{% extends 'core/base.html' %}

{% block title %}Dirigente de Equipo (Demo) | NEXUS{% endblock %}

{% block contenido %}
<div class="container py-4">
    <h4 class="fw-black mb-1" style="color: var(--text-main);"><i class="bi bi-person-badge-fill text-primary me-2"></i>Dirigente de Equipo</h4>
    <p class="text-muted mb-4">Elige con cuál de tus 6 equipos demo quieres entrar al sistema. Verás el panel real que usa un Dirigente — fichajes, finanzas y todo lo demás — para ese equipo.</p>

    <div class="row g-3">
        {% for equipo in equipos %}
        <div class="col-md-4">
            <div class="card border-0 rounded-4 shadow-sm h-100 p-3 d-flex flex-column">
                <div class="d-flex align-items-center gap-2 mb-2">
                    <i class="bi bi-shield-fill text-primary fs-4"></i>
                    <h5 class="fw-bold m-0" style="color: var(--text-main);">{{ equipo.nombre }}</h5>
                </div>
                <p class="text-muted small mb-3">{{ equipo.jugadores.count }} jugadores inscritos</p>
                <form method="post" action="{% url 'prueba_activar_dirigente' equipo.id %}" class="mt-auto">
                    {% csrf_token %}
                    <button type="submit" class="btn btn-primary w-100 rounded-pill fw-bold">Entrar como Dirigente</button>
                </form>
            </div>
        </div>
        {% endfor %}
    </div>
</div>
{% endblock %}
```

- [ ] **Step 4: Confirmar que pasa**

Run: `python3 manage.py test core.tests.SelectorDirigenteRediseniadoTest -v 1`
Expected: `OK` (1 test)

- [ ] **Step 5: Commit**

```bash
git add core/templates/core/prueba_seleccionar_equipo.html core/tests.py
git commit -m "$(cat <<'EOF'
Rediseña el selector "Dirigente de Equipo": contraste y CTA reales

El nombre del equipo usaba la clase Bootstrap "text-dark" (color fijo
que queda casi invisible en el tema oscuro de la app, que usa
variables CSS). Ahora usa var(--text-main) como el resto del sitio, y
cada tarjeta tiene un botón "Entrar como Dirigente" que activa el
modo Dirigente simulado para ese equipo.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RHn9nvU9sj2GA39FdVhWbb
EOF
)"
```

---

## Task 8: Elimina las vistas/plantillas obsoletas y agrega el test end-to-end del flujo completo

**Files:**
- Modify: `core/views.py` (elimina `prueba_ver_como_dirigente` y `prueba_agregar_jugador`)
- Modify: `config/urls.py:131-132` (elimina las 2 URLs obsoletas)
- Delete: `core/templates/core/prueba_dirigente_equipo.html`
- Delete: `core/templates/core/prueba_agregar_jugador.html`
- Modify: `core/tests.py` (elimina `PruebaDirigenteEquipoTest` y `PruebaAgregarJugadorTest`, agrega el test end-to-end)

**Interfaces:**
- Consumes: todo lo de las Tasks 2-7.
- Ninguna tarea posterior depende de esto — es la última pieza funcional del mecanismo.

- [ ] **Step 1: Escribir el test que falla**

En `core/tests.py`, **elimina por completo** las clases `PruebaDirigenteEquipoTest` y `PruebaAgregarJugadorTest` (probaban las vistas que se están eliminando en este paso).

Añade al final de `core/tests.py` (usa la fixture `setUp` de la Task 6 como referencia, este es un test nuevo e independiente):

```python
class ModoDirigenteSimuladoFlujoCompletoTest(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user("flujo1", password="pass12345")
        self.complejo_demo = crear_entorno_prueba(self.usuario)
        self.mi_equipo = Equipo.objects.filter(torneo__complejo=self.complejo_demo).order_by('id').first()
        self.client.login(username="flujo1", password="pass12345")

    def test_flujo_completo_activar_fichar_y_salir(self):
        # 1. Activa el modo Dirigente para su primer equipo demo.
        self.client.post(f"/prueba/dirigente/activar/{self.mi_equipo.id}/")

        # 2. El dashboard real ya lo trata como Dirigente de ese equipo.
        dash = self.client.get("/dashboard/")
        self.assertEqual(dash.context["mi_rol_principal"], "DIR")

        # 3. Ficha un jugador nuevo desde la pantalla real de Dirigente.
        jugadores_antes = self.mi_equipo.jugadores.count()
        ficha = self.client.post("/jugadores/", {
            "equipo": self.mi_equipo.id,
            "nombres": "Jugador Fichado En Flujo",
            "dorsal": "91",
            "cedula": "1710000091",
        })
        self.assertEqual(ficha.status_code, 302)
        self.assertEqual(self.mi_equipo.jugadores.count(), jugadores_antes + 1)

        # 4. Sale del modo Dirigente y vuelve a ver su panel de Organizador.
        self.client.post("/prueba/dirigente/salir/")
        dash_final = self.client.get("/dashboard/")
        self.assertEqual(dash_final.context["mi_rol_principal"], "ORG")

    def test_revocar_el_rol_de_prueba_con_el_modo_activo_no_rompe_el_dashboard(self):
        self.client.post(f"/prueba/dirigente/activar/{self.mi_equipo.id}/")

        eliminar_entorno_prueba(self.usuario)

        response = self.client.get("/dashboard/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["mi_rol_principal"], "FAN")

    def test_las_urls_de_las_vistas_paralelas_eliminadas_ya_no_existen(self):
        from django.urls import NoReverseMatch, reverse
        with self.assertRaises(NoReverseMatch):
            reverse('prueba_ver_como_dirigente', args=[self.mi_equipo.id])
```

- [ ] **Step 2: Confirmar que falla**

Run: `python3 manage.py test core.tests.ModoDirigenteSimuladoFlujoCompletoTest -v 1`
Expected: el primer y segundo test deberían pasar ya (el mecanismo ya existe desde las Tasks 3-6); el tercero (`test_las_urls_de_las_vistas_paralelas_eliminadas_ya_no_existen`) **falla** porque `prueba_ver_como_dirigente` todavía existe.

- [ ] **Step 3: Implementar**

En `core/views.py`, **elimina por completo** las funciones `prueba_ver_como_dirigente` y `prueba_agregar_jugador` (quedan `prueba_seleccionar_equipo`, `prueba_activar_dirigente` y `prueba_salir_modo_dirigente`).

En `config/urls.py`, elimina las 2 líneas:

```python
    path('prueba/dirigente/<int:equipo_id>/', views.prueba_ver_como_dirigente, name='prueba_ver_como_dirigente'),
    path('prueba/dirigente/<int:equipo_id>/agregar-jugador/', views.prueba_agregar_jugador, name='prueba_agregar_jugador'),
```

Borra los archivos de plantilla:

```bash
rm core/templates/core/prueba_dirigente_equipo.html
rm core/templates/core/prueba_agregar_jugador.html
```

- [ ] **Step 4: Confirmar que pasa**

Run: `python3 manage.py test core.tests.ModoDirigenteSimuladoFlujoCompletoTest -v 1`
Expected: `OK` (3 tests)

- [ ] **Step 5: Correr la suite completa de `core.tests` para confirmar que nada quedó roto**

Run: `python3 manage.py test core.tests -v 1`
Expected: `OK` (todos los tests pasan; ya no existen `PruebaDirigenteEquipoTest` ni `PruebaAgregarJugadorTest`)

- [ ] **Step 6: Commit**

```bash
git add core/views.py config/urls.py core/tests.py
git rm core/templates/core/prueba_dirigente_equipo.html core/templates/core/prueba_agregar_jugador.html
git commit -m "$(cat <<'EOF'
Elimina las vistas paralelas de Dirigente y agrega el test end-to-end

prueba_ver_como_dirigente y prueba_agregar_jugador (la réplica
simulada) ya no hacen falta: el usuario de prueba usa las vistas
reales (dashboard, gestionar_jugadores) a través del modo Dirigente
simulado. Se reemplazan sus tests por un flujo end-to-end completo:
activar → ver el dashboard real → fichar un jugador real → salir.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RHn9nvU9sj2GA39FdVhWbb
EOF
)"
```

---

## Task 9: Reorganiza "Gestor Administrativo" del dashboard en 3 bloques

**Files:**
- Modify: `core/templates/core/dashboard.html:395-409`
- Test: `core/tests.py`

**Interfaces:**
- Ninguna — cambio puramente visual/estructural, mismos `{% url %}` y clases `.admin-btn`/`.admin-grid` de siempre.

- [ ] **Step 1: Escribir el test que falla**

Añade al final de `core/tests.py`:

```python
class DashboardGestorAdministrativoAgrupadoTest(TestCase):
    def test_el_gestor_administrativo_esta_agrupado_en_tres_bloques(self):
        plan = PlanSuscripcion.objects.create(nombre="Plan Grupos", precio_mensual=Decimal("10.00"))
        organizador = User.objects.create_user("grupos1", password="pass12345")
        ComplejoDeportivo.objects.create(
            nombre="Cancha Grupos", slug="cancha-grupos", organizador=organizador, plan=plan,
        )
        self.client.login(username="grupos1", password="pass12345")

        response = self.client.get("/dashboard/")

        self.assertContains(response, "Competición")
        self.assertContains(response, "Fichajes y Cobros")
        self.assertContains(response, "Cancha y Sistema")
        for path in ['/configuracion/', '/torneos/', '/equipos/', '/programar/',
                     '/jugadores/', '/admin_jugadores/', '/finanzas/',
                     '/finanzas/caja-diaria/', '/medios/', '/admin_usuarios/']:
            self.assertContains(response, f'href="{path}"')
```

- [ ] **Step 2: Confirmar que falla**

Run: `python3 manage.py test core.tests.DashboardGestorAdministrativoAgrupadoTest -v 1`
Expected: `FAIL` — no existen los textos "Competición" / "Fichajes y Cobros" / "Cancha y Sistema" en el dashboard todavía.

- [ ] **Step 3: Implementar**

En `core/templates/core/dashboard.html`, reemplaza:

```html
    <h6 class="fw-bold text-muted text-uppercase small mb-3 ps-1">Gestor Administrativo</h6>
    <!-- ICONOS LINEALES APLICADOS -->
    <div class="admin-grid">
        <a href="{% url 'gestionar_configuracion' %}" class="admin-btn"><i class="bi bi-palette" style="color: #ec4899;"></i><span>Ajustes</span></a>
        <a href="{% url 'gestionar_torneos' %}" class="admin-btn"><i class="bi bi-trophy text-primary"></i><span>Torneos</span></a>
        <a href="{% url 'gestionar_equipos' %}" class="admin-btn"><i class="bi bi-shield text-info"></i><span>Equipos</span></a>
        <a href="{% url 'programar_partidos' %}" class="admin-btn"><i class="bi bi-calendar-event text-warning"></i><span>Fixture</span></a>
        <a href="{% url 'gestionar_jugadores' %}" class="admin-btn"><i class="bi bi-person-plus text-success"></i><span>Fichar</span></a>
        <a href="{% url 'admin_gestion_jugadores' %}" class="admin-btn"><i class="bi bi-people text-primary"></i><span>Jugadores</span></a>
        <a href="{% url 'gestionar_finanzas' %}" class="admin-btn"><i class="bi bi-cash-stack text-success"></i><span>Finanzas</span></a>
        <a href="{% url 'cierre_diario_caja' %}" class="admin-btn"><i class="bi bi-clock-history text-secondary"></i><span>Caja Diaria</span></a>
        <a href="{% url 'gestionar_medios' %}" class="admin-btn"><i class="bi bi-image text-danger"></i><span>Medios</span></a>
        <a href="{% url 'admin_gestion_usuarios' %}" class="admin-btn"><i class="bi bi-person-gear text-dark"></i><span>Usuarios</span></a>
    </div>
```

por:

```html
    <h6 class="fw-bold text-muted text-uppercase small mb-3 ps-1">Gestor Administrativo</h6>

    <div class="mb-3">
        <div class="text-muted fw-bold small mb-2 ps-1">Competición</div>
        <div class="admin-grid">
            <a href="{% url 'gestionar_torneos' %}" class="admin-btn"><i class="bi bi-trophy text-primary"></i><span>Torneos</span></a>
            <a href="{% url 'gestionar_equipos' %}" class="admin-btn"><i class="bi bi-shield text-info"></i><span>Equipos</span></a>
            <a href="{% url 'programar_partidos' %}" class="admin-btn"><i class="bi bi-calendar-event text-warning"></i><span>Fixture</span></a>
            <a href="{% url 'admin_gestion_jugadores' %}" class="admin-btn"><i class="bi bi-people text-primary"></i><span>Jugadores</span></a>
        </div>
    </div>

    <div class="mb-3">
        <div class="text-muted fw-bold small mb-2 ps-1">Fichajes y Cobros</div>
        <div class="admin-grid">
            <a href="{% url 'gestionar_jugadores' %}" class="admin-btn"><i class="bi bi-person-plus text-success"></i><span>Fichar</span></a>
            <a href="{% url 'gestionar_finanzas' %}" class="admin-btn"><i class="bi bi-cash-stack text-success"></i><span>Finanzas</span></a>
            <a href="{% url 'cierre_diario_caja' %}" class="admin-btn"><i class="bi bi-clock-history text-secondary"></i><span>Caja Diaria</span></a>
        </div>
    </div>

    <div class="mb-3">
        <div class="text-muted fw-bold small mb-2 ps-1">Cancha y Sistema</div>
        <div class="admin-grid">
            <a href="{% url 'gestionar_configuracion' %}" class="admin-btn"><i class="bi bi-palette" style="color: #ec4899;"></i><span>Ajustes</span></a>
            <a href="{% url 'gestionar_medios' %}" class="admin-btn"><i class="bi bi-image text-danger"></i><span>Medios</span></a>
            <a href="{% url 'admin_gestion_usuarios' %}" class="admin-btn"><i class="bi bi-person-gear text-dark"></i><span>Usuarios</span></a>
        </div>
    </div>
```

- [ ] **Step 4: Confirmar que pasa**

Run: `python3 manage.py test core.tests.DashboardGestorAdministrativoAgrupadoTest -v 1`
Expected: `OK` (1 test)

- [ ] **Step 5: Commit**

```bash
git add core/templates/core/dashboard.html core/tests.py
git commit -m "$(cat <<'EOF'
Agrupa "Gestor Administrativo" en 3 bloques coherentes

Los 10 íconos del panel de Organizador estaban en una sola fila
plana sin jerarquía. Ahora se agrupan en Competición (Torneos,
Equipos, Fixture, Jugadores), Fichajes y Cobros (Fichar, Finanzas,
Caja Diaria) y Cancha y Sistema (Ajustes, Medios, Usuarios) — mismos
links y mismo estilo .admin-btn, solo agrupados.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RHn9nvU9sj2GA39FdVhWbb
EOF
)"
```

---

## Task 10: Agrupa la navegación superior del Super Admin en "Panel SaaS"

**Files:**
- Modify: `core/templates/core/base.html:496-500`
- Test: `core/tests.py`

**Interfaces:**
- Ninguna — cambio puramente visual/estructural.

- [ ] **Step 1: Escribir el test que falla**

Añade al final de `core/tests.py`:

```python
class NavSuperAdminAgrupadaTest(TestCase):
    def test_el_menu_superadmin_agrupa_canchas_planes_y_roles_en_un_dropdown(self):
        User.objects.create_superuser("navgrupo1", password="pass12345")
        self.client.login(username="navgrupo1", password="pass12345")

        response = self.client.get("/nexus-admin/")

        self.assertContains(response, "Panel SaaS")
        self.assertContains(response, 'href="/nexus-admin/canchas/"')
        self.assertContains(response, 'href="/nexus-admin/planes/"')
        self.assertContains(response, 'href="/nexus-admin/pruebas/"')
        self.assertContains(response, 'href="/nexus-admin/"')
```

- [ ] **Step 2: Confirmar que falla**

Run: `python3 manage.py test core.tests.NavSuperAdminAgrupadaTest -v 1`
Expected: `FAIL` — el texto "Panel SaaS" no existe todavía en la barra de navegación.

- [ ] **Step 3: Implementar**

En `core/templates/core/base.html`, reemplaza:

```html
                        {% if user.is_superuser %}
                            <li class="nav-item"><a class="nav-link text-primary fw-medium" href="{% url 'dashboard_saas' %}">Control SaaS</a></li>
                            <li class="nav-item"><a class="nav-link text-primary fw-medium" href="{% url 'gestionar_canchas_saas' %}">Canchas</a></li>
                            <li class="nav-item"><a class="nav-link text-primary fw-medium" href="{% url 'gestionar_planes_saas' %}">Planes</a></li>
                            <li class="nav-item"><a class="nav-link text-primary fw-medium" href="{% url 'gestionar_roles_prueba' %}">Roles de Prueba</a></li>
                            
                        {% elif rol_nav_efectivo == 'ORG' %}
```

por:

```html
                        {% if user.is_superuser %}
                            <li class="nav-item"><a class="nav-link text-primary fw-medium" href="{% url 'dashboard_saas' %}">Control SaaS</a></li>
                            <li class="nav-item dropdown">
                                <a class="nav-link dropdown-toggle text-primary fw-medium" href="#" data-bs-toggle="dropdown">Panel SaaS</a>
                                <ul class="dropdown-menu">
                                    <li><a class="dropdown-item" href="{% url 'gestionar_canchas_saas' %}">Canchas</a></li>
                                    <li><a class="dropdown-item" href="{% url 'gestionar_planes_saas' %}">Planes</a></li>
                                    <li><a class="dropdown-item" href="{% url 'gestionar_roles_prueba' %}">Roles de Prueba</a></li>
                                </ul>
                            </li>

                        {% elif rol_nav_efectivo == 'ORG' %}
```

- [ ] **Step 4: Confirmar que pasa**

Run: `python3 manage.py test core.tests.NavSuperAdminAgrupadaTest -v 1`
Expected: `OK` (1 test)

- [ ] **Step 5: Commit**

```bash
git add core/templates/core/base.html core/tests.py
git commit -m "$(cat <<'EOF'
Agrupa Canchas/Planes/Roles de Prueba en un dropdown "Panel SaaS"

La barra de navegación del Super Admin tenía 4 links sueltos y se
veía apretada. Canchas, Planes y Roles de Prueba ahora viven en un
único dropdown "Panel SaaS", junto al link directo "Control SaaS".

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RHn9nvU9sj2GA39FdVhWbb
EOF
)"
```

---

## Task 11: Regresión completa

**Files:**
- Ninguno (solo verificación).

- [ ] **Step 1: Correr toda la suite**

Run: `python3 manage.py test core.tests -v 1`
Expected: `OK`, todos los tests pasan (los ~88 preexistentes + todos los agregados en este plan).

- [ ] **Step 2: Verificación manual en el navegador**

Levanta el servidor local (`python3 manage.py runserver`) y repite en vivo, como usuario de prueba, el flujo: Super Admin asigna el Rol de Prueba → el usuario entra a "Dirigente de Equipo" → elige un equipo → confirma que ve el dashboard/fichaje reales (no una réplica) → ficha un jugador → sale del modo Dirigente → confirma que el banner, la nav y el "Gestor Administrativo" agrupado se ven bien en las 3 superficies rediseñadas.

- [ ] **Step 3: Actualizar el spec si algo cambió durante la implementación**

Si algún detalle del código terminó siendo distinto de lo descrito en `docs/superpowers/specs/2026-09-07-modo-dirigente-simulado-y-navegacion-design.md` (nombres de variables, rutas), actualiza el spec para que quede como documentación fiel de lo implementado.

- [ ] **Step 4: Commit final (si el Step 3 generó cambios)**

```bash
git add docs/superpowers/specs/2026-09-07-modo-dirigente-simulado-y-navegacion-design.md
git commit -m "$(cat <<'EOF'
Actualiza el spec con los ajustes finales de la implementación

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RHn9nvU9sj2GA39FdVhWbb
EOF
)"
```
