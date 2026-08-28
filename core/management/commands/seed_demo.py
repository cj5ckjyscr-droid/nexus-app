from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import (
    Categoria, ComplejoDeportivo, Equipo, Jugador, Partido,
    PlanSuscripcion, RolComplejo, Torneo,
)


def _cedula_valida(numero):
    valor = str(numero)
    provincia = int(valor[0:2])
    if provincia < 1 or provincia > 24:
        return False
    coeficientes = [2, 1, 2, 1, 2, 1, 2, 1, 2]
    total = sum(
        (int(valor[i]) * coeficientes[i] if int(valor[i]) * coeficientes[i] < 10
         else int(valor[i]) * coeficientes[i] - 9)
        for i in range(9)
    )
    digito = int(valor[9])
    calculado = (total + 9) // 10 * 10 - total
    if calculado == 10:
        calculado = 0
    return calculado == digito


def generador_cedulas():
    base = 1700000000
    while True:
        candidata = str(base)
        if _cedula_valida(candidata):
            yield candidata
        base += 1


class Command(BaseCommand):
    help = "Llena la base de datos local con varias canchas, usuarios y datos de prueba para QA manual."

    def handle(self, *args, **options):
        cedulas = generador_cedulas()
        hoy = timezone.now().date()
        credenciales = []

        superadmin, _ = User.objects.get_or_create(
            username="nexus_admin",
            defaults={"email": "nexus_admin@example.com", "is_staff": True, "is_superuser": True},
        )
        superadmin.set_password("NexusAdmin2026!")
        superadmin.is_staff = True
        superadmin.is_superuser = True
        superadmin.save()
        credenciales.append(("Súper Admin (NEXUS)", "nexus_admin", "NexusAdmin2026!", "/nexus-admin/"))

        plan_basico, _ = PlanSuscripcion.objects.update_or_create(
            nombre="Básico Demo",
            defaults={
                "costo_inscripcion": Decimal("0.00"),
                "precio_mensual": Decimal("15.00"),
                "max_torneos": 1,
                "max_categorias_por_torneo": 2,
                "max_jugadores": 3,
            },
        )
        plan_pro, _ = PlanSuscripcion.objects.update_or_create(
            nombre="Pro Demo",
            defaults={
                "costo_inscripcion": Decimal("0.00"),
                "precio_mensual": Decimal("35.00"),
                "max_torneos": 3,
                "max_categorias_por_torneo": 5,
                "max_jugadores": 50,
            },
        )

        canchas_config = [
            {
                "nombre": "Cancha Los Pinos", "slug": "los-pinos", "plan": plan_basico,
                "org_user": "los_pinos_admin", "voc_user": "los_pinos_vocal",
                "torneo": "Copa Los Pinos", "categoria": "Libre",
                "equipos": [
                    {"nombre": "Tigres FC", "dirigente": "los_pinos_dt_tigres", "jugadores": ["Ana Torres", "Luis Peña"]},
                    {"nombre": "Halcones FC", "dirigente": "los_pinos_dt_halcones", "jugadores": ["Marco Ruiz"]},
                ],
                # Nota: 2 + 1 = 3 jugadores = tope EXACTO del plan Básico (max_jugadores=3).
                # Sirve para probar en vivo que la 4ta ficha se bloquea.
            },
            {
                "nombre": "Cancha El Bosque", "slug": "el-bosque", "plan": plan_pro,
                "org_user": "el_bosque_admin", "voc_user": "el_bosque_vocal",
                "torneo": "Liga El Bosque Sub-20", "categoria": "Sub-20",
                "equipos": [
                    {"nombre": "Águilas FC", "dirigente": "el_bosque_dt_aguilas", "jugadores": ["Pedro Vega", "Jorge Salas", "Iván Cruz"]},
                    {"nombre": "Cóndores FC", "dirigente": "el_bosque_dt_condores", "jugadores": ["Sofía León", "Diego Mora"]},
                ],
            },
        ]

        password_comun = "Demo2026!"

        for cfg in canchas_config:
            org_user, creado = User.objects.get_or_create(
                username=cfg["org_user"], defaults={"email": f"{cfg['org_user']}@example.com"},
            )
            org_user.set_password(password_comun)
            org_user.save()
            credenciales.append((f"Organizador de {cfg['nombre']}", cfg["org_user"], password_comun, f"/cancha/{cfg['slug']}/"))

            cancha, _ = ComplejoDeportivo.objects.update_or_create(
                slug=cfg["slug"],
                defaults={
                    "nombre": cfg["nombre"],
                    "organizador": org_user,
                    "plan": cfg["plan"],
                    "activo": True,
                    "fecha_vencimiento": hoy + timedelta(days=30),
                },
            )
            RolComplejo.objects.get_or_create(usuario=org_user, complejo=cancha, defaults={"rol": "ORG"})

            voc_user, _ = User.objects.get_or_create(
                username=cfg["voc_user"], defaults={"email": f"{cfg['voc_user']}@example.com"},
            )
            voc_user.set_password(password_comun)
            voc_user.save()
            RolComplejo.objects.update_or_create(usuario=voc_user, complejo=cancha, defaults={"rol": "VOC"})
            credenciales.append((f"Vocal de {cfg['nombre']}", cfg["voc_user"], password_comun, "/login/"))

            categoria, _ = Categoria.objects.get_or_create(
                complejo=cancha, nombre=cfg["categoria"], defaults={"color_carnet": "#1D4ED8"},
            )
            torneo, _ = Torneo.objects.get_or_create(
                complejo=cancha, nombre=cfg["torneo"],
                defaults={
                    "organizador": org_user, "categoria": categoria,
                    "costo_inscripcion": Decimal("20.00"), "activo": True,
                },
            )

            equipos_creados = []
            for eq_cfg in cfg["equipos"]:
                dirigente, _ = User.objects.get_or_create(
                    username=eq_cfg["dirigente"], defaults={"email": f"{eq_cfg['dirigente']}@example.com"},
                )
                dirigente.set_password(password_comun)
                dirigente.save()
                credenciales.append((f"Dirigente de {eq_cfg['nombre']} ({cfg['nombre']})", eq_cfg["dirigente"], password_comun, "/login/"))

                equipo, _ = Equipo.objects.update_or_create(
                    torneo=torneo, nombre=eq_cfg["nombre"],
                    defaults={"dirigente": dirigente, "estado_inscripcion": "APROBADO", "pagado": True},
                )
                RolComplejo.objects.get_or_create(usuario=dirigente, complejo=cancha, defaults={"rol": "DIR"})
                equipos_creados.append(equipo)

                for i, nombre_jugador in enumerate(eq_cfg["jugadores"], start=1):
                    Jugador.objects.get_or_create(
                        equipo=equipo, dorsal=i,
                        defaults={"nombres": nombre_jugador, "cedula": next(cedulas)},
                    )

            if len(equipos_creados) >= 2:
                Partido.objects.get_or_create(
                    torneo=torneo, etapa="F1", numero_fecha=1,
                    equipo_local=equipos_creados[0], equipo_visita=equipos_creados[1],
                    defaults={"fecha_hora": timezone.now() + timedelta(days=2), "estado": "PROG"},
                )

        self.stdout.write(self.style.SUCCESS("\nDatos de prueba listos. Credenciales:\n"))
        for rol, usuario, clave, ruta in credenciales:
            self.stdout.write(f"- {rol}: usuario='{usuario}' clave='{clave}' -> {ruta}")
