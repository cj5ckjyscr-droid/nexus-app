from collections import Counter
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from .models import ComplejoDeportivo, Equipo, Llave, Partido, PlanSuscripcion, RolComplejo, Torneo
from .services import campeonato as c


class FuncionesPurasTest(TestCase):
    def test_orden_semillas_separa_al_1_y_al_2(self):
        self.assertEqual(c.orden_semillas(8), [1, 8, 4, 5, 2, 7, 3, 6])
        orden16 = c.orden_semillas(16)
        self.assertEqual(sorted(orden16), list(range(1, 17)))
        # 1 en la primera mitad, 2 en la segunda: solo se cruzan en la final
        self.assertIn(1, orden16[:8])
        self.assertIn(2, orden16[8:])

    def test_round_robin_todos_contra_todos_una_vez(self):
        equipos = list(range(1, 8))  # impar: hay descanso
        jornadas = c.round_robin(equipos)
        cruces = [frozenset(p) for j in jornadas for p in j]
        self.assertEqual(len(cruces), 21)
        self.assertEqual(len(set(cruces)), 21)
        locales = Counter(a for j in jornadas for a, _ in j)
        self.assertLessEqual(max(locales.values()) - min(locales.values()), 1)

    def test_round_robin_ida_y_vuelta_invierte_localia(self):
        jornadas = c.round_robin([1, 2, 3, 4], ida_vuelta=True)
        self.assertEqual(len(jornadas), 6)
        partidos = [p for j in jornadas for p in j]
        self.assertEqual(len(partidos), 12)
        self.assertEqual(len(set(partidos)), 12)

    def test_validar_24_equipos_6_grupos_2_mas_4_terceros(self):
        errores, resumen = c.validar_configuracion('GRUPOS', 24, num_grupos=6, clasifican=2, mejores=4)
        self.assertEqual(errores, [])
        self.assertEqual(resumen['clasificados'], 16)
        self.assertEqual(resumen['rondas'][0], 'Octavos de final')

    def test_validar_rechaza_clasificados_que_no_son_potencia_de_2(self):
        errores, _ = c.validar_configuracion('GRUPOS', 24, num_grupos=6, clasifican=2, mejores=0)
        self.assertTrue(any('12' in e for e in errores))

    def test_validar_rechaza_mas_mejores_que_grupos(self):
        errores, _ = c.validar_configuracion('GRUPOS', 12, num_grupos=4, clasifican=1, mejores=4)
        self.assertTrue(errores)

    def test_semillas_de_grupos_nunca_cruzan_mismo_grupo(self):
        for g, k, m in [(2, 2, 0), (3, 2, 2), (4, 2, 0), (6, 2, 4), (8, 2, 0), (4, 4, 0), (2, 4, 0)]:
            self.assertEqual(c._choques_mismo_grupo(c.semillas_grupos(g, k, m)), 0, (g, k, m))

    def test_sugerencias_para_24_incluyen_el_formato_mundial(self):
        sug = c.sugerencias_grupos(24)
        self.assertIn((6, 2, 4), [(s['grupos'], s['clasifican'], s['mejores']) for s in sug])

    def test_sorteo_reproducible_con_la_misma_semilla(self):
        class E:
            def __init__(self, i): self.id = i
        equipos = [E(i) for i in range(1, 13)]
        g1 = c.sortear_grupos(equipos, 3, 777)
        g2 = c.sortear_grupos(list(reversed(equipos)), 3, 777)
        self.assertEqual({k: [e.id for e in v] for k, v in g1.items()},
                         {k: [e.id for e in v] for k, v in g2.items()})
        self.assertEqual(sorted(len(v) for v in g1.values()), [4, 4, 4])


class CampeonatoBase(TestCase):
    def setUp(self):
        plan = PlanSuscripcion.objects.create(nombre="Pro", precio_mensual=Decimal("10"), max_torneos=5, max_categorias_por_torneo=5)
        self.org = User.objects.create_user("org", password="pass12345")
        self.complejo = ComplejoDeportivo.objects.create(nombre="Cancha Norte", slug="cancha-norte", organizador=self.org, plan=plan)
        RolComplejo.objects.create(usuario=self.org, complejo=self.complejo, rol="ORG")
        self.torneo = Torneo.objects.create(complejo=self.complejo, nombre="Copa Barrial", organizador=self.org)

    def crear_equipos(self, n):
        nombres = ["Atlético Sur", "Deportivo Pichincha", "Real Carcelén", "Unión Comité",
                   "Los Halcones", "Juventud Norte", "Estrella Roja", "San José FC"]
        return [Equipo.objects.create(torneo=self.torneo, dirigente=self.org, estado_inscripcion='APROBADO',
                                      nombre=f"{nombres[i % len(nombres)]} {i // len(nombres) + 1}")
                for i in range(n)]

    def cerrar(self, partido, gl, gv, penales=None):
        partido.goles_local, partido.goles_visita, partido.estado = gl, gv, 'JUG'
        if penales:
            partido.hubo_penales = True
            partido.penales_local, partido.penales_visita = penales
        partido.save()
        c.procesar_partido_cerrado(partido)


class FaseDeGruposTest(CampeonatoBase):
    def test_24_equipos_crea_grupos_fixture_y_cuadro_completo(self):
        self.crear_equipos(24)
        # uno RECHAZADO no debe participar
        Equipo.objects.create(torneo=self.torneo, dirigente=self.org, nombre="Retirado FC", estado_inscripcion='RECHAZADO')
        c.iniciar_campeonato(self.torneo, 'GRUPOS', num_grupos=6, clasifican=2, mejores=4, semilla=42)
        self.torneo.refresh_from_db()
        self.assertEqual(self.torneo.formato, 'GRUPOS')
        self.assertEqual(Partido.objects.filter(torneo=self.torneo, etapa='GRP').count(), 6 * 6)
        self.assertFalse(Equipo.objects.filter(nombre="Retirado FC").exclude(grupo='').exists())
        # cuadro: 8 octavos + 4 cuartos + 2 semis + final + 3er lugar
        self.assertEqual(Llave.objects.filter(torneo=self.torneo, ronda='8VOS').count(), 8)
        self.assertEqual(Llave.objects.filter(torneo=self.torneo).count(), 16)
        etiquetas = set(Llave.objects.filter(ronda='8VOS').values_list('etiqueta_a', flat=True))
        self.assertIn('1° Grupo A', etiquetas)
        # Los partidos de llaves NO existen hasta que termine la fase de grupos
        self.assertFalse(Partido.objects.filter(torneo=self.torneo, etapa='8VOS').exists())

    def test_no_se_puede_cerrar_fase_con_partidos_pendientes(self):
        self.crear_equipos(8)
        c.iniciar_campeonato(self.torneo, 'GRUPOS', num_grupos=2, clasifican=2, semilla=1)
        with self.assertRaises(c.CampeonatoError):
            c.cerrar_fase_regular(self.torneo)

    def test_flujo_completo_hasta_el_campeon(self):
        self.crear_equipos(8)
        # 2 grupos de 4, pasan los 4 de cada grupo -> cuartos de final
        c.iniciar_campeonato(self.torneo, 'GRUPOS', num_grupos=2, clasifican=4, semilla=5)
        for p in Partido.objects.filter(torneo=self.torneo, etapa='GRP'):
            # gana siempre el de menor id
            if p.equipo_local_id < p.equipo_visita_id:
                self.cerrar(p, 2, 0)
            else:
                self.cerrar(p, 0, 1)
        c.cerrar_fase_regular(self.torneo)
        cuartos = Partido.objects.filter(torneo=self.torneo, etapa='4TOS')
        self.assertEqual(cuartos.count(), 4)
        # 1° de un grupo nunca juega contra alguien de su propio grupo en cuartos
        for p in cuartos:
            self.assertNotEqual(p.equipo_local.grupo, p.equipo_visita.grupo)
        for p in cuartos:
            self.cerrar(p, 1, 0)
        semis = Partido.objects.filter(torneo=self.torneo, etapa='SEMI')
        self.assertEqual(semis.count(), 2)
        for p in semis:
            self.cerrar(p, 1, 1, penales=(5, 4))
        final = Partido.objects.get(torneo=self.torneo, etapa='FINAL')
        tercero = Partido.objects.get(torneo=self.torneo, etapa='TERC')
        self.cerrar(tercero, 0, 2)
        self.cerrar(final, 3, 1)
        campeon = c.datos_cuadro(self.torneo)['campeon']
        self.assertEqual(campeon, final.equipo_local)

    def test_mejores_terceros_se_eligen_y_no_cruzan_con_su_grupo(self):
        self.crear_equipos(12)
        # 3 grupos de 4: pasan 2 + 2 mejores terceros = 8
        c.iniciar_campeonato(self.torneo, 'GRUPOS', num_grupos=3, clasifican=2, mejores=2, semilla=9)
        for p in Partido.objects.filter(torneo=self.torneo, etapa='GRP'):
            self.cerrar(p, 1, 0)
        c.cerrar_fase_regular(self.torneo)
        cuartos = list(Partido.objects.filter(torneo=self.torneo, etapa='4TOS').select_related('equipo_local', 'equipo_visita'))
        self.assertEqual(len(cuartos), 4)
        for p in cuartos:
            self.assertNotEqual(p.equipo_local.grupo, p.equipo_visita.grupo)

    def test_reinicio_bloqueado_si_ya_se_jugo(self):
        self.crear_equipos(4)
        c.iniciar_campeonato(self.torneo, 'GRUPOS', num_grupos=2, clasifican=1, semilla=3)
        p = Partido.objects.filter(torneo=self.torneo).first()
        self.cerrar(p, 1, 0)
        with self.assertRaises(c.CampeonatoError):
            c.reiniciar_campeonato(self.torneo)

    def test_reinicio_permitido_si_nada_se_jugo(self):
        self.crear_equipos(4)
        c.iniciar_campeonato(self.torneo, 'GRUPOS', num_grupos=2, clasifican=1, semilla=3)
        c.reiniciar_campeonato(self.torneo)
        self.torneo.refresh_from_db()
        self.assertEqual(self.torneo.formato, '')
        self.assertFalse(Partido.objects.filter(torneo=self.torneo).exists())
        self.assertFalse(Llave.objects.filter(torneo=self.torneo).exists())


class OtrasModalidadesTest(CampeonatoBase):
    def test_liga_solo_ida(self):
        self.crear_equipos(6)
        c.iniciar_campeonato(self.torneo, 'LIGA')
        self.assertEqual(Partido.objects.filter(torneo=self.torneo, etapa='F1').count(), 15)
        self.assertFalse(Llave.objects.filter(torneo=self.torneo).exists())

    def test_liga_playoff_cruza_1_con_4_y_2_con_3(self):
        equipos = self.crear_equipos(6)
        c.iniciar_campeonato(self.torneo, 'LIGA_PLAYOFF', clasifican_liga=4, tercer_lugar=False)
        for p in Partido.objects.filter(torneo=self.torneo, etapa='F1'):
            ganador_local = p.equipo_local_id < p.equipo_visita_id
            self.cerrar(p, 1 if ganador_local else 0, 0 if ganador_local else 1)
        c.cerrar_fase_regular(self.torneo)
        semis = Llave.objects.filter(torneo=self.torneo, ronda='SEMI').order_by('orden')
        self.assertEqual([(ll.equipo_a, ll.equipo_b) for ll in semis],
                         [(equipos[0], equipos[3]), (equipos[1], equipos[2])])

    def test_eliminacion_directa_con_byes(self):
        self.crear_equipos(6)
        c.iniciar_campeonato(self.torneo, 'ELIMINACION', semilla=11)
        # cuadro de 8 con 2 pases directos -> solo 2 partidos de cuartos
        self.assertEqual(Partido.objects.filter(torneo=self.torneo, etapa='4TOS').count(), 2)
        con_bye = Llave.objects.filter(torneo=self.torneo, ronda='4TOS').filter(origen_b='BYE')
        self.assertEqual(con_bye.count(), 2)
        for ll in con_bye:
            self.assertIsNotNone(ll.ganador)

    def test_ida_y_vuelta_global_y_penales(self):
        self.crear_equipos(2)
        c.iniciar_campeonato(self.torneo, 'ELIMINACION', ida_vuelta_llaves=True, final_ida_vuelta=True, semilla=1)
        ida, vuelta = Partido.objects.filter(torneo=self.torneo, etapa='FINAL').order_by('numero_fecha')
        self.cerrar(ida, 2, 1)
        llave = ida.llave
        llave.refresh_from_db()
        self.assertIsNone(llave.ganador)  # falta la vuelta
        self.cerrar(vuelta, 1, 0, penales=(3, 4))  # global 2-2, penales para el visitante de la vuelta
        llave.refresh_from_db()
        self.assertEqual(llave.ganador, ida.equipo_local)

    def test_wo_doble_cuenta_como_derrota_para_ambos(self):
        a, b = self.crear_equipos(2)
        p = Partido(torneo=self.torneo, etapa='F1', equipo_local=a, equipo_visita=b, estado='WO', ganador_wo=None)
        tabla = c.calcular_tabla([a, b], [p])
        self.assertEqual([f['pts'] for f in tabla], [0, 0])
        self.assertEqual([f['pp'] for f in tabla], [1, 1])

    def test_revertir_llave_deshace_avance(self):
        self.crear_equipos(4)
        c.iniciar_campeonato(self.torneo, 'ELIMINACION', semilla=2)
        semi = Partido.objects.filter(torneo=self.torneo, etapa='SEMI').first()
        self.cerrar(semi, 1, 0)
        final = Llave.objects.get(torneo=self.torneo, ronda='FINAL')
        self.assertTrue(final.equipo_a_id or final.equipo_b_id)
        c.revertir_llave(semi.llave)
        final.refresh_from_db()
        self.assertIsNone(final.equipo_a_id if semi.llave.slot_siguiente == 'A' else final.equipo_b_id)


class ExclusionesYRetirosTest(CampeonatoBase):
    def test_excluir_equipo_al_cerrar_fase_sube_el_siguiente(self):
        equipos = self.crear_equipos(6)
        c.iniciar_campeonato(self.torneo, 'LIGA_PLAYOFF', clasifican_liga=4, tercer_lugar=False)
        for p in Partido.objects.filter(torneo=self.torneo, etapa='F1'):
            ganador_local = p.equipo_local_id < p.equipo_visita_id
            self.cerrar(p, 1 if ganador_local else 0, 0 if ganador_local else 1)
        # El 1° es sancionado: no pasa; entra el 5°
        self.torneo.refresh_from_db()
        previa = c.previa_siguiente_fase(self.torneo, {equipos[0].id})
        nombres = {x['a'] for x in previa} | {x['b'] for x in previa}
        self.assertNotIn(equipos[0], nombres)
        self.assertIn(equipos[4], nombres)
        c.cerrar_fase_regular(self.torneo, {equipos[0].id})
        en_llaves = set(Partido.objects.filter(torneo=self.torneo, etapa='SEMI').values_list('equipo_local_id', 'equipo_visita_id'))
        ids = {i for par in en_llaves for i in par}
        self.assertNotIn(equipos[0].id, ids)
        self.assertIn(equipos[4].id, ids)

    def test_retirar_equipo_de_llave_avanza_el_rival(self):
        self.crear_equipos(4)
        c.iniciar_campeonato(self.torneo, 'ELIMINACION', ida_vuelta_llaves=True, semilla=4)
        semi = Llave.objects.filter(torneo=self.torneo, ronda='SEMI').first()
        ida = semi.partidos.order_by('numero_fecha').first()
        # el que se retira iba ganando 5-0 la ida
        self.cerrar(ida, 5, 0)
        retirado = ida.equipo_local
        rival = c.retirar_equipo_de_llave(semi, retirado)
        semi.refresh_from_db()
        self.assertEqual(semi.ganador, rival)
        final = Llave.objects.get(torneo=self.torneo, ronda='FINAL')
        self.assertIn(rival.id, (final.equipo_a_id, final.equipo_b_id))


class EdicionLlaveTest(CampeonatoBase):
    def test_admin_corrige_marcador_y_cambia_quien_avanza(self):
        from django.test import Client
        self.crear_equipos(4)
        c.iniciar_campeonato(self.torneo, 'ELIMINACION', semilla=8)
        semi = Partido.objects.filter(torneo=self.torneo, etapa='SEMI').first()
        self.cerrar(semi, 2, 0)
        final = Llave.objects.get(torneo=self.torneo, ronda='FINAL')
        slot = 'equipo_a_id' if semi.llave.slot_siguiente == 'A' else 'equipo_b_id'
        self.assertEqual(getattr(final, slot), semi.equipo_local_id)
        cli = Client(); cli.login(username="org", password="pass12345")
        cli.post(f"/partido/resultado/{semi.id}/", {"goles_local": "0", "goles_visita": "1"})
        final.refresh_from_db()
        self.assertEqual(getattr(final, slot), semi.equipo_visita_id)
        self.assertTrue(semi.ediciones.filter(detalle__contains="2-0 → 0-1").exists())
