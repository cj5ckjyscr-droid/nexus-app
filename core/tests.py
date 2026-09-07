from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import (
    AbonoSancion, ComplejoDeportivo, Configuracion, DetallePartido, Equipo,
    FotoGaleria, Jugador, Partido, Pago, PlanSuscripcion, RolComplejo, Sancion,
    Torneo,
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


from .services.pruebas import crear_entorno_prueba, eliminar_entorno_prueba, obtener_o_crear_plan_demo


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
