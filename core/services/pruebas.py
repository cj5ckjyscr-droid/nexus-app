from decimal import Decimal

from django.utils import timezone
from django.utils.text import slugify

from ..models import (
    Categoria, ComplejoDeportivo, DetallePartido, Equipo, Jugador, Partido,
    PlanSuscripcion, RolComplejo, Sancion, Torneo,
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

    equipos = _sembrar_equipos_y_jugadores(torneo, usuario)
    _sembrar_partidos(torneo, equipos)

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
