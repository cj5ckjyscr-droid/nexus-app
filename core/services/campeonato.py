"""Motor del campeonato: modalidades, sorteo de grupos, tablas y llaves.

Reglas de diseño (pedidas por el organizador):
- Nada de cruces "a mano": el cuadro eliminatorio se crea COMPLETO al empezar
  el campeonato, con etiquetas fijas ("1° Grupo A vs Mejor 3° #2"), y los
  ganadores avanzan solos. Así todos ven desde el inicio cómo se cruzan.
- El sorteo de grupos usa una semilla que queda guardada en el torneo: con la
  misma semilla el sorteo da exactamente el mismo resultado (auditable).
- Todo se calcula con pocas consultas (una por torneo) para ahorrar BD.
"""
import itertools
import random

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ..models import Equipo, Llave, Partido, DetallePartido

LETRAS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
MAX_CLASIFICADOS = 32

# Ronda según cuántos equipos la juegan
RONDA_POR_EQUIPOS = {32: '16VOS', 16: '8VOS', 8: '4TOS', 4: 'SEMI', 2: 'FINAL'}
NOMBRE_RONDA = {
    '16VOS': 'Dieciseisavos', '8VOS': 'Octavos de final', '4TOS': 'Cuartos de final',
    'SEMI': 'Semifinal', 'FINAL': 'Final', 'TERC': 'Tercer lugar',
}
ORDEN_RONDAS = ['16VOS', '8VOS', '4TOS', 'SEMI', 'FINAL']
ESTADOS_CERRADOS = ('JUG', 'WO')


class CampeonatoError(Exception):
    pass


# ---------------------------------------------------------------------------
# Utilidades puras
# ---------------------------------------------------------------------------
def es_potencia_2(n):
    return n >= 2 and (n & (n - 1)) == 0


def siguiente_potencia_2(n):
    p = 2
    while p < n:
        p *= 2
    return p


def orden_semillas(n):
    """Orden estándar de cabezas de serie para un cuadro de n (potencia de 2):
    el 1 y el 2 solo pueden cruzarse en la final, 1-4 en semis, etc.
    n=8 -> [1, 8, 4, 5, 2, 7, 3, 6] (cruces 1v8, 4v5, 2v7, 3v6)."""
    orden = [1]
    while len(orden) < n:
        m = len(orden) * 2
        orden = [x for s in orden for x in (s, m + 1 - s)]
    return orden


def round_robin(equipos, ida_vuelta=False):
    """Todos contra todos (método del círculo). Devuelve una lista de
    jornadas; cada jornada es una lista de tuplas (local, visita). La localía
    se reparte para que cada equipo juegue de local casi la mitad de veces."""
    lista = list(equipos)
    if len(lista) < 2:
        return []
    if len(lista) % 2:
        lista.append(None)  # descansa
    n = len(lista)
    locales = {}
    jornadas = []
    for r in range(n - 1):
        partidos = []
        for i in range(n // 2):
            a, b = lista[i], lista[n - 1 - i]
            if a is None or b is None:
                continue
            la, lb = locales.get(id(a), 0), locales.get(id(b), 0)
            if lb < la or (lb == la and (r + i) % 2 == 1):
                a, b = b, a
            locales[id(a)] = locales.get(id(a), 0) + 1
            partidos.append((a, b))
        jornadas.append(partidos)
        lista.insert(1, lista.pop())
    if ida_vuelta:
        jornadas += [[(b, a) for a, b in j] for j in jornadas]
    return jornadas


def tamanos_grupos(n, g):
    base, extra = divmod(n, g)
    return [base + (1 if i < extra else 0) for i in range(g)]


def sortear_grupos(equipos, num_grupos, semilla):
    """Reparte los equipos en grupos de forma aleatoria pero REPRODUCIBLE con
    la semilla. Tamaños balanceados (difieren a lo sumo en 1)."""
    lista = sorted(equipos, key=lambda e: e.id)
    random.Random(semilla).shuffle(lista)
    grupos = {LETRAS[i]: [] for i in range(num_grupos)}
    for idx, eq in enumerate(lista):
        grupos[LETRAS[idx % num_grupos]].append(eq)
    return grupos


def contar_partidos_liga(n, ida_vuelta):
    return n * (n - 1) // 2 * (2 if ida_vuelta else 1)


def validar_configuracion(formato, n, num_grupos=0, clasifican=0, mejores=0,
                          clasifican_liga=0, ida_vuelta_liga=False):
    """Revisa que la modalidad elegida tenga una estructura válida. Devuelve
    (errores, resumen). Si hay errores no se puede empezar el campeonato."""
    errores = []
    resumen = {'equipos': n}
    if n < 2:
        return ["Se necesitan al menos 2 equipos APROBADOS para empezar."], resumen

    if formato == 'LIGA':
        resumen['partidos_fase'] = contar_partidos_liga(n, ida_vuelta_liga)
    elif formato == 'LIGA_PLAYOFF':
        resumen['partidos_fase'] = contar_partidos_liga(n, ida_vuelta_liga)
        if not es_potencia_2(clasifican_liga):
            errores.append("Los clasificados a las llaves deben ser 2, 4, 8, 16 o 32 (para que el cuadro cierre exacto).")
        elif clasifican_liga > n:
            errores.append(f"No pueden clasificar {clasifican_liga} si solo hay {n} equipos.")
        resumen['clasificados'] = clasifican_liga
    elif formato == 'GRUPOS':
        if num_grupos < 2:
            errores.append("Debe haber al menos 2 grupos.")
            return errores, resumen
        tams = tamanos_grupos(n, num_grupos)
        resumen['tamanos'] = tams
        if min(tams) < 2:
            errores.append(f"Con {n} equipos no alcanzan para {num_grupos} grupos (cada grupo necesita mínimo 2).")
            return errores, resumen
        if clasifican < 1:
            errores.append("Debe clasificar al menos 1 equipo por grupo.")
        if clasifican > min(tams):
            errores.append(f"No pueden clasificar {clasifican} por grupo: el grupo más chico tiene {min(tams)} equipos.")
        if mejores and clasifican + 1 > min(tams):
            errores.append(f"Para tomar a los mejores {clasifican + 1}° todos los grupos deben tener al menos {clasifican + 1} equipos.")
        if mejores >= num_grupos and mejores:
            errores.append(f"Los 'mejores {clasifican + 1}°' deben ser menos que la cantidad de grupos ({num_grupos}).")
        total = num_grupos * clasifican + mejores
        resumen['clasificados'] = total
        if not es_potencia_2(total):
            errores.append(
                f"Clasifican {total} equipos ({num_grupos} grupos × {clasifican}"
                f"{f' + {mejores} mejores {clasifican + 1}°' if mejores else ''}). "
                "Para armar llaves sin trampas deben ser 2, 4, 8, 16 o 32."
            )
        elif total > MAX_CLASIFICADOS:
            errores.append(f"Máximo {MAX_CLASIFICADOS} clasificados a las llaves.")
        resumen['partidos_fase'] = sum(contar_partidos_liga(t, ida_vuelta_liga) for t in tams)
    elif formato == 'ELIMINACION':
        if n > MAX_CLASIFICADOS:
            errores.append(f"La eliminación directa admite hasta {MAX_CLASIFICADOS} equipos.")
        resumen['clasificados'] = n
        resumen['cuadro'] = siguiente_potencia_2(n)
        resumen['byes'] = siguiente_potencia_2(n) - n
    else:
        errores.append("Elige una modalidad válida.")

    if 'clasificados' in resumen and es_potencia_2(resumen.get('clasificados', 0)):
        rondas, m = [], resumen['clasificados']
        while m >= 2:
            rondas.append(NOMBRE_RONDA[RONDA_POR_EQUIPOS[m]])
            m //= 2
        resumen['rondas'] = rondas
    elif formato == 'ELIMINACION' and n >= 2:
        rondas, m = [], siguiente_potencia_2(n)
        while m >= 2:
            rondas.append(NOMBRE_RONDA[RONDA_POR_EQUIPOS[m]])
            m //= 2
        resumen['rondas'] = rondas
    return errores, resumen


def sugerencias_grupos(n, limite=6):
    """Combinaciones válidas de grupos para n equipos (grupos de 3 a 6)."""
    opciones = []
    for g in range(2, n // 3 + 1):
        tams = tamanos_grupos(n, g)
        if min(tams) < 3 or max(tams) > 6:
            continue
        for k in range(1, min(tams) + 1):
            for m in range(0, g):
                total = g * k + m
                if m and k + 1 > min(tams):
                    continue
                if k == min(tams) and m:
                    continue
                if es_potencia_2(total) and total <= MAX_CLASIFICADOS and total < n:
                    opciones.append({'grupos': g, 'clasifican': k, 'mejores': m, 'total': total, 'tamanos': tams})
    # Preferimos grupos parejos de 4 y pocos "mejores"
    opciones.sort(key=lambda o: (abs(o['tamanos'][0] - 4), o['mejores'], -o['total']))
    return opciones[:limite]


# ---------------------------------------------------------------------------
# Tablas de posiciones (una sola consulta, maneja W.O. correctamente)
# ---------------------------------------------------------------------------
def calcular_tabla(equipos, partidos, con_bono=False):
    filas = {}
    for e in equipos:
        filas[e.id] = {'equipo': e, 'pj': 0, 'pg': 0, 'pe': 0, 'pp': 0, 'gf': 0, 'gc': 0,
                       'pts': 0, 'bono': e.puntos_bonificacion if con_bono else 0}
    for p in partidos:
        if p.estado not in ESTADOS_CERRADOS:
            continue
        loc, vis = filas.get(p.equipo_local_id), filas.get(p.equipo_visita_id)
        if loc is None or vis is None:
            continue
        loc['pj'] += 1; vis['pj'] += 1
        loc['gf'] += p.goles_local; loc['gc'] += p.goles_visita
        vis['gf'] += p.goles_visita; vis['gc'] += p.goles_local
        if p.estado == 'WO':
            if p.ganador_wo_id == p.equipo_local_id:
                loc['pg'] += 1; vis['pp'] += 1
            elif p.ganador_wo_id == p.equipo_visita_id:
                vis['pg'] += 1; loc['pp'] += 1
            else:  # doble W.O.: nadie suma
                loc['pp'] += 1; vis['pp'] += 1
        elif p.goles_local > p.goles_visita:
            loc['pg'] += 1; vis['pp'] += 1
        elif p.goles_local < p.goles_visita:
            vis['pg'] += 1; loc['pp'] += 1
        else:
            loc['pe'] += 1; vis['pe'] += 1
    for f in filas.values():
        f['gd'] = f['gf'] - f['gc']
        f['pts'] = f['pg'] * 3 + f['pe'] + f['bono']
    tabla = sorted(filas.values(), key=lambda f: (-f['pts'], -f['gd'], -f['gf'], -f['pg'], f['equipo'].nombre.lower()))
    for i, f in enumerate(tabla, start=1):
        f['pos'] = i
    return tabla


def tabla_liga(torneo, etapa='F1', con_bono=False):
    equipos = list(Equipo.objects.filter(torneo=torneo, estado_inscripcion='APROBADO'))
    partidos = Partido.objects.filter(torneo=torneo, etapa=etapa).only(
        'estado', 'equipo_local_id', 'equipo_visita_id', 'goles_local', 'goles_visita', 'ganador_wo_id')
    return calcular_tabla(equipos, partidos, con_bono)


def tablas_grupos(torneo):
    """{'A': tabla, 'B': tabla, ...} de la fase de grupos."""
    equipos = list(Equipo.objects.filter(torneo=torneo, estado_inscripcion='APROBADO').exclude(grupo=''))
    partidos = list(Partido.objects.filter(torneo=torneo, etapa='GRP').only(
        'estado', 'equipo_local_id', 'equipo_visita_id', 'goles_local', 'goles_visita', 'ganador_wo_id'))
    tablas = {}
    for letra in sorted({e.grupo for e in equipos}):
        tablas[letra] = calcular_tabla([e for e in equipos if e.grupo == letra], partidos)
    return tablas


def ranking_mejores(tablas, posicion):
    """Ranking de los equipos que terminaron en `posicion` en cada grupo.
    Se compara por promedio (puntos/partido, DG/partido, GF/partido) para que
    sea justo aunque haya grupos de distinto tamaño."""
    candidatos = []
    for letra, tabla in tablas.items():
        if len(tabla) >= posicion:
            f = dict(tabla[posicion - 1]); f['grupo'] = letra
            candidatos.append(f)

    def clave(f):
        pj = f['pj'] or 1
        return (-f['pts'] / pj, -f['gd'] / pj, -f['gf'] / pj, -f['pts'], -f['gd'], -f['gf'], f['grupo'])
    return sorted(candidatos, key=clave)


# ---------------------------------------------------------------------------
# Cuadro eliminatorio
# ---------------------------------------------------------------------------
def _choques_mismo_grupo(slots):
    """Cuántos cruces de primera ronda enfrentan a dos equipos del mismo grupo."""
    tam = siguiente_potencia_2(len(slots))
    orden = orden_semillas(tam)
    n = 0
    for i in range(tam // 2):
        sa, sb = orden[2 * i] - 1, orden[2 * i + 1] - 1
        if sa < len(slots) and sb < len(slots):
            ca, cb = slots[sa][0], slots[sb][0]
            if ca.startswith('G') and cb.startswith('G') and ca[1] == cb[1]:
                n += 1
    return n


def semillas_grupos(num_grupos, clasifican, mejores):
    """Códigos de los clasificados en orden de cabeza de serie: primero
    todos los 1°, luego los 2°, ... y al final los mejores. El orden de los
    grupos en cada puesto se elige para que en la primera ronda NUNCA se
    repita un cruce del mismo grupo (ej. 1° A nunca contra 2° A)."""
    letras = [LETRAS[i] for i in range(num_grupos)]

    def armar(rot, invertir):
        slots = []
        for pos in range(1, clasifican + 1):
            orden = list(letras)
            if pos > 1:
                if invertir:
                    orden.reverse()
                k = (rot * (pos - 1)) % num_grupos
                orden = orden[k:] + orden[:k]
            for l in orden:
                slots.append((f"G{l}{pos}", f"{pos}° Grupo {l}"))
        for r in range(1, mejores + 1):
            slots.append((f"M{clasifican + 1}{r:02d}", f"Mejor {clasifican + 1}° #{r}"))
        return slots

    mejor, mejor_n = None, None
    for invertir in (True, False):
        for rot in range(num_grupos):
            cand = armar(rot, invertir)
            n = _choques_mismo_grupo(cand)
            if mejor_n is None or n < mejor_n:
                mejor, mejor_n = cand, n
            if n == 0:
                return cand
    return mejor


def semillas_liga(k):
    return [(f"L{pos}", f"{pos}° de la Liga") for pos in range(1, k + 1)]


def _etiqueta_ganador(ronda, orden_en_ronda):
    return f"Ganador {NOMBRE_RONDA[ronda]} {orden_en_ronda}"


def construir_cuadro(torneo, slots, equipos_directos=None):
    """Crea TODAS las llaves del cuadro. `slots` es una lista (codigo,
    etiqueta) ordenada por cabeza de serie. Si el tamaño no es potencia de 2
    se completan con BYE (pase directo para las mejores semillas)."""
    equipos_directos = equipos_directos or {}
    tam = siguiente_potencia_2(len(slots))
    slots = list(slots) + [('BYE', 'Pase directo')] * (tam - len(slots))
    orden = orden_semillas(tam)

    rondas = []
    m = tam
    while m >= 2:
        rondas.append(RONDA_POR_EQUIPOS[m])
        m //= 2

    por_ronda = {}
    contador = 0
    for idx_r, ronda in enumerate(rondas):
        cantidad = tam // (2 ** (idx_r + 1))
        lista = []
        for i in range(cantidad):
            contador += 1
            ll = Llave(torneo=torneo, ronda=ronda, orden=contador)
            if idx_r == 0:
                ca, la = slots[orden[2 * i] - 1]
                cb, lb = slots[orden[2 * i + 1] - 1]
                ll.origen_a, ll.etiqueta_a = ca, la
                ll.origen_b, ll.etiqueta_b = cb, lb
                ll.equipo_a = equipos_directos.get(ca)
                ll.equipo_b = equipos_directos.get(cb)
            else:
                previa = rondas[idx_r - 1]
                ll.etiqueta_a = _etiqueta_ganador(previa, 2 * i + 1)
                ll.etiqueta_b = _etiqueta_ganador(previa, 2 * i + 2)
            ll.save()
            lista.append(ll)
        por_ronda[ronda] = lista

    for idx_r, ronda in enumerate(rondas[:-1]):
        sig = por_ronda[rondas[idx_r + 1]]
        for i, ll in enumerate(por_ronda[ronda]):
            ll.siguiente = sig[i // 2]
            ll.slot_siguiente = 'A' if i % 2 == 0 else 'B'
            ll.save(update_fields=['siguiente', 'slot_siguiente'])

    if torneo.tercer_lugar and 'SEMI' in por_ronda:
        contador += 1
        terc = Llave.objects.create(torneo=torneo, ronda='TERC', orden=contador,
                                    etiqueta_a='Perdedor Semifinal 1', etiqueta_b='Perdedor Semifinal 2')
        for i, semi in enumerate(por_ronda['SEMI']):
            semi.siguiente_perdedor = terc
            semi.slot_perdedor = 'A' if i == 0 else 'B'
            semi.save(update_fields=['siguiente_perdedor', 'slot_perdedor'])
    return por_ronda


def crear_partidos_llave(llave):
    if llave.partidos.exists() or not (llave.equipo_a_id and llave.equipo_b_id):
        return
    torneo = llave.torneo
    if llave.ronda == 'FINAL':
        ida_vuelta = torneo.final_ida_vuelta
    elif llave.ronda == 'TERC':
        ida_vuelta = False
    else:
        ida_vuelta = torneo.fase3_ida_vuelta
    Partido.objects.create(torneo=torneo, etapa=llave.ronda, numero_fecha=1, llave=llave,
                           equipo_local=llave.equipo_a, equipo_visita=llave.equipo_b)
    if ida_vuelta:
        Partido.objects.create(torneo=torneo, etapa=llave.ronda, numero_fecha=2, llave=llave,
                               equipo_local=llave.equipo_b, equipo_visita=llave.equipo_a)


def ganador_llave(llave):
    """Ganador por marcador global; si empatan, por penales. None si aún no
    se define (partidos sin cerrar, empate sin penales o doble W.O.)."""
    if llave.es_bye:
        return llave.equipo_a or llave.equipo_b
    partidos = list(llave.partidos.all())
    if not partidos or any(p.estado not in ESTADOS_CERRADOS for p in partidos):
        return None
    a, b = llave.equipo_a_id, llave.equipo_b_id
    if len(partidos) == 1 and partidos[0].estado == 'WO':
        g = partidos[0].ganador_wo_id
        return llave.equipo_a if g == a else llave.equipo_b if g == b else None
    goles = {a: 0, b: 0}
    penales = {a: 0, b: 0}
    for p in partidos:
        goles[p.equipo_local_id] += p.goles_local
        goles[p.equipo_visita_id] += p.goles_visita
        if p.hubo_penales:
            penales[p.equipo_local_id] += p.penales_local or 0
            penales[p.equipo_visita_id] += p.penales_visita or 0
    if goles[a] != goles[b]:
        return llave.equipo_a if goles[a] > goles[b] else llave.equipo_b
    if penales[a] != penales[b]:
        return llave.equipo_a if penales[a] > penales[b] else llave.equipo_b
    return None


def _colocar(llave_destino, slot, equipo):
    if llave_destino is None:
        return
    llave_destino.refresh_from_db()
    campo = 'equipo_a' if slot == 'A' else 'equipo_b'
    setattr(llave_destino, campo, equipo)
    llave_destino.save(update_fields=[campo])
    crear_partidos_llave(llave_destino)
    if llave_destino.es_bye:
        avanzar_llave(llave_destino)


def avanzar_llave(llave):
    """Si la llave ya tiene ganador lo pasa a la siguiente ronda (y el
    perdedor de semifinal al partido por el 3er lugar)."""
    ganador = ganador_llave(llave)
    if ganador is None or llave.ganador_id == ganador.id:
        return ganador
    llave.ganador = ganador
    llave.save(update_fields=['ganador'])
    _colocar(llave.siguiente, llave.slot_siguiente, ganador)
    if llave.siguiente_perdedor_id and llave.equipo_a_id and llave.equipo_b_id:
        perdedor = llave.equipo_b if ganador.id == llave.equipo_a_id else llave.equipo_a
        _colocar(llave.siguiente_perdedor, llave.slot_perdedor, perdedor)
    return ganador


def _llave_ya_jugada(llave):
    return Partido.objects.filter(llave=llave).filter(
        Q(estado__in=['VIVO', 'ACTA', 'JUG', 'WO']) | Q(detalles__isnull=False)).exists()


def revertir_llave(llave):
    """Deshace el avance de una llave (al reiniciar uno de sus partidos).
    Falla si la ronda siguiente ya empezó a jugarse."""
    if not llave.ganador_id:
        return
    destinos = [(llave.siguiente, llave.slot_siguiente), (llave.siguiente_perdedor, llave.slot_perdedor)]
    for destino, _slot in destinos:
        if destino and _llave_ya_jugada(destino):
            raise CampeonatoError(
                f"No se puede reiniciar: la llave siguiente ({NOMBRE_RONDA.get(destino.ronda, destino.ronda)}) ya se empezó a jugar.")
    for destino, slot in destinos:
        if destino:
            destino.partidos.all().delete()
            campo = 'equipo_a' if slot == 'A' else 'equipo_b'
            setattr(destino, campo, None)
            destino.ganador = None
            destino.save(update_fields=[campo, 'ganador'])
    llave.ganador = None
    llave.save(update_fields=['ganador'])


def procesar_partido_cerrado(partido):
    """Llamar cada vez que un partido pasa a JUG o WO."""
    if partido.llave_id:
        return avanzar_llave(partido.llave)
    return None


# ---------------------------------------------------------------------------
# Inicio, cierre de fase regular y reinicio
# ---------------------------------------------------------------------------
def equipos_participantes(torneo):
    return list(Equipo.objects.filter(torneo=torneo, estado_inscripcion='APROBADO').order_by('id'))


@transaction.atomic
def iniciar_campeonato(torneo, formato, *, ida_vuelta_liga=False, num_grupos=0, clasifican=0,
                       mejores=0, clasifican_liga=0, ida_vuelta_llaves=False, final_ida_vuelta=False,
                       tercer_lugar=True, semilla=None, grupos_manual=None):
    """Crea todo el fixture del campeonato de una sola vez.
    grupos_manual: {equipo_id: 'A', ...} si el organizador ajustó el sorteo."""
    torneo = type(torneo).objects.select_for_update().get(pk=torneo.pk)
    if torneo.formato:
        raise CampeonatoError("Este campeonato ya fue iniciado.")
    if Partido.objects.filter(torneo=torneo).exists():
        raise CampeonatoError("Este torneo ya tiene partidos creados.")
    equipos = equipos_participantes(torneo)
    errores, _ = validar_configuracion(formato, len(equipos), num_grupos, clasifican, mejores,
                                       clasifican_liga, ida_vuelta_liga)
    if errores:
        raise CampeonatoError(" ".join(errores))
    if semilla is None:
        semilla = random.SystemRandom().randint(1000, 999999)

    torneo.formato = formato
    torneo.fase1_ida_vuelta = ida_vuelta_liga
    torneo.fase3_ida_vuelta = ida_vuelta_llaves
    torneo.final_ida_vuelta = final_ida_vuelta
    torneo.tercer_lugar = tercer_lugar
    torneo.num_grupos = num_grupos if formato == 'GRUPOS' else 0
    torneo.clasifican_por_grupo = clasifican if formato == 'GRUPOS' else 0
    torneo.mejores_extra = mejores if formato == 'GRUPOS' else 0
    torneo.clasifican_liga = clasifican_liga if formato == 'LIGA_PLAYOFF' else 0
    torneo.semilla_sorteo = semilla
    torneo.campeonato_iniciado_en = timezone.now()
    torneo.fase_regular_cerrada = False
    # OJO: no se cierra inscripcion_abierta: controla también el fichaje de
    # jugadores. Los equipos nuevos ya se bloquean por campeonato_iniciado.
    torneo.save()

    if formato in ('LIGA', 'LIGA_PLAYOFF'):
        for num, jornada in enumerate(round_robin(equipos, ida_vuelta_liga), start=1):
            Partido.objects.bulk_create([
                Partido(torneo=torneo, etapa='F1', numero_fecha=num, equipo_local=a, equipo_visita=b)
                for a, b in jornada])
        if formato == 'LIGA_PLAYOFF':
            construir_cuadro(torneo, semillas_liga(clasifican_liga))

    elif formato == 'GRUPOS':
        grupos = armar_grupos(equipos, num_grupos, semilla, grupos_manual)
        for letra, miembros in grupos.items():
            Equipo.objects.filter(id__in=[e.id for e in miembros]).update(grupo=letra)
            for num, jornada in enumerate(round_robin(miembros, ida_vuelta_liga), start=1):
                Partido.objects.bulk_create([
                    Partido(torneo=torneo, etapa='GRP', numero_fecha=num, equipo_local=a, equipo_visita=b)
                    for a, b in jornada])
        construir_cuadro(torneo, semillas_grupos(num_grupos, clasifican, mejores))

    elif formato == 'ELIMINACION':
        if len(equipos) < 4 and torneo.tercer_lugar:
            torneo.tercer_lugar = False
            torneo.save(update_fields=['tercer_lugar'])
        orden = sorted(equipos, key=lambda e: e.id)
        random.Random(semilla).shuffle(orden)
        slots = [(f"E{e.id}", e.nombre) for e in orden]
        directos = {f"E{e.id}": e for e in orden}
        por_ronda = construir_cuadro(torneo, slots, directos)
        torneo.fase_regular_cerrada = True
        torneo.save(update_fields=['fase_regular_cerrada'])
        for ll in next(iter(por_ronda.values())):
            if ll.es_bye:
                avanzar_llave(ll)
            else:
                crear_partidos_llave(ll)
    return torneo


def armar_grupos(equipos, num_grupos, semilla, grupos_manual=None):
    if not grupos_manual:
        return sortear_grupos(equipos, num_grupos, semilla)
    letras = [LETRAS[i] for i in range(num_grupos)]
    grupos = {l: [] for l in letras}
    for e in equipos:
        letra = grupos_manual.get(e.id)
        if letra not in grupos:
            raise CampeonatoError(f"Falta asignar grupo a {e.nombre}.")
        grupos[letra].append(e)
    tams = sorted(len(v) for v in grupos.values())
    if tams[-1] - tams[0] > 1:
        raise CampeonatoError("Los grupos deben quedar parejos (máximo 1 equipo de diferencia entre grupos).")
    return grupos


def etapa_regular(torneo):
    return 'GRP' if torneo.formato == 'GRUPOS' else 'F1'


def fase_regular_completa(torneo):
    etapa = etapa_regular(torneo)
    qs = Partido.objects.filter(torneo=torneo, etapa=etapa)
    return qs.exists() and not qs.exclude(estado__in=ESTADOS_CERRADOS).exists()


def _sin_excluidos(tabla, excluidos):
    """Quita a los equipos excluidos y renumera: el siguiente sube de puesto."""
    filas = [dict(f) for f in tabla if f['equipo'].id not in excluidos]
    for i, f in enumerate(filas, start=1):
        f['pos'] = i
    return filas


def resolver_clasificados(torneo, excluidos=frozenset()):
    """Devuelve {codigo: equipo} con los clasificados de la fase regular.
    `excluidos`: ids de equipos que el organizador saca de la siguiente fase
    (retirados, sancionados); su lugar lo toma el siguiente de la tabla."""
    excluidos = set(excluidos or ())
    if torneo.formato == 'LIGA_PLAYOFF':
        tabla = _sin_excluidos(tabla_liga(torneo), excluidos)
        return {f"L{f['pos']}": f['equipo'] for f in tabla[:torneo.clasifican_liga]}
    if torneo.formato == 'GRUPOS':
        tablas = {l: _sin_excluidos(t, excluidos) for l, t in tablas_grupos(torneo).items()}
        res = {}
        for letra, tabla in tablas.items():
            for f in tabla[:torneo.clasifican_por_grupo]:
                res[f"G{letra}{f['pos']}"] = f['equipo']
        pos_extra = torneo.clasifican_por_grupo + 1
        ranking = ranking_mejores(tablas, pos_extra)[:torneo.mejores_extra]
        for r, f in enumerate(ranking, start=1):
            res[f"M{pos_extra}{r:02d}"] = f['equipo']
        return res
    return {}


def _grupo_de_codigo(codigo, mapa):
    if codigo.startswith('G'):
        return codigo[1]
    eq = mapa.get(codigo)
    return eq.grupo if eq else None


def _evitar_cruces_mismo_grupo(llaves_r1, mapa):
    """Si un 'mejor tercero' cae contra un equipo de su mismo grupo, se
    intercambian los mejores entre sí (siempre la primera combinación válida,
    determinística) para evitar repetir el cruce de grupos."""
    codigos_m = sorted(c for c in mapa if c.startswith('M'))
    if not codigos_m or len(codigos_m) > 8:
        return mapa
    equipos_m = [mapa[c] for c in codigos_m]

    def conflictos(m):
        n = 0
        for ll in llaves_r1:
            ga, gb = _grupo_de_codigo(ll.origen_a, m), _grupo_de_codigo(ll.origen_b, m)
            if ga and ga == gb:
                n += 1
        return n

    mejor, mejor_n = mapa, conflictos(mapa)
    if mejor_n == 0:
        return mapa
    for perm in itertools.permutations(equipos_m):
        prueba = dict(mapa)
        prueba.update(dict(zip(codigos_m, perm)))
        n = conflictos(prueba)
        if n < mejor_n:
            mejor, mejor_n = prueba, n
            if n == 0:
                break
    return mejor


def previa_siguiente_fase(torneo, excluidos=frozenset()):
    """Cruces de la primera ronda de llaves SIN guardar nada (para revisar,
    excluir equipos y descargar el PDF antes de confirmar)."""
    mapa = _evitar_cruces_mismo_grupo(primera_ronda(torneo), resolver_clasificados(torneo, excluidos))
    cruces = []
    for ll in primera_ronda(torneo):
        cruces.append({'llave': ll, 'a': mapa.get(ll.origen_a), 'b': mapa.get(ll.origen_b),
                       'etiqueta_a': ll.etiqueta_a, 'etiqueta_b': ll.etiqueta_b})
    return cruces


@transaction.atomic
def cerrar_fase_regular(torneo, excluidos=frozenset()):
    """Cierra la liga / fase de grupos y coloca a los clasificados en las
    llaves ya definidas desde el inicio. Si un puesto queda vacío (por
    excluir equipos) el rival pasa directo."""
    torneo = type(torneo).objects.select_for_update().get(pk=torneo.pk)
    if torneo.fase_regular_cerrada:
        raise CampeonatoError("La fase regular ya fue cerrada.")
    if not fase_regular_completa(torneo):
        raise CampeonatoError("Aún hay partidos de la fase regular sin finalizar.")
    torneo.fase_regular_cerrada = True
    torneo.save(update_fields=['fase_regular_cerrada'])
    if torneo.formato == 'LIGA':
        return torneo

    primera = primera_ronda(torneo)
    mapa = _evitar_cruces_mismo_grupo(primera, resolver_clasificados(torneo, excluidos))
    for ll in primera:
        ll.equipo_a = mapa.get(ll.origen_a)
        ll.equipo_b = mapa.get(ll.origen_b)
        if ll.equipo_a is None and ll.equipo_b is None:
            raise CampeonatoError("Con los equipos excluidos quedan cruces vacíos. Excluye menos equipos.")
        if ll.equipo_a is None:
            ll.origen_a, ll.etiqueta_a = 'BYE', 'Pase directo'
        if ll.equipo_b is None:
            ll.origen_b, ll.etiqueta_b = 'BYE', 'Pase directo'
        ll.save()
        if ll.es_bye:
            avanzar_llave(ll)
        else:
            crear_partidos_llave(ll)
    return torneo


@transaction.atomic
def retirar_equipo_de_llave(llave, equipo):
    """Saca a un equipo de su llave (sanción, retiro): sus partidos pendientes
    se cierran por W.O. a favor del rival, que avanza solo."""
    if equipo.id not in (llave.equipo_a_id, llave.equipo_b_id):
        raise CampeonatoError("Ese equipo no juega esta llave.")
    if llave.ganador_id:
        raise CampeonatoError("Esta llave ya está definida.")
    rival = llave.equipo_b if equipo.id == llave.equipo_a_id else llave.equipo_a
    if rival is None:
        raise CampeonatoError("Aún no se conoce al rival de esta llave.")
    crear_partidos_llave(llave)
    for p in llave.partidos.exclude(estado__in=ESTADOS_CERRADOS):
        if p.detalles.exists() and p.estado == 'VIVO':
            p.detalles.all().delete()
        p.estado = 'WO'
        p.ganador_wo = rival
        p.goles_local, p.goles_visita = (3, 0) if p.equipo_local_id == rival.id else (0, 3)
        p.validado_local = p.validado_visita = True
        p.sanciones_aplicadas = True
        p.informe_vocal = f"{equipo.nombre} retirado de la llave por el organizador."
        p.save()
    llave.refresh_from_db()
    # El rival avanza SIEMPRE (aunque el retirado fuera ganando en el global)
    _forzar_ganador(llave, rival)
    return rival


def _forzar_ganador(llave, ganador):
    llave.ganador = ganador
    llave.save(update_fields=['ganador'])
    _colocar(llave.siguiente, llave.slot_siguiente, ganador)
    if llave.siguiente_perdedor_id:
        perdedor = llave.equipo_b if ganador.id == llave.equipo_a_id else llave.equipo_a
        _colocar(llave.siguiente_perdedor, llave.slot_perdedor, perdedor)


def primera_ronda(torneo):
    llaves = list(Llave.objects.filter(torneo=torneo).exclude(ronda='TERC'))
    if not llaves:
        return []
    for r in ORDEN_RONDAS:
        sel = [ll for ll in llaves if ll.ronda == r]
        if sel:
            return sorted(sel, key=lambda ll: ll.orden)
    return []


def hay_partidos_jugados(torneo):
    return Partido.objects.filter(torneo=torneo).filter(
        Q(estado__in=['VIVO', 'ACTA', 'JUG', 'WO']) | Q(detalles__isnull=False)).exists()


@transaction.atomic
def reiniciar_campeonato(torneo):
    if hay_partidos_jugados(torneo):
        raise CampeonatoError("No se puede reiniciar: ya hay partidos jugados o en juego. Esto evita cambiar el campeonato a mitad de camino.")
    Partido.objects.filter(torneo=torneo).delete()
    Llave.objects.filter(torneo=torneo).delete()
    Equipo.objects.filter(torneo=torneo).update(grupo='')
    torneo.formato = ''
    torneo.fase_regular_cerrada = False
    torneo.campeonato_iniciado_en = None
    torneo.semilla_sorteo = None
    torneo.save()


# ---------------------------------------------------------------------------
# Datos para pintar el cuadro
# ---------------------------------------------------------------------------
def datos_cuadro(torneo):
    llaves = list(Llave.objects.filter(torneo=torneo).select_related(
        'equipo_a', 'equipo_b', 'ganador').prefetch_related('partidos'))
    rondas = []
    for r in ORDEN_RONDAS:
        sel = sorted([ll for ll in llaves if ll.ronda == r], key=lambda ll: ll.orden)
        if sel:
            rondas.append({'codigo': r, 'nombre': NOMBRE_RONDA[r],
                           'llaves': [_info_llave(ll, i) for i, ll in enumerate(sel, start=1)]})
    terc = next((ll for ll in llaves if ll.ronda == 'TERC'), None)
    final = next((ll for ll in llaves if ll.ronda == 'FINAL'), None)
    return {'rondas': rondas, 'tercer': _info_llave(terc, 1) if terc else None,
            'campeon': final.ganador if final else None}


def _info_llave(ll, numero):
    partidos = sorted(ll.partidos.all(), key=lambda p: p.numero_fecha)
    ga = gb = 0
    pen_a = pen_b = 0
    jugado = False
    for p in partidos:
        if p.estado in ESTADOS_CERRADOS or p.estado in ('VIVO', 'ACTA'):
            jugado = True
            if p.equipo_local_id == ll.equipo_a_id:
                ga += p.goles_local; gb += p.goles_visita
                if p.hubo_penales:
                    pen_a += p.penales_local or 0; pen_b += p.penales_visita or 0
            else:
                ga += p.goles_visita; gb += p.goles_local
                if p.hubo_penales:
                    pen_a += p.penales_visita or 0; pen_b += p.penales_local or 0
    return {
        'llave': ll, 'numero': numero,
        'a': ll.equipo_a, 'b': ll.equipo_b,
        'etiqueta_a': ll.etiqueta_a, 'etiqueta_b': ll.etiqueta_b,
        'goles_a': ga if jugado else None, 'goles_b': gb if jugado else None,
        'penales': (pen_a, pen_b) if (pen_a or pen_b) else None,
        'ganador_id': ll.ganador_id, 'partidos': partidos, 'bye': ll.es_bye,
    }
