from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import (
    AbonoSancion, ComplejoDeportivo, Configuracion, Equipo, FotoGaleria,
    Jugador, Partido, Pago, PlanSuscripcion, RolComplejo, Sancion, Torneo,
)


def imagen_falsa(nombre="foto.jpg"):
    return SimpleUploadedFile(nombre, b"contenido-de-prueba", content_type="image/jpeg")


class DosCanchasTestCase(TestCase):
    """Fixture base: dos ComplejoDeportivo (tenants) totalmente independientes,
    Cancha A y Cancha B, cada uno con su propio dueño, torneo, equipos,
    jugador, partido, sanción y foto de galería."""

    def setUp(self):
        self.plan = PlanSuscripcion.objects.create(
            nombre="Básico", precio_mensual=Decimal("10.00"),
            max_torneos=5, max_categorias_por_torneo=5,
        )

        self.org_a = User.objects.create_user("org_a", password="pass12345")
        self.complejo_a = ComplejoDeportivo.objects.create(
            nombre="Cancha A", slug="cancha-a", organizador=self.org_a,
            plan=self.plan, activo=True,
        )
        # En producción, gestionar_canchas_saas crea este RolComplejo
        # automáticamente al registrar la cancha; lo replicamos aquí.
        RolComplejo.objects.create(usuario=self.org_a, complejo=self.complejo_a, rol="ORG")
        self.torneo_a = Torneo.objects.create(
            complejo=self.complejo_a, nombre="Torneo A", organizador=self.org_a,
            costo_inscripcion=Decimal("50.00"),
        )
        self.equipo_a = Equipo.objects.create(
            torneo=self.torneo_a, dirigente=self.org_a, nombre="Equipo A",
            estado_inscripcion="APROBADO",
        )
        self.equipo_a2 = Equipo.objects.create(
            torneo=self.torneo_a, dirigente=self.org_a, nombre="Equipo A2",
            estado_inscripcion="APROBADO",
        )
        self.jugador_a = Jugador.objects.create(
            equipo=self.equipo_a, nombres="Jugador A", dorsal=10, cedula="1710034065",
        )
        self.partido_a = Partido.objects.create(
            torneo=self.torneo_a, equipo_local=self.equipo_a, equipo_visita=self.equipo_a2,
        )
        self.sancion_a = Sancion.objects.create(
            torneo=self.torneo_a, equipo=self.equipo_a, tipo="ADMIN",
            monto=Decimal("20.00"), descripcion="Deuda inscripción A", pagada=False,
        )
        self.foto_a = FotoGaleria.objects.create(
            complejo=self.complejo_a, titulo="Foto A", imagen=imagen_falsa("a.jpg"),
        )
        self.pago_a = Pago.objects.create(equipo=self.equipo_a, monto=Decimal("5.00"))

        self.org_b = User.objects.create_user("org_b", password="pass12345")
        self.complejo_b = ComplejoDeportivo.objects.create(
            nombre="Cancha B", slug="cancha-b", organizador=self.org_b,
            plan=self.plan, activo=True,
        )
        RolComplejo.objects.create(usuario=self.org_b, complejo=self.complejo_b, rol="ORG")
        self.torneo_b = Torneo.objects.create(
            complejo=self.complejo_b, nombre="Torneo B", organizador=self.org_b,
            costo_inscripcion=Decimal("50.00"),
        )
        self.equipo_b = Equipo.objects.create(
            torneo=self.torneo_b, dirigente=self.org_b, nombre="Equipo B",
            estado_inscripcion="APROBADO",
        )
        self.equipo_b2 = Equipo.objects.create(
            torneo=self.torneo_b, dirigente=self.org_b, nombre="Equipo B2",
            estado_inscripcion="APROBADO",
        )
        self.jugador_b = Jugador.objects.create(
            equipo=self.equipo_b, nombres="Jugador B", dorsal=7, cedula="1710034073",
        )
        self.partido_b = Partido.objects.create(
            torneo=self.torneo_b, equipo_local=self.equipo_b, equipo_visita=self.equipo_b2,
        )
        self.sancion_b = Sancion.objects.create(
            torneo=self.torneo_b, equipo=self.equipo_b, tipo="ADMIN",
            monto=Decimal("30.00"), descripcion="Deuda inscripción B", pagada=False,
        )
        self.foto_b = FotoGaleria.objects.create(
            complejo=self.complejo_b, titulo="Foto B", imagen=imagen_falsa("b.jpg"),
        )
        self.pago_b = Pago.objects.create(equipo=self.equipo_b, monto=Decimal("8.00"))


class ConfiguracionPorComplejoTest(DosCanchasTestCase):
    def test_organizador_no_comparte_configuracion_con_otra_cancha(self):
        self.client.login(username="org_a", password="pass12345")
        self.client.post("/configuracion/", {"iva_porcentaje": "18.00"})

        self.client.login(username="org_b", password="pass12345")
        self.client.post("/configuracion/", {"iva_porcentaje": "5.00"})

        config_a = Configuracion.objects.get(complejo=self.complejo_a)
        config_b = Configuracion.objects.get(complejo=self.complejo_b)

        self.assertEqual(config_a.iva_porcentaje, Decimal("18.00"))
        self.assertEqual(config_b.iva_porcentaje, Decimal("5.00"))


class GaleriaPorComplejoTest(DosCanchasTestCase):
    def test_organizador_no_ve_fotos_de_otra_cancha(self):
        self.client.login(username="org_a", password="pass12345")
        response = self.client.get("/medios/")

        fotos_mostradas = list(response.context["fotos"])
        self.assertIn(self.foto_a, fotos_mostradas)
        self.assertNotIn(self.foto_b, fotos_mostradas)

    def test_organizador_no_puede_borrar_foto_de_otra_cancha(self):
        self.client.login(username="org_a", password="pass12345")
        self.client.post(f"/medios/eliminar-foto/{self.foto_b.id}/")

        self.assertTrue(FotoGaleria.objects.filter(id=self.foto_b.id).exists())


class CancelarInscripcionTest(DosCanchasTestCase):
    def test_organizador_no_puede_cancelar_inscripcion_de_equipo_de_otra_cancha(self):
        self.client.login(username="org_a", password="pass12345")
        self.client.post(f"/cancelar-inscripcion/{self.equipo_b.id}/", {})

        self.equipo_b.refresh_from_db()
        self.assertEqual(self.equipo_b.estado_inscripcion, "APROBADO")


class CarnetsTest(DosCanchasTestCase):
    def test_usuario_ajeno_no_puede_imprimir_carnets_de_otra_cancha(self):
        User.objects.create_user("aficionado", password="pass12345")
        self.client.login(username="aficionado", password="pass12345")

        response = self.client.get(f"/imprimir-carnets/{self.equipo_a.id}/")

        self.assertNotEqual(response.status_code, 200)

    def test_organizador_no_puede_imprimir_carnets_de_otra_cancha(self):
        self.client.login(username="org_b", password="pass12345")

        response = self.client.get(f"/imprimir-carnets/{self.equipo_a.id}/")

        self.assertNotEqual(response.status_code, 200)


class ReciboPagoTest(DosCanchasTestCase):
    """Usamos raise_request_exception=False para que un error inesperado
    dentro de la vista (por ejemplo, el bug preexistente y no relacionado
    del filtro 'floatform' en acta_pago_pdf.html) no se confunda con el
    bloqueo de acceso que estamos verificando aquí: la única respuesta
    aceptable para estos casos es una redirección (302), nunca un 200
    ni un crash."""

    def test_anonimo_no_puede_ver_recibo_de_pago(self):
        client = self.client_class(raise_request_exception=False)
        response = client.get(f"/pago/pdf/{self.pago_a.id}/")

        self.assertEqual(response.status_code, 302)

    def test_organizador_no_puede_ver_recibo_de_pago_de_otra_cancha(self):
        client = self.client_class(raise_request_exception=False)
        client.login(username="org_b", password="pass12345")

        response = client.get(f"/pago/pdf/{self.pago_a.id}/")

        self.assertEqual(response.status_code, 302)


class RegistrarPagoTest(DosCanchasTestCase):
    def test_organizador_no_puede_registrar_pago_a_equipo_de_otra_cancha(self):
        self.client.login(username="org_a", password="pass12345")

        pagos_previos_equipo_b = Pago.objects.filter(equipo=self.equipo_b).count()

        # POST directo sin '?equipo=' en la URL, intentando inyectar un
        # equipo de la Cancha B en el campo 'equipo' del formulario.
        self.client.post("/pago/registrar/", {
            "equipo": self.equipo_b.id,
            "monto": "10.00",
            "fecha": "2026-01-01",
        })

        self.assertEqual(
            Pago.objects.filter(equipo=self.equipo_b).count(),
            pagos_previos_equipo_b,
        )


class EliminarMultaTest(DosCanchasTestCase):
    def test_vocal_no_puede_borrar_sancion_sin_partido_de_otra_cancha(self):
        # sancion_b no tiene 'partido' asociado (es una deuda administrativa
        # de inscripción), que es justo el caso que se salta la verificación
        # de acceso en el código actual.
        self.assertIsNone(self.sancion_b.partido)

        self.client.login(username="org_a", password="pass12345")
        self.client.post(f"/vocalia/eliminar_multa/{self.sancion_b.id}/")

        self.assertTrue(Sancion.objects.filter(id=self.sancion_b.id).exists())


class RevertirCobroSancionTest(DosCanchasTestCase):
    def test_vocal_no_puede_reversar_abono_de_sancion_de_otra_cancha(self):
        from .models import AbonoSancion

        self.sancion_b.monto_pagado = Decimal("10.00")
        self.sancion_b.save()
        AbonoSancion.objects.create(sancion=self.sancion_b, monto=Decimal("10.00"))

        self.client.login(username="org_a", password="pass12345")
        self.client.post(f"/sancion/reversar/{self.sancion_b.id}/")

        self.sancion_b.refresh_from_db()
        self.assertEqual(self.sancion_b.monto_pagado, Decimal("10.00"))


class GestionarVocaliaTest(DosCanchasTestCase):
    def test_vocal_no_puede_cobrar_deuda_de_sancion_de_otra_cancha(self):
        self.client.login(username="org_a", password="pass12345")

        self.client.post(f"/vocalia/{self.partido_a.id}/", {
            "cobrar_deuda": "1",
            "sancion_id": self.sancion_b.id,
            "monto_abono": "30.00",
        })

        self.sancion_b.refresh_from_db()
        self.assertEqual(self.sancion_b.monto_pagado, Decimal("0.00"))
        self.assertFalse(self.sancion_b.pagada)

    def test_vocal_no_puede_multar_equipo_de_otra_cancha_desde_su_propio_partido(self):
        self.client.login(username="org_a", password="pass12345")

        multas_previas_equipo_b = Sancion.objects.filter(equipo=self.equipo_b).count()

        self.client.post(f"/vocalia/{self.partido_a.id}/", {
            "nueva_multa": "1",
            "equipo_multa": self.equipo_b.id,
            "motivo_multa": "Multa inyectada desde otra cancha",
            "monto_multa": "5.00",
        })

        self.assertEqual(
            Sancion.objects.filter(equipo=self.equipo_b).count(),
            multas_previas_equipo_b,
        )

    def test_vocal_no_puede_registrar_incidencia_a_jugador_de_otro_equipo(self):
        self.client.login(username="org_a", password="pass12345")

        goles_antes = self.partido_a.goles_local

        # jugador_b no juega en este partido (ni siquiera es de esta cancha).
        self.client.post(f"/vocalia/incidencia/{self.partido_a.id}/", {
            "jugador_id": self.jugador_b.id,
            "tipo": "GOL",
            "minuto": "10",
        })

        self.partido_a.refresh_from_db()
        self.assertEqual(self.partido_a.goles_local, goles_antes)
        self.assertFalse(
            self.jugador_b.detallepartido_set.filter(partido=self.partido_a).exists()
        )


class AutomatizacionDiariaSaasTest(TestCase):
    """El token del cron debe leerse de settings (configurable por variable
    de entorno), no estar hardcodeado en la vista."""

    @override_settings(CRON_SECRET_TOKEN="otro-token-de-prueba")
    def test_acepta_el_token_configurado_en_settings(self):
        response = self.client.get("/api/cron/revision-diaria/?token=otro-token-de-prueba")
        self.assertEqual(response.status_code, 200)

    @override_settings(CRON_SECRET_TOKEN="otro-token-de-prueba")
    def test_rechaza_el_token_viejo_si_settings_cambio(self):
        response = self.client.get("/api/cron/revision-diaria/?token=NEXUS_SECRETO_2026")
        self.assertEqual(response.status_code, 403)


class LimiteJugadoresPorPlanTest(DosCanchasTestCase):
    def test_no_deja_fichar_mas_jugadores_que_el_limite_del_plan(self):
        self.plan.max_jugadores = 1
        self.plan.save()
        # complejo_a ya tiene 1 jugador (jugador_a) por el fixture base.

        self.client.login(username="org_a", password="pass12345")
        self.client.post(f"/jugadores/?equipo={self.equipo_a2.id}", {
            "equipo": self.equipo_a2.id,
            "nombres": "Jugador Nuevo",
            "dorsal": "99",
            "cedula": "1710000017",
        })

        self.assertEqual(
            Jugador.objects.filter(equipo__torneo__complejo=self.complejo_a).count(), 1,
        )

    def test_limite_de_una_cancha_no_afecta_a_la_otra(self):
        self.plan.max_jugadores = 1
        self.plan.save()
        # complejo_a está al límite (1/1), pero complejo_b debe poder seguir
        # fichando dentro de su propio cupo independiente.
        self.equipo_b.cupos_pagados = 10
        self.equipo_b.save()
        self.jugador_b.delete()  # dejamos a complejo_b en 0/1 para este caso

        self.client.login(username="org_b", password="pass12345")
        self.client.post(f"/jugadores/?equipo={self.equipo_b.id}", {
            "equipo": self.equipo_b.id,
            "nombres": "Jugador B Nuevo",
            "dorsal": "9",
            "cedula": "1710000025",
        })

        self.assertEqual(
            Jugador.objects.filter(equipo__torneo__complejo=self.complejo_b).count(), 1,
        )


class CierreDiarioCajaTest(DosCanchasTestCase):
    def setUp(self):
        super().setUp()
        self.hoy = timezone.localtime(timezone.now()).date()

        # Cancha A: una inscripción abonada hoy ($20) + un pago directo hoy ($5, ya viene del fixture).
        self.abono_a = AbonoSancion.objects.create(sancion=self.sancion_a, monto=Decimal("20.00"))

        # Cancha B: un abono de sanción hoy que NO debe filtrarse a la caja de A.
        self.abono_b = AbonoSancion.objects.create(sancion=self.sancion_b, monto=Decimal("30.00"))

        # Un abono de la Cancha A pero de ayer: no debe salir en la caja de HOY.
        self.sancion_a_vieja = Sancion.objects.create(
            torneo=self.torneo_a, equipo=self.equipo_a, tipo="ADMIN",
            monto=Decimal("15.00"), descripcion="Deuda vieja A", pagada=False,
        )
        self.abono_a_viejo = AbonoSancion.objects.create(sancion=self.sancion_a_vieja, monto=Decimal("15.00"))
        AbonoSancion.objects.filter(id=self.abono_a_viejo.id).update(
            fecha=timezone.now() - timedelta(days=1)
        )

    def test_caja_de_una_cancha_no_incluye_movimientos_de_otra(self):
        self.client.login(username="org_a", password="pass12345")
        response = self.client.get("/finanzas/caja-diaria/")

        self.assertEqual(response.context["total_inscripciones"], 20.0)
        self.assertEqual(response.context["total_pagos_directos"], 5.0)
        self.assertEqual(response.context["total_ingresos"], 25.0)

    def test_caja_no_incluye_abonos_de_otro_dia(self):
        self.client.login(username="org_a", password="pass12345")
        response = self.client.get("/finanzas/caja-diaria/")

        descripciones = [m["descripcion"] for m in response.context["multas_cobradas"]]
        self.assertNotIn("Deuda vieja A", descripciones)

    def test_caja_respeta_el_filtro_de_fecha(self):
        self.client.login(username="org_a", password="pass12345")
        ayer = (self.hoy - timedelta(days=1)).isoformat()

        response = self.client.get(f"/finanzas/caja-diaria/?fecha={ayer}")

        self.assertEqual(response.context["total_multas"], 15.0)
        self.assertEqual(response.context["total_inscripciones"], 0.0)


class VocaliaFirmasTest(DosCanchasTestCase):
    def test_guardar_informe_registra_las_firmas_digitales(self):
        self.client.login(username="org_a", password="pass12345")

        self.client.post(f"/vocalia/{self.partido_a.id}/", {
            "guardar_informe": "1",
            "informe_vocal": "Sin novedad",
            "informe_arbitro": "Partido normal",
            "firma_local_base64": "data:image/png;base64,AAAA",
            "firma_visita_base64": "data:image/png;base64,BBBB",
            "validado_local": "on",
            "validado_visita": "on",
        })

        self.partido_a.refresh_from_db()
        self.assertEqual(self.partido_a.firma_local_base64, "data:image/png;base64,AAAA")
        self.assertEqual(self.partido_a.firma_visita_base64, "data:image/png;base64,BBBB")

    def test_vocal_de_otra_cancha_no_puede_firmar_partido_ajeno(self):
        self.client.login(username="org_b", password="pass12345")

        self.client.post(f"/vocalia/{self.partido_a.id}/", {
            "guardar_informe": "1",
            "firma_local_base64": "data:image/png;base64,INTRUSO",
        })

        self.partido_a.refresh_from_db()
        self.assertNotEqual(self.partido_a.firma_local_base64, "data:image/png;base64,INTRUSO")


class GestionarUsuariosTest(DosCanchasTestCase):
    def test_no_ve_ni_encuentra_usuarios_de_otra_cancha(self):
        self.client.login(username="org_a", password="pass12345")

        response = self.client.get("/usuarios/gestionar/", {"q": "org_b"})

        usuarios_listados = [p.usuario for p in response.context["perfiles"]]
        self.assertNotIn(self.org_b, usuarios_listados)


class CambiarEstadoTorneoTest(DosCanchasTestCase):
    def test_organizador_no_puede_cambiar_estado_de_torneo_de_otra_cancha(self):
        self.client.login(username="org_a", password="pass12345")

        self.client.post(f"/torneos/estado/{self.torneo_b.id}/")

        self.torneo_b.refresh_from_db()
        self.assertTrue(self.torneo_b.activo)

    def test_no_puede_reabrir_torneo_si_ya_esta_en_el_limite_del_plan(self):
        self.plan.max_torneos = 1
        self.plan.save()
        self.torneo_a.activo = False
        self.torneo_a.save()
        Torneo.objects.create(complejo=self.complejo_a, nombre="Otro Torneo A", organizador=self.org_a, activo=True)

        self.client.login(username="org_a", password="pass12345")
        self.client.post(f"/torneos/estado/{self.torneo_a.id}/")

        self.torneo_a.refresh_from_db()
        self.assertFalse(self.torneo_a.activo)

    def test_organizador_puede_finalizar_y_reabrir_su_propio_torneo(self):
        self.client.login(username="org_a", password="pass12345")

        self.client.post(f"/torneos/estado/{self.torneo_a.id}/")
        self.torneo_a.refresh_from_db()
        self.assertFalse(self.torneo_a.activo)

        self.client.post(f"/torneos/estado/{self.torneo_a.id}/")
        self.torneo_a.refresh_from_db()
        self.assertTrue(self.torneo_a.activo)


class GestionarMediosMultiUploadTest(DosCanchasTestCase):
    def test_puede_subir_varias_fotos_a_la_vez_y_quedan_en_su_cancha(self):
        self.client.login(username="org_a", password="pass12345")

        self.client.post("/medios/", {
            "btn_foto": "1",
            "titulo": "Fotos del torneo",
            "orden": "0",
            "imagen": [imagen_falsa("una.jpg"), imagen_falsa("dos.jpg")],
        })

        nuevas = FotoGaleria.objects.filter(complejo=self.complejo_a, titulo="Fotos del torneo")
        self.assertEqual(nuevas.count(), 2)


class GestionarSolicitudesTest(DosCanchasTestCase):
    def setUp(self):
        super().setUp()
        self.equipo_a.estado_inscripcion = "PENDIENTE"
        self.equipo_a.save()

    def test_la_pagina_carga_sin_reventar(self):
        self.client.login(username="org_a", password="pass12345")
        response = self.client.get("/solicitudes/")
        self.assertEqual(response.status_code, 200)

    def test_aprobar_solicitud_no_revienta_y_actualiza_estado(self):
        self.client.login(username="org_a", password="pass12345")
        response = self.client.post("/solicitudes/", {"equipo_id": self.equipo_a.id, "accion": "APROBAR"})

        self.assertEqual(response.status_code, 302)
        self.equipo_a.refresh_from_db()
        self.assertEqual(self.equipo_a.estado_inscripcion, "APROBADO")


class NotificarEquipoWhatsappTest(DosCanchasTestCase):
    def test_no_puede_notificar_a_equipo_de_otra_cancha(self):
        self.equipo_b.telefono_contacto = "0991234567"
        self.equipo_b.save()

        self.client.login(username="org_a", password="pass12345")
        response = self.client.get(f"/finanzas/notificar-whatsapp/{self.equipo_b.id}/")

        self.assertNotEqual(response.status_code, 200)
        self.assertNotIn("wa.me", response.get("Location", ""))

    def test_genera_enlace_de_whatsapp_para_su_propio_equipo(self):
        self.equipo_a.telefono_contacto = "0991234567"
        self.equipo_a.save()

        self.client.login(username="org_a", password="pass12345")
        response = self.client.get(f"/finanzas/notificar-whatsapp/{self.equipo_a.id}/")

        self.assertTrue(response["Location"].startswith("https://wa.me/593991234567?text="))


class GenerarHorariosImagenTest(DosCanchasTestCase):
    def setUp(self):
        super().setUp()
        self.partido_a.estado = "PROG"
        self.partido_a.fecha_hora = timezone.now() + timedelta(days=1)
        self.partido_a.save()

        self.partido_b.estado = "PROG"
        self.partido_b.fecha_hora = timezone.now() + timedelta(days=1)
        self.partido_b.save()

    def test_solo_muestra_partidos_de_su_propia_cancha(self):
        self.client.login(username="org_a", password="pass12345")
        response = self.client.get("/horarios/imagen/")

        partidos_mostrados = list(response.context["partidos"])
        self.assertIn(self.partido_a, partidos_mostrados)
        self.assertNotIn(self.partido_b, partidos_mostrados)


class MisFinanzasEquipoTest(DosCanchasTestCase):
    """org_a es dirigente de DOS equipos (equipo_a y equipo_a2) en el
    fixture base — el .get() de gestion_futbol asumía un solo equipo por
    dirigente y hubiera reventado con MultipleObjectsReturned aquí."""

    def test_no_revienta_cuando_el_dirigente_tiene_varios_equipos(self):
        self.client.login(username="org_a", password="pass12345")
        response = self.client.get("/mis-finanzas-equipo/")
        self.assertEqual(response.status_code, 200)

    def test_puede_elegir_entre_sus_equipos_y_ver_solo_esas_deudas(self):
        Sancion.objects.create(torneo=self.torneo_a, equipo=self.equipo_a, tipo="ADMIN", monto=Decimal("10.00"), descripcion="Deuda equipo A", pagada=False)
        Sancion.objects.create(torneo=self.torneo_a, equipo=self.equipo_a2, tipo="ADMIN", monto=Decimal("20.00"), descripcion="Deuda equipo A2", pagada=False)

        self.client.login(username="org_a", password="pass12345")
        response = self.client.get(f"/mis-finanzas-equipo/?equipo={self.equipo_a2.id}")

        self.assertEqual(response.context["equipo"], self.equipo_a2)
        descripciones = [s.descripcion for s in response.context["sanciones"]]
        self.assertIn("Deuda equipo A2", descripciones)
        self.assertNotIn("Deuda equipo A", descripciones)

    def test_no_puede_ver_finanzas_de_equipo_de_otro_dirigente(self):
        self.client.login(username="org_a", password="pass12345")
        response = self.client.get(f"/mis-finanzas-equipo/?equipo={self.equipo_b.id}")

        self.assertNotEqual(response.context["equipo"], self.equipo_b)


class LoginPorCedulaTest(DosCanchasTestCase):
    def setUp(self):
        super().setUp()
        self.org_a.perfil.cedula = "1710000009"
        self.org_a.perfil.save()
        self.org_b.perfil.cedula = "1710000017"
        self.org_b.perfil.save()

    def test_puede_iniciar_sesion_con_la_cedula(self):
        user = authenticate(username="1710000009", password="pass12345")
        self.assertEqual(user, self.org_a)

    def test_sigue_pudiendo_iniciar_sesion_con_el_username(self):
        user = authenticate(username="org_a", password="pass12345")
        self.assertEqual(user, self.org_a)

    def test_cedula_de_un_usuario_no_autentica_a_otro_con_su_propia_clave(self):
        user = authenticate(username="1710000009", password="otra-clave-cualquiera")
        self.assertIsNone(user)

    def test_cedula_inexistente_no_revienta(self):
        user = authenticate(username="9999999999", password="pass12345")
        self.assertIsNone(user)

    def test_login_por_cedula_via_formulario_funciona_end_to_end(self):
        response = self.client.post("/login/", {"username": "1710000017", "password": "pass12345"})
        self.assertRedirects(response, "/dashboard/", fetch_redirect_response=False)

    def test_registro_publico_no_revienta_al_iniciar_sesion_automaticamente(self):
        response = self.client.post("/registro/", {
            "username": "nuevo_fan",
            "password1": "ClaveSegura123!",
            "password2": "ClaveSegura123!",
            "first_name": "Nuevo",
            "last_name": "Fan",
            "email": "nuevo_fan@example.com",
        })
        self.assertEqual(response.status_code, 302)
