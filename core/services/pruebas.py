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
