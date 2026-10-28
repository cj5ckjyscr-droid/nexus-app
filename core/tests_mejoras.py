from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from .models import (AbonoSancion, ComplejoDeportivo, DetallePartido, Equipo, Jugador, MovimientoFinanciero,
                     Partido, PlanSuscripcion, RolComplejo, Sancion, Torneo)
from .tests import DosCanchasTestCase


class UnirseCanchaTest(DosCanchasTestCase):
    def test_ya_no_existe_unirse_como_aficionado(self):
        User.objects.create_user("aficionado", password="pass12345")
        self.client.login(username="aficionado", password="pass12345")
        r = self.client.post(f"/cancha/{self.complejo_a.slug}/unirme/")
        self.assertEqual(r.status_code, 404)
        self.assertFalse(RolComplejo.objects.filter(usuario__username="aficionado").exists())

    def test_dueno_crea_vocal_que_solo_entra_a_su_cancha(self):
        self.client.login(username="org_a", password="pass12345")
        r = self.client.post("/usuarios/crear/", {"first_name": "Juan Carlos", "last_name": "Pérez", "rol": "VOC"})
        self.assertRedirects(r, "/usuarios/credenciales/", fetch_redirect_response=False)
        vocal = User.objects.get(username="juan.perez")
        rc = RolComplejo.objects.get(usuario=vocal)
        self.assertEqual((rc.complejo, rc.rol, rc.creado_por_cancha), (self.complejo_a, "VOC", True))

        # La contraseña generada se muestra una sola vez
        r = self.client.get("/usuarios/credenciales/")
        clave = r.context["cred"]["clave"]
        self.assertContains(r, "juan.perez")
        self.assertRedirects(self.client.get("/usuarios/credenciales/"), "/usuarios/gestionar/", fetch_redirect_response=False)

        # Con esas credenciales entra (desde cualquier dispositivo) solo a SU cancha
        self.client.logout()
        self.assertTrue(self.client.login(username="juan.perez", password=clave))
        self.assertEqual(self.client.get(f"/vocalia/{self.partido_a.id}/").status_code, 200)
        r = self.client.get(f"/vocalia/{self.partido_b.id}/")
        self.assertEqual(r.status_code, 302)

    def test_solo_el_dueno_crea_cuentas_no_el_staff_ni_otros(self):
        staff = User.objects.create_user("staff_a", password="pass12345")
        RolComplejo.objects.create(usuario=staff, complejo=self.complejo_a, rol="ORG")
        self.client.login(username="staff_a", password="pass12345")
        self.client.post("/usuarios/crear/", {"first_name": "Intruso", "rol": "VOC"})
        self.assertFalse(User.objects.filter(first_name="Intruso").exists())

    def test_restablecer_y_quitar_cuenta_de_la_cancha(self):
        self.client.login(username="org_a", password="pass12345")
        self.client.post("/usuarios/crear/", {"first_name": "Ana", "username": "ana.vocal", "password": "ClaveSegura123", "rol": "VOC"})
        rc = RolComplejo.objects.get(usuario__username="ana.vocal")
        self.client.post("/usuarios/gestionar/", {"rol_cancha_id": rc.id, "restablecer": "1"})
        nueva = self.client.get("/usuarios/credenciales/").context["cred"]["clave"]
        rc.usuario.refresh_from_db()
        self.assertTrue(rc.usuario.check_password(nueva))
        self.assertFalse(rc.usuario.check_password("ClaveSegura123"))

        # Quitarla de la cancha la desactiva: ya no puede iniciar sesión
        self.client.post("/usuarios/gestionar/", {"rol_cancha_id": rc.id, "quitar": "1"})
        rc.usuario.refresh_from_db()
        self.assertFalse(rc.usuario.is_active)

    def test_no_se_restablece_la_clave_de_una_cuenta_ajena(self):
        # Un dirigente que se registró solo NO es una cuenta de la cancha
        dirigente = User.objects.create_user("dir_libre", password="pass12345")
        rc = RolComplejo.objects.create(usuario=dirigente, complejo=self.complejo_a, rol="DIR")
        self.client.login(username="org_a", password="pass12345")
        self.client.post("/usuarios/gestionar/", {"rol_cancha_id": rc.id, "restablecer": "1"})
        dirigente.refresh_from_db()
        self.assertTrue(dirigente.check_password("pass12345"))

    def test_org_de_otra_cancha_no_cambia_roles_ajenos(self):
        fan = User.objects.create_user("aficionado", password="pass12345")
        rc = RolComplejo.objects.create(usuario=fan, complejo=self.complejo_a, rol="FAN")
        self.client.login(username="org_b", password="pass12345")
        self.client.post("/usuarios/gestionar/", {"rol_cancha_id": rc.id, "nuevo_rol": "ORG"})
        rc.refresh_from_db()
        self.assertEqual(rc.rol, "FAN")


class RolDirigenteNoDegradaTest(DosCanchasTestCase):
    def test_vocal_que_inscribe_equipo_sigue_siendo_vocal(self):
        vocal = User.objects.create_user("vocal", password="pass12345")
        RolComplejo.objects.create(usuario=vocal, complejo=self.complejo_a, rol="VOC")
        self.client.login(username="vocal", password="pass12345")
        self.client.post(f"/solicitar-inscripcion/{self.torneo_a.id}/", {
            "nombre": "Los Halcones", "telefono_contacto": "0991234567"})
        self.assertEqual(RolComplejo.objects.get(usuario=vocal, complejo=self.complejo_a).rol, "VOC")


class UsuariosMuestraEquipoTest(DosCanchasTestCase):
    def test_lista_indica_que_equipo_dirige(self):
        dir_ = User.objects.create_user("dirigente1", password="pass12345")
        RolComplejo.objects.create(usuario=dir_, complejo=self.complejo_a, rol="DIR")
        Equipo.objects.create(torneo=self.torneo_a, dirigente=dir_, nombre="Deportivo Carcelén", estado_inscripcion="APROBADO")
        self.client.login(username="org_a", password="pass12345")
        r = self.client.get("/usuarios/gestionar/")
        self.assertContains(r, "Deportivo Carcelén")


class SuspenderJugadorTest(DosCanchasTestCase):
    def test_suspender_y_sumar_partidos(self):
        self.client.login(username="org_a", password="pass12345")
        self.client.post(f"/jugadores/suspender/{self.jugador_a.id}/", {"accion": "partidos", "partidos": "2", "motivo": "Agresión"})
        self.client.post(f"/jugadores/suspender/{self.jugador_a.id}/", {"accion": "partidos", "partidos": "3"})
        self.jugador_a.refresh_from_db()
        self.assertEqual(self.jugador_a.partidos_suspension, 5)
        self.assertEqual(self.jugador_a.motivo_suspension, "Agresión")
        self.assertFalse(self.jugador_a.esta_habilitado)
        self.client.post(f"/jugadores/suspender/{self.jugador_a.id}/", {"accion": "levantar"})
        self.jugador_a.refresh_from_db()
        self.assertTrue(self.jugador_a.esta_habilitado)

    def test_no_puede_suspender_jugador_de_otra_cancha(self):
        self.client.login(username="org_a", password="pass12345")
        r = self.client.post(f"/jugadores/suspender/{self.jugador_b.id}/", {"accion": "expulsar"})
        self.assertEqual(r.status_code, 404)
        self.jugador_b.refresh_from_db()
        self.assertFalse(self.jugador_b.expulsado_torneo)

    def test_suspendido_no_puede_entrar_a_la_cancha(self):
        self.jugador_a.partidos_suspension = 1
        self.jugador_a.save()
        self.client.login(username="org_a", password="pass12345")
        self.client.post(f"/vocalia/toggle-asistencia/{self.partido_a.id}/{self.jugador_a.id}/")
        self.assertFalse(DetallePartido.objects.filter(partido=self.partido_a, jugador=self.jugador_a).exists())


class CuotaPartidosTest(DosCanchasTestCase):
    def test_bloquea_a_quien_no_cumple_el_minimo(self):
        jugador2 = Jugador.objects.create(equipo=self.equipo_a, nombres="Pedro Cevallos", dorsal=11, cedula="1710034081")
        DetallePartido.objects.create(partido=self.partido_a, jugador=jugador2, tipo="ASIS", equipo_incidencia=self.equipo_a)
        self.client.login(username="org_a", password="pass12345")
        self.client.post(f"/torneo/{self.torneo_a.id}/suspender-cuota/", {"limite_partidos": "1"})
        self.jugador_a.refresh_from_db(); jugador2.refresh_from_db()
        self.assertTrue(self.jugador_a.bloqueado_por_cuota)
        self.assertFalse(jugador2.bloqueado_por_cuota)
        self.client.post(f"/torneo/{self.torneo_a.id}/revertir-cuota/")
        self.jugador_a.refresh_from_db()
        self.assertFalse(self.jugador_a.bloqueado_por_cuota)

    def test_otra_cancha_no_puede_aplicar_cuota(self):
        self.client.login(username="org_b", password="pass12345")
        r = self.client.post(f"/torneo/{self.torneo_a.id}/suspender-cuota/", {"limite_partidos": "5"})
        self.assertEqual(r.status_code, 404)


class DocumentoExtranjeroTest(DosCanchasTestCase):
    def test_admin_ficha_jugador_venezolano(self):
        self.client.login(username="org_a", password="pass12345")
        self.client.post(f"/jugadores/?equipo={self.equipo_a2.id}", {
            "equipo": self.equipo_a2.id, "nombres": "Luis Rondon", "dorsal": "9",
            "tipo_documento": "VE", "cedula": "V-12345678"})
        j = Jugador.objects.get(nombres="Luis Rondon")
        self.assertEqual((j.tipo_documento, j.cedula), ("VE", "12345678"))

    def test_dirigente_no_puede_fichar_colombiano(self):
        dir_ = User.objects.create_user("dirigente1", password="pass12345")
        RolComplejo.objects.create(usuario=dir_, complejo=self.complejo_a, rol="DIR")
        eq = Equipo.objects.create(torneo=self.torneo_a, dirigente=dir_, nombre="Unión Comité", estado_inscripcion="APROBADO")
        self.client.login(username="dirigente1", password="pass12345")
        self.client.post(f"/jugadores/?equipo={eq.id}", {
            "equipo": eq.id, "nombres": "Juan Cuadrado", "dorsal": "11",
            "tipo_documento": "CO", "cedula": "12345678"})
        self.assertFalse(Jugador.objects.filter(nombres="Juan Cuadrado").exists())

    def test_admin_no_puede_fichar_en_equipo_de_otra_cancha(self):
        self.client.login(username="org_a", password="pass12345")
        self.client.post(f"/jugadores/?equipo={self.equipo_a.id}", {
            "equipo": self.equipo_b.id, "nombres": "Intruso Total", "dorsal": "50", "cedula": "1710000017"})
        self.assertFalse(Jugador.objects.filter(nombres="Intruso Total").exists())


class TrazabilidadFinancieraTest(DosCanchasTestCase):
    def test_cobro_y_reverso_del_vocal_quedan_registrados(self):
        vocal = User.objects.create_user("vocal", password="pass12345")
        RolComplejo.objects.create(usuario=vocal, complejo=self.complejo_a, rol="VOC")
        self.client.login(username="vocal", password="pass12345")
        self.client.post(f"/vocalia/{self.partido_a.id}/", {"cobrar_deuda": "1", "sancion_id": self.sancion_a.id, "monto_abono": "5.00"})
        self.client.post(f"/sancion/reversar/{self.sancion_a.id}/")
        movs = MovimientoFinanciero.objects.filter(complejo=self.complejo_a, usuario=vocal)
        self.assertEqual(set(movs.values_list("tipo", flat=True)), {"ABONO", "REVERSO"})
        self.assertTrue(all(m.origen == "VOCALIA" for m in movs))

    def test_abono_negativo_o_mayor_al_saldo_se_rechaza(self):
        self.client.login(username="org_a", password="pass12345")
        self.client.post(f"/vocalia/{self.partido_a.id}/", {"cobrar_deuda": "1", "sancion_id": self.sancion_a.id, "monto_abono": "-10"})
        self.client.post(f"/vocalia/{self.partido_a.id}/", {"cobrar_deuda": "1", "sancion_id": self.sancion_a.id, "monto_abono": "999"})
        self.sancion_a.refresh_from_db()
        self.assertEqual(self.sancion_a.monto_pagado, Decimal("0.00"))

    def test_borrar_multa_queda_registrado_y_bloqueado_si_tiene_cobros(self):
        multa = Sancion.objects.create(torneo=self.torneo_a, equipo=self.equipo_a, partido=self.partido_a,
                                       tipo="ADMIN", monto=Decimal("5"), descripcion="Barra agresiva")
        self.client.login(username="org_a", password="pass12345")
        self.client.post(f"/vocalia/eliminar_multa/{multa.id}/")
        self.assertFalse(Sancion.objects.filter(id=multa.id).exists())
        self.assertTrue(MovimientoFinanciero.objects.filter(tipo="ANULACION", sancion_ref=multa.id).exists())

        cobrada = Sancion.objects.create(torneo=self.torneo_a, equipo=self.equipo_a, tipo="ADMIN",
                                         monto=Decimal("5"), monto_pagado=Decimal("5"), pagada=True, descripcion="Multa pagada")
        self.client.post(f"/vocalia/eliminar_multa/{cobrada.id}/")
        self.assertTrue(Sancion.objects.filter(id=cobrada.id).exists())

    def test_cada_cancha_solo_ve_su_historial(self):
        self.client.login(username="org_a", password="pass12345")
        self.client.post(f"/vocalia/{self.partido_a.id}/", {"cobrar_deuda": "1", "sancion_id": self.sancion_a.id, "monto_abono": "5.00"})
        self.client.login(username="org_b", password="pass12345")
        r = self.client.get("/finanzas/trazabilidad/")
        self.assertTrue(MovimientoFinanciero.objects.filter(complejo=self.complejo_a, tipo="ABONO").exists())
        self.assertFalse(any(m.complejo_id == self.complejo_a.id for m in r.context["movimientos"]))


class PartidoCerradoTest(DosCanchasTestCase):
    def _finalizado(self):
        DetallePartido.objects.create(partido=self.partido_a, jugador=self.jugador_a, tipo="ASIS", equipo_incidencia=self.equipo_a)
        self.partido_a.estado = "JUG"
        self.partido_a.sanciones_aplicadas = True
        self.partido_a.save()

    def test_vocal_no_puede_editar_partido_finalizado(self):
        self._finalizado()
        vocal = User.objects.create_user("vocal", password="pass12345")
        RolComplejo.objects.create(usuario=vocal, complejo=self.complejo_a, rol="VOC")
        self.client.login(username="vocal", password="pass12345")
        self.client.post(f"/vocalia/incidencia/{self.partido_a.id}/", {"jugador_id": self.jugador_a.id, "tipo": "GOL"})
        self.partido_a.refresh_from_db()
        self.assertEqual(self.partido_a.goles_local, 0)
        self.assertFalse(self.partido_a.ediciones.exists())

    def test_admin_edita_partido_finalizado_y_queda_registrado(self):
        from .models import EdicionPartido
        self._finalizado()
        self.client.login(username="org_a", password="pass12345")
        self.client.post(f"/vocalia/incidencia/{self.partido_a.id}/", {"jugador_id": self.jugador_a.id, "tipo": "GOL"})
        self.client.post(f"/vocalia/incidencia/{self.partido_a.id}/", {"jugador_id": self.jugador_a.id, "tipo": "TA"})
        self.partido_a.refresh_from_db()
        self.assertEqual((self.partido_a.goles_local, self.partido_a.estado), (1, "JUG"))
        detalles = list(EdicionPartido.objects.filter(partido=self.partido_a).values_list("detalle", flat=True))
        self.assertEqual(len(detalles), 2)
        self.assertIn("Marcador 0-0 → 1-0", detalles[0])
        # la amarilla genera su multa una sola vez aunque se recalculen sanciones
        self.client.post(f"/vocalia/{self.partido_a.id}/", {"guardar_informe": "1", "informe_vocal": "Corregido", "informe_arbitro": ""})
        self.assertEqual(Sancion.objects.filter(partido=self.partido_a, tipo="AMARILLA").count(), 1)
        self.assertEqual(EdicionPartido.objects.filter(partido=self.partido_a).count(), 3)
        r = self.client.get(f"/vocalia/{self.partido_a.id}/")
        self.assertContains(r, "Ediciones del administrador")
        r = self.client.get(f"/acta/pdf/{self.partido_a.id}/")
        self.assertEqual(r["Content-Type"], "application/pdf")

    def test_edicion_sin_cambios_no_registra_nada(self):
        self._finalizado()
        self.client.login(username="org_a", password="pass12345")
        self.client.post(f"/vocalia/{self.partido_a.id}/", {"guardar_informe": "1", "informe_vocal": "", "informe_arbitro": ""})
        self.assertFalse(self.partido_a.ediciones.exists())

    def test_acciones_destructivas_por_get_no_hacen_nada(self):
        evento = DetallePartido.objects.create(partido=self.partido_a, jugador=self.jugador_a, tipo="ASIS", equipo_incidencia=self.equipo_a)
        self.client.login(username="org_a", password="pass12345")
        r = self.client.get(f"/vocalia/eliminar_evento_exacto/{evento.id}/")
        self.assertEqual(r.status_code, 405)
        r = self.client.get(f"/equipos/eliminar/{self.equipo_a.id}/")
        self.assertEqual(r.status_code, 405)
        self.assertTrue(Equipo.objects.filter(id=self.equipo_a.id).exists())

    def test_wo_sin_tipo_no_cierra_el_partido(self):
        self.client.login(username="org_a", password="pass12345")
        self.client.post(f"/vocalia/{self.partido_a.id}/", {"declarar_wo": "1"})
        self.partido_a.refresh_from_db()
        self.assertEqual(self.partido_a.estado, "PROG")

    def test_wo_valido_cierra(self):
        self.client.login(username="org_a", password="pass12345")
        self.client.post(f"/vocalia/{self.partido_a.id}/", {"declarar_wo": "1", "tipo_wo": "VISITA"})
        self.partido_a.refresh_from_db()
        self.assertEqual((self.partido_a.estado, self.partido_a.ganador_wo), ("WO", self.equipo_a2))


class EquiposRetiradosTest(DosCanchasTestCase):
    def test_equipos_rechazados_no_aparecen_en_la_lista(self):
        Equipo.objects.create(torneo=self.torneo_a, dirigente=self.org_a, nombre="Retirado Sporting", estado_inscripcion="RECHAZADO")
        self.client.login(username="org_a", password="pass12345")
        r = self.client.get("/equipos/")
        self.assertNotContains(r, "Retirado Sporting")
        r = self.client.get("/equipos/?ver=retirados")
        self.assertContains(r, "Retirado Sporting")


class FlujoCampeonatoVistasTest(DosCanchasTestCase):
    def setUp(self):
        super().setUp()
        self.torneo = Torneo.objects.create(complejo=self.complejo_a, nombre="Copa Verano", organizador=self.org_a)
        nombres = ["Atlético Sur", "Real Carcelén", "Unión Comité", "Los Halcones",
                   "Juventud Norte", "Estrella Roja", "San José FC", "Deportivo Pichincha"]
        self.equipos = [Equipo.objects.create(torneo=self.torneo, dirigente=self.org_a, nombre=n, estado_inscripcion="APROBADO") for n in nombres]
        self.client.login(username="org_a", password="pass12345")

    def test_no_se_pueden_crear_partidos_a_mano_sin_empezar_campeonato(self):
        self.client.post("/programar/", {"torneo": self.torneo.id, "numero_fecha": 1, "etapa": "F1",
                                         "equipo_local": self.equipos[0].id, "equipo_visita": self.equipos[1].id, "cancha": "Principal"})
        self.assertFalse(Partido.objects.filter(torneo=self.torneo).exists())

    def test_vista_previa_no_guarda_y_confirmar_si(self):
        datos = {"formato": "GRUPOS", "num_grupos": "2", "clasifican": "2", "mejores": "0", "tercer_lugar": "on"}
        r = self.client.post(f"/campeonato/{self.torneo.id}/empezar/", {**datos, "accion": "previsualizar"})
        self.assertContains(r, "Grupo A")
        self.assertFalse(Partido.objects.filter(torneo=self.torneo).exists())
        semilla = r.context["semilla"]
        r = self.client.post(f"/campeonato/{self.torneo.id}/empezar/", {**datos, "accion": "pdf", "semilla": semilla})
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.client.post(f"/campeonato/{self.torneo.id}/empezar/", {**datos, "accion": "confirmar", "semilla": semilla})
        self.torneo.refresh_from_db()
        self.assertEqual(self.torneo.formato, "GRUPOS")
        self.assertEqual(self.torneo.semilla_sorteo, semilla)
        self.assertEqual(Partido.objects.filter(torneo=self.torneo, etapa="GRP").count(), 12)
        r = self.client.get(f"/campeonato/{self.torneo.id}/")
        self.assertContains(r, "1° Grupo A")

    def test_estructura_invalida_muestra_error(self):
        r = self.client.post(f"/campeonato/{self.torneo.id}/empezar/", {
            "formato": "GRUPOS", "num_grupos": "2", "clasifican": "3", "mejores": "0", "accion": "confirmar"})
        self.assertContains(r, "deben ser 2, 4, 8, 16 o 32")
        self.assertFalse(Partido.objects.filter(torneo=self.torneo).exists())

    def test_otra_cancha_no_puede_empezar_mi_campeonato(self):
        self.client.login(username="org_b", password="pass12345")
        r = self.client.post(f"/campeonato/{self.torneo.id}/empezar/", {"formato": "LIGA", "accion": "confirmar"})
        self.assertEqual(r.status_code, 404)

    def test_cerrar_fase_con_exclusion_y_pdf(self):
        self.client.post(f"/campeonato/{self.torneo.id}/empezar/", {
            "formato": "LIGA_PLAYOFF", "clasifican_liga": "4", "accion": "confirmar", "semilla": "77"})
        for p in Partido.objects.filter(torneo=self.torneo):
            p.goles_local, p.goles_visita, p.estado = (1, 0, "JUG") if p.equipo_local_id < p.equipo_visita_id else (0, 1, "JUG")
            p.save()
        r = self.client.post(f"/campeonato/{self.torneo.id}/cerrar-fase/", {"accion": "pdf"})
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.client.post(f"/campeonato/{self.torneo.id}/cerrar-fase/", {"accion": "confirmar", "excluir": [self.equipos[0].id]})
        ids = set()
        for p in Partido.objects.filter(torneo=self.torneo, etapa="SEMI"):
            ids |= {p.equipo_local_id, p.equipo_visita_id}
        self.assertEqual(len(ids), 4)
        self.assertNotIn(self.equipos[0].id, ids)
        r = self.client.get(f"/campeonato/{self.torneo.id}/fixture.pdf?fase=SEMI")
        self.assertEqual(r["Content-Type"], "application/pdf")

    def test_no_se_aprueban_equipos_despues_de_empezar(self):
        self.client.post(f"/campeonato/{self.torneo.id}/empezar/", {"formato": "LIGA", "accion": "confirmar"})
        tarde = Equipo.objects.create(torneo=self.torneo, dirigente=self.org_a, nombre="Llegó Tarde FC")
        self.client.post("/solicitudes/", {"equipo_id": tarde.id, "accion": "APROBAR"})
        tarde.refresh_from_db()
        self.assertEqual(tarde.estado_inscripcion, "PENDIENTE")


class ClasicoExclusionTest(DosCanchasTestCase):
    def test_generar_fase2_excluye_equipo(self):
        self.torneo_a.formato = "CLASICO"
        self.torneo_a.save()
        extra = Equipo.objects.create(torneo=self.torneo_a, dirigente=self.org_a, nombre="Sancionado FC", estado_inscripcion="APROBADO")
        self.client.login(username="org_a", password="pass12345")
        self.client.post(f"/generar_fase2/{self.torneo_a.id}/", {"excluir": [extra.id]})
        extra.refresh_from_db(); self.equipo_a.refresh_from_db()
        self.assertIsNone(extra.grupo_fase2)
        self.assertIn(self.equipo_a.grupo_fase2, ("A", "B"))

    def test_panel_de_transicion_visible_para_el_organizador(self):
        self.torneo_a.formato = "CLASICO"
        self.torneo_a.save()
        self.client.login(username="org_a", password="pass12345")
        r = self.client.get(f"/posiciones/{self.torneo_a.id}/")
        self.assertContains(r, "Transición de Torneo")


class ActaYCarnetsTest(DosCanchasTestCase):
    def test_planilla_agrupa_goles_tarjetas_y_figura_por_jugador(self):
        from .views import _planilla_equipo
        for tipo in ("ASIS", "GOL", "GOL", "TA", "STAR"):
            DetallePartido.objects.create(partido=self.partido_a, jugador=self.jugador_a, tipo=tipo, equipo_incidencia=self.equipo_a)
        detalles = list(DetallePartido.objects.filter(partido=self.partido_a).select_related("jugador"))
        filas = _planilla_equipo(self.equipo_a, detalles)
        self.assertEqual(len(filas), 1)
        f = filas[0]
        self.assertEqual((f["presente"], f["goles"], f["ta"], f["figura"]), (True, 2, 1, True))

    def test_acta_pdf_se_genera_sin_escudos(self):
        self.client.login(username="org_a", password="pass12345")
        DetallePartido.objects.create(partido=self.partido_a, jugador=self.jugador_a, tipo="TR", observacion="Agresión", equipo_incidencia=self.equipo_a)
        r = self.client.get(f"/acta/pdf/{self.partido_a.id}/")
        self.assertEqual(r["Content-Type"], "application/pdf")

    def test_carnets_muestran_escudo_o_iniciales(self):
        self.client.login(username="org_a", password="pass12345")
        r = self.client.get(f"/imprimir-carnets/{self.equipo_a.id}/")
        self.assertEqual(r.status_code, 200)
        iniciales = "".join(p[0] for p in self.equipo_a.nombre.split()[:2]).upper()
        self.assertContains(r, f'<span class="iniciales">{iniciales}</span>', html=True)


class PanelSaasPlanesTest(DosCanchasTestCase):
    def setUp(self):
        super().setUp()
        from .models import PlanSuscripcion
        self.Plan = PlanSuscripcion
        User.objects.create_superuser("jefe_saas", password="pass12345")
        self.client.login(username="jefe_saas", password="pass12345")

    def _datos_plan(self, **extra):
        datos = {"nombre": "Plan Secreto", "descripcion": "Solo por invitación", "costo_inscripcion": "0",
                 "precio_mensual": "25", "max_torneos": "3", "max_categorias_por_torneo": "2",
                 "max_jugadores": "200"}
        datos.update(extra)
        return datos

    def test_plan_oculto_no_sale_en_precios_pero_si_se_puede_asignar(self):
        self.client.post("/nexus-admin/planes/", self._datos_plan())  # sin marcar visible_publico
        plan = self.Plan.objects.get(nombre="Plan Secreto")
        self.assertFalse(plan.visible_publico)
        r = self.client.get("/precios/")
        self.assertNotIn(plan, list(r.context["planes"]))
        from .forms import ComplejoDeportivoForm
        self.assertIn(plan, ComplejoDeportivoForm().fields["plan"].queryset)

    def test_editar_plan_y_alternar_visibilidad(self):
        plan = self.Plan.objects.create(nombre="Plan Editable", precio_mensual=Decimal("10"))
        r = self.client.get(f"/nexus-admin/planes/{plan.id}/editar/")
        self.assertContains(r, "Editar «Plan Editable»")
        self.client.post(f"/nexus-admin/planes/{plan.id}/editar/",
                         self._datos_plan(nombre="Plan Editado", visible_publico="on", destacado="on"))
        plan.refresh_from_db()
        self.assertEqual((plan.nombre, plan.precio_mensual, plan.destacado, plan.visible_publico),
                         ("Plan Editado", Decimal("25"), True, True))
        self.assertIn(plan, list(self.client.get("/precios/").context["planes"]))

        self.client.post(f"/nexus-admin/planes/{plan.id}/visibilidad/")
        plan.refresh_from_db()
        self.assertFalse(plan.visible_publico)
        self.assertNotIn(plan, list(self.client.get("/precios/").context["planes"]))

    def test_no_se_elimina_un_plan_en_uso(self):
        en_uso = self.complejo_a.plan
        self.client.post(f"/nexus-admin/planes/{en_uso.id}/eliminar/")
        self.assertTrue(self.Plan.objects.filter(id=en_uso.id).exists())
        libre = self.Plan.objects.create(nombre="Plan Libre", precio_mensual=Decimal("5"))
        self.client.post(f"/nexus-admin/planes/{libre.id}/eliminar/")
        self.assertFalse(self.Plan.objects.filter(id=libre.id).exists())

    def test_solo_el_superadmin_gestiona_planes(self):
        plan = self.Plan.objects.create(nombre="Plan Ajeno", precio_mensual=Decimal("5"))
        self.client.login(username="org_a", password="pass12345")
        r = self.client.post(f"/nexus-admin/planes/{plan.id}/editar/", self._datos_plan(nombre="Hackeado"))
        self.assertEqual(r.status_code, 302)
        plan.refresh_from_db()
        self.assertEqual(plan.nombre, "Plan Ajeno")

    def test_pago_extiende_fecha_y_el_reverso_la_devuelve(self):
        from datetime import date, timedelta
        c = self.complejo_a
        c.fecha_vencimiento = date.today() + timedelta(days=10)
        c.save()
        self.client.post("/nexus-admin/pagos/", {"complejo": c.id, "monto": "20", "meses_pagados": "2",
                                                 "fecha_pago": date.today().isoformat()})
        c.refresh_from_db()
        self.assertEqual(c.fecha_vencimiento, date.today() + timedelta(days=70))
        pago = c.pagos_saas.get()
        self.client.post(f"/saas/pago/reversar/{pago.id}/")
        c.refresh_from_db()
        self.assertEqual(c.fecha_vencimiento, date.today() + timedelta(days=10))
        self.assertFalse(c.pagos_saas.exists())

    def test_todas_las_secciones_cargan(self):
        for url in ["/nexus-admin/", "/nexus-admin/canchas/", "/nexus-admin/canchas/?estado=vencida&q=a",
                    f"/nexus-admin/canchas/editar/{self.complejo_a.id}/", "/nexus-admin/planes/",
                    "/nexus-admin/pagos/", f"/nexus-admin/pagos/?ver={self.complejo_a.id}", "/nexus-admin/pruebas/"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)


class CentroAyudaTest(DosCanchasTestCase):
    def test_todas_las_guias_cargan_y_sus_botones_apuntan_a_pantallas_reales(self):
        from django.urls import reverse
        from .ayuda import GUIAS, RUTA_CAMPEONATO, AYUDA_POR_PANTALLA, GUIAS_POR_SLUG
        for g in GUIAS:
            for paso in g['pasos']:
                if paso.get('url'):
                    reverse(paso['url'])  # revienta si la ruta no existe
        for p in RUTA_CAMPEONATO:
            self.assertIn(p['guia'], GUIAS_POR_SLUG)
        for slug in AYUDA_POR_PANTALLA.values():
            self.assertIn(slug, GUIAS_POR_SLUG)
        # Anónimo y organizador pueden abrir todas las guías
        for usuario in (None, "org_a"):
            if usuario:
                self.client.login(username=usuario, password="pass12345")
            for g in GUIAS:
                r = self.client.get(f"/ayuda/{g['slug']}/")
                self.assertContains(r, g['titulo'], msg_prefix=g['slug'])
        self.assertEqual(self.client.get("/ayuda/no-existe/").status_code, 404)

    def test_centro_de_ayuda_filtra_por_rol(self):
        r = self.client.get("/ayuda/?rol=VOC")
        self.assertEqual(r.status_code, 200)
        slugs = {g['slug'] for g in r.context["guias"]}
        self.assertIn("vocalia", slugs)
        self.assertNotIn("crear-torneo", slugs)

    def test_progreso_del_organizador_refleja_su_cancha(self):
        self.client.login(username="org_a", password="pass12345")
        r = self.client.get("/ayuda/")
        progreso = r.context["progreso"]
        self.assertIsNotNone(progreso)
        hecho = {f['texto']: f['hecho'] for f in progreso['filas']}
        self.assertTrue(hecho['Crear un torneo'])
        self.assertFalse(hecho['Crear la cuenta de tu vocal'])
        self.client.post("/usuarios/crear/", {"first_name": "Vocal", "rol": "VOC"})
        r = self.client.get("/ayuda/")
        hecho = {f['texto']: f['hecho'] for f in r.context["progreso"]['filas']}
        self.assertTrue(hecho['Crear la cuenta de tu vocal'])

    def test_boton_de_ayuda_de_la_pantalla_y_enlace_en_el_menu(self):
        self.client.login(username="org_a", password="pass12345")
        r = self.client.get("/torneos/")
        self.assertContains(r, 'href="/ayuda/crear-torneo/"')
        self.assertContains(r, 'href="/ayuda/"')

    def test_el_dirigente_nunca_puede_imprimir_carnets(self):
        from .models import Equipo
        dirigente = User.objects.create_user("dir_carnets", password="pass12345")
        equipo = Equipo.objects.create(torneo=self.torneo_a, dirigente=dirigente, nombre="Los Carnets FC",
                                       estado_inscripcion="APROBADO")
        RolComplejo.objects.create(usuario=dirigente, complejo=self.complejo_a, rol="DIR")
        self.client.login(username="dir_carnets", password="pass12345")
        r = self.client.get(f"/jugadores/?equipo={equipo.id}")
        self.assertNotContains(r, f'href="/imprimir-carnets/{equipo.id}/"')
        self.assertRedirects(self.client.get(f"/imprimir-carnets/{equipo.id}/"), "/dashboard/", fetch_redirect_response=False)
        # El organizador sí
        self.client.login(username="org_a", password="pass12345")
        self.assertEqual(self.client.get(f"/imprimir-carnets/{equipo.id}/").status_code, 200)

    def test_en_rol_de_prueba_simulando_dirigente_tampoco_hay_carnets(self):
        from .services.pruebas import crear_entorno_prueba
        tester = User.objects.create_user("tester_carnet", password="pass12345")
        demo = crear_entorno_prueba(tester)
        equipo = Equipo.objects.filter(torneo__complejo=demo).first()
        self.client.login(username="tester_carnet", password="pass12345")
        self.assertEqual(self.client.get(f"/imprimir-carnets/{equipo.id}/").status_code, 200)  # como organizador
        self.client.post(f"/prueba/dirigente/activar/{equipo.id}/")
        self.assertEqual(self.client.get(f"/imprimir-carnets/{equipo.id}/").status_code, 302)  # como dirigente

class DirigenteSoloSuEquipoTest(DosCanchasTestCase):
    def _datos_jugador(self, equipo_id, cedula="1710034065", dorsal="9"):
        return {"equipo": str(equipo_id), "nombres": "Pedro Pablo Mina", "dorsal": dorsal, "cedula": cedula}

    def test_el_dirigente_no_elige_equipo_al_fichar(self):
        dirigente = User.objects.create_user("dir_dos", password="pass12345")
        mio = Equipo.objects.create(torneo=self.torneo_a, dirigente=dirigente, nombre="Mi Equipo", estado_inscripcion="APROBADO", cupos_pagados=10)
        otro_mio = Equipo.objects.create(torneo=self.torneo_a, dirigente=dirigente, nombre="Mi Otro", estado_inscripcion="APROBADO")
        RolComplejo.objects.create(usuario=dirigente, complejo=self.complejo_a, rol="DIR")
        self.client.login(username="dir_dos", password="pass12345")

        r = self.client.get(f"/jugadores/?equipo={mio.id}")
        self.assertContains(r, "Fichando en")
        self.assertContains(r, f'<input type="hidden" name="equipo" value="{mio.id}"', html=False)
        self.assertNotContains(r, "Equipo Destino")

        # Aunque se envíe otro equipo (o uno ajeno), el jugador queda en el equipo abierto
        for intruso in (otro_mio.id, self.equipo_a.id):
            Jugador.objects.filter(cedula="1710034065").delete()
            self.client.post(f"/jugadores/?equipo={mio.id}", self._datos_jugador(intruso))
            self.assertEqual(Jugador.objects.get(cedula="1710034065").equipo, mio)

    def test_rol_de_prueba_solo_ve_el_equipo_simulado(self):
        from .services.pruebas import crear_entorno_prueba
        tester = User.objects.create_user("tester_sim", password="pass12345")
        complejo_demo = crear_entorno_prueba(tester)
        equipos_demo = list(Equipo.objects.filter(torneo__complejo=complejo_demo, estado_inscripcion="APROBADO")[:2])
        simulado, ajeno = equipos_demo
        self.client.login(username="tester_sim", password="pass12345")
        self.client.post(f"/prueba/dirigente/activar/{simulado.id}/")

        # Nómina: solo su equipo, aunque pida otro por la URL
        for url in ("/jugadores/", f"/jugadores/?equipo={ajeno.id}"):
            r = self.client.get(url)
            self.assertEqual(r.context["equipo_obj"], simulado)
            self.assertEqual(list(r.context["equipos_activos"]), [simulado])
        # Finanzas: igual
        r = self.client.get(f"/mis-finanzas-equipo/?equipo={ajeno.id}")
        self.assertEqual(r.context["equipo"], simulado)
        # Inicio del dirigente simulado
        r = self.client.get("/dashboard/")
        self.assertEqual(r.context["mi_equipo"], simulado)



class ModoSoporteSuperAdminTest(DosCanchasTestCase):
    def setUp(self):
        super().setUp()
        User.objects.create_superuser("jefe_soporte", password="pass12345")
        self.client.login(username="jefe_soporte", password="pass12345")

    def test_entra_a_una_cancha_como_su_administrador_y_sale(self):
        self.assertRedirects(self.client.get("/dashboard/"), "/nexus-admin/", fetch_redirect_response=False)
        self.client.post(f"/nexus-admin/soporte/entrar/{self.complejo_a.id}/")

        r = self.client.get("/dashboard/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Modo soporte")
        self.assertEqual(r.context["mi_complejo"], self.complejo_a)
        # Solo ve los torneos de ESA cancha
        r = self.client.get("/programar/")
        self.assertIn(self.torneo_a, list(r.context["torneos"]))
        self.assertNotIn(self.torneo_b, list(r.context["torneos"]))
        # Carnets de esa cancha sí; de otra no
        self.assertEqual(self.client.get(f"/imprimir-carnets/{self.equipo_a.id}/").status_code, 200)
        self.assertEqual(self.client.get(f"/imprimir-carnets/{self.equipo_b.id}/").status_code, 302)
        # Puede crear la cuenta del vocal de esa cancha
        self.client.post("/usuarios/crear/", {"first_name": "Vocal Soporte", "rol": "VOC"})
        self.assertEqual(RolComplejo.objects.get(usuario__first_name="Vocal Soporte").complejo, self.complejo_a)

        self.client.post("/nexus-admin/soporte/salir/")
        self.assertRedirects(self.client.get("/dashboard/"), "/nexus-admin/", fetch_redirect_response=False)

    def test_torneo_creado_en_soporte_queda_a_nombre_del_dueno(self):
        from .models import Torneo, Categoria
        cat = Categoria.objects.create(complejo=self.complejo_a, nombre="Libre")
        self.client.post(f"/nexus-admin/soporte/entrar/{self.complejo_a.id}/")
        self.client.post("/torneos/", {"nombre": "Copa Soporte", "categoria": cat.id, "fecha_inicio": "2026-11-01",
                                       "inscripcion_abierta": "on", "activo": "on", "costo_inscripcion": "0",
                                       "costo_inscripcion_jugador": "0", "costo_amarilla": "1", "costo_roja": "2"})
        t = Torneo.objects.get(nombre="Copa Soporte")
        self.assertEqual((t.complejo, t.organizador), (self.complejo_a, self.org_a))

    def test_un_organizador_normal_no_puede_usar_el_modo_soporte(self):
        self.client.login(username="org_a", password="pass12345")
        self.client.post(f"/nexus-admin/soporte/entrar/{self.complejo_b.id}/")
        self.assertNotIn("complejo_soporte_id", self.client.session)
        r = self.client.get("/programar/")
        self.assertNotIn(self.torneo_b, list(r.context["torneos"]))


class EstadisticasRenderTest(DosCanchasTestCase):
    def test_la_pagina_de_estadisticas_carga_para_cada_rol(self):
        from .models import DetallePartido
        DetallePartido.objects.create(partido=self.partido_a, jugador=self.jugador_a, tipo="GOL", equipo_incidencia=self.equipo_a)
        DetallePartido.objects.create(partido=self.partido_a, jugador=self.jugador_a, tipo="STAR", equipo_incidencia=self.equipo_a)
        url = f"/estadisticas/{self.torneo_a.id}/"
        self.client.login(username="org_a", password="pass12345")
        r = self.client.get(f"{url}?equipo={self.equipo_a.id}")
        self.assertContains(r, "Tabla de posiciones")
        self.assertContains(r, "Máximo goleador")
        self.assertContains(r, "Plantel y fair play")
        self.assertContains(r, "Control de cuota de partidos")
        User.objects.create_user("hincha", password="pass12345")
        self.client.login(username="hincha", password="pass12345")
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Control de cuota de partidos")



class TorneoCategoriaObligatoriaTest(DosCanchasTestCase):
    def _datos(self, **extra):
        d = {"nombre": "Copa Nueva", "fecha_inicio": "2026-11-01", "inscripcion_abierta": "on", "activo": "on",
             "costo_inscripcion": "10", "costo_inscripcion_jugador": "0", "costo_amarilla": "1", "costo_roja": "2"}
        d.update(extra)
        return d

    def test_sin_categorias_avisa_y_no_deja_crear(self):
        from .models import Categoria, Torneo
        Categoria.objects.filter(complejo=self.complejo_a).delete()
        self.client.login(username="org_a", password="pass12345")
        r = self.client.get("/torneos/")
        self.assertContains(r, "Primero crea una categoría")
        r = self.client.post("/torneos/", self._datos())
        self.assertRedirects(r, "/categorias/", fetch_redirect_response=False)
        self.assertFalse(Torneo.objects.filter(nombre="Copa Nueva").exists())

    def test_la_categoria_es_obligatoria_y_debe_ser_de_mi_cancha(self):
        from .models import Categoria, Torneo
        mia = Categoria.objects.create(complejo=self.complejo_a, nombre="Máster")
        ajena = Categoria.objects.create(complejo=self.complejo_b, nombre="Ajena")
        self.client.login(username="org_a", password="pass12345")
        r = self.client.post("/torneos/", self._datos())
        self.assertContains(r, "Elige la categoría del torneo")
        self.client.post("/torneos/", self._datos(categoria=ajena.id))
        self.assertFalse(Torneo.objects.filter(nombre="Copa Nueva").exists())
        self.client.post("/torneos/", self._datos(categoria=mia.id))
        self.assertEqual(Torneo.objects.get(nombre="Copa Nueva").categoria, mia)

    def test_al_editar_se_ven_los_datos_guardados_incluida_la_fecha(self):
        from datetime import date
        from .models import Categoria
        cat = Categoria.objects.create(complejo=self.complejo_a, nombre="Libre")
        self.torneo_a.categoria = cat
        self.torneo_a.fecha_inicio = date(2026, 3, 15)
        self.torneo_a.save()
        self.client.login(username="org_a", password="pass12345")
        r = self.client.get(f"/torneos/editar/{self.torneo_a.id}/")
        self.assertContains(r, 'value="2026-03-15"')
        self.assertContains(r, f'<option value="{cat.id}" selected>')
        self.assertContains(r, f'value="{self.torneo_a.nombre}"')



class ReglasDeFichajeDelDirigenteTest(DosCanchasTestCase):
    def setUp(self):
        super().setUp()
        self.dirigente = User.objects.create_user("dir_reglas", password="pass12345")
        RolComplejo.objects.create(usuario=self.dirigente, complejo=self.complejo_a, rol="DIR")
        self.complejo_a.plan.max_jugadores = 500
        self.complejo_a.plan.save()
        self.client.login(username="dir_reglas", password="pass12345")

    def _equipo(self, **kw):
        datos = dict(torneo=self.torneo_a, dirigente=self.dirigente, nombre="Los Reglamentarios", estado_inscripcion="APROBADO", cupos_pagados=2)
        datos.update(kw)
        return Equipo.objects.create(**datos)

    def _fichar(self, equipo, cedula, dorsal):
        return self.client.post(f"/jugadores/?equipo={equipo.id}", {"equipo": str(equipo.id), "nombres": "Jugador Prueba",
                                                                    "dorsal": str(dorsal), "cedula": cedula})

    def test_equipo_pendiente_no_puede_fichar(self):
        eq = self._equipo(estado_inscripcion="PENDIENTE")
        r = self.client.get(f"/jugadores/?equipo={eq.id}")
        self.assertContains(r, "Esperando aprobación")
        self._fichar(eq, "1710034065", 9)
        self.assertEqual(eq.jugadores.count(), 0)

    def test_sin_cupos_asignados_no_puede_fichar(self):
        eq = self._equipo(cupos_pagados=0)
        r = self.client.get(f"/jugadores/?equipo={eq.id}")
        self.assertContains(r, "Cupos sin asignar")
        self._fichar(eq, "1710034065", 9)
        self.assertEqual(eq.jugadores.count(), 0)

    def test_solo_ficha_hasta_el_limite_de_cupos(self):
        eq = self._equipo(cupos_pagados=2)
        for i, ced in enumerate(["1710034065", "1713175071", "1714616123"]):
            self._fichar(eq, ced, i + 1)
        self.assertEqual(eq.jugadores.count(), 2)
        r = self.client.get(f"/jugadores/?equipo={eq.id}")
        self.assertContains(r, "Límite alcanzado")

    def test_limite_de_jugadores_del_plan_de_la_cancha(self):
        self.complejo_a.plan.max_jugadores = Jugador.objects.filter(equipo__torneo__complejo=self.complejo_a).count()
        self.complejo_a.plan.save()
        eq = self._equipo(cupos_pagados=5)
        self._fichar(eq, "1710034065", 9)
        self.assertEqual(eq.jugadores.count(), 0)


class BitacoraDeCambiosTest(DosCanchasTestCase):
    def setUp(self):
        super().setUp()
        self.client.login(username="org_a", password="pass12345")

    def test_editar_jugador_queda_registrado_campo_por_campo(self):
        from .models import RegistroCambio
        j = self.jugador_a
        datos = {"equipo": j.equipo_id, "nombres": "Nombre Corregido", "dorsal": "77",
                 "tipo_documento": j.tipo_documento or "EC", "cedula": j.cedula}
        self.client.post(f"/jugadores/editar/{j.id}/", datos)
        r = RegistroCambio.objects.get(accion="EDITAR", entidad="JUGADOR")
        campos = {c["campo"]: (c["antes"], c["despues"]) for c in r.cambios}
        self.assertEqual(campos["Dorsal"][1], "77")
        self.assertEqual(campos["Nombres"][1], "Nombre Corregido")
        self.assertEqual(r.complejo, self.complejo_a)
        self.assertFalse(r.en_soporte)
        page = self.client.get("/trazabilidad/cambios/")
        self.assertContains(page, "Nombre Corregido")

    def test_los_cambios_del_soporte_tecnico_quedan_marcados(self):
        from .models import RegistroCambio
        User.objects.create_superuser("jefe_bit", password="pass12345")
        self.client.login(username="jefe_bit", password="pass12345")
        self.client.post(f"/nexus-admin/soporte/entrar/{self.complejo_a.id}/")
        j = self.jugador_a
        self.client.post(f"/jugadores/editar/{j.id}/", {"equipo": j.equipo_id, "nombres": j.nombres, "dorsal": "55",
                                                         "tipo_documento": j.tipo_documento or "EC", "cedula": j.cedula})
        r = RegistroCambio.objects.get(accion="EDITAR")
        self.assertTrue(r.en_soporte)
        self.assertContains(self.client.get("/trazabilidad/cambios/?soporte=1"), "Soporte técnico NEXUS")

    def test_cada_cancha_solo_ve_su_bitacora(self):
        from .models import RegistroCambio
        RegistroCambio.objects.create(complejo=self.complejo_b, entidad="JUGADOR", accion="EDITAR", objeto="Secreto de B")
        self.assertNotContains(self.client.get("/trazabilidad/cambios/"), "Secreto de B")


class BotonHorariosTest(DosCanchasTestCase):
    def test_solo_con_partidos_proximos_y_solo_para_el_organizador(self):
        from datetime import timedelta
        from django.utils import timezone
        from .models import Partido
        self.client.login(username="org_a", password="pass12345")
        Partido.objects.filter(torneo__complejo=self.complejo_a).update(fecha_hora=None)
        self.assertNotContains(self.client.get("/dashboard/"), "Imagen de horarios")
        Partido.objects.create(torneo=self.torneo_a, equipo_local=self.equipo_a, equipo_visita=self.equipo_a2,
                               estado="PROG", fecha_hora=timezone.now() + timedelta(days=1))
        self.assertContains(self.client.get("/dashboard/"), "Imagen de horarios")


class TrazabilidadRetencionYPaginacionTest(DosCanchasTestCase):
    def setUp(self):
        super().setUp()
        self.client.login(username="org_a", password="pass12345")

    def _cambio(self, objeto, dias=0):
        from datetime import timedelta
        from django.utils import timezone
        from .models import RegistroCambio
        r = RegistroCambio.objects.create(complejo=self.complejo_a, entidad="JUGADOR", accion="EDITAR", objeto=objeto)
        if dias:
            RegistroCambio.objects.filter(id=r.id).update(fecha=timezone.now() - timedelta(days=dias))
        return r

    def test_lo_de_mas_de_20_dias_se_borra_solo(self):
        from datetime import timedelta
        from django.utils import timezone
        from .models import MovimientoFinanciero, RegistroCambio, limpiar_trazabilidad_vieja
        self._cambio("Viejo", dias=21)
        self._cambio("Reciente", dias=19)
        m = MovimientoFinanciero.objects.create(complejo=self.complejo_a, tipo="ABONO", monto=5)
        MovimientoFinanciero.objects.filter(id=m.id).update(fecha=timezone.now() - timedelta(days=25))
        self.assertEqual(limpiar_trazabilidad_vieja(forzar=True), (1, 1))
        self.assertEqual(list(RegistroCambio.objects.values_list("objeto", flat=True)), ["Reciente"])

    def test_paginacion_con_tamano_y_pagina_fuera_de_rango(self):
        for n in range(45):
            self._cambio(f"Jugador {n:02d}")
        r = self.client.get("/trazabilidad/cambios/")
        self.assertContains(r, "Mostrando <b>1–20</b> de <b>45</b> cambios", html=False)
        r = self.client.get("/trazabilidad/cambios/?por=50")
        self.assertContains(r, "Mostrando <b>1–45</b> de <b>45</b>", html=False)
        r = self.client.get("/trazabilidad/cambios/?page=99&entidad=JUGADOR")
        self.assertContains(r, "Mostrando <b>41–45</b>", html=False)
        self.assertContains(r, 'href="?entidad=JUGADOR&page=2"', html=False)  # los filtros viajan al paginar
        self.assertEqual(self.client.get("/trazabilidad/cambios/?por=9999").status_code, 200)

    def test_aprobar_equipo_y_crear_torneo_quedan_registrados(self):
        from .models import Categoria, RegistroCambio
        self.equipo_a2.estado_inscripcion = "PENDIENTE"
        self.equipo_a2.save()
        self.client.post("/solicitudes/", {"equipo_id": self.equipo_a2.id, "accion": "APROBAR"})
        r = RegistroCambio.objects.get(entidad="EQUIPO", accion="ESTADO")
        self.assertEqual(r.cambios[0]["despues"], "Aprobada")

    def test_editar_sin_cambiar_nada_no_ensucia_la_bitacora(self):
        from .models import RegistroCambio
        j = self.jugador_a
        self.client.post(f"/jugadores/editar/{j.id}/", {"equipo": j.equipo_id, "nombres": j.nombres + "  ", "dorsal": j.dorsal,
                                                         "tipo_documento": j.tipo_documento or "EC", "cedula": j.cedula})
        self.assertFalse(RegistroCambio.objects.exists())

    def test_movimientos_automaticos_ocultos_por_defecto(self):
        from .models import MovimientoFinanciero
        MovimientoFinanciero.objects.create(complejo=self.complejo_a, tipo="CARGO", origen="SISTEMA", monto=3, equipo_nombre="Auto FC")
        MovimientoFinanciero.objects.create(complejo=self.complejo_a, tipo="ABONO", origen="FINANZAS", monto=3, equipo_nombre="Manual FC")
        r = self.client.get("/finanzas/trazabilidad/")
        self.assertContains(r, "Manual FC")
        self.assertNotContains(r, "Auto FC")
        self.assertContains(self.client.get("/finanzas/trazabilidad/?auto=1"), "Auto FC")


class PanelSaasEficienteTest(TestCase):
    def setUp(self):
        from datetime import timedelta
        from django.utils import timezone
        self.hoy = timezone.localdate()
        self.td = timedelta
        User.objects.create_superuser("jefe_saas", password="pass12345")
        self.plan = PlanSuscripcion.objects.create(nombre="Plan Liga", precio_mensual=Decimal("12.00"), max_torneos=2, max_jugadores=10)
        self.client.login(username="jefe_saas", password="pass12345")

    def _cancha(self, n, dias=30, activo=True):
        dueno = User.objects.create_user(f"dueno_{n}", password="x")
        return ComplejoDeportivo.objects.create(nombre=f"Cancha {n}", slug=f"cancha-{n}", organizador=dueno, plan=self.plan,
                                                activo=activo, fecha_vencimiento=self.hoy + self.td(days=dias))

    def _consultas(self, url):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(url).status_code, 200)
        return len(ctx.captured_queries)

    def test_las_consultas_no_crecen_con_el_numero_de_canchas(self):
        for n in range(3):
            self._cancha(n)
        antes = {u: self._consultas(u) for u in ("/nexus-admin/", "/nexus-admin/canchas/", "/nexus-admin/pagos/")}
        for n in range(3, 12):
            self._cancha(n)
        despues = {u: self._consultas(u) for u in antes}
        self.assertEqual(antes, despues)

    def test_filtro_por_estado_y_uso_del_plan(self):
        self._cancha("aldia", dias=40)
        self._cancha("vencida", dias=-3)
        self._cancha("pronto", dias=2)
        r = self.client.get("/nexus-admin/canchas/?estado=vencida")
        self.assertEqual([c.nombre for c in r.context["canchas"]], ["Cancha vencida"])
        self.assertEqual(r.context["conteo"]["total"], 3)
        self.assertEqual(r.context["conteo"]["por_vencer"], 1)
        r = self.client.get("/nexus-admin/")
        self.assertContains(r, "Ingresos · últimos 6 meses")
        self.assertEqual(len(r.context["serie"]), 6)


class BitacoraSoloOrganizadoresTest(DosCanchasTestCase):
    def _editar_dorsal(self, dorsal):
        j = self.jugador_a
        return self.client.post(f"/jugadores/editar/{j.id}/", {"equipo": j.equipo_id, "nombres": j.nombres, "dorsal": str(dorsal),
                                                                "tipo_documento": j.tipo_documento or "EC", "cedula": j.cedula})

    def test_el_fichaje_del_dirigente_no_se_guarda(self):
        from .models import RegistroCambio
        dirigente = User.objects.create_user("dir_bit", password="pass12345")
        RolComplejo.objects.create(usuario=dirigente, complejo=self.complejo_a, rol="DIR")
        eq = Equipo.objects.create(torneo=self.torneo_a, dirigente=dirigente, nombre="Los del Barrio",
                                   estado_inscripcion="APROBADO", cupos_pagados=5)
        self.client.login(username="dir_bit", password="pass12345")
        self.client.post(f"/jugadores/?equipo={eq.id}", {"equipo": str(eq.id), "nombres": "Nuevo Fichaje", "dorsal": "7", "cedula": "1713175071"})
        self.assertEqual(eq.jugadores.count(), 1)
        self.assertFalse(RegistroCambio.objects.exists())

    def test_el_staff_organizador_si_queda_registrado(self):
        from .models import RegistroCambio
        staff = User.objects.create_user("staff_bit", password="pass12345")
        RolComplejo.objects.create(usuario=staff, complejo=self.complejo_a, rol="ORG")
        self.client.login(username="staff_bit", password="pass12345")
        self._editar_dorsal(44)
        self.assertEqual(RegistroCambio.objects.get().usuario, staff)

    def test_la_limpieza_borra_lo_que_no_hizo_un_organizador(self):
        import importlib
        from django.apps import apps
        from .models import RegistroCambio
        vocal = User.objects.create_user("vocal_bit", password="x")
        RegistroCambio.objects.create(complejo=self.complejo_a, usuario=vocal, entidad="JUGADOR", accion="CREAR", objeto="De vocal")
        RegistroCambio.objects.create(complejo=self.complejo_a, usuario=self.org_a, entidad="JUGADOR", accion="CREAR",
                                      objeto="Del dirigente", detalle="Fichado por el dirigente · cédula 1")
        RegistroCambio.objects.create(complejo=self.complejo_a, usuario=self.org_a, entidad="JUGADOR", accion="EDITAR", objeto="Del dueño")
        RegistroCambio.objects.create(complejo=self.complejo_a, usuario=None, en_soporte=True, entidad="EQUIPO", accion="EDITAR", objeto="Soporte")
        importlib.import_module("core.migrations.0035_bitacora_solo_organizadores").limpiar(apps, None)
        self.assertEqual(sorted(RegistroCambio.objects.values_list("objeto", flat=True)), ["Del dueño", "Soporte"])


class EliminarJugadorTest(DosCanchasTestCase):
    def test_eliminar_dos_veces_no_da_404(self):
        User.objects.create_superuser("sop_elim", password="pass12345")
        self.client.login(username="sop_elim", password="pass12345")
        self.client.post(f"/nexus-admin/soporte/entrar/{self.complejo_a.id}/")
        url = f"/jugadores/eliminar/{self.jugador_a.id}/"
        r1 = self.client.post(url, HTTP_REFERER="http://testserver/admin_jugadores/")
        r2 = self.client.post(url, HTTP_REFERER="http://testserver/admin_jugadores/")
        self.assertFalse(Jugador.objects.filter(id=self.jugador_a.id).exists())
        self.assertEqual((r1.status_code, r2.status_code), (302, 302))
        self.assertEqual(r2["Location"], "http://testserver/admin_jugadores/")

    def test_quien_ya_piso_cancha_no_se_elimina_y_se_ve_el_candado(self):
        DetallePartido.objects.create(partido=self.partido_a, jugador=self.jugador_a, tipo="ASIS")
        self.client.login(username="org_a", password="pass12345")
        r = self.client.get("/admin_jugadores/")
        self.assertContains(r, "Ya pisó cancha")
        self.client.post(f"/jugadores/eliminar/{self.jugador_a.id}/")
        self.assertTrue(Jugador.objects.filter(id=self.jugador_a.id).exists())

    def test_referer_externo_no_se_usa_para_volver(self):
        self.client.login(username="org_a", password="pass12345")
        r = self.client.post(f"/jugadores/eliminar/{self.jugador_a.id}/", HTTP_REFERER="https://sitio-malo.com/")
        self.assertEqual(r["Location"], "/admin_jugadores/")

    def test_el_dirigente_no_puede_eliminar_ni_a_su_propio_jugador(self):
        dirigente = User.objects.create_user("dir_elim", password="pass12345")
        RolComplejo.objects.create(usuario=dirigente, complejo=self.complejo_a, rol="DIR")
        self.equipo_a.dirigente = dirigente
        self.equipo_a.save()
        self.client.login(username="dir_elim", password="pass12345")
        self.client.post(f"/jugadores/eliminar/{self.jugador_a.id}/")
        self.assertTrue(Jugador.objects.filter(id=self.jugador_a.id).exists())


class ListasCompletasYLivianasTest(DosCanchasTestCase):
    def test_equipos_muestra_todos_los_aceptados(self):
        for n in range(18):
            Equipo.objects.create(torneo=self.torneo_a, dirigente=self.org_a, nombre=f"Club Aceptado {n:02d}", estado_inscripcion="APROBADO")
        self.client.login(username="org_a", password="pass12345")
        r = self.client.get("/equipos/")
        for n in range(18):
            self.assertContains(r, f"Club Aceptado {n:02d}")

    def test_jugadores_del_organizador_sin_consultas_por_jugador(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        self.client.login(username="org_a", password="pass12345")
        def consultas():
            with CaptureQueriesContext(connection) as ctx:
                self.client.get("/admin_jugadores/")
            return len(ctx.captured_queries)
        antes = consultas()
        Jugador.objects.bulk_create([Jugador(equipo=self.equipo_a2, nombres=f"Carga {k}", dorsal=k, cedula=f"09{k:08d}") for k in range(1, 40)])
        self.assertEqual(consultas(), antes)


class FichajeDesdeLaBaseDeDatosTest(DosCanchasTestCase):
    """Al escribir la cédula se traen los datos y la foto que ya están en la
    base; un jugador no puede estar en dos equipos del mismo campeonato, pero
    sí en otro campeonato (reutilizando su foto, sin volver a subirla)."""

    def setUp(self):
        super().setUp()
        from .tests import imagen_falsa
        self.jugador_a.foto = imagen_falsa("cara.jpg")
        self.jugador_a.save()
        self.torneo_otro = Torneo.objects.create(complejo=self.complejo_a, nombre="Copa Verano",
                                                 organizador=self.org_a, costo_inscripcion=Decimal("0"))
        self.equipo_otro = Equipo.objects.create(torneo=self.torneo_otro, dirigente=self.org_a,
                                                 nombre="Halcones", estado_inscripcion="APROBADO")
        self.client.login(username="org_a", password="pass12345")

    def test_la_cedula_trae_nombres_y_foto(self):
        r = self.client.get(f"/api/buscar_jugador/{self.jugador_a.cedula}/?equipo={self.equipo_otro.id}").json()
        self.assertTrue(r["encontrado"])
        self.assertEqual(r["nombres"], "Jugador A")
        self.assertTrue(r["foto"])
        self.assertIsNone(r["conflicto"])
        self.assertIn("Equipo A · Torneo A", r["otros_campeonatos"])

    def test_avisa_si_ya_juega_en_el_mismo_campeonato(self):
        r = self.client.get(f"/api/buscar_jugador/{self.jugador_a.cedula}/?equipo={self.equipo_a2.id}").json()
        self.assertEqual(r["conflicto"]["equipo"], "Equipo A")

    def test_otra_cancha_no_ve_al_jugador(self):
        self.client.login(username="org_b", password="pass12345")
        r = self.client.get(f"/api/buscar_jugador/{self.jugador_a.cedula}/").json()
        self.assertFalse(r["encontrado"])

    def _fichar(self, equipo):
        return self.client.post("/jugadores/", {"equipo": equipo.id, "nombres": "Jugador A", "dorsal": 7,
                                                "tipo_documento": "EC", "cedula": self.jugador_a.cedula})

    def test_se_ficha_en_otro_campeonato_con_la_misma_foto(self):
        self.torneo_otro.categoria = self.torneo_a.categoria
        self.torneo_otro.save()
        self._fichar(self.equipo_otro)
        nuevo = Jugador.objects.get(equipo=self.equipo_otro, cedula=self.jugador_a.cedula)
        self.assertEqual(nuevo.foto.name, self.jugador_a.foto.name)

    def test_no_se_ficha_dos_veces_en_el_mismo_campeonato(self):
        self._fichar(self.equipo_a2)
        self.assertFalse(Jugador.objects.filter(equipo=self.equipo_a2, cedula=self.jugador_a.cedula).exists())


class FixturePublicoEImagenHorariosTest(DosCanchasTestCase):
    def setUp(self):
        super().setUp()
        from datetime import timedelta
        from django.utils import timezone
        Partido.objects.filter(id=self.partido_a.id).update(fecha_hora=None)
        self.programado = Partido.objects.create(torneo=self.torneo_a, equipo_local=self.equipo_a2, equipo_visita=self.equipo_a,
                                                 estado="PROG", numero_fecha=2, fecha_hora=timezone.now() + timedelta(days=2))

    def test_el_fixture_publico_solo_muestra_lo_programado(self):
        r = self.client.get(f"/proxima-jornada/{self.torneo_a.id}/")
        self.assertEqual([p.id for p in r.context["partidos"]], [self.programado.id])

    def test_la_imagen_es_solo_del_organizador_y_lleva_la_publicidad(self):
        self.client.login(username="org_a", password="pass12345")
        r = self.client.get("/horarios/imagen/")
        self.assertContains(r, "NEXUS SPORTOPS")
        self.assertContains(r, "0987 408 528")
        dirigente = User.objects.create_user("dir_img", password="pass12345")
        RolComplejo.objects.create(usuario=dirigente, complejo=self.complejo_a, rol="DIR")
        self.client.login(username="dir_img", password="pass12345")
        self.assertNotEqual(self.client.get("/horarios/imagen/").status_code, 200)

    def test_el_soporte_tecnico_genera_la_imagen_de_la_cancha(self):
        User.objects.create_superuser("sop_img", password="pass12345")
        self.client.login(username="sop_img", password="pass12345")
        self.client.post(f"/nexus-admin/soporte/entrar/{self.complejo_a.id}/")
        r = self.client.get("/horarios/imagen/")
        self.assertEqual(r.context["complejo"], self.complejo_a)


class VitrinaNexusTest(TestCase):
    def test_la_vitrina_es_publica_y_muestra_todas_las_funciones(self):
        r = self.client.get("/conoce-nexus/")
        self.assertEqual(r.status_code, 200)
        for nombre in ("Vocalía", "Estadísticas", "Carnets", "Jugadores", "Horarios", "Finanzas"):
            self.assertContains(r, nombre)
        self.assertContains(r, "vitrina/vocalia-pc.webp")
        self.assertContains(r, "wa.me/593987408528")

    def test_inicio_y_precios_enlazan_a_la_vitrina(self):
        for url in ("/", "/precios/"):
            self.assertContains(self.client.get(url), "/conoce-nexus/")

    def test_existen_todas_las_capturas(self):
        from django.contrib.staticfiles import finders
        from .views import FUNCIONES_VITRINA
        for f in FUNCIONES_VITRINA:
            for tipo in ("pc", "cel"):
                self.assertTrue(finders.find(f"core/vitrina/{f['clave']}-{tipo}.webp"), f"{f['clave']}-{tipo}")


class InicioPublicoPromocionalTest(TestCase):
    def test_el_inicio_muestra_primero_la_promocion_y_luego_las_canchas(self):
        from .models import ComplejoDeportivo
        dueno = User.objects.create_user("dueno_vitrina", password="pass12345")
        ComplejoDeportivo.objects.create(nombre="Cancha El Ejido", slug="cancha-el-ejido", organizador=dueno, activo=True)
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertLess(html.index("Todo lo que hace"), html.index("Encuentra tu cancha"))
        self.assertIn("Cancha El Ejido", html)
        self.assertIn("cancha-el-ejido", html)  # enlace al portal de la cancha
        self.assertIn("vitrina.js", html)
