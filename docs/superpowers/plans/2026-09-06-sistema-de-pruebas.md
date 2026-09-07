# Sistema de Pruebas (Rol de Prueba) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar al Super Admin (`is_superuser`) la capacidad de asignar/quitar un "Rol de Prueba" a cualquier usuario elegible, que le da un entorno de demostración aislado (cancha demo con datos precargados) donde puede operar casi como un organizador real sin afectar jamás datos reales ni los de otros usuarios de prueba.

**Architecture:** Un "entorno de prueba" es simplemente otro `ComplejoDeportivo` (tenant), marcado `es_demo=True`, del cual el usuario de prueba es `organizador` — exactamente igual que un dueño real. Esto reutiliza el 100% del sistema de scoping multi-tenant ya existente (`obtener_mi_complejo`, `es_organizador`, etc.) sin tocarlo. Revocar el rol es un `DELETE` en cascada sobre esa cancha.

**Tech Stack:** Django 6.0.1, `python3 manage.py test` (Django `TestCase` + `self.client`, estilo ya usado en `core/tests.py`), Bootstrap 5 + Bootstrap Icons (ya cargados en `core/templates/core/base.html`).

**Spec:** `docs/superpowers/specs/2026-09-06-sistema-de-pruebas-design.md`

## Global Constraints

- El Rol de Prueba **solo** se puede asignar a un usuario que **no** sea ya `organizador` de una cancha real (`ComplejoDeportivo.objects.filter(organizador=usuario).exists()` debe estar vacío antes de asignar). Si ya tiene una, se rechaza con un mensaje claro — nunca se lanza una excepción no controlada.
- Ninguna vista, formulario ni plantilla **real** (no relacionada a "prueba") se modifica, salvo el único cambio aditivo explícito al queryset de `dashboard_saas` (Task 7) y la extensión aditiva del context processor (Task 8).
- Todo dato demo se crea con ORM directo (`Model.objects.create(...)`), no vía `ModelForm`/`full_clean()` — así los datos de fixture (cédulas sintéticas, etc.) no necesitan pasar los validadores de negocio pensados para gente real.
- Todas las vistas nuevas bajo `/prueba/...` deben verificar que el `equipo`/complejo consultado pertenezca a la cancha demo del usuario logueado (`torneo__complejo=mi_complejo_demo`), nunca confiar solo en el ID de la URL.
- Comandos de test siempre con `python3` (no `python` — no existe en este entorno), ej: `python3 manage.py test core.tests.NombreClase -v 1`.

---

## Task 1: Modelo — campos `es_demo` y `fecha_asignacion_prueba`

**Files:**
- Modify: `core/models.py:53-74` (clase `ComplejoDeportivo`)
- Create: `core/migrations/0027_complejodeportivo_es_demo_and_more.py`
- Test: `core/tests.py`

**Interfaces:**
- Produces: `ComplejoDeportivo.es_demo` (bool, default `False`), `ComplejoDeportivo.fecha_asignacion_prueba` (datetime o `None`). Todas las tareas siguientes dependen de estos dos campos.

- [ ] **Step 1: Escribir el test que falla**

Añade al final de `core/tests.py`:

```python
class ComplejoDeportivoEsDemoTest(TestCase):
    def test_es_demo_por_defecto_es_false(self):
        plan = PlanSuscripcion.objects.create(nombre="Plan X", precio_mensual=Decimal("10.00"))
        organizador = User.objects.create_user("dueno_real", password="pass12345")
        complejo = ComplejoDeportivo.objects.create(
            nombre="Cancha Real", slug="cancha-real", organizador=organizador, plan=plan,
        )
        self.assertFalse(complejo.es_demo)
        self.assertIsNone(complejo.fecha_asignacion_prueba)

    def test_puede_marcar_como_demo_con_fecha_de_asignacion(self):
        plan = PlanSuscripcion.objects.create(nombre="Plan Y", precio_mensual=Decimal("0.00"))
        usuario = User.objects.create_user("usuario_demo", password="pass12345")
        ahora = timezone.now()
        complejo = ComplejoDeportivo.objects.create(
            nombre="Cancha Demo", slug="cancha-demo", organizador=usuario, plan=plan,
            es_demo=True, fecha_asignacion_prueba=ahora,
        )
        self.assertTrue(complejo.es_demo)
        self.assertEqual(complejo.fecha_asignacion_prueba, ahora)
```

- [ ] **Step 2: Confirmar que falla**

Run: `python3 manage.py test core.tests.ComplejoDeportivoEsDemoTest -v 1`
Expected: `FAIL` — `TypeError: ComplejoDeportivo() got unexpected keyword arguments: 'es_demo'` (o similar, el campo no existe todavía).

- [ ] **Step 3: Agregar los campos al modelo**

En `core/models.py`, dentro de `class ComplejoDeportivo(models.Model):`, justo después de la línea `telefono_contacto = models.CharField(max_length=15, blank=True, null=True)` (línea 63), agrega:

```python
    es_demo = models.BooleanField(default=False, verbose_name="Es entorno de prueba (demo)")
    fecha_asignacion_prueba = models.DateTimeField(null=True, blank=True, verbose_name="Fecha de asignación del Rol de Prueba")
```

- [ ] **Step 4: Generar y aplicar la migración**

Run: `python3 manage.py makemigrations core`

Debe generar un archivo nuevo en `core/migrations/` (nombre autogenerado, probablemente
`0027_complejodeportivo_es_demo_and_more.py`) con contenido equivalente a:

```python
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0026_configuracion_logo_sistema'),
    ]

    operations = [
        migrations.AddField(
            model_name='complejodeportivo',
            name='es_demo',
            field=models.BooleanField(default=False, verbose_name='Es entorno de prueba (demo)'),
        ),
        migrations.AddField(
            model_name='complejodeportivo',
            name='fecha_asignacion_prueba',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Fecha de asignación del Rol de Prueba'),
        ),
    ]
```

Si el nombre o el orden de las operaciones generadas difiere, está bien — lo importante es
que ambos campos queden agregados. Luego aplica: `python3 manage.py migrate core`

- [ ] **Step 5: Confirmar que el test pasa**

Run: `python3 manage.py test core.tests.ComplejoDeportivoEsDemoTest -v 1`
Expected: `OK` (2 tests)

- [ ] **Step 6: Commit**

```bash
git add core/models.py core/migrations/ core/tests.py
git commit -m "$(cat <<'EOF'
Agrega campos es_demo y fecha_asignacion_prueba a ComplejoDeportivo

Base para el Sistema de Pruebas: marcan qué canchas son entornos de
demostración aislados en vez de clientes reales.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `core/services/pruebas.py` — crear el complejo demo base (sin datos deportivos aún)

**Files:**
- Create: `core/services/__init__.py`
- Create: `core/services/pruebas.py`
- Test: `core/tests.py`

**Interfaces:**
- Consumes: `ComplejoDeportivo.es_demo`, `ComplejoDeportivo.fecha_asignacion_prueba` (Task 1).
- Produces: `crear_entorno_prueba(usuario) -> ComplejoDeportivo` (lanza `ValueError` si `usuario` ya es `organizador` de cualquier cancha). `obtener_o_crear_plan_demo() -> PlanSuscripcion`. Las tareas 3, 4, 5 y 6 importan y extienden estas dos funciones.

- [ ] **Step 1: Escribir el test que falla**

Añade al final de `core/tests.py`:

```python
from .services.pruebas import crear_entorno_prueba, obtener_o_crear_plan_demo


class CrearEntornoPruebaBaseTest(TestCase):
    def test_crea_complejo_demo_propiedad_del_usuario(self):
        usuario = User.objects.create_user("tester1", password="pass12345")

        complejo = crear_entorno_prueba(usuario)

        self.assertTrue(complejo.es_demo)
        self.assertEqual(complejo.organizador, usuario)
        self.assertTrue(complejo.activo)
        self.assertIsNone(complejo.fecha_vencimiento)
        self.assertIsNotNone(complejo.fecha_asignacion_prueba)
        self.assertTrue(RolComplejo.objects.filter(usuario=usuario, complejo=complejo, rol="ORG").exists())

    def test_usa_un_plan_demo_con_limites_generosos(self):
        usuario = User.objects.create_user("tester2", password="pass12345")

        complejo = crear_entorno_prueba(usuario)

        self.assertEqual(complejo.plan.nombre, "Plan Demo (Prueba)")
        self.assertGreaterEqual(complejo.plan.max_jugadores, 36)

    def test_reutiliza_el_mismo_plan_demo_entre_usuarios(self):
        usuario1 = User.objects.create_user("tester3", password="pass12345")
        usuario2 = User.objects.create_user("tester4", password="pass12345")

        complejo1 = crear_entorno_prueba(usuario1)
        complejo2 = crear_entorno_prueba(usuario2)

        self.assertEqual(complejo1.plan_id, complejo2.plan_id)
        self.assertEqual(PlanSuscripcion.objects.filter(nombre="Plan Demo (Prueba)").count(), 1)

    def test_no_permite_asignar_a_quien_ya_es_organizador_de_una_cancha_real(self):
        plan = PlanSuscripcion.objects.create(nombre="Plan Z", precio_mensual=Decimal("10.00"))
        dueno_real = User.objects.create_user("dueno_real2", password="pass12345")
        ComplejoDeportivo.objects.create(
            nombre="Cancha Real 2", slug="cancha-real-2", organizador=dueno_real, plan=plan,
        )

        with self.assertRaises(ValueError):
            crear_entorno_prueba(dueno_real)

    def test_no_permite_asignar_dos_veces_al_mismo_usuario_sin_revocar(self):
        usuario = User.objects.create_user("tester5", password="pass12345")
        crear_entorno_prueba(usuario)

        with self.assertRaises(ValueError):
            crear_entorno_prueba(usuario)
```

- [ ] **Step 2: Confirmar que falla**

Run: `python3 manage.py test core.tests.CrearEntornoPruebaBaseTest -v 1`
Expected: `FAIL` — `ModuleNotFoundError: No module named 'core.services'`

- [ ] **Step 3: Implementar**

Crea `core/services/__init__.py` (vacío):

```python
```

Crea `core/services/pruebas.py`:

```python
from decimal import Decimal

from django.utils import timezone
from django.utils.text import slugify

from ..models import ComplejoDeportivo, PlanSuscripcion, RolComplejo

NOMBRE_PLAN_DEMO = "Plan Demo (Prueba)"


def obtener_o_crear_plan_demo():
    """Plan de suscripción reservado para canchas demo, con límites
    generosos para que un usuario de prueba pueda operar sin toparse
    con los topes pensados para un cliente real."""
    plan, _ = PlanSuscripcion.objects.get_or_create(
        nombre=NOMBRE_PLAN_DEMO,
        defaults={
            "costo_inscripcion": Decimal("0.00"),
            "precio_mensual": Decimal("0.00"),
            "max_torneos": 5,
            "max_categorias_por_torneo": 5,
            "max_jugadores": 100,
        },
    )
    return plan


def crear_entorno_prueba(usuario):
    """Crea una cancha demo (ComplejoDeportivo con es_demo=True), propiedad
    exclusiva de `usuario`. Lanza ValueError si el usuario ya es dueño de
    cualquier cancha (real o demo) — ComplejoDeportivo.organizador es
    OneToOne, así que no puede tener dos."""
    if ComplejoDeportivo.objects.filter(organizador=usuario).exists():
        raise ValueError(
            f"{usuario.username} ya es dueño de una cancha y no puede recibir el Rol de Prueba."
        )

    plan_demo = obtener_o_crear_plan_demo()
    slug = slugify(f"demo-{usuario.username}-{usuario.id}")

    complejo = ComplejoDeportivo.objects.create(
        nombre=f"Demo - {usuario.username}",
        slug=slug,
        organizador=usuario,
        plan=plan_demo,
        activo=True,
        fecha_vencimiento=None,
        es_demo=True,
        fecha_asignacion_prueba=timezone.now(),
    )
    RolComplejo.objects.create(usuario=usuario, complejo=complejo, rol="ORG")

    return complejo
```

- [ ] **Step 4: Confirmar que pasa**

Run: `python3 manage.py test core.tests.CrearEntornoPruebaBaseTest -v 1`
Expected: `OK` (5 tests)

- [ ] **Step 5: Commit**

```bash
git add core/services/ core/tests.py
git commit -m "$(cat <<'EOF'
Agrega crear_entorno_prueba: cancha demo base propiedad del usuario

Primer paso del Sistema de Pruebas: crea el ComplejoDeportivo demo
(sin datos deportivos aún) y bloquea la asignación a quien ya sea
dueño de una cancha real.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Sembrar 6 equipos y 6 jugadores por equipo

**Files:**
- Modify: `core/services/pruebas.py`
- Test: `core/tests.py`

**Interfaces:**
- Consumes: `crear_entorno_prueba` (Task 2).
- Produces: `crear_entorno_prueba` ahora también crea `Categoria`, `Torneo`, 6 `Equipo` y 36 `Jugador`. Nueva función interna `_sembrar_equipos_y_jugadores(torneo, usuario) -> list[Equipo]` (orden estable: `equipos[0]`..`equipos[5]`), usada por la Task 4.

- [ ] **Step 1: Escribir el test que falla**

Añade al final de `core/tests.py`:

```python
class CrearEntornoPruebaEquiposYJugadoresTest(TestCase):
    def test_crea_un_torneo_con_seis_equipos(self):
        usuario = User.objects.create_user("tester6", password="pass12345")

        complejo = crear_entorno_prueba(usuario)

        torneo = Torneo.objects.get(complejo=complejo)
        self.assertEqual(Equipo.objects.filter(torneo=torneo).count(), 6)

    def test_cada_equipo_tiene_seis_jugadores_con_dorsales_del_uno_al_seis(self):
        usuario = User.objects.create_user("tester7", password="pass12345")

        complejo = crear_entorno_prueba(usuario)

        for equipo in Equipo.objects.filter(torneo__complejo=complejo):
            dorsales = sorted(equipo.jugadores.values_list("dorsal", flat=True))
            self.assertEqual(dorsales, [1, 2, 3, 4, 5, 6])

    def test_36_jugadores_con_cedulas_unicas(self):
        usuario = User.objects.create_user("tester8", password="pass12345")

        complejo = crear_entorno_prueba(usuario)

        jugadores = Jugador.objects.filter(equipo__torneo__complejo=complejo)
        self.assertEqual(jugadores.count(), 36)
        cedulas = list(jugadores.values_list("cedula", flat=True))
        self.assertEqual(len(cedulas), len(set(cedulas)))

    def test_equipos_estan_aprobados_y_el_usuario_de_prueba_es_el_dirigente(self):
        usuario = User.objects.create_user("tester9", password="pass12345")

        complejo = crear_entorno_prueba(usuario)

        for equipo in Equipo.objects.filter(torneo__complejo=complejo):
            self.assertEqual(equipo.estado_inscripcion, "APROBADO")
            self.assertEqual(equipo.dirigente, usuario)
            self.assertGreater(equipo.cupos_disponibles, 0)
```

- [ ] **Step 2: Confirmar que falla**

Run: `python3 manage.py test core.tests.CrearEntornoPruebaEquiposYJugadoresTest -v 1`
Expected: `FAIL` — `Torneo matching query does not exist` (el torneo/equipos todavía no se crean).

- [ ] **Step 3: Implementar**

En `core/services/pruebas.py`, actualiza el import y agrega la siembra:

```python
from decimal import Decimal

from django.utils import timezone
from django.utils.text import slugify

from ..models import (
    Categoria, ComplejoDeportivo, Equipo, Jugador, PlanSuscripcion,
    RolComplejo, Torneo,
)

NOMBRE_PLAN_DEMO = "Plan Demo (Prueba)"


def obtener_o_crear_plan_demo():
    """Plan de suscripción reservado para canchas demo, con límites
    generosos para que un usuario de prueba pueda operar sin toparse
    con los topes pensados para un cliente real."""
    plan, _ = PlanSuscripcion.objects.get_or_create(
        nombre=NOMBRE_PLAN_DEMO,
        defaults={
            "costo_inscripcion": Decimal("0.00"),
            "precio_mensual": Decimal("0.00"),
            "max_torneos": 5,
            "max_categorias_por_torneo": 5,
            "max_jugadores": 100,
        },
    )
    return plan


def crear_entorno_prueba(usuario):
    """Crea una cancha demo (ComplejoDeportivo con es_demo=True), propiedad
    exclusiva de `usuario`, con un torneo y datos deportivos precargados.
    Lanza ValueError si el usuario ya es dueño de cualquier cancha (real o
    demo) — ComplejoDeportivo.organizador es OneToOne, así que no puede
    tener dos."""
    if ComplejoDeportivo.objects.filter(organizador=usuario).exists():
        raise ValueError(
            f"{usuario.username} ya es dueño de una cancha y no puede recibir el Rol de Prueba."
        )

    plan_demo = obtener_o_crear_plan_demo()
    slug = slugify(f"demo-{usuario.username}-{usuario.id}")

    complejo = ComplejoDeportivo.objects.create(
        nombre=f"Demo - {usuario.username}",
        slug=slug,
        organizador=usuario,
        plan=plan_demo,
        activo=True,
        fecha_vencimiento=None,
        es_demo=True,
        fecha_asignacion_prueba=timezone.now(),
    )
    RolComplejo.objects.create(usuario=usuario, complejo=complejo, rol="ORG")

    categoria = Categoria.objects.create(complejo=complejo, nombre="Categoría Demo")
    torneo = Torneo.objects.create(
        complejo=complejo,
        nombre="Torneo Demo",
        organizador=usuario,
        categoria=categoria,
        inscripcion_abierta=True,
    )

    _sembrar_equipos_y_jugadores(torneo, usuario)

    return complejo


def _sembrar_equipos_y_jugadores(torneo, usuario):
    equipos = []
    contador_jugador = 0
    for i in range(1, 7):
        equipo = Equipo.objects.create(
            torneo=torneo,
            dirigente=usuario,
            nombre=f"Equipo Demo {i}",
            estado_inscripcion="APROBADO",
            pagado=True,
            cupos_pagados=10,
        )
        for dorsal in range(1, 7):
            contador_jugador += 1
            Jugador.objects.create(
                equipo=equipo,
                nombres=f"Jugador {dorsal} - Equipo {i}",
                dorsal=dorsal,
                cedula=f"90{contador_jugador:08d}",
            )
        equipos.append(equipo)
    return equipos
```

- [ ] **Step 4: Confirmar que pasa**

Run: `python3 manage.py test core.tests.CrearEntornoPruebaEquiposYJugadoresTest -v 1`
Expected: `OK` (4 tests)

También vuelve a correr la tarea anterior para asegurarte de no haber roto nada:
Run: `python3 manage.py test core.tests.CrearEntornoPruebaBaseTest -v 1`
Expected: `OK` (5 tests)

- [ ] **Step 5: Commit**

```bash
git add core/services/pruebas.py core/tests.py
git commit -m "$(cat <<'EOF'
Siembra torneo, 6 equipos y 36 jugadores en el entorno de prueba

crear_entorno_prueba ahora genera un Torneo Demo con 6 Equipos
aprobados (dirigidos por el propio usuario de prueba) y 6 Jugadores
por equipo con dorsales 1-6 y cédulas sintéticas únicas.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Sembrar partidos jugados (goles + tarjetas + multas) y partidos futuros

**Files:**
- Modify: `core/services/pruebas.py`
- Test: `core/tests.py`

**Interfaces:**
- Consumes: `_sembrar_equipos_y_jugadores` (Task 3), devuelve lista ordenada de 6 `Equipo`.
- Produces: `crear_entorno_prueba` ahora también crea 3 `Partido` jugados (con `DetallePartido` de gol y al menos una tarjeta amarilla y una roja, con su `Sancion` correspondiente) y 3 `Partido` futuros (`estado='PROG'`).

- [ ] **Step 1: Escribir el test que falla**

Añade al final de `core/tests.py`:

```python
class CrearEntornoPruebaPartidosTest(TestCase):
    def test_crea_partidos_jugados_y_partidos_futuros(self):
        usuario = User.objects.create_user("tester10", password="pass12345")

        complejo = crear_entorno_prueba(usuario)

        partidos = Partido.objects.filter(torneo__complejo=complejo)
        self.assertEqual(partidos.filter(estado="JUG").count(), 3)
        self.assertEqual(partidos.filter(estado="PROG").count(), 3)

    def test_partidos_futuros_tienen_fecha_en_el_futuro_y_sin_resultado(self):
        usuario = User.objects.create_user("tester11", password="pass12345")

        complejo = crear_entorno_prueba(usuario)

        ahora = timezone.now()
        for partido in Partido.objects.filter(torneo__complejo=complejo, estado="PROG"):
            self.assertIsNotNone(partido.fecha_hora)
            self.assertGreater(partido.fecha_hora, ahora)
            self.assertEqual(partido.goles_local, 0)
            self.assertEqual(partido.goles_visita, 0)

    def test_hay_al_menos_una_tarjeta_amarilla_y_una_roja_con_su_multa(self):
        usuario = User.objects.create_user("tester12", password="pass12345")

        complejo = crear_entorno_prueba(usuario)

        self.assertTrue(DetallePartido.objects.filter(
            partido__torneo__complejo=complejo, tipo="TA",
        ).exists())
        self.assertTrue(DetallePartido.objects.filter(
            partido__torneo__complejo=complejo, tipo="TR",
        ).exists())
        self.assertTrue(Sancion.objects.filter(
            torneo__complejo=complejo, tipo="AMARILLA",
        ).exists())
        self.assertTrue(Sancion.objects.filter(
            torneo__complejo=complejo, tipo="ROJA",
        ).exists())

    def test_tarjeta_roja_incrementa_el_contador_del_jugador(self):
        usuario = User.objects.create_user("tester13", password="pass12345")

        complejo = crear_entorno_prueba(usuario)

        jugador_expulsado = Jugador.objects.get(
            equipo__torneo__complejo=complejo,
            detallepartido__tipo="TR",
        )
        self.assertEqual(jugador_expulsado.rojas_directas_acumuladas, 1)

    def test_partidos_jugados_tienen_goles_registrados_como_detalle(self):
        usuario = User.objects.create_user("tester14", password="pass12345")

        complejo = crear_entorno_prueba(usuario)

        goles = DetallePartido.objects.filter(partido__torneo__complejo=complejo, tipo="GOL")
        self.assertGreaterEqual(goles.count(), 4)
```

- [ ] **Step 2: Confirmar que falla**

Run: `python3 manage.py test core.tests.CrearEntornoPruebaPartidosTest -v 1`
Expected: `FAIL` — los `assertEqual`/`assertTrue` de conteo de `Partido`/`Sancion` fallan (todavía en 0).

- [ ] **Step 3: Implementar**

En `core/services/pruebas.py`, actualiza el import y agrega la siembra de partidos.
Reemplaza el bloque de imports por:

```python
from decimal import Decimal

from django.utils import timezone
from django.utils.text import slugify

from ..models import (
    Categoria, ComplejoDeportivo, DetallePartido, Equipo, Jugador, Partido,
    PlanSuscripcion, RolComplejo, Sancion, Torneo,
)
```

Dentro de `crear_entorno_prueba`, reemplaza la línea `_sembrar_equipos_y_jugadores(torneo, usuario)` por:

```python
    equipos = _sembrar_equipos_y_jugadores(torneo, usuario)
    _sembrar_partidos(torneo, equipos)
```

Y agrega, al final del archivo, después de `_sembrar_equipos_y_jugadores`:

```python
def _sembrar_partidos(torneo, equipos):
    ahora = timezone.now()

    _crear_partido_jugado(
        torneo, equipos[0], equipos[1], numero_fecha=1,
        goles_local=2, goles_visita=1,
        goleador_local=equipos[0].jugadores.get(dorsal=1),
        goleador_visita=equipos[1].jugadores.get(dorsal=1),
        tarjeta_amarilla_a=equipos[1].jugadores.get(dorsal=2),
    )
    _crear_partido_jugado(
        torneo, equipos[2], equipos[3], numero_fecha=1,
        goles_local=1, goles_visita=1,
        goleador_local=equipos[2].jugadores.get(dorsal=1),
        goleador_visita=equipos[3].jugadores.get(dorsal=1),
        tarjeta_roja_a=equipos[3].jugadores.get(dorsal=3),
    )
    _crear_partido_jugado(
        torneo, equipos[4], equipos[5], numero_fecha=1,
        goles_local=3, goles_visita=0,
        goleador_local=equipos[4].jugadores.get(dorsal=1),
    )

    Partido.objects.create(
        torneo=torneo, equipo_local=equipos[0], equipo_visita=equipos[2],
        numero_fecha=2, fecha_hora=ahora + timezone.timedelta(days=7), estado="PROG",
    )
    Partido.objects.create(
        torneo=torneo, equipo_local=equipos[1], equipo_visita=equipos[4],
        numero_fecha=2, fecha_hora=ahora + timezone.timedelta(days=8), estado="PROG",
    )
    Partido.objects.create(
        torneo=torneo, equipo_local=equipos[3], equipo_visita=equipos[5],
        numero_fecha=2, fecha_hora=ahora + timezone.timedelta(days=9), estado="PROG",
    )


def _crear_partido_jugado(torneo, equipo_local, equipo_visita, numero_fecha,
                           goles_local, goles_visita,
                           goleador_local=None, goleador_visita=None,
                           tarjeta_amarilla_a=None, tarjeta_roja_a=None):
    partido = Partido.objects.create(
        torneo=torneo, equipo_local=equipo_local, equipo_visita=equipo_visita,
        numero_fecha=numero_fecha, estado="JUG",
        goles_local=goles_local, goles_visita=goles_visita,
    )

    if goleador_local:
        DetallePartido.objects.create(
            partido=partido, jugador=goleador_local, equipo_incidencia=equipo_local, tipo="GOL",
        )
    if goleador_visita:
        DetallePartido.objects.create(
            partido=partido, jugador=goleador_visita, equipo_incidencia=equipo_visita, tipo="GOL",
        )
    if tarjeta_amarilla_a:
        _aplicar_tarjeta(partido, tarjeta_amarilla_a, "TA", torneo.costo_amarilla)
    if tarjeta_roja_a:
        _aplicar_tarjeta(partido, tarjeta_roja_a, "TR", torneo.costo_roja)

    return partido


def _aplicar_tarjeta(partido, jugador, tipo, monto):
    equipo = jugador.equipo
    DetallePartido.objects.create(
        partido=partido, jugador=jugador, equipo_incidencia=equipo, tipo=tipo,
    )
    Sancion.objects.create(
        torneo=partido.torneo, equipo=equipo, jugador=jugador, partido=partido,
        tipo="AMARILLA" if tipo == "TA" else "ROJA",
        monto=monto,
        descripcion=f"Tarjeta {'amarilla' if tipo == 'TA' else 'roja'} - {jugador.nombres}",
    )
    if tipo == "TR":
        jugador.rojas_directas_acumuladas += 1
        jugador.save(update_fields=["rojas_directas_acumuladas"])
```

- [ ] **Step 4: Confirmar que pasa**

Run: `python3 manage.py test core.tests.CrearEntornoPruebaPartidosTest -v 1`
Expected: `OK` (5 tests)

Vuelve a correr las tareas 2 y 3 para confirmar que nada se rompió:
Run: `python3 manage.py test core.tests.CrearEntornoPruebaBaseTest core.tests.CrearEntornoPruebaEquiposYJugadoresTest -v 1`
Expected: `OK` (9 tests)

- [ ] **Step 5: Commit**

```bash
git add core/services/pruebas.py core/tests.py
git commit -m "$(cat <<'EOF'
Siembra partidos jugados con goles/tarjetas y partidos futuros

crear_entorno_prueba ahora genera 3 partidos ya jugados (con goles,
una tarjeta amarilla y una roja, cada una con su Sancion y el
contador de rojas del jugador actualizado) y 3 partidos futuros
programados — datos suficientes para demostrar vocalía, finanzas y
estadísticas.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `eliminar_entorno_prueba` — revocar y borrar todo en cascada

**Files:**
- Modify: `core/services/pruebas.py`
- Test: `core/tests.py`

**Interfaces:**
- Consumes: `crear_entorno_prueba` (Tasks 2-4).
- Produces: `eliminar_entorno_prueba(usuario) -> None`. La Task 6 (vista del Super Admin) la usa directamente.

- [ ] **Step 1: Escribir el test que falla**

Añade al final de `core/tests.py`:

```python
class EliminarEntornoPruebaTest(TestCase):
    def test_borra_el_complejo_demo_y_todos_sus_datos(self):
        usuario = User.objects.create_user("tester15", password="pass12345")
        complejo = crear_entorno_prueba(usuario)
        complejo_id = complejo.id

        eliminar_entorno_prueba(usuario)

        self.assertFalse(ComplejoDeportivo.objects.filter(id=complejo_id).exists())
        self.assertFalse(Torneo.objects.filter(complejo_id=complejo_id).exists())
        self.assertFalse(Equipo.objects.filter(torneo__complejo_id=complejo_id).exists())
        self.assertFalse(Jugador.objects.filter(equipo__torneo__complejo_id=complejo_id).exists())
        self.assertFalse(Partido.objects.filter(torneo__complejo_id=complejo_id).exists())
        self.assertFalse(Sancion.objects.filter(torneo__complejo_id=complejo_id).exists())
        self.assertFalse(RolComplejo.objects.filter(complejo_id=complejo_id).exists())

    def test_no_afecta_cancha_real_del_mismo_usuario_si_no_es_demo(self):
        # Caso defensivo: aunque hoy no debería poder coexistir (organizador
        # es OneToOne), confirmamos que el filtro es siempre es_demo=True.
        plan = PlanSuscripcion.objects.create(nombre="Plan W", precio_mensual=Decimal("10.00"))
        usuario = User.objects.create_user("dueno_real3", password="pass12345")
        cancha_real = ComplejoDeportivo.objects.create(
            nombre="Cancha Real 3", slug="cancha-real-3", organizador=usuario, plan=plan,
            es_demo=False,
        )

        eliminar_entorno_prueba(usuario)

        self.assertTrue(ComplejoDeportivo.objects.filter(id=cancha_real.id).exists())

    def test_es_idempotente_si_el_usuario_no_tiene_entorno_de_prueba(self):
        usuario = User.objects.create_user("tester16", password="pass12345")

        eliminar_entorno_prueba(usuario)  # no debe lanzar excepción

        self.assertFalse(ComplejoDeportivo.objects.filter(organizador=usuario).exists())

    def test_reasignar_despues_de_revocar_genera_datos_frescos(self):
        usuario = User.objects.create_user("tester17", password="pass12345")
        complejo1 = crear_entorno_prueba(usuario)
        equipo1_ids = set(Equipo.objects.filter(torneo__complejo=complejo1).values_list("id", flat=True))

        eliminar_entorno_prueba(usuario)
        complejo2 = crear_entorno_prueba(usuario)
        equipo2_ids = set(Equipo.objects.filter(torneo__complejo=complejo2).values_list("id", flat=True))

        self.assertNotEqual(complejo1.id, complejo2.id)
        self.assertEqual(equipo1_ids.intersection(equipo2_ids), set())
        self.assertEqual(Equipo.objects.filter(torneo__complejo=complejo2).count(), 6)
```

- [ ] **Step 2: Confirmar que falla**

Run: `python3 manage.py test core.tests.EliminarEntornoPruebaTest -v 1`
Expected: `FAIL` — `ImportError: cannot import name 'eliminar_entorno_prueba'`

- [ ] **Step 3: Implementar**

Actualiza el `import` en `core/tests.py`:

```python
from .services.pruebas import crear_entorno_prueba, eliminar_entorno_prueba, obtener_o_crear_plan_demo
```

Agrega al final de `core/services/pruebas.py`:

```python
def eliminar_entorno_prueba(usuario):
    """Borra la cancha demo de `usuario`, si la tiene. La cascada ya
    declarada en el modelo (Torneo, Equipo, Jugador, Partido, Sancion,
    DetallePartido, RolComplejo, etc.) se encarga de borrar absolutamente
    todo lo que dependía de esa cancha. Idempotente: si no tiene entorno
    de prueba, no hace nada."""
    ComplejoDeportivo.objects.filter(organizador=usuario, es_demo=True).delete()
```

- [ ] **Step 4: Confirmar que pasa**

Run: `python3 manage.py test core.tests.EliminarEntornoPruebaTest -v 1`
Expected: `OK` (4 tests)

- [ ] **Step 5: Commit**

```bash
git add core/services/pruebas.py core/tests.py
git commit -m "$(cat <<'EOF'
Agrega eliminar_entorno_prueba: revoca el Rol de Prueba en cascada

Borra el ComplejoDeportivo demo del usuario; el CASCADE ya declarado
en el modelo limpia automáticamente todo lo que dependía de él. Es
idempotente y no toca canchas reales.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Panel del Super Admin — asignar/quitar el Rol de Prueba

**Files:**
- Modify: `core/views.py` (agregar imports y la vista al final del archivo)
- Modify: `config/urls.py:126` (después de la línea `path('nexus-admin/pagos/', ...)`)
- Modify: `core/templates/core/base.html:499` (después del link "Planes")
- Create: `core/templates/core/gestionar_roles_prueba.html`
- Test: `core/tests.py`

**Interfaces:**
- Consumes: `crear_entorno_prueba`, `eliminar_entorno_prueba` (Tasks 2-5).
- Produces: URL `gestionar_roles_prueba` (GET/POST). Ninguna tarea posterior depende de sus internals, solo de la URL/vista existiendo.

- [ ] **Step 1: Escribir el test que falla**

Añade al final de `core/tests.py`:

```python
class GestionarRolesPruebaTest(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_superuser("elsuper", password="pass12345")
        self.candidato = User.objects.create_user("candidato1", password="pass12345")

    def test_usuario_normal_no_puede_acceder(self):
        self.client.login(username="candidato1", password="pass12345")
        response = self.client.get("/nexus-admin/pruebas/")
        self.assertNotEqual(response.status_code, 200)

    def test_superadmin_puede_asignar_el_rol(self):
        self.client.login(username="elsuper", password="pass12345")

        response = self.client.post("/nexus-admin/pruebas/", {
            "usuario_id": self.candidato.id, "asignar": "1",
        })

        self.assertEqual(response.status_code, 302)
        self.assertTrue(ComplejoDeportivo.objects.filter(organizador=self.candidato, es_demo=True).exists())

    def test_superadmin_puede_quitar_el_rol(self):
        crear_entorno_prueba(self.candidato)
        self.client.login(username="elsuper", password="pass12345")

        response = self.client.post("/nexus-admin/pruebas/", {
            "usuario_id": self.candidato.id, "quitar": "1",
        })

        self.assertEqual(response.status_code, 302)
        self.assertFalse(ComplejoDeportivo.objects.filter(organizador=self.candidato).exists())

    def test_no_puede_asignar_a_un_organizador_real_via_el_panel(self):
        plan = PlanSuscripcion.objects.create(nombre="Plan V", precio_mensual=Decimal("10.00"))
        ComplejoDeportivo.objects.create(
            nombre="Cancha Real 4", slug="cancha-real-4", organizador=self.candidato, plan=plan,
        )
        self.client.login(username="elsuper", password="pass12345")

        self.client.post("/nexus-admin/pruebas/", {
            "usuario_id": self.candidato.id, "asignar": "1",
        })

        self.assertEqual(ComplejoDeportivo.objects.filter(organizador=self.candidato).count(), 1)
        self.assertFalse(ComplejoDeportivo.objects.filter(organizador=self.candidato, es_demo=True).exists())

    def test_la_lista_muestra_el_estado_de_cada_usuario(self):
        crear_entorno_prueba(self.candidato)
        self.client.login(username="elsuper", password="pass12345")

        response = self.client.get("/nexus-admin/pruebas/")

        filas = {fila["usuario"]: fila for fila in response.context["filas"]}
        self.assertTrue(filas[self.candidato]["tiene_prueba"])
```

- [ ] **Step 2: Confirmar que falla**

Run: `python3 manage.py test core.tests.GestionarRolesPruebaTest -v 1`
Expected: `FAIL` — `django.urls.exceptions.NoReverseMatch` o 404 (la URL no existe todavía).

- [ ] **Step 3: Implementar**

En `core/views.py`, agrega el import al principio (junto a los demás imports, después de la línea 40 `from .utils import validar_cedula_ecuador, consultar_sri`):

```python
from .services.pruebas import crear_entorno_prueba, eliminar_entorno_prueba
```

Agrega al final de `core/views.py`:

```python
@login_required
@user_passes_test(lambda u: u.is_superuser)
def gestionar_roles_prueba(request):
    if request.method == 'POST':
        usuario = get_object_or_404(User, id=request.POST.get('usuario_id'))
        if 'asignar' in request.POST:
            try:
                crear_entorno_prueba(usuario)
                messages.success(request, f"✅ Rol de Prueba asignado a {usuario.username}. Su entorno de demostración ya está listo.")
            except ValueError as e:
                messages.error(request, f"⛔ {e}")
        elif 'quitar' in request.POST:
            eliminar_entorno_prueba(usuario)
            messages.success(request, f"🗑️ Rol de Prueba retirado de {usuario.username}. Todos sus datos de prueba fueron eliminados.")
        return redirect('gestionar_roles_prueba')

    usuarios_reales_ids = set(
        ComplejoDeportivo.objects.filter(es_demo=False).values_list('organizador_id', flat=True)
    )
    demos_por_usuario = {
        c.organizador_id: c
        for c in ComplejoDeportivo.objects.filter(es_demo=True)
    }

    filas = []
    for usuario in User.objects.exclude(is_superuser=True).order_by('username'):
        filas.append({
            'usuario': usuario,
            'tiene_prueba': usuario.id in demos_por_usuario,
            'complejo_demo': demos_por_usuario.get(usuario.id),
            'es_organizador_real': usuario.id in usuarios_reales_ids,
        })

    return render(request, 'core/gestionar_roles_prueba.html', {'filas': filas})
```

En `config/urls.py`, después de la línea `path('nexus-admin/pagos/', views.registrar_pago_saas, name='registrar_pago_saas'),`, agrega:

```python
    path('nexus-admin/pruebas/', views.gestionar_roles_prueba, name='gestionar_roles_prueba'),
```

En `core/templates/core/base.html`, después de la línea (≈499):
```html
                            <li class="nav-item"><a class="nav-link text-primary fw-medium" href="{% url 'gestionar_planes_saas' %}">Planes</a></li>
```
agrega:
```html
                            <li class="nav-item"><a class="nav-link text-primary fw-medium" href="{% url 'gestionar_roles_prueba' %}">Roles de Prueba</a></li>
```

Crea `core/templates/core/gestionar_roles_prueba.html`:

```html
{% extends 'core/base.html' %}

{% block title %}Roles de Prueba | NEXUS SaaS{% endblock %}

{% block contenido %}
<div class="container py-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h4 class="fw-black text-dark m-0"><i class="bi bi-flask-fill text-primary me-2"></i>Roles de Prueba</h4>
    </div>

    <div class="card border-0 rounded-4 shadow-sm">
        <div class="table-responsive">
            <table class="table align-middle mb-0">
                <thead class="table-light">
                    <tr>
                        <th>Usuario</th>
                        <th>Estado</th>
                        <th>Asignado</th>
                        <th class="text-end">Acción</th>
                    </tr>
                </thead>
                <tbody>
                    {% for fila in filas %}
                    <tr>
                        <td class="fw-bold">{{ fila.usuario.username }}</td>
                        <td>
                            {% if fila.tiene_prueba %}
                                <span class="badge bg-info-subtle text-info-emphasis">🧪 En Prueba</span>
                            {% elif fila.es_organizador_real %}
                                <span class="badge bg-secondary-subtle text-secondary-emphasis">Organizador Real</span>
                            {% else %}
                                <span class="badge bg-light text-muted">Sin rol</span>
                            {% endif %}
                        </td>
                        <td class="small text-muted">
                            {% if fila.complejo_demo.fecha_asignacion_prueba %}
                                {{ fila.complejo_demo.fecha_asignacion_prueba|date:"d/m/Y H:i" }}
                            {% else %}
                                —
                            {% endif %}
                        </td>
                        <td class="text-end">
                            {% if fila.tiene_prueba %}
                                <form method="post" onsubmit="return confirm('¿Quitar el Rol de Prueba a {{ fila.usuario.username }}? Se borrarán todos sus datos de prueba.');" class="d-inline">
                                    {% csrf_token %}
                                    <input type="hidden" name="usuario_id" value="{{ fila.usuario.id }}">
                                    <button type="submit" name="quitar" value="1" class="btn btn-sm btn-outline-danger rounded-pill">Quitar</button>
                                </form>
                            {% elif fila.es_organizador_real %}
                                <button type="button" class="btn btn-sm btn-outline-secondary rounded-pill" disabled title="Ya es dueño de una cancha real">Asignar</button>
                            {% else %}
                                <form method="post" class="d-inline">
                                    {% csrf_token %}
                                    <input type="hidden" name="usuario_id" value="{{ fila.usuario.id }}">
                                    <button type="submit" name="asignar" value="1" class="btn btn-sm btn-primary rounded-pill">Asignar</button>
                                </form>
                            {% endif %}
                        </td>
                    </tr>
                    {% empty %}
                    <tr><td colspan="4" class="text-center text-muted py-4">No hay usuarios registrados todavía.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 4: Confirmar que pasa**

Run: `python3 manage.py test core.tests.GestionarRolesPruebaTest -v 1`
Expected: `OK` (5 tests)

- [ ] **Step 5: Commit**

```bash
git add core/views.py config/urls.py core/templates/core/base.html core/templates/core/gestionar_roles_prueba.html core/tests.py
git commit -m "$(cat <<'EOF'
Agrega panel del Super Admin para asignar/quitar el Rol de Prueba

Nueva sección /nexus-admin/pruebas/, solo accesible por is_superuser,
que lista usuarios elegibles y permite asignar o revocar el entorno
de demostración con un click.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Excluir canchas demo del Control SaaS real (`dashboard_saas`)

**Files:**
- Modify: `core/views.py` (dentro de `dashboard_saas`, la línea que arma `canchas_list`)
- Test: `core/tests.py`

**Interfaces:**
- Ninguna — cambio de comportamiento puro, aditivo (un `.filter()` más), sin nuevas interfaces.

- [ ] **Step 1: Escribir el test que falla**

Añade al final de `core/tests.py`:

```python
class DashboardSaasExcluyeDemoTest(TestCase):
    def test_canchas_demo_no_aparecen_en_el_control_saas(self):
        superadmin = User.objects.create_superuser("elsuper2", password="pass12345")
        usuario_demo = User.objects.create_user("candidato2", password="pass12345")
        plan = PlanSuscripcion.objects.create(nombre="Plan U", precio_mensual=Decimal("10.00"))
        organizador_real = User.objects.create_user("dueno_real5", password="pass12345")
        cancha_real = ComplejoDeportivo.objects.create(
            nombre="Cancha Real 5", slug="cancha-real-5", organizador=organizador_real, plan=plan,
        )
        cancha_demo = crear_entorno_prueba(usuario_demo)

        self.client.login(username="elsuper2", password="pass12345")
        response = self.client.get("/nexus-admin/")

        canchas_mostradas = [c.id for c in response.context["canchas"]]
        self.assertIn(cancha_real.id, canchas_mostradas)
        self.assertNotIn(cancha_demo.id, canchas_mostradas)
```

- [ ] **Step 2: Confirmar que falla**

Run: `python3 manage.py test core.tests.DashboardSaasExcluyeDemoTest -v 1`
Expected: `FAIL` — `cancha_demo.id` aparece en `canchas_mostradas`.

- [ ] **Step 3: Implementar**

En `core/views.py`, dentro de `dashboard_saas`, busca la línea:

```python
    canchas_list = ComplejoDeportivo.objects.select_related('organizador', 'plan').all().order_by('fecha_vencimiento')
```

y reemplázala por:

```python
    canchas_list = ComplejoDeportivo.objects.select_related('organizador', 'plan').filter(es_demo=False).order_by('fecha_vencimiento')
```

- [ ] **Step 4: Confirmar que pasa**

Run: `python3 manage.py test core.tests.DashboardSaasExcluyeDemoTest -v 1`
Expected: `OK` (1 test)

- [ ] **Step 5: Commit**

```bash
git add core/views.py core/tests.py
git commit -m "$(cat <<'EOF'
Excluye canchas demo de las cifras reales del Control SaaS

dashboard_saas ya no cuenta entornos de prueba como clientes reales
en su lista, total de ingresos, ni recordatorios de vencimiento.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Banner "modo prueba" global

**Files:**
- Modify: `core/context_processors.py`
- Modify: `core/templates/core/base.html:541` (después de `</nav>`)
- Test: `core/tests.py`

**Interfaces:**
- Produces: contexto global `es_entorno_prueba` (bool), disponible en toda plantilla que extienda `base.html`. La Task 9 lo reutiliza para el link de nav "Dirigente de Equipo".

- [ ] **Step 1: Escribir el test que falla**

Añade al final de `core/tests.py`:

```python
class BannerModoPruebaTest(TestCase):
    def test_usuario_de_prueba_ve_el_banner(self):
        usuario = User.objects.create_user("tester18", password="pass12345")
        crear_entorno_prueba(usuario)
        self.client.login(username="tester18", password="pass12345")

        response = self.client.get("/dashboard/")

        self.assertTrue(response.context["es_entorno_prueba"])
        self.assertContains(response, "PRUEBA")

    def test_usuario_normal_no_ve_el_banner(self):
        plan = PlanSuscripcion.objects.create(nombre="Plan T", precio_mensual=Decimal("10.00"))
        organizador = User.objects.create_user("dueno_real6", password="pass12345")
        ComplejoDeportivo.objects.create(
            nombre="Cancha Real 6", slug="cancha-real-6", organizador=organizador, plan=plan,
        )
        self.client.login(username="dueno_real6", password="pass12345")

        response = self.client.get("/dashboard/")

        self.assertFalse(response.context["es_entorno_prueba"])

    def test_anonimo_no_revienta(self):
        response = self.client.get("/login/")
        self.assertEqual(response.status_code, 200)
```

- [ ] **Step 2: Confirmar que falla**

Run: `python3 manage.py test core.tests.BannerModoPruebaTest -v 1`
Expected: `FAIL` — `KeyError: 'es_entorno_prueba'`

- [ ] **Step 3: Implementar**

Reemplaza el contenido completo de `core/context_processors.py`:

```python
# core/context_processors.py
from .models import ComplejoDeportivo, Configuracion

def configuracion_global(request):
    config = Configuracion.objects.first()
    es_entorno_prueba = False
    if request.user.is_authenticated:
        es_entorno_prueba = ComplejoDeportivo.objects.filter(
            organizador=request.user, es_demo=True
        ).exists()
    return {'config_global': config, 'es_entorno_prueba': es_entorno_prueba}
```

En `core/templates/core/base.html`, justo después de `</nav>` (línea 541) y antes de `{% if messages %}`, agrega:

```html
    {% if es_entorno_prueba %}
    <div class="bg-warning bg-opacity-25 border-bottom border-warning text-center py-2 fw-bold small">
        🧪 Estás en un entorno de PRUEBA — nada de lo que hagas aquí afecta datos reales.
    </div>
    {% endif %}
```

- [ ] **Step 4: Confirmar que pasa**

Run: `python3 manage.py test core.tests.BannerModoPruebaTest -v 1`
Expected: `OK` (3 tests)

- [ ] **Step 5: Commit**

```bash
git add core/context_processors.py core/templates/core/base.html core/tests.py
git commit -m "$(cat <<'EOF'
Agrega banner "modo prueba" visible en todo el sitio

es_entorno_prueba llega al contexto global vía configuracion_global;
un usuario de prueba ve una franja fija recordándole que está en un
entorno de demostración aislado.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Sección "Dirigente de Equipo" — elegir equipo y ver su gestión

**Files:**
- Modify: `core/views.py` (agregar guard + 2 vistas al final del archivo)
- Modify: `config/urls.py` (2 URLs nuevas)
- Modify: `core/templates/core/base.html` (link de nav condicional a `es_entorno_prueba`)
- Create: `core/templates/core/prueba_seleccionar_equipo.html`
- Create: `core/templates/core/prueba_dirigente_equipo.html`
- Test: `core/tests.py`

**Interfaces:**
- Consumes: `es_entorno_prueba` (Task 8, para el link de nav).
- Produces: `es_dueno_de_entorno_prueba(user) -> bool` y `obtener_mi_complejo_demo(user) -> ComplejoDeportivo | None` — reutilizadas por la Task 10.

- [ ] **Step 1: Escribir el test que falla**

Añade al final de `core/tests.py`:

```python
class PruebaDirigenteEquipoTest(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user("tester19", password="pass12345")
        self.complejo_demo = crear_entorno_prueba(self.usuario)
        self.mi_equipo = Equipo.objects.filter(torneo__complejo=self.complejo_demo).first()

        plan = PlanSuscripcion.objects.create(nombre="Plan S", precio_mensual=Decimal("10.00"))
        self.otro_usuario = User.objects.create_user("tester20", password="pass12345")
        self.otro_complejo = crear_entorno_prueba(self.otro_usuario)
        self.equipo_ajeno = Equipo.objects.filter(torneo__complejo=self.otro_complejo).first()

    def test_usuario_sin_entorno_de_prueba_no_puede_entrar(self):
        User.objects.create_user("sin_prueba", password="pass12345")
        self.client.login(username="sin_prueba", password="pass12345")

        response = self.client.get("/prueba/dirigente/")

        self.assertNotEqual(response.status_code, 200)

    def test_selector_muestra_los_seis_equipos_del_propio_entorno(self):
        self.client.login(username="tester19", password="pass12345")

        response = self.client.get("/prueba/dirigente/")

        self.assertEqual(len(response.context["equipos"]), 6)

    def test_puede_ver_el_detalle_de_su_propio_equipo(self):
        self.client.login(username="tester19", password="pass12345")

        response = self.client.get(f"/prueba/dirigente/{self.mi_equipo.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["equipo"], self.mi_equipo)
        self.assertEqual(len(response.context["jugadores"]), 6)

    def test_no_puede_ver_el_equipo_de_otro_usuario_de_prueba(self):
        self.client.login(username="tester19", password="pass12345")

        response = self.client.get(f"/prueba/dirigente/{self.equipo_ajeno.id}/")

        self.assertEqual(response.status_code, 404)
```

- [ ] **Step 2: Confirmar que falla**

Run: `python3 manage.py test core.tests.PruebaDirigenteEquipoTest -v 1`
Expected: `FAIL` — 404/`NoReverseMatch` (las URLs no existen todavía).

- [ ] **Step 3: Implementar**

Agrega al final de `core/views.py`:

```python
def es_dueno_de_entorno_prueba(user):
    if not user.is_authenticated: return False
    return ComplejoDeportivo.objects.filter(organizador=user, es_demo=True).exists()


def obtener_mi_complejo_demo(user):
    return ComplejoDeportivo.objects.filter(organizador=user, es_demo=True).first()


@login_required
@user_passes_test(es_dueno_de_entorno_prueba)
def prueba_seleccionar_equipo(request):
    mi_complejo_demo = obtener_mi_complejo_demo(request.user)
    equipos = Equipo.objects.filter(torneo__complejo=mi_complejo_demo).order_by('nombre')
    return render(request, 'core/prueba_seleccionar_equipo.html', {'equipos': equipos})


@login_required
@user_passes_test(es_dueno_de_entorno_prueba)
def prueba_ver_como_dirigente(request, equipo_id):
    mi_complejo_demo = obtener_mi_complejo_demo(request.user)
    equipo = get_object_or_404(Equipo, id=equipo_id, torneo__complejo=mi_complejo_demo)

    jugadores = equipo.jugadores.order_by('dorsal')
    partidos_jugados = Partido.objects.filter(
        Q(equipo_local=equipo) | Q(equipo_visita=equipo), estado='JUG'
    ).order_by('-fecha_hora', '-id')
    proximos_partidos = Partido.objects.filter(
        Q(equipo_local=equipo) | Q(equipo_visita=equipo), estado='PROG'
    ).order_by('fecha_hora')
    tarjetas = DetallePartido.objects.filter(
        jugador__equipo=equipo, tipo__in=['TA', 'TR']
    ).select_related('jugador', 'partido')
    deudas = Sancion.objects.filter(equipo=equipo, pagada=False)
    total_deuda = deudas.aggregate(Sum('monto'))['monto__sum'] or 0

    return render(request, 'core/prueba_dirigente_equipo.html', {
        'equipo': equipo,
        'jugadores': jugadores,
        'partidos_jugados': partidos_jugados,
        'proximos_partidos': proximos_partidos,
        'tarjetas': tarjetas,
        'deudas': deudas,
        'total_deuda': total_deuda,
    })
```

En `config/urls.py`, después de la línea `path('nexus-admin/pruebas/', views.gestionar_roles_prueba, name='gestionar_roles_prueba'),` agrega:

```python
    path('prueba/dirigente/', views.prueba_seleccionar_equipo, name='prueba_seleccionar_equipo'),
    path('prueba/dirigente/<int:equipo_id>/', views.prueba_ver_como_dirigente, name='prueba_ver_como_dirigente'),
```

En `core/templates/core/base.html`, dentro del bloque `{% elif user.perfil.rol_principal == 'ORG' %}` (≈línea 500, justo después del link "Panel"), agrega:

```html
                            {% if es_entorno_prueba %}
                                <li class="nav-item"><a class="nav-link text-warning fw-bold" href="{% url 'prueba_seleccionar_equipo' %}">🧪 Dirigente de Equipo</a></li>
                            {% endif %}
```

Crea `core/templates/core/prueba_seleccionar_equipo.html`:

```html
{% extends 'core/base.html' %}

{% block title %}Dirigente de Equipo (Demo) | NEXUS{% endblock %}

{% block contenido %}
<div class="container py-4">
    <h4 class="fw-black text-dark mb-4"><i class="bi bi-person-badge-fill text-primary me-2"></i>Simular Dirigente de Equipo</h4>
    <p class="text-muted mb-4">Elige uno de tus 6 equipos demo para ver cómo lo gestionaría un Dirigente real.</p>

    <div class="row g-3">
        {% for equipo in equipos %}
        <div class="col-md-4">
            <a href="{% url 'prueba_ver_como_dirigente' equipo.id %}" class="text-decoration-none">
                <div class="card border-0 rounded-4 shadow-sm h-100 p-3">
                    <h5 class="fw-bold text-dark m-0">{{ equipo.nombre }}</h5>
                    <p class="text-muted small mb-0">{{ equipo.jugadores.count }} jugadores</p>
                </div>
            </a>
        </div>
        {% endfor %}
    </div>
</div>
{% endblock %}
```

Crea `core/templates/core/prueba_dirigente_equipo.html`:

```html
{% extends 'core/base.html' %}

{% block title %}{{ equipo.nombre }} | Dirigente de Equipo (Demo){% endblock %}

{% block contenido %}
<div class="container py-4">
    <a href="{% url 'prueba_seleccionar_equipo' %}" class="text-muted small mb-2 d-inline-block"><i class="bi bi-arrow-left"></i> Volver a mis equipos</a>
    <h4 class="fw-black text-dark mb-4"><i class="bi bi-shield-fill text-primary me-2"></i>{{ equipo.nombre }}</h4>

    <div class="row g-4">
        <div class="col-lg-6">
            <div class="card border-0 rounded-4 shadow-sm p-3 mb-4">
                <h6 class="fw-bold text-dark">Plantel</h6>
                <table class="table table-sm mb-0">
                    <tbody>
                        {% for jugador in jugadores %}
                        <tr>
                            <td class="fw-bold">#{{ jugador.dorsal }}</td>
                            <td>{{ jugador.nombres }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
                <a href="{% url 'prueba_agregar_jugador' equipo.id %}" class="btn btn-sm btn-primary rounded-pill mt-2">+ Agregar Jugador</a>
            </div>

            <div class="card border-0 rounded-4 shadow-sm p-3">
                <h6 class="fw-bold text-dark">Tarjetas</h6>
                {% for tarjeta in tarjetas %}
                <p class="small mb-1">
                    {% if tarjeta.tipo == 'TA' %}🟨{% else %}🟥{% endif %}
                    {{ tarjeta.jugador.nombres }} — {{ tarjeta.partido }}
                </p>
                {% empty %}
                <p class="text-muted small mb-0">Sin tarjetas.</p>
                {% endfor %}
            </div>
        </div>

        <div class="col-lg-6">
            <div class="card border-0 rounded-4 shadow-sm p-3 mb-4">
                <h6 class="fw-bold text-dark">Próximos Partidos</h6>
                {% for partido in proximos_partidos %}
                <p class="small mb-1">{{ partido.equipo_local }} vs {{ partido.equipo_visita }} — {{ partido.fecha_hora|date:"d/m/Y H:i" }}</p>
                {% empty %}
                <p class="text-muted small mb-0">Sin partidos programados.</p>
                {% endfor %}
            </div>

            <div class="card border-0 rounded-4 shadow-sm p-3 mb-4">
                <h6 class="fw-bold text-dark">Partidos Jugados</h6>
                {% for partido in partidos_jugados %}
                <p class="small mb-1">{{ partido.equipo_local }} {{ partido.goles_local }} - {{ partido.goles_visita }} {{ partido.equipo_visita }}</p>
                {% empty %}
                <p class="text-muted small mb-0">Sin partidos jugados todavía.</p>
                {% endfor %}
            </div>

            <div class="card border-0 rounded-4 shadow-sm p-3">
                <h6 class="fw-bold text-dark">Finanzas</h6>
                <p class="small mb-0">Deuda total: <strong>${{ total_deuda }}</strong></p>
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 4: Confirmar que pasa**

Run: `python3 manage.py test core.tests.PruebaDirigenteEquipoTest -v 1`
Expected: `OK` (4 tests)

- [ ] **Step 5: Commit**

```bash
git add core/views.py config/urls.py core/templates/core/base.html core/templates/core/prueba_seleccionar_equipo.html core/templates/core/prueba_dirigente_equipo.html core/tests.py
git commit -m "$(cat <<'EOF'
Agrega la sección "Dirigente de Equipo" al entorno de prueba

Vistas y plantillas nuevas e independientes de las reales de
Dirigente: el usuario de prueba elige uno de sus 6 equipos demo y ve
plantel, tarjetas, próximos partidos, historial y finanzas — sin
tocar ni una línea del código real de Dirigente.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Agregar jugador desde "Dirigente de Equipo" (reutiliza `JugadorForm`)

**Files:**
- Modify: `core/views.py` (agregar 1 vista al final del archivo)
- Modify: `config/urls.py` (1 URL nueva)
- Create: `core/templates/core/prueba_agregar_jugador.html`
- Test: `core/tests.py`

**Interfaces:**
- Consumes: `es_dueno_de_entorno_prueba`, `obtener_mi_complejo_demo` (Task 9); `JugadorForm` (ya existente en `core/forms.py`, sin modificar).

- [ ] **Step 1: Escribir el test que falla**

Añade al final de `core/tests.py`:

```python
class PruebaAgregarJugadorTest(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user("tester21", password="pass12345")
        self.complejo_demo = crear_entorno_prueba(self.usuario)
        self.mi_equipo = Equipo.objects.filter(torneo__complejo=self.complejo_demo).first()

        self.otro_usuario = User.objects.create_user("tester22", password="pass12345")
        self.otro_complejo = crear_entorno_prueba(self.otro_usuario)
        self.equipo_ajeno = Equipo.objects.filter(torneo__complejo=self.otro_complejo).first()

    def test_puede_agregar_un_jugador_a_su_propio_equipo_demo(self):
        self.client.login(username="tester21", password="pass12345")
        jugadores_antes = self.mi_equipo.jugadores.count()

        response = self.client.post(f"/prueba/dirigente/{self.mi_equipo.id}/agregar-jugador/", {
            "equipo": self.mi_equipo.id,
            "nombres": "Jugador Nuevo Demo",
            "dorsal": "99",
            "cedula": "1710000033",
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.mi_equipo.jugadores.count(), jugadores_antes + 1)

    def test_no_puede_agregar_jugador_a_equipo_de_otro_usuario_de_prueba(self):
        self.client.login(username="tester21", password="pass12345")
        jugadores_antes_ajeno = self.equipo_ajeno.jugadores.count()

        response = self.client.get(f"/prueba/dirigente/{self.equipo_ajeno.id}/agregar-jugador/")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.equipo_ajeno.jugadores.count(), jugadores_antes_ajeno)

    def test_no_puede_inyectar_el_jugador_en_el_equipo_ajeno_via_post(self):
        self.client.login(username="tester21", password="pass12345")
        jugadores_antes_ajeno = self.equipo_ajeno.jugadores.count()

        self.client.post(f"/prueba/dirigente/{self.mi_equipo.id}/agregar-jugador/", {
            "equipo": self.equipo_ajeno.id,
            "nombres": "Intruso",
            "dorsal": "98",
            "cedula": "1710000041",
        })

        self.assertEqual(self.equipo_ajeno.jugadores.count(), jugadores_antes_ajeno)
```

- [ ] **Step 2: Confirmar que falla**

Run: `python3 manage.py test core.tests.PruebaAgregarJugadorTest -v 1`
Expected: `FAIL` — 404/`NoReverseMatch` (la URL no existe todavía).

- [ ] **Step 3: Implementar**

Agrega al final de `core/views.py`:

```python
@login_required
@user_passes_test(es_dueno_de_entorno_prueba)
def prueba_agregar_jugador(request, equipo_id):
    mi_complejo_demo = obtener_mi_complejo_demo(request.user)
    equipo = get_object_or_404(Equipo, id=equipo_id, torneo__complejo=mi_complejo_demo)
    equipos_del_entorno = Equipo.objects.filter(torneo__complejo=mi_complejo_demo)

    if request.method == 'POST':
        form = JugadorForm(request.POST, request.FILES)
        form.fields['equipo'].queryset = equipos_del_entorno
        if form.is_valid():
            jugador = form.save()
            messages.success(request, f"✅ {jugador.nombres} agregado a {jugador.equipo.nombre}.")
            return redirect('prueba_ver_como_dirigente', equipo_id=jugador.equipo.id)
    else:
        form = JugadorForm(initial={'equipo': equipo})
        form.fields['equipo'].queryset = equipos_del_entorno

    return render(request, 'core/prueba_agregar_jugador.html', {'form': form, 'equipo': equipo})
```

En `config/urls.py`, después de `path('prueba/dirigente/<int:equipo_id>/', views.prueba_ver_como_dirigente, name='prueba_ver_como_dirigente'),` agrega:

```python
    path('prueba/dirigente/<int:equipo_id>/agregar-jugador/', views.prueba_agregar_jugador, name='prueba_agregar_jugador'),
```

Crea `core/templates/core/prueba_agregar_jugador.html`:

```html
{% extends 'core/base.html' %}
{% load crispy_forms_tags %}

{% block title %}Agregar Jugador | Dirigente de Equipo (Demo){% endblock %}

{% block contenido %}
<div class="row justify-content-center">
    <div class="col-md-6">
        <div class="card border-0 rounded-4 shadow-sm mt-4 p-4">
            <h5 class="fw-black text-dark mb-3">Agregar Jugador a {{ equipo.nombre }}</h5>
            <form method="post" enctype="multipart/form-data">
                {% csrf_token %}
                {{ form|crispy }}
                <button type="submit" class="btn btn-primary w-100 mt-3 rounded-pill">Guardar</button>
                <a href="{% url 'prueba_ver_como_dirigente' equipo.id %}" class="btn btn-light w-100 mt-2 rounded-pill">Cancelar</a>
            </form>
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 4: Confirmar que pasa**

Run: `python3 manage.py test core.tests.PruebaAgregarJugadorTest -v 1`
Expected: `OK` (3 tests)

- [ ] **Step 5: Correr la suite completa de `core.tests` para confirmar que nada quedó roto**

Run: `python3 manage.py test core.tests -v 1`
Expected: `OK` — todos los tests existentes (los del archivo original más los de este plan) pasan.

- [ ] **Step 6: Commit**

```bash
git add core/views.py config/urls.py core/templates/core/prueba_agregar_jugador.html core/tests.py
git commit -m "$(cat <<'EOF'
Permite agregar jugadores desde la vista de Dirigente de Equipo demo

Reutiliza JugadorForm tal cual; el queryset del campo 'equipo' se
restringe a los equipos del propio entorno de prueba del usuario,
así que no se puede inyectar un jugador en un equipo ajeno vía POST.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review (completado antes de entregar el plan)

**Cobertura del spec:**
- Modelo (`es_demo`, `fecha_asignacion_prueba`) → Task 1.
- Plan Demo con límites generosos → Task 2.
- Siembra: 6 equipos, 6 jugadores c/u → Task 3.
- Siembra: partidos jugados/futuros, tarjetas amarillas/rojas con `Sancion` → Task 4.
- Revocar = cascada → Task 5.
- Panel Super Admin asignar/quitar, restricción a organizadores reales → Task 6.
- Exclusión de canchas demo en `dashboard_saas` → Task 7.
- Banner "modo prueba" → Task 8.
- Sección "Dirigente de Equipo" (vistas/plantillas propias) → Task 9.
- Edición dentro de esa sección reutilizando `JugadorForm` → Task 10.
- Tests de aislamiento cross-usuario están repartidos en las Tasks 6, 9 y 10 (nunca se puede ver/tocar el equipo/cancha de otro).

**Sin placeholders:** cada paso trae código completo, sin "TODO" ni "similar a la tarea N".

**Consistencia de tipos:** `crear_entorno_prueba(usuario) -> ComplejoDeportivo`, `eliminar_entorno_prueba(usuario) -> None`, `es_dueno_de_entorno_prueba(user) -> bool` y `obtener_mi_complejo_demo(user) -> ComplejoDeportivo | None` se usan con la misma firma en todas las tareas que los consumen (6, 7, 8, 9, 10).
