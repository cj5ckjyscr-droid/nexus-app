from decimal import Decimal

from django.contrib.auth.models import User

from .models import (AbonoSancion, ComplejoDeportivo, DetallePartido, Equipo, Jugador, MovimientoFinanciero,
                     Partido, RolComplejo, Sancion, Torneo)
from .tests import DosCanchasTestCase


class UnirseCanchaTest(DosCanchasTestCase):
    def test_aficionado_se_une_sin_crear_equipo_y_el_admin_lo_hace_vocal(self):
        fan = User.objects.create_user("aficionado", password="pass12345")
        self.client.login(username="aficionado", password="pass12345")
        self.client.post(f"/cancha/{self.complejo_a.slug}/unirme/")
        rc = RolComplejo.objects.get(usuario=fan, complejo=self.complejo_a)
        self.assertEqual(rc.rol, "FAN")
        self.assertFalse(Equipo.objects.filter(dirigente=fan).exists())

        self.client.login(username="org_a", password="pass12345")
        self.client.post("/usuarios/gestionar/", {"rol_cancha_id": rc.id, "nuevo_rol": "VOC"})
        rc.refresh_from_db()
        self.assertEqual(rc.rol, "VOC")
        # Ser vocal en A no da nada en B
        self.assertFalse(RolComplejo.objects.filter(usuario=fan, complejo=self.complejo_b).exists())

    def test_unirse_requiere_post(self):
        User.objects.create_user("aficionado", password="pass12345")
        self.client.login(username="aficionado", password="pass12345")
        r = self.client.get(f"/cancha/{self.complejo_a.slug}/unirme/")
        self.assertEqual(r.status_code, 405)

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
