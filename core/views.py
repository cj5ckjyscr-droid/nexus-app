from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse, HttpResponse, Http404
from django.db.models import Count, Q, Sum, F
from django.template.loader import get_template
from django.db import transaction, IntegrityError
from xhtml2pdf import pisa 
from django.contrib.auth.models import User
from django.utils import timezone  
from datetime import datetime, time, timedelta, date
from django.core.exceptions import ValidationError
from urllib.parse import quote
import os
import urllib.parse
from decimal import Decimal
from django.contrib.auth import login
from django.core.mail import send_mail
from django.conf import settings
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST

# Formularios
from .forms import (
    RegistroUsuarioForm, TorneoForm, EquipoForm, JugadorForm, 
    ProgramarPartidoForm, PagoForm, RegistroPublicoForm,
    EquipoSolicitudForm, FotoGaleriaForm,
    TraspasoJugadorForm, AsignarCuposForm, SancionListaNegraForm, 
    SancionManualForm, ConfiguracionForm,
    ComplejoDeportivoForm, PlanSuscripcionForm, PagoSaaSForm
)

# Modelos SaaS (De .models) - Añadido RolComplejo
from .models import (
    Configuracion, Torneo, Equipo, Jugador, Partido, 
    DetallePartido, Pago, Perfil, Sancion, FotoGaleria, 
    AbonoSancion, ComplejoDeportivo, PlanSuscripcion, Categoria,
    PagoSuscripcionSaaS, RolComplejo, Llave, MovimientoFinanciero, EdicionPartido
)

from .utils import validar_cedula_ecuador, consultar_sri
from .services.pruebas import crear_entorno_prueba, eliminar_entorno_prueba, obtener_equipo_simulado, NOMBRE_PLAN_DEMO
from .services.google_auth import verificar_token_google, obtener_o_crear_usuario_de_google, GoogleTokenInvalido
from .services import campeonato as motor
from .services.finanzas import registrar_movimiento
from .imagenes import comprimir_firma

# =========================================================
# --- FUNCIONES DE CONTROL DE ACCESO (PERMISOS CONTEXTUALES) ---
# =========================================================

def es_organizador(user):
    if not user.is_authenticated: return False
    if user.is_superuser: return True
    return ComplejoDeportivo.objects.filter(organizador=user, activo=True).exists() or \
           RolComplejo.objects.filter(usuario=user, rol='ORG').exists()

def es_vocal_o_admin(user):
    if not user.is_authenticated: return False
    if user.is_superuser: return True
    return ComplejoDeportivo.objects.filter(organizador=user, activo=True).exists() or \
           RolComplejo.objects.filter(usuario=user, rol__in=['ORG', 'VOC']).exists()

def es_dirigente_o_admin(user):
    if not user.is_authenticated: return False
    if user.is_superuser: return True
    return ComplejoDeportivo.objects.filter(organizador=user, activo=True).exists() or \
           RolComplejo.objects.filter(usuario=user, rol__in=['ORG', 'DIR']).exists()

def obtener_mi_complejo(user):
    """Obtiene la cancha donde el usuario es DUEÑO o STAFF(ORG)"""
    if not user.is_authenticated: return None
    c = ComplejoDeportivo.objects.filter(organizador=user, activo=True).first()
    if c: return c
    rc = RolComplejo.objects.filter(usuario=user, rol='ORG').first()
    if rc: return rc.complejo
    return None

def rol_en_complejo(user, complejo):
    """Rol del usuario DENTRO de una cancha concreta (cada cancha es
    independiente: ser vocal en una no da permisos en otra)."""
    if not user.is_authenticated or complejo is None:
        return None
    if user.is_superuser or complejo.organizador_id == user.id:
        return 'ORG'
    rc = RolComplejo.objects.filter(usuario=user, complejo=complejo).only('rol').first()
    if rc:
        return rc.rol
    if Equipo.objects.filter(dirigente=user, torneo__complejo=complejo).exists():
        return 'DIR'
    return None


PRIORIDAD_ROL = {'FAN': 0, 'DIR': 1, 'VOC': 2, 'ORG': 3}


def asegurar_rol_dirigente(user, complejo):
    """Al tener un equipo, el usuario pasa a Dirigente en ESA cancha, pero
    nunca se le baja un rol superior (un Vocal o el Staff no pierden su rol)."""
    rc, creado = RolComplejo.objects.get_or_create(usuario=user, complejo=complejo, defaults={'rol': 'DIR'})
    if not creado and PRIORIDAD_ROL.get(rc.rol, 0) < PRIORIDAD_ROL['DIR']:
        rc.rol = 'DIR'
        rc.save(update_fields=['rol'])
    return rc


def registrar_anulaciones(sanciones, usuario, motivo, origen='FINANZAS'):
    """Deja en la bitácora cada deuda que se borra (sin FKs a lo que se va a
    eliminar, para que el borrado en cascada no falle)."""
    for s_ in sanciones:
        MovimientoFinanciero.objects.create(
            complejo=s_.torneo.complejo, tipo='ANULACION', monto=s_.monto,
            usuario=usuario if usuario.is_authenticated else None,
            equipo_nombre=s_.equipo.nombre, sancion_ref=s_.id, origen=origen,
            descripcion=f"{motivo}: {s_.descripcion} (pagado ${s_.monto_pagado})"[:200],
        )


def limite_jugadores_alcanzado(complejo):
    """Cupo de jugadores inscritos del plan SaaS de esta cancha, independiente
    de cualquier otra cancha del sistema."""
    limite = complejo.plan.max_jugadores if complejo.plan else 1
    actuales = Jugador.objects.filter(equipo__torneo__complejo=complejo).count()
    return actuales >= limite

def obtener_rol_principal(user):
    """Infiere el rol principal del usuario para pintar la interfaz adecuadamente"""
    if user.is_superuser: return 'ORG'
    if ComplejoDeportivo.objects.filter(organizador=user).exists(): return 'ORG'
    rc = RolComplejo.objects.filter(usuario=user).order_by('id').first() # El primer rol que tenga
    if rc: return rc.rol
    # Fallback por si migraron datos y tiene equipo pero no RolComplejo
    if Equipo.objects.filter(dirigente=user).exists(): return 'DIR'
    return 'FAN'

# =========================================================
# 1. VISTAS GENERALES Y DE GESTIÓN (CRUD)
# =========================================================

@login_required
def dashboard(request):
    if request.user.is_superuser:
        return redirect('dashboard_saas')

    ctx = {}
    ahora = timezone.now()
    
    if request.user.is_authenticated:
        rol = obtener_rol_principal(request.user)
        equipo_simulado = obtener_equipo_simulado(request)
        if equipo_simulado:
            rol = 'DIR'
        ctx['mi_rol_principal'] = rol # Pasamos el rol a la plantilla

        if rol == 'ORG':
            # 🔥 MAGIA SAAS: Buscamos la cancha exclusiva de este organizador
            mi_complejo = obtener_mi_complejo(request.user)
            
            if not mi_complejo:
                messages.error(request, "Tu complejo está suspendido por falta de pago o aún no tienes uno asignado.")
                return redirect('landing_principal')
            
            ctx['mi_complejo'] = mi_complejo
            
            # 🔥 FILTRAMOS ABSOLUTAMENTE TODO SOLO PARA SU CANCHA
            ctx['torneos'] = Torneo.objects.filter(complejo=mi_complejo, activo=True).order_by('-id')
            
            partidos_qs = Partido.objects.filter(
                torneo__complejo=mi_complejo,
                estado='PROG',
                fecha_hora__gte=ahora
            ).select_related('equipo_local', 'equipo_visita', 'torneo').order_by('fecha_hora')[:10]

            for p in partidos_qs:
                p.fecha_local = timezone.localtime(p.fecha_hora).date()
            ctx['proximos_partidos'] = partidos_qs

            deudas_pendientes = Sancion.objects.filter(torneo__complejo=mi_complejo, pagada=False).exclude(descripcion__icontains='Inscripci')
            total = deudas_pendientes.aggregate(Sum('monto'))['monto__sum'] or 0
            
            inscripciones_pendientes = Sancion.objects.filter(torneo__complejo=mi_complejo, pagada=False, descripcion__icontains='Inscripci').aggregate(Sum('monto'))['monto__sum'] or 0
            abonos_inscripciones = Sancion.objects.filter(torneo__complejo=mi_complejo, pagada=False, descripcion__icontains='Inscripci').aggregate(Sum('monto_pagado'))['monto_pagado__sum'] or 0
            saldo_inscripciones = inscripciones_pendientes - abonos_inscripciones
            
            ctx['deudas'] = deudas_pendientes
            ctx['total_por_cobrar'] = total + saldo_inscripciones 
            ctx['equipos_pendientes'] = Equipo.objects.filter(torneo__complejo=mi_complejo, estado_inscripcion='PENDIENTE')

        elif rol == 'DIR':
            mis_equipos = Equipo.objects.filter(dirigente=request.user).exclude(estado_inscripcion='RECHAZADO')
            if mis_equipos.exists():
                ctx['mi_equipo'] = equipo_simulado or mis_equipos.first() 
                mis_deudas = Sancion.objects.filter(equipo__in=mis_equipos, pagada=False).exclude(descripcion__icontains='Inscripci').select_related('partido', 'jugador').order_by('-partido__fecha_hora', '-id')
                
                if mis_deudas.exists():
                    total_deuda = mis_deudas.aggregate(Sum('monto'))['monto__sum'] or 0
                    ctx['tengo_deudas'] = True
                    ctx['monto_deuda'] = total_deuda
                    ctx['lista_mis_deudas'] = mis_deudas
            else:
                ctx['mi_equipo'] = None

        elif rol == 'VOC':
            # Filtra solo los partidos de las canchas donde este usuario es Vocal
            mis_canchas_vocal = RolComplejo.objects.filter(usuario=request.user, rol='VOC').values_list('complejo_id', flat=True)
            ctx['partidos_vocal'] = Partido.objects.filter(torneo__complejo_id__in=mis_canchas_vocal, estado__in=['PROG', 'VIVO']).select_related('equipo_local', 'equipo_visita', 'torneo').order_by('fecha_hora')[:10]
            ctx['actas_pendientes'] = Partido.objects.filter(torneo__complejo_id__in=mis_canchas_vocal, estado='ACTA').select_related('equipo_local', 'equipo_visita', 'torneo').order_by('fecha_hora')[:10]

        if rol in ('FAN', 'DIR', 'VOC'):
            mis_canchas_ids = list(RolComplejo.objects.filter(usuario=request.user).values_list('complejo_id', flat=True))
            ctx['mis_canchas'] = ComplejoDeportivo.objects.filter(id__in=mis_canchas_ids, activo=True).order_by('nombre')
            ctx['canchas_para_unirse'] = ComplejoDeportivo.objects.filter(
                activo=True, es_demo=False).exclude(id__in=mis_canchas_ids).order_by('nombre')[:30]

    return render(request, 'core/dashboard.html', ctx)

@login_required
@user_passes_test(es_organizador)
def crear_usuario(request):
    mi_complejo = obtener_mi_complejo(request.user)
    if request.method == 'POST':
        form = RegistroUsuarioForm(request.POST)
        if form.is_valid():
            u = form.save()
            # 🔥 MULTI-TENANCY: Se crea el rol SOLO para la cancha actual
            RolComplejo.objects.create(
                usuario=u,
                complejo=mi_complejo,
                rol=form.cleaned_data['rol']
            )
            # Creamos su perfil global base
            perfil, _ = Perfil.objects.get_or_create(usuario=u)
            if form.cleaned_data.get('cedula'):
                perfil.cedula = form.cleaned_data['cedula']
                perfil.save()
            messages.success(request, f'Usuario "{u.username}" creado y asignado a {mi_complejo.nombre}.')
            return redirect('gestionar_usuarios')
    else:
        form = RegistroUsuarioForm()
    return render(request, 'core/crear_usuario.html', {'form': form})

@login_required
@user_passes_test(es_organizador)
def gestionar_usuarios(request):
    mi_complejo = obtener_mi_complejo(request.user)
    # Filtramos SOLO los usuarios que pertenecen a ESTA cancha
    roles_cancha = RolComplejo.objects.filter(complejo=mi_complejo).exclude(usuario=request.user).select_related('usuario').order_by('-id')

    if request.method == 'POST':
        rol_cancha_id = request.POST.get('rol_cancha_id')
        nuevo_rol = request.POST.get('nuevo_rol')
        if rol_cancha_id and request.POST.get('quitar') == '1':
            rc = get_object_or_404(RolComplejo, id=rol_cancha_id, complejo=mi_complejo)
            if Equipo.objects.filter(dirigente=rc.usuario, torneo__complejo=mi_complejo, torneo__activo=True).exclude(estado_inscripcion='RECHAZADO').exists():
                messages.error(request, f'⛔ {rc.usuario.username} dirige un equipo activo en esta cancha. Primero retira o reasigna el equipo.')
            else:
                rc.delete()
                messages.warning(request, f'{rc.usuario.username} ya no pertenece a esta cancha.')
            return redirect('gestionar_usuarios')
        if rol_cancha_id and nuevo_rol in dict(RolComplejo.ROLES):
            rc = get_object_or_404(RolComplejo, id=rol_cancha_id, complejo=mi_complejo)
            rc.rol = nuevo_rol
            rc.save()
            messages.success(request, f'Rol de {rc.usuario.username} actualizado a {rc.get_rol_display()} en esta cancha.')
            return redirect('gestionar_usuarios')

    query = request.GET.get('q', '')
    if query:
        roles_cancha = roles_cancha.filter(
            Q(usuario__first_name__icontains=query) |
            Q(usuario__last_name__icontains=query) |
            Q(usuario__username__icontains=query) |
            Q(usuario__email__icontains=query)
        )

    filtro_rol = request.GET.get('rol', '')
    if filtro_rol in dict(RolComplejo.ROLES):
        roles_cancha = roles_cancha.filter(rol=filtro_rol)

    paginator = Paginator(roles_cancha, 15)
    perfiles = paginator.get_page(request.GET.get('page'))

    # Equipos que dirige cada usuario EN ESTA cancha (una sola consulta)
    ids_pagina = [rc.usuario_id for rc in perfiles]
    equipos_por_usuario = {}
    for eq in Equipo.objects.filter(dirigente_id__in=ids_pagina, torneo__complejo=mi_complejo).exclude(
            estado_inscripcion='RECHAZADO').select_related('torneo', 'torneo__categoria').order_by('-torneo__activo', 'nombre'):
        equipos_por_usuario.setdefault(eq.dirigente_id, []).append(eq)
    for rc in perfiles:
        rc.equipos_dirigidos = equipos_por_usuario.get(rc.usuario_id, [])

    conteo_roles = dict(RolComplejo.objects.filter(complejo=mi_complejo).exclude(usuario=request.user)
                        .values_list('rol').annotate(n=Count('id')).values_list('rol', 'n'))

    return render(request, 'core/gestionar_usuarios.html', {
        'perfiles': perfiles, 'query': query, 'filtro_rol': filtro_rol,
        'roles': [(v, n, conteo_roles.get(v, 0)) for v, n in RolComplejo.ROLES], 'mi_complejo': mi_complejo,
    })


@login_required
@require_POST
def unirse_cancha(request, slug_complejo):
    """Un usuario se registra como AFICIONADO en una cancha. Así el
    administrador lo ve en "Usuarios" y puede hacerlo Vocal, sin tener que
    inventar un equipo."""
    complejo = get_object_or_404(ComplejoDeportivo, slug=slug_complejo, activo=True, es_demo=False)
    rc, creado = RolComplejo.objects.get_or_create(usuario=request.user, complejo=complejo, defaults={'rol': 'FAN'})
    if creado:
        messages.success(request, f"✅ Te uniste a {complejo.nombre} como Aficionado. Si vas a ser vocal, pide al administrador que cambie tu rol.")
    else:
        messages.info(request, f"Ya perteneces a {complejo.nombre} como {rc.get_rol_display()}.")
    return redirect('dashboard')

@login_required
@user_passes_test(es_organizador)
def gestionar_torneos(request):
    mi_complejo = obtener_mi_complejo(request.user)
    
    # 1. LEER LÍMITES DEL PLAN SAAS (Solo contamos torneos ACTIVOS)
    limite_torneos = mi_complejo.plan.max_torneos if mi_complejo.plan else 1
    torneos_activos_count = Torneo.objects.filter(complejo=mi_complejo, activo=True).count()
    puede_crear = torneos_activos_count < limite_torneos

    torneos_list = Torneo.objects.filter(complejo=mi_complejo).select_related('categoria').order_by('categoria__nombre', '-fecha_inicio')
    
    paginator = Paginator(torneos_list, 10) 
    page = request.GET.get('page')
    try:
        torneos = paginator.page(page)
    except PageNotAnInteger:
        torneos = paginator.page(1)
    except EmptyPage:
        torneos = paginator.page(paginator.num_pages)
    
    if request.method == 'POST':
        # 2. APLICAR CANDADO AL GUARDAR
        if not puede_crear:
            messages.error(request, f"⛔ Límite alcanzado: Tu plan solo permite {limite_torneos} torneos activos simultáneamente. Finaliza uno viejo o mejora tu plan.")
            return redirect('gestionar_torneos')

        form = TorneoForm(request.POST)
        if form.is_valid():
            t = form.save(commit=False)
            t.organizador = request.user
            t.complejo = mi_complejo
            t.save()
            messages.success(request, f'✅ Torneo "{t.nombre}" creado.')
            return redirect('gestionar_torneos')
        else:
            for campo, errores in form.errors.items():
                for error in errores:
                    messages.error(request, f"❌ Error en {campo}: {error}")
    else:
        form = TorneoForm()
    
    form.fields['categoria'].queryset = Categoria.objects.filter(complejo=mi_complejo).order_by('nombre')
    
    return render(request, 'core/gestionar_torneos.html', {
        'form': form, 
        'torneos': torneos,
        'puede_crear': puede_crear,
        'limite': limite_torneos,
        'actuales': torneos_activos_count
    })

@login_required
@user_passes_test(es_organizador)
def editar_torneo(request, torneo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    torneo = get_object_or_404(Torneo, id=torneo_id, complejo=mi_complejo)
    if request.method == 'POST':
        form = TorneoForm(request.POST, instance=torneo)
        if form.is_valid():
            form.save()
            messages.success(request, f'✅ Torneo "{torneo.nombre}" actualizado correctamente.')
            return redirect('gestionar_torneos')
        else:
            for campo, errores in form.errors.items():
                for error in errores:
                    messages.error(request, f"❌ Error en {campo}: {error}")
    else:
        form = TorneoForm(instance=torneo)
    
    # 🔥 AISLAMIENTO: Restringe la lista en modo edición
    form.fields['categoria'].queryset = Categoria.objects.filter(complejo=mi_complejo).order_by('nombre')
        
    return render(request, 'core/gestionar_torneos.html', {
        'form': form, 'torneos': Torneo.objects.filter(complejo=mi_complejo).order_by('-id'), 'editando': True, 'torneo_edit': torneo
    })

@login_required
@user_passes_test(es_organizador)
@require_POST
def eliminar_torneo(request, torneo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    torneo = get_object_or_404(Torneo, id=torneo_id, complejo=mi_complejo)
    nombre_torneo = torneo.nombre
    with transaction.atomic():
        registrar_anulaciones(Sancion.objects.filter(torneo=torneo).select_related('torneo__complejo', 'equipo'), request.user, f"Torneo eliminado ({nombre_torneo})")
        torneo.delete()
    messages.success(request, f'🗑️ El torneo "{nombre_torneo}" ha sido eliminado completamente.')
    return redirect('gestionar_torneos')

@login_required
@user_passes_test(es_organizador)
@require_POST
def cambiar_estado_torneo(request, torneo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    torneo = get_object_or_404(Torneo, id=torneo_id, complejo=mi_complejo)

    if torneo.activo:
        torneo.activo = False
        torneo.inscripcion_abierta = False
        torneo.save()
        messages.success(request, f"El torneo '{torneo.nombre}' ha sido FINALIZADO y movido al historial.")
    else:
        limite_torneos = mi_complejo.plan.max_torneos if mi_complejo.plan else 1
        torneos_activos_count = Torneo.objects.filter(complejo=mi_complejo, activo=True).count()
        if torneos_activos_count >= limite_torneos:
            messages.error(request, f"⛔ Límite alcanzado: Tu plan solo permite {limite_torneos} torneos activos simultáneamente. Finaliza uno viejo o mejora tu plan.")
        else:
            torneo.activo = True
            torneo.save()
            messages.success(request, f"El torneo '{torneo.nombre}' ha sido REABIERTO.")

    return redirect('gestionar_torneos')

@login_required
@user_passes_test(es_organizador)
def gestionar_equipos(request):
    mi_complejo = obtener_mi_complejo(request.user)
    
    # 🔥 OPTIMIZACIÓN DE DB
    ver_retirados = request.GET.get('ver') == 'retirados'
    equipos_list = Equipo.objects.filter(torneo__complejo=mi_complejo, torneo__activo=True).select_related(
        'torneo', 'torneo__categoria', 'dirigente'
    ).order_by('torneo__categoria__nombre', 'torneo__nombre', 'nombre')
    # Los equipos RECHAZADOS / retirados no participan: no se mezclan con los
    # que sí juegan (se pueden consultar aparte con ?ver=retirados).
    retirados_count = equipos_list.filter(estado_inscripcion='RECHAZADO').count()
    if ver_retirados:
        equipos_list = equipos_list.filter(estado_inscripcion='RECHAZADO')
    else:
        equipos_list = equipos_list.exclude(estado_inscripcion='RECHAZADO')
    
    # --- PAGINACIÓN DE EQUIPOS ---
    paginator = Paginator(equipos_list, 10) # 10 Equipos por página
    page = request.GET.get('page')
    try:
        equipos = paginator.page(page)
    except PageNotAnInteger:
        equipos = paginator.page(1)
    except EmptyPage:
        equipos = paginator.page(paginator.num_pages)
        
    # 🔥 AISLAMIENTO: estos querysets se fijan ANTES de validar el POST —
    # si se fijan después de is_valid() (como estaba antes para "torneo"),
    # la validación real corre sin restricción y un POST manipulado con el
    # ID de un torneo/usuario de OTRO complejo pasaría igual. Solo usuarios
    # que ya pertenecen a ESTE complejo (o su organizador) pueden ser
    # elegidos como dirigente — nunca cualquier usuario del sistema, que es
    # compartido entre varios complejos.
    torneos_del_complejo = Torneo.objects.filter(complejo=mi_complejo, activo=True).order_by('categoria__nombre', 'nombre')
    usuarios_del_complejo = User.objects.filter(
        Q(roles_cancha__complejo=mi_complejo) | Q(id=mi_complejo.organizador_id)
    ).distinct().order_by('username')

    if request.method == 'POST':
        form = EquipoForm(request.POST, request.FILES)
        form.fields['torneo'].queryset = torneos_del_complejo
        form.fields['dirigente'].queryset = usuarios_del_complejo
        if form.is_valid() and form.cleaned_data['torneo'].campeonato_iniciado and form.cleaned_data['estado_inscripcion'] == 'APROBADO':
            messages.error(request, f"⛔ El campeonato «{form.cleaned_data['torneo'].nombre}» ya empezó: no se pueden sumar equipos aprobados (alteraría el fixture).")
            return redirect('gestionar_equipos')
        if form.is_valid():
            nuevo_equipo = form.save()
            # 🔥 El dirigente pasa a rol DIR en esta cancha (si era FAN), sin
            # bajarle el rol si ya era Vocal/Staff.
            asegurar_rol_dirigente(nuevo_equipo.dirigente, mi_complejo)
            if not nuevo_equipo.torneo.cobro_por_jugador:
                costo_inscripcion = getattr(nuevo_equipo.torneo, 'costo_inscripcion', Decimal('0.00'))
                Sancion.objects.create(
                    torneo=nuevo_equipo.torneo, equipo=nuevo_equipo, tipo='ADMIN',
                    monto=costo_inscripcion, monto_pagado=Decimal('0.00'),
                    descripcion=f"Inscripción al Torneo {nuevo_equipo.torneo.nombre}", pagada=False
                )
            messages.success(request, '¡Equipo inscrito correctamente!')
            return redirect('gestionar_equipos')
    else:
        form = EquipoForm()
        form.fields['torneo'].queryset = torneos_del_complejo
        form.fields['dirigente'].queryset = usuarios_del_complejo

    return render(request, 'core/gestionar_equipos.html', {
        'form': form, 'equipos': equipos, 'sin_usuarios_disponibles': not usuarios_del_complejo.exists(),
        'ver_retirados': ver_retirados, 'retirados_count': retirados_count,
    })

@login_required
@user_passes_test(es_organizador)
def editar_equipo(request, equipo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    equipo = get_object_or_404(Equipo, id=equipo_id, torneo__complejo=mi_complejo)

    # 🔥 AISLAMIENTO: fijados ANTES de is_valid() — ver nota en gestionar_equipos.
    torneos_del_complejo = Torneo.objects.filter(complejo=mi_complejo, activo=True).order_by('categoria__nombre', 'nombre')
    usuarios_del_complejo = User.objects.filter(
        Q(roles_cancha__complejo=mi_complejo) | Q(id=mi_complejo.organizador_id)
    ).distinct().order_by('username')

    if request.method == 'POST':
        estado_previo, torneo_previo = equipo.estado_inscripcion, equipo.torneo_id
        form = EquipoForm(request.POST, request.FILES, instance=equipo)
        form.fields['torneo'].queryset = torneos_del_complejo
        form.fields['dirigente'].queryset = usuarios_del_complejo
        if form.is_valid():
            t = form.cleaned_data['torneo']
            entra_nuevo = form.cleaned_data['estado_inscripcion'] == 'APROBADO' and (estado_previo != 'APROBADO' or torneo_previo != t.id)
            if t.campeonato_iniciado and entra_nuevo:
                messages.error(request, f"⛔ El campeonato «{t.nombre}» ya empezó: no se puede aprobar ni mover equipos a él.")
                return redirect('editar_equipo', equipo_id=equipo.id)
            if torneo_previo != t.id and Partido.objects.filter(Q(equipo_local=equipo) | Q(equipo_visita=equipo)).exists():
                messages.error(request, "⛔ Este equipo ya tiene partidos en su torneo: no se puede cambiar de torneo.")
                return redirect('editar_equipo', equipo_id=equipo.id)
        if form.is_valid():
            form.save()
            asegurar_rol_dirigente(equipo.dirigente, mi_complejo)
            messages.success(request, 'Equipo actualizado correctamente.')
            return redirect('gestionar_equipos')
    else:
        form = EquipoForm(instance=equipo)
        form.fields['torneo'].queryset = torneos_del_complejo
        form.fields['dirigente'].queryset = usuarios_del_complejo

    equipos = Equipo.objects.filter(torneo__complejo=mi_complejo, torneo__activo=True).exclude(
        estado_inscripcion='RECHAZADO').select_related(
        'torneo', 'torneo__categoria', 'dirigente'
    ).order_by('torneo__categoria__nombre', 'torneo__nombre', 'nombre')

    return render(request, 'core/gestionar_equipos.html', {'form': form, 'equipos': equipos, 'editando': True})

@login_required
@user_passes_test(es_organizador)
@require_POST
def eliminar_equipo(request, equipo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    equipo = get_object_or_404(Equipo, id=equipo_id, torneo__complejo=mi_complejo)
    if Partido.objects.filter(Q(equipo_local=equipo) | Q(equipo_visita=equipo)).exclude(estado='PROG').exists():
        messages.error(request, f'⛔ {equipo.nombre} ya jugó partidos. Para sacarlo del torneo cambia su estado a "Rechazado" en vez de borrarlo (así no se pierde el historial).')
        return redirect('gestionar_equipos')
    with transaction.atomic():
        registrar_anulaciones(equipo.sanciones.select_related('torneo__complejo', 'equipo'), request.user, f"Equipo eliminado ({equipo.nombre})")
        equipo.delete()
    messages.success(request, 'Equipo eliminado. Los jugadores quedaron libres.')
    return redirect('gestionar_equipos')

# =========================================================
# ✨ LÓGICA BLINDADA: GESTIÓN DE JUGADORES Y CUPOS ✨
# =========================================================

@login_required
def gestionar_jugadores(request):
    rol_principal = obtener_rol_principal(request.user)
    equipo_simulado = obtener_equipo_simulado(request)
    if equipo_simulado:
        rol_principal = 'DIR'
    puede_fichar = True
    query = request.GET.get('q', '').strip()

    if rol_principal == 'DIR':
        mis_equipos = Equipo.objects.filter(dirigente=request.user).exclude(estado_inscripcion='RECHAZADO')
        if not mis_equipos.exists():
            messages.error(request, 'No tienes un equipo inscrito. Inscríbete a un torneo primero.')
            return redirect('ver_torneos_activos')

        equipos_activos = mis_equipos.filter(torneo__activo=True).order_by('torneo__categoria__nombre', 'torneo__nombre', 'nombre')
        equipo_id = request.GET.get('equipo') or (equipo_simulado.id if equipo_simulado else None)
        # 🔥 Si el ID pedido no es un equipo propio (ajeno o inexistente),
        # nunca se revienta: cae de vuelta al equipo activo por defecto.
        mi_equipo = (mis_equipos.filter(id=equipo_id).first() if equipo_id else None) or equipos_activos.first() or mis_equipos.first()

        mi_complejo = mi_equipo.torneo.complejo # 🔥 AISLAMIENTO AÑADIDO

        jugadores = Jugador.objects.filter(equipo=mi_equipo).order_by('dorsal')
        if query:
            jugadores = jugadores.filter(Q(nombres__icontains=query) | Q(cedula__icontains=query))
        equipo_seleccionado = mi_equipo.id
        
        if mi_equipo.esta_sancionado:
            puede_fichar = False
            messages.error(request, f'⛔ TU EQUIPO ESTÁ SANCIONADO HASTA {mi_equipo.sancionado_hasta}.')
        else:
            puede_fichar = mi_equipo.puede_fichar
        
        if request.method == 'POST':
            if not puede_fichar:
                messages.error(request, '⛔ Fichajes cerrados o límite de jugadores alcanzado. No se permiten más inscripciones.')
                return redirect(f"{request.path}?equipo={mi_equipo.id}")

            # 🔒 Segundo candado de seguridad: si el equipo tiene cupos asignados,
            # nunca se pasa de ese tope, sin importar el flag cobro_por_jugador.
            if mi_equipo.cupos_pagados > 0 and mi_equipo.cupos_disponibles <= 0:
                messages.error(request, f'⛔ LÍMITE ALCANZADO: El equipo "{mi_equipo.nombre}" ya tiene el máximo de {mi_equipo.cupos_pagados} jugadores permitidos.')
                return redirect(f"{request.path}?equipo={mi_equipo.id}")

            form = JugadorForm(request.POST, request.FILES, es_admin=False)
            form.fields['equipo'].queryset = mis_equipos

            if form.is_valid():
                cedula_ingresada = form.cleaned_data.get('cedula')

                # 🔥 AISLAMIENTO: Solo busca si el jugador está en otro equipo de ESTA cancha
                jugadores_activos_bd = Jugador.objects.filter(
                    cedula=cedula_ingresada, 
                    equipo__torneo__activo=True,
                    equipo__torneo__complejo=mi_complejo 
                )
                
                misma_categoria = None
                if mi_equipo.torneo.categoria:
                    misma_categoria = jugadores_activos_bd.filter(equipo__torneo__categoria=mi_equipo.torneo.categoria).first()
                else:
                    misma_categoria = jugadores_activos_bd.filter(equipo__torneo=mi_equipo.torneo).first()

                if misma_categoria:
                    if misma_categoria.equipo != mi_equipo:
                        messages.error(request, f"⛔ ¡ALERTA! Este jugador ya compite en el equipo '{misma_categoria.equipo.nombre}' en esta misma categoría.")
                        return redirect(f"{request.path}?equipo={mi_equipo.id}")
                    else:
                        misma_categoria.nombres = form.cleaned_data.get('nombres')
                        misma_categoria.dorsal = form.cleaned_data.get('dorsal')
                        if form.cleaned_data.get('foto'):
                            misma_categoria.foto = form.cleaned_data.get('foto')
                        misma_categoria.save()
                        messages.success(request, f'¡Datos de {misma_categoria.nombres} actualizados!')
                elif limite_jugadores_alcanzado(mi_complejo):
                    limite = mi_complejo.plan.max_jugadores if mi_complejo.plan else 1
                    messages.error(request, f"⛔ Límite alcanzado: Tu plan solo permite {limite} jugadores inscritos. Mejora tu plan para fichar más.")
                    return redirect(f"{request.path}?equipo={mi_equipo.id}")
                else:
                    # 🔥 AISLAMIENTO: Solo copia la foto si ya jugó en ESTA cancha antes
                    jugador_historial = Jugador.objects.filter(cedula=cedula_ingresada, equipo__torneo__complejo=mi_complejo).last()
                    nuevo_jugador = form.save(commit=False)
                    nuevo_jugador.equipo = mi_equipo

                    if jugador_historial:
                        if not form.cleaned_data.get('foto') and jugador_historial.foto:
                            nuevo_jugador.foto = jugador_historial.foto
                        
                        nuevo_jugador.rojas_directas_acumuladas = 0
                        nuevo_jugador.partidos_suspension = 0
                        nuevo_jugador.expulsado_torneo = False
                        nuevo_jugador.sancionado_hasta = None

                    nuevo_jugador.save()
                    
                    if jugador_historial:
                        messages.success(request, f'¡{nuevo_jugador.nombres} fichado! (Ahora compite en múltiples categorías)')
                    else:
                        messages.success(request, f'¡{nuevo_jugador.nombres} fichado exitosamente!')
                        
                return redirect(f"{request.path}?equipo={mi_equipo.id}")
            else:
                messages.error(request, "❌ Error en el formulario.")
        else:
            form = JugadorForm(initial={'equipo': mi_equipo}, es_admin=False)
            form.fields['equipo'].queryset = mis_equipos 

    elif rol_principal == 'ORG':
        mi_complejo = obtener_mi_complejo(request.user)
        equipos_activos = Equipo.objects.filter(torneo__complejo=mi_complejo, torneo__activo=True).exclude(
            estado_inscripcion='RECHAZADO').order_by('torneo__categoria__nombre', 'torneo__nombre', 'nombre')
        equipo_id = request.GET.get('equipo')
        mi_equipo = Equipo.objects.filter(id=equipo_id, torneo__complejo=mi_complejo).first() if equipo_id else equipos_activos.first()
            
        if mi_equipo:
            jugadores = Jugador.objects.filter(equipo=mi_equipo).order_by('dorsal')
            if query:
                jugadores = jugadores.filter(Q(nombres__icontains=query) | Q(cedula__icontains=query))
            equipo_seleccionado = mi_equipo.id
        else:
            jugadores = Jugador.objects.none()
            equipo_seleccionado = None
            
        if request.method == 'POST':
            form = JugadorForm(request.POST, request.FILES, es_admin=True)
            # 🔥 AISLAMIENTO: solo equipos de ESTA cancha
            form.fields['equipo'].queryset = equipos_activos
            if form.is_valid():
                cedula_ingresada = form.cleaned_data.get('cedula')
                equipo_destino = form.cleaned_data.get('equipo')

                # 🔒 Segundo candado de seguridad: tope de cupos del equipo destino.
                if equipo_destino and equipo_destino.cupos_pagados > 0 and equipo_destino.cupos_disponibles <= 0:
                    messages.error(request, f'⛔ LÍMITE ALCANZADO: El equipo "{equipo_destino.nombre}" ya tiene el máximo de {equipo_destino.cupos_pagados} jugadores permitidos.')
                    return redirect(f"{request.path}?equipo={equipo_destino.id}")

                # 🔥 AISLAMIENTO
                jugadores_activos_bd = Jugador.objects.filter(
                    cedula=cedula_ingresada,
                    equipo__torneo__activo=True,
                    equipo__torneo__complejo=mi_complejo
                )
                
                misma_categoria = None
                if equipo_destino.torneo.categoria:
                    misma_categoria = jugadores_activos_bd.filter(equipo__torneo__categoria=equipo_destino.torneo.categoria).first()
                else:
                    misma_categoria = jugadores_activos_bd.filter(equipo__torneo=equipo_destino.torneo).first()

                if misma_categoria and misma_categoria.equipo != equipo_destino:
                    messages.error(request, f"⛔ ¡ALERTA! El jugador ya compite en '{misma_categoria.equipo.nombre}' en esa categoría.")
                else:
                    if misma_categoria and misma_categoria.equipo == equipo_destino:
                        misma_categoria.nombres = form.cleaned_data.get('nombres')
                        misma_categoria.dorsal = form.cleaned_data.get('dorsal')
                        if form.cleaned_data.get('foto'):
                            misma_categoria.foto = form.cleaned_data.get('foto')
                        misma_categoria.save()
                        messages.success(request, 'Jugador actualizado.')
                    elif limite_jugadores_alcanzado(mi_complejo):
                        limite = mi_complejo.plan.max_jugadores if mi_complejo.plan else 1
                        messages.error(request, f"⛔ Límite alcanzado: Tu plan solo permite {limite} jugadores inscritos. Mejora tu plan para fichar más.")
                        return redirect(f"{request.path}?equipo={form.cleaned_data['equipo'].id}")
                    else:
                        # 🔥 AISLAMIENTO
                        jugador_historial = Jugador.objects.filter(cedula=cedula_ingresada, equipo__torneo__complejo=mi_complejo).last()
                        nuevo_jugador = form.save(commit=False)
                        if jugador_historial and not nuevo_jugador.foto and jugador_historial.foto:
                            nuevo_jugador.foto = jugador_historial.foto
                        nuevo_jugador.save()
                        messages.success(request, 'Jugador registrado en nueva categoría por Administración.')
                        
                return redirect(f"{request.path}?equipo={form.cleaned_data['equipo'].id}")
            else:
                for campo, errores in form.errors.items():
                    for error in errores:
                        messages.error(request, f"❌ {error}")
        else:
            form = JugadorForm(es_admin=True, initial={'equipo': mi_equipo})
            form.fields['equipo'].queryset = equipos_activos
    else:
        messages.error(request, "Acceso denegado.")
        return redirect('dashboard')

    if mi_equipo and 'jugadores' in locals() and jugadores.exists(): 
        # (Nota interna: en tu código original tenías 'jugadores = Jugador.objects.filter...' arriba. Ahora lo paginaremos)
        paginator = Paginator(jugadores, 12) # 12 jugadores por página para diseño en cuadrícula
        page = request.GET.get('page')
        try:
            jugadores_paginados = paginator.page(page)
        except PageNotAnInteger:
            jugadores_paginados = paginator.page(1)
        except EmptyPage:
            jugadores_paginados = paginator.page(paginator.num_pages)
            
        # Otros equipos del mismo jugador en ESTA cancha: una sola consulta
        cedulas = [j.cedula for j in jugadores_paginados]
        otros = {}
        for o in Jugador.objects.filter(cedula__in=cedulas, equipo__torneo__activo=True,
                                        equipo__torneo__complejo=mi_equipo.torneo.complejo).select_related('equipo', 'equipo__torneo'):
            otros.setdefault(o.cedula, []).append(o)
        for j in jugadores_paginados:
            j.otros_equipos = [o for o in otros.get(j.cedula, []) if o.id != j.id]
    else:
        jugadores_paginados = []

    return render(request, 'core/gestionar_jugadores.html', {
        'form': form, 
        'jugadores': jugadores_paginados, # Enviamos la versión paginada
        'equipos_activos': equipos_activos if rol_principal == 'ORG' else mis_equipos.filter(torneo__activo=True).order_by('torneo__categoria__nombre', 'torneo__nombre', 'nombre'), 
        'equipo_seleccionado': equipo_seleccionado, 
        'es_dirigente': (rol_principal == 'DIR'),
        'puede_fichar': puede_fichar,
        'equipo_obj': mi_equipo,
        'query': query,
        'es_admin': rol_principal == 'ORG',
    })

@login_required
def editar_jugador(request, jugador_id):
    jugador = get_object_or_404(Jugador, id=jugador_id)
    rol_principal = obtener_rol_principal(request.user)
    
    if rol_principal != 'ORG':
        messages.error(request, "⛔ Solo el Organizador puede editar los datos de un jugador ya inscrito.")
        return redirect(f"/jugadores/?equipo={jugador.equipo.id}")

    mi_complejo = obtener_mi_complejo(request.user)
    if jugador.equipo.torneo.complejo != mi_complejo:
        messages.error(request, "Acceso denegado. Este jugador pertenece a otro complejo.")
        return redirect('dashboard')

    equipos_activos = Equipo.objects.filter(torneo__complejo=mi_complejo, torneo__activo=True).exclude(
        estado_inscripcion='RECHAZADO').order_by('torneo__categoria__nombre', 'torneo__nombre', 'nombre')
    if request.method == 'POST':
        form = JugadorForm(request.POST, request.FILES, instance=jugador, es_admin=True)
        form.fields['equipo'].queryset = equipos_activos
        if form.is_valid():
            form.save()
            messages.success(request, f'✅ Datos de {jugador.nombres} actualizados correctamente.')
            return redirect(f"/jugadores/?equipo={jugador.equipo.id}")
        else:
            for campo, errores in form.errors.items():
                for error in errores:
                    messages.error(request, f"❌ {error}")
    else:
        form = JugadorForm(instance=jugador, es_admin=True)
        form.fields['equipo'].queryset = equipos_activos

    return render(request, 'core/gestionar_jugadores.html', {
        'form': form, 
        'jugadores': Jugador.objects.filter(equipo=jugador.equipo).order_by('dorsal'), 
        'equipos_activos': equipos_activos, 
        'editando': True, 
        'es_dirigente': False,
        'equipo_seleccionado': jugador.equipo.id,
        'equipo_obj': jugador.equipo, 
        'puede_fichar': True,
        'es_admin': True,
    })

@login_required
@require_POST
def eliminar_jugador(request, jugador_id):
    jugador = get_object_or_404(Jugador, id=jugador_id)
    rol_principal = obtener_rol_principal(request.user)
    
    es_admin = rol_principal == 'ORG' and jugador.equipo.torneo.complejo == obtener_mi_complejo(request.user)
    es_dueno = (rol_principal == 'DIR' and jugador.equipo.dirigente == request.user)

    if not (es_admin or es_dueno):
        messages.error(request, "No tienes permiso para eliminar a este jugador.")
        return redirect('dashboard')

    if jugador.detallepartido_set.exists():
        messages.error(request, f"No se puede eliminar a {jugador.nombres} porque ya tiene registros en partidos jugados.")
        if es_admin: return redirect('admin_gestion_jugadores')
        else: return redirect('gestionar_jugadores')

    nombre = jugador.nombres
    jugador.delete()
    messages.success(request, f'Jugador "{nombre}" eliminado correctamente.')
    if es_admin: return redirect('admin_gestion_jugadores')
    else: return redirect('gestionar_jugadores')


# =========================================================
# ✨ NUEVO: TRASPASOS, CUPOS Y SANCIONES (ORGANIZADOR) ✨
# =========================================================

@login_required
@user_passes_test(es_organizador)
def traspasar_jugador(request, jugador_id):
    jugador = get_object_or_404(Jugador, id=jugador_id)
    mi_complejo = obtener_mi_complejo(request.user)
    
    if jugador.equipo.torneo.complejo != mi_complejo:
        messages.error(request, "Acceso denegado a este complejo.")
        return redirect('dashboard')
        
    if request.method == 'POST':
        form = TraspasoJugadorForm(
            request.POST, 
            torneo_id=jugador.equipo.torneo.id, 
            equipo_actual_id=jugador.equipo.id
        )
        if form.is_valid():
            nuevo_equipo = form.cleaned_data['nuevo_equipo']
            nuevo_dorsal = form.cleaned_data['nuevo_dorsal']
            
            jugador.equipo = nuevo_equipo
            jugador.dorsal = nuevo_dorsal
            jugador.rojas_directas_acumuladas = 0
            jugador.partidos_suspension = 0
            jugador.expulsado_torneo = False
            jugador.sancionado_hasta = None
            jugador.save()
            
            messages.success(request, f'✅ ¡Traspaso Exitoso! {jugador.nombres} pasó a {nuevo_equipo.nombre} (Dorsal {nuevo_dorsal}).')
            return redirect('admin_gestion_jugadores')
    else:
        form = TraspasoJugadorForm(
            torneo_id=jugador.equipo.torneo.id, 
            equipo_actual_id=jugador.equipo.id
        )
        
    return render(request, 'core/traspasar_jugador.html', {'form': form, 'jugador': jugador})

@login_required
@user_passes_test(es_organizador)
def asignar_cupos(request, equipo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    equipo = get_object_or_404(Equipo, id=equipo_id, torneo__complejo=mi_complejo)
    cupos_anteriores = equipo.cupos_pagados

    if request.method == 'POST':
        form = AsignarCuposForm(request.POST, instance=equipo)
        if form.is_valid():
            equipo_actualizado = form.save(commit=False)
            nuevos_cupos = equipo_actualizado.cupos_pagados
            diferencia = nuevos_cupos - cupos_anteriores
            equipo_actualizado.save()
            
            if diferencia > 0 and equipo.torneo.cobro_por_jugador:
                costo_adicional = diferencia * equipo.torneo.costo_inscripcion_jugador
                Sancion.objects.create(
                    torneo=equipo.torneo, equipo=equipo, tipo='ADMIN',
                    monto=costo_adicional, descripcion=f"Ampliación: {diferencia} cupo(s) extra", pagada=False
                )
                messages.success(request, f'✅ Límite ampliado a {nuevos_cupos} cupos. Se generó factura por ${costo_adicional}.')
            elif diferencia < 0:
                messages.warning(request, f'⚠️ Límite corregido y reducido a {nuevos_cupos} cupos. (Revisa Finanzas si necesitas anular cobros incorrectos previos).')
            else:
                messages.info(request, "No se hicieron cambios en el número de cupos.")
                
            return redirect('gestionar_equipos')
    else:
        form = AsignarCuposForm(instance=equipo)
        
    return render(request, 'core/asignar_cupos.html', {'form': form, 'equipo': equipo})

@login_required
@user_passes_test(es_organizador)
def sancionar_equipo(request, equipo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    equipo = get_object_or_404(Equipo, id=equipo_id, torneo__complejo=mi_complejo)
    
    if request.method == 'POST':
        form = SancionListaNegraForm(request.POST, instance=equipo)
        if form.is_valid():
            equipo = form.save()
            if equipo.sancionado_hasta:
                equipo.dirigente.perfil.sancionado_hasta = equipo.sancionado_hasta
                equipo.dirigente.perfil.save()
                Jugador.objects.filter(equipo=equipo).update(sancionado_hasta=equipo.sancionado_hasta)
                messages.error(request, f'🚨 EQUIPO SANCIONADO: {equipo.nombre} ha sido ingresado a la Lista Negra hasta {equipo.sancionado_hasta}.')
            else:
                equipo.dirigente.perfil.sancionado_hasta = None
                equipo.dirigente.perfil.save()
                Jugador.objects.filter(equipo=equipo).update(sancionado_hasta=None)
                messages.success(request, f'✅ Sanción levantada para {equipo.nombre}. Todos los jugadores han sido liberados.')
            return redirect('gestionar_equipos')
    else:
        form = SancionListaNegraForm(instance=equipo)
    return render(request, 'core/sancionar_equipo.html', {'form': form, 'equipo': equipo})

@login_required
@user_passes_test(es_organizador)
@require_POST
def suspender_jugador(request, jugador_id):
    """Sanción manual a un jugador por el administrador de la cancha:
    - 'partidos': suma N partidos de suspensión (sirve también para AUMENTAR
      una sanción que ya tenía),
    - 'reducir': resta partidos (corrección),
    - 'fecha': suspendido hasta una fecha (sanciones graves),
    - 'expulsar': fuera del torneo,
    - 'levantar': quita toda sanción manual."""
    mi_complejo = obtener_mi_complejo(request.user)
    jugador = get_object_or_404(Jugador, id=jugador_id, equipo__torneo__complejo=mi_complejo)
    accion = request.POST.get('accion')
    motivo = (request.POST.get('motivo') or '').strip()[:200]
    volver = request.POST.get('next') or f"/jugadores/?equipo={jugador.equipo_id}"
    if not volver.startswith('/'):
        volver = '/jugadores/'

    if accion in ('partidos', 'reducir'):
        try:
            n = int(request.POST.get('partidos', 0))
        except ValueError:
            n = 0
        if n <= 0 or n > 50:
            messages.error(request, "⛔ Indica un número de partidos entre 1 y 50.")
            return redirect(volver)
        if accion == 'partidos':
            jugador.partidos_suspension = max(0, jugador.partidos_suspension) + n
            texto = f"🚫 {jugador.nombres} suspendido {n} partido(s) más. Total pendiente: {jugador.partidos_suspension}."
        else:
            jugador.partidos_suspension = max(0, jugador.partidos_suspension - n)
            texto = f"✅ Se redujo la suspensión de {jugador.nombres}. Pendiente: {jugador.partidos_suspension}."
    elif accion == 'fecha':
        try:
            hasta = datetime.strptime(request.POST.get('hasta', ''), '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, "⛔ Fecha inválida.")
            return redirect(volver)
        if hasta < timezone.localdate():
            messages.error(request, "⛔ La fecha de la sanción debe ser futura.")
            return redirect(volver)
        jugador.sancionado_hasta = hasta
        texto = f"🚫 {jugador.nombres} suspendido hasta el {hasta:%d/%m/%Y}."
    elif accion == 'expulsar':
        jugador.expulsado_torneo = True
        texto = f"🟥 {jugador.nombres} fue expulsado del torneo."
    elif accion == 'levantar':
        jugador.partidos_suspension = 0
        jugador.sancionado_hasta = None
        jugador.expulsado_torneo = False
        jugador.bloqueado_por_cuota = False
        jugador.rojas_directas_acumuladas = min(jugador.rojas_directas_acumuladas, 2)
        motivo = ''
        texto = f"✅ Se levantaron las sanciones de {jugador.nombres}. Ya puede jugar."
    else:
        messages.error(request, "Acción no válida.")
        return redirect(volver)

    if motivo:
        jugador.motivo_suspension = motivo
    elif accion == 'levantar':
        jugador.motivo_suspension = ''
    jugador.save()
    messages.success(request, texto)
    return redirect(volver)


@login_required
@user_passes_test(es_organizador)
@require_POST
def suspender_por_cuota(request, torneo_id):
    """Igual que en gestion_futbol: bloquea en ESTE torneo a los jugadores que
    no alcanzaron el mínimo de partidos jugados (asistencias registradas)."""
    mi_complejo = obtener_mi_complejo(request.user)
    torneo = get_object_or_404(Torneo, id=torneo_id, complejo=mi_complejo)
    try:
        limite = int(request.POST.get('limite_partidos', 0))
    except ValueError:
        limite = 0
    if limite < 1:
        messages.error(request, "⛔ Indica un mínimo de partidos válido (1 o más).")
        return redirect('reporte_estadisticas', torneo_id=torneo.id)

    jugadores = Jugador.objects.filter(equipo__torneo=torneo, equipo__estado_inscripcion='APROBADO').annotate(
        pj=Count('detallepartido', filter=Q(detallepartido__tipo='ASIS', detallepartido__partido__torneo=torneo))
    )
    ids = [j.id for j in jugadores if j.pj < limite]
    bloqueados = Jugador.objects.filter(id__in=ids, bloqueado_por_cuota=False).update(bloqueado_por_cuota=True)
    messages.success(request, f"¡Control aplicado! Se bloquearon {bloqueados} jugadores por no alcanzar el mínimo de {limite} partidos.")
    return redirect('reporte_estadisticas', torneo_id=torneo.id)


@login_required
@user_passes_test(es_organizador)
@require_POST
def revertir_cuota(request, torneo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    torneo = get_object_or_404(Torneo, id=torneo_id, complejo=mi_complejo)
    liberados = Jugador.objects.filter(equipo__torneo=torneo, bloqueado_por_cuota=True).update(bloqueado_por_cuota=False)
    messages.info(request, f"Reverso exitoso. Se han desbloqueado {liberados} jugadores.")
    return redirect('reporte_estadisticas', torneo_id=torneo.id)


def api_consultar_cedula(request):
    cedula = request.GET.get('cedula', '')
    if not validar_cedula_ecuador(cedula):
        return JsonResponse({'error': 'Cédula inválida o incorrecta.'}, status=400)
    
    nombre = consultar_sri(cedula)
    if nombre: return JsonResponse({'nombre': nombre, 'exito': True})
    else: return JsonResponse({'exito': False, 'mensaje': 'Cédula válida, sin datos públicos.'})

# =========================================================
# 2. CALENDARIO Y PARTIDOS (ACCESO VOCAL Y ADMIN)
# =========================================================
@login_required
@user_passes_test(es_vocal_o_admin)
def programar_partidos(request):
    mis_canchas_ids = list(RolComplejo.objects.filter(usuario=request.user, rol__in=['ORG', 'VOC']).values_list('complejo_id', flat=True))
    mis_canchas_ids += list(ComplejoDeportivo.objects.filter(organizador=request.user).values_list('id', flat=True))
    if request.user.is_superuser:
        torneos = Torneo.objects.filter(activo=True).order_by('-fecha_inicio')
    else:
        torneos = Torneo.objects.filter(activo=True, complejo_id__in=mis_canchas_ids).order_by('-fecha_inicio')
        
    torneo_id_get = request.GET.get('torneo')
    torneo_obj = None
    partidos = []

    if torneo_id_get:
        torneo_obj = get_object_or_404(Torneo, id=torneo_id_get) if str(torneo_id_get).isdigit() else None
        if torneo_obj is None:
            return redirect('programar_partidos')
        if not request.user.is_superuser and torneo_obj.complejo.id not in mis_canchas_ids:
            messages.error(request, "Acceso denegado a este complejo.")
            return redirect('dashboard')
            
        orden_etapas = {e: i for i, (e, _) in enumerate(Partido.ETAPAS)}
        partidos_qs = sorted(
            Partido.objects.filter(torneo=torneo_obj).select_related('equipo_local', 'equipo_visita'),
            key=lambda p: (orden_etapas.get(p.etapa, 99), p.numero_fecha, p.equipo_local.grupo, p.fecha_hora or timezone.now() + timedelta(days=3650), p.id))
            
        partidos_lista = list(partidos_qs)
        total_equipos = Equipo.objects.filter(torneo=torneo_obj, estado_inscripcion='APROBADO').count()
        if total_equipos > 0:
            fechas_ida = total_equipos - 1 if total_equipos % 2 == 0 else total_equipos
            for p in partidos_lista:
                if p.etapa == 'F1' and p.numero_fecha and p.numero_fecha > fechas_ida:
                    p.es_vuelta_visual = True
                else:
                    p.es_vuelta_visual = False
        partidos = partidos_lista

    if request.method == 'POST' and es_organizador(request.user):
        t_post = Torneo.objects.filter(id=request.POST.get('torneo'), complejo_id__in=mis_canchas_ids).first()
        if t_post is None or t_post.formato != 'CLASICO':
            # 🔒 Sin atajos: en las modalidades nuevas los partidos solo los
            # crea "Empezar campeonato" y las llaves avanzan solas.
            messages.error(request, "⛔ Los partidos de este torneo se generan con «Empezar campeonato». No se pueden crear cruces a mano.")
            return redirect(f"{request.path}?torneo={t_post.id}" if t_post else request.path)
        form = ProgramarPartidoForm(request.POST)
        if 'torneo' in form.fields:
            if request.user.is_superuser:
                form.fields['torneo'].queryset = Torneo.objects.filter(activo=True)
            else:
                form.fields['torneo'].queryset = Torneo.objects.filter(activo=True, complejo_id__in=mis_canchas_ids)
            
        if form.is_valid():
            t_form = form.cleaned_data['torneo']
            equipo_local = form.cleaned_data['equipo_local']
            equipo_visita = form.cleaned_data['equipo_visita']
            etapa_seleccionada = form.cleaned_data.get('etapa', 'F1')
            
            if equipo_local == equipo_visita:
                messages.error(request, "⛔ Error: Un equipo no puede jugar contra sí mismo.")
                return redirect(f"{request.path}?torneo={t_form.id}")

            if etapa_seleccionada == 'F1':
                conteo_previo = Partido.objects.filter(
                    torneo=t_form, etapa='F1'
                ).filter(
                    (Q(equipo_local=equipo_local) & Q(equipo_visita=equipo_visita)) |
                    (Q(equipo_local=equipo_visita) & Q(equipo_visita=equipo_local))
                ).count()

                if not t_form.fase1_ida_vuelta and conteo_previo >= 1:
                    messages.error(request, f"⛔ Error: El torneo es SOLO IDA. {equipo_local} y {equipo_visita} ya tienen un partido programado.")
                    return redirect(f"{request.path}?torneo={t_form.id}")
                
                if t_form.fase1_ida_vuelta and conteo_previo >= 2:
                    messages.error(request, f"⛔ Error: Ya se han programado los dos partidos (Ida y Vuelta) permitidos entre estos equipos.")
                    return redirect(f"{request.path}?torneo={t_form.id}")

            if etapa_seleccionada == 'F2':
                if not equipo_local.grupo_fase2 or not equipo_visita.grupo_fase2:
                    messages.error(request, "⛔ Error: Ambos equipos deben tener un grupo asignado (A o B) para la Fase 2.")
                    return redirect(f"{request.path}?torneo={t_form.id}")
                
                if equipo_local.grupo_fase2 != equipo_visita.grupo_fase2:
                    messages.error(request, f"⛔ Regla de Grupos: {equipo_local.nombre} (Grupo {equipo_local.grupo_fase2}) no puede jugar contra {equipo_visita.nombre} (Grupo {equipo_visita.grupo_fase2}).")
                    return redirect(f"{request.path}?torneo={t_form.id}")
            
            if equipo_local.tiene_deudas():
                messages.warning(request, f"⚠️ Aviso: {equipo_local.nombre} tiene deudas pendientes.")
            if equipo_visita.tiene_deudas():
                messages.warning(request, f"⚠️ Aviso: {equipo_visita.nombre} tiene deudas pendientes.")
            
            try:
                with transaction.atomic():
                    partido = form.save()
                messages.success(request, '✅ Partido agendado con éxito.')
                return redirect(f"{request.path}?torneo={t_form.id}")
            
            except ValidationError:
                messages.error(request, '⛔ La cancha ya tiene una reserva externa en ese horario.')
            except Exception as e:
                messages.error(request, f'Error al agendar: {str(e)}')
        else:
            messages.error(request, "Formulario inválido. Revisa los campos.")
            
    else:
        form = ProgramarPartidoForm(initial={'torneo': torneo_id_get})
        if 'torneo' in form.fields:
            if request.user.is_superuser:
                form.fields['torneo'].queryset = Torneo.objects.filter(activo=True).order_by('-fecha_inicio')
            else:
                form.fields['torneo'].queryset = Torneo.objects.filter(activo=True, complejo_id__in=mis_canchas_ids).order_by('-fecha_inicio')
            
        if torneo_obj:
            equipos_aprobados = Equipo.objects.filter(torneo=torneo_obj, estado_inscripcion='APROBADO')
            if 'equipo_local' in form.fields:
                form.fields['equipo_local'].queryset = equipos_aprobados
            if 'equipo_visita' in form.fields:
                form.fields['equipo_visita'].queryset = equipos_aprobados

    ctx_camp = {}
    if torneo_obj:
        ctx_camp = {
            'puede_cerrar_fase': torneo_obj.formato in ('LIGA', 'LIGA_PLAYOFF', 'GRUPOS') and not torneo_obj.fase_regular_cerrada and motor.fase_regular_completa(torneo_obj),
            'equipos_aprobados_count': Equipo.objects.filter(torneo=torneo_obj, estado_inscripcion='APROBADO').count(),
            'es_admin_torneo': rol_en_complejo(request.user, torneo_obj.complejo) == 'ORG',
        }
    return render(request, 'core/programar_partidos.html', {
        'partidos': partidos, 
        'form': form, 
        'torneos': torneos,
        'torneo_actual': int(torneo_id_get) if torneo_id_get and str(torneo_id_get).isdigit() else None,
        'torneo': torneo_obj,
        **ctx_camp,
    })

@login_required
@user_passes_test(es_organizador)
def editar_partido(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    mi_complejo = obtener_mi_complejo(request.user)
    if partido.torneo.complejo != mi_complejo and not request.user.is_superuser:
        return redirect('dashboard')

    # En las modalidades nuevas los cruces los decide el sistema: aquí solo
    # se programa el día, la hora y la cancha (nada de cambiar equipos).
    solo_horario = partido.torneo.formato != 'CLASICO'
    if request.method == 'POST':
        if solo_horario:
            valor = request.POST.get('fecha_hora') or ''
            try:
                partido.fecha_hora = timezone.make_aware(datetime.strptime(valor, '%Y-%m-%dT%H:%M')) if valor else None
            except ValueError:
                messages.error(request, "⛔ Fecha u hora inválida.")
                return redirect('editar_partido', partido_id=partido.id)
            partido.cancha = (request.POST.get('cancha') or partido.cancha)[:100]
            partido.save(update_fields=['fecha_hora', 'cancha'])
            if es_edicion_post_cierre(partido):
                EdicionPartido.objects.create(partido=partido, usuario=request.user,
                    detalle=f"Cambió fecha/cancha: {timezone.localtime(partido.fecha_hora):%d/%m/%Y %H:%M} · {partido.cancha}" if partido.fecha_hora else f"Cambió la cancha: {partido.cancha}")
            messages.success(request, 'Horario del partido actualizado.')
            return redirect(f"/programar/?torneo={partido.torneo.id}")
        estaba_cerrado = es_edicion_post_cierre(partido)
        form = ProgramarPartidoForm(request.POST, instance=partido)
        if form.is_valid():
            form.save()
            if estaba_cerrado and form.changed_data:
                EdicionPartido.objects.create(partido=partido, usuario=request.user,
                    detalle="Editó datos del partido: " + ", ".join(form.fields[c].label or c for c in form.changed_data))
            messages.success(request, 'Datos del partido actualizados.')
            return redirect(f"/programar/?torneo={partido.torneo.id}")
    else:
        form = ProgramarPartidoForm(instance=partido)
    return render(request, 'core/editar_partido.html', {'form': form, 'partido': partido, 'solo_horario': solo_horario})

@login_required
@user_passes_test(es_organizador)
@require_POST
def eliminar_partido(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    mi_complejo = obtener_mi_complejo(request.user)
    if partido.torneo.complejo != mi_complejo and not request.user.is_superuser:
        return redirect('dashboard')
    torneo_id = partido.torneo.id
    if partido.torneo.formato != 'CLASICO':
        messages.error(request, "⛔ En esta modalidad los partidos los genera el sistema y no se pueden borrar sueltos. Si nada se ha jugado puedes reiniciar el campeonato completo.")
        return redirect(f"/programar/?torneo={torneo_id}")
    if partido.estado != 'PROG' or partido.detalles.exists():
        messages.error(request, "⛔ Este partido ya tiene datos registrados. Reinícialo primero si necesitas borrarlo.")
        return redirect(f"/programar/?torneo={torneo_id}")
    partido.delete()
    messages.warning(request, 'Partido eliminado del calendario.')
    return redirect(f"/programar/?torneo={torneo_id}")

@login_required
@user_passes_test(es_organizador)
@require_POST
def reiniciar_partido(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    mi_complejo = obtener_mi_complejo(request.user)
    if partido.torneo.complejo != mi_complejo and not request.user.is_superuser:
        return redirect('dashboard')

    try:
        with transaction.atomic():
            if partido.llave_id:
                motor.revertir_llave(partido.llave)
            sanciones = list(Sancion.objects.filter(partido=partido).select_related('torneo__complejo', 'equipo'))
            registrar_anulaciones(sanciones, request.user, "Partido reiniciado", origen='VOCALIA')
            # Devolver las suspensiones que generó este partido
            if partido.sanciones_aplicadas and partido.estado == 'JUG':
                revertir_suspensiones_partido(partido)
            partido.detalles.all().delete()
            Sancion.objects.filter(partido=partido).delete()

            partido.goles_local = 0
            partido.goles_visita = 0
            partido.estado = 'PROG'
            partido.informe_vocal = ""
            partido.informe_arbitro = ""
            partido.validado_local = False
            partido.validado_visita = False
            partido.hubo_penales = False
            partido.penales_local = 0
            partido.penales_visita = 0
            partido.ganador_wo = None
            partido.sanciones_aplicadas = False
            partido.firma_local_base64 = None
            partido.firma_visita_base64 = None
            partido.save()
            EdicionPartido.objects.create(partido=partido, usuario=request.user,
                detalle="Reinició el partido: se borraron goles, tarjetas, firmas y multas automáticas")
    except motor.CampeonatoError as e:
        messages.error(request, f"⛔ {e}")
        return redirect(f"/programar/?torneo={partido.torneo.id}")

    messages.info(request, 'El partido ha sido reiniciado. Ahora está pendiente de juego.')
    return redirect(f"/programar/?torneo={partido.torneo.id}")

# =========================================================
# 3. JUEGO, VOCALÍA Y RESULTADOS (ACCESO VOCAL Y ADMIN)
# =========================================================

def verificar_acceso_partido(user, partido):
    return rol_en_complejo(user, partido.torneo.complejo) in ('ORG', 'VOC')

def verificar_acceso_complejo(user, complejo):
    """Igual que verificar_acceso_partido pero para objetos (como Sancion)
    que pueden no estar ligados a un Partido."""
    return rol_en_complejo(user, complejo) in ('ORG', 'VOC')


def partido_bloqueado(request, partido):
    """Un partido FINALIZADO o por W.O. solo lo puede modificar el
    ADMINISTRADOR de la cancha (y cada cambio queda registrado en la hoja de
    vocalía). El vocal ya no puede tocarlo."""
    if partido.estado in ('JUG', 'WO'):
        if rol_en_complejo(request.user, partido.torneo.complejo) == 'ORG':
            return False
        messages.error(request, "🔒 Este partido ya está finalizado. Solo el administrador de la cancha puede modificarlo.")
        return True
    return False


def es_edicion_post_cierre(partido):
    return partido.estado in ('JUG', 'WO')


def preparar_edicion(partido, usuario):
    """Antes de modificar un partido finalizado se deshacen sus efectos
    automáticos (suspensiones y multas por tarjetas aún no cobradas) para
    volver a calcularlos con los datos corregidos."""
    if partido.estado == 'JUG' and partido.sanciones_aplicadas:
        revertir_suspensiones_partido(partido)
        auto = list(Sancion.objects.filter(partido=partido, tipo__in=['AMARILLA', 'ROJA'], monto_pagado=0)
                    .select_related('torneo__complejo', 'equipo'))
        registrar_anulaciones(auto, usuario, "Recalculo por edición del administrador", origen='VOCALIA')
        Sancion.objects.filter(id__in=[x.id for x in auto]).delete()


def cerrar_edicion(request, partido, detalle):
    """Después de modificar un partido finalizado: vuelve a aplicar sanciones,
    corrige la llave si cambió el ganador y deja constancia del cambio."""
    partido.refresh_from_db()
    if partido.estado == 'JUG' and partido.sanciones_aplicadas:
        aplicar_sanciones_partido(partido, descontar_cumplidas=False)
    if partido.llave_id:
        llave = partido.llave
        nuevo = motor.ganador_llave(llave)
        if (nuevo.id if nuevo else None) != llave.ganador_id:
            motor.revertir_llave(llave)   # falla si la ronda siguiente ya se jugó
            motor.avanzar_llave(llave)
    EdicionPartido.objects.create(partido=partido, usuario=request.user, detalle=detalle[:300])


def _monto_abono(request, sancion):
    """Lee el abono del formulario: debe ser > 0 y no mayor al saldo."""
    abono_str = (request.POST.get('monto_abono') or '').strip()
    try:
        abono = Decimal(abono_str) if abono_str else sancion.saldo
    except Exception:
        return None
    if abono <= 0 or abono > sancion.saldo:
        return None
    return abono.quantize(Decimal('0.01'))


def aplicar_sanciones_partido(partido, descontar_cumplidas=True):
    """Descuenta suspensiones cumplidas y genera tarjetas/multas del partido.
    descontar_cumplidas=False al recalcular tras una edición del administrador
    (las fechas cumplidas ya se descontaron al finalizar)."""
    detalles = list(DetallePartido.objects.filter(partido=partido).select_related('jugador', 'jugador__equipo'))
    con_roja = {d.jugador_id for d in detalles if d.tipo in ('DA', 'TR')}

    if descontar_cumplidas:
        jugadores_ambos_equipos = Jugador.objects.filter(equipo__in=[partido.equipo_local, partido.equipo_visita], partidos_suspension__gt=0)
        for j in jugadores_ambos_equipos:
            if j.id not in con_roja:
                j.partidos_suspension -= 1
                j.save(update_fields=['partidos_suspension'])

    def multar(j, tipo, monto, descripcion):
        # Si ya existe (p. ej. ya estaba cobrada) no se duplica
        if not Sancion.objects.filter(partido=partido, jugador=j, tipo=tipo, descripcion=descripcion).exists():
            Sancion.objects.create(torneo=partido.torneo, equipo=j.equipo, jugador=j, partido=partido,
                                   tipo=tipo, monto=monto, descripcion=descripcion)

    if partido.etapa in ('F1', 'GRP'):
        fases_validas = [partido.etapa]
    elif partido.etapa == 'F2':
        fases_validas = ['F2']
    else:
        fases_validas = Partido.ETAPAS_ELIMINATORIAS

    por_jugador = {}
    for d in detalles:
        por_jugador.setdefault(d.jugador_id, (d.jugador, []))[1].append(d.tipo)

    for j, tipos in por_jugador.values():
        ta_partido = tipos.count('TA')
        da_partido = tipos.count('DA')
        tr_partido = tipos.count('TR')
        if tr_partido > 0:
            j.partidos_suspension += 2
            j.rojas_directas_acumuladas += 1
            if j.rojas_directas_acumuladas >= 3:
                j.expulsado_torneo = True
                desc_roja = f"Expulsión Definitiva del Torneo (Límite 3 Rojas) - {j.nombres}"
            else:
                desc_roja = f"Roja Directa - {j.nombres}"
            j.save()
            multar(j, 'ROJA', partido.torneo.costo_roja, desc_roja)
        if da_partido > 0:
            j.partidos_suspension += 1
            j.save()
            multar(j, 'ROJA', partido.torneo.costo_roja, f"Roja por Acumulación - {j.nombres}")
        if ta_partido > 0:
            multar(j, 'AMARILLA', partido.torneo.costo_amarilla, f"Tarjeta Amarilla - {j.nombres}")
            total_ta_fase = DetallePartido.objects.filter(
                jugador=j, partido__torneo=partido.torneo, partido__etapa__in=fases_validas, tipo='TA'
            ).count()
            if total_ta_fase > 0 and total_ta_fase % 4 == 0:
                j.partidos_suspension += 1
                j.save()

    partido.sanciones_aplicadas = True
    partido.save(update_fields=['sanciones_aplicadas'])


def revertir_suspensiones_partido(partido):
    """Al reiniciar un partido finalizado se devuelven las suspensiones que
    generó (rojas y amarillas acumuladas) para no castigar dos veces."""
    detalles = list(DetallePartido.objects.filter(partido=partido).select_related('jugador'))
    fases = [partido.etapa] if partido.etapa in ('F1', 'GRP', 'F2') else Partido.ETAPAS_ELIMINATORIAS
    vistos = {}
    for d in detalles:
        vistos.setdefault(d.jugador_id, (d.jugador, []))[1].append(d.tipo)
    for j, tipos in vistos.values():
        cambios = 0
        if 'TR' in tipos:
            cambios += 2
            j.rojas_directas_acumuladas = max(0, j.rojas_directas_acumuladas - 1)
            if j.rojas_directas_acumuladas < 3:
                j.expulsado_torneo = False
        if 'DA' in tipos:
            cambios += 1
        if 'TA' in tipos:
            total_ta = DetallePartido.objects.filter(jugador=j, partido__torneo=partido.torneo,
                                                     partido__etapa__in=fases, tipo='TA').count()
            if total_ta > 0 and total_ta % 4 == 0:
                cambios += 1
        j.partidos_suspension = max(0, j.partidos_suspension - cambios)
        j.save()


def cerrar_partido(partido):
    """Pasa el partido a finalizado y, si es de llaves, mueve al ganador."""
    if partido.estado == 'JUG' and not partido.sanciones_aplicadas:
        aplicar_sanciones_partido(partido)
    motor.procesar_partido_cerrado(partido)


def _editar_acta_cerrada(request, partido):
    """El administrador corrige informes, penales o firmas de un partido ya
    finalizado. Se registra exactamente qué cambió."""
    def accion():
        cambios = []
        for campo, nombre in (('informe_vocal', 'informe del vocal'), ('informe_arbitro', 'informe del árbitro')):
            nuevo = (request.POST.get(campo) or '')[:4000]
            if nuevo.strip() != (getattr(partido, campo) or '').strip():
                setattr(partido, campo, nuevo)
                cambios.append(f"Modificó el {nombre}")
        for campo, nombre in (('firma_local_base64', 'firma local'), ('firma_visita_base64', 'firma visitante')):
            valor = request.POST.get(campo)
            if valor and valor != getattr(partido, campo):
                comprimida = comprimir_firma(valor)
                if comprimida:
                    setattr(partido, campo, comprimida)
                    cambios.append(f"Cambió la {nombre}")
        if partido.etapa in Partido.ETAPAS_ELIMINATORIAS:
            try:
                pl = max(0, int(request.POST.get('penales_local') or 0))
                pv = max(0, int(request.POST.get('penales_visita') or 0))
            except ValueError:
                pl, pv = partido.penales_local or 0, partido.penales_visita or 0
            if (pl, pv) != ((partido.penales_local or 0), (partido.penales_visita or 0)):
                cambios.append(f"Penales {(partido.penales_local or 0)}-{(partido.penales_visita or 0)} → {pl}-{pv}")
                partido.penales_local, partido.penales_visita = pl, pv
                partido.hubo_penales = bool(pl or pv)
        if not cambios:
            return None
        partido.save()
        return "; ".join(cambios)

    _con_registro(request, partido, accion)
    messages.success(request, "✅ Cambios guardados. Quedaron registrados en la hoja de vocalía como edición del administrador.")
    return redirect('gestionar_vocalia', partido_id=partido.id)


@login_required
@user_passes_test(es_vocal_o_admin)
def registrar_resultado(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    if not verificar_acceso_partido(request.user, partido): return redirect('dashboard')

    if request.method == 'POST':
        if partido_bloqueado(request, partido):
            return redirect(f"/programar/?torneo={partido.torneo.id}")
        if es_edicion_post_cierre(partido):
            try:
                gl = max(0, int(request.POST.get('goles_local')))
                gv = max(0, int(request.POST.get('goles_visita')))
            except (TypeError, ValueError):
                messages.error(request, "⛔ Marcador inválido.")
                return redirect('registrar_resultado', partido_id=partido.id)

            def accion():
                antes = _marcador(partido)
                if (gl, gv) == (partido.goles_local, partido.goles_visita):
                    return None
                partido.goles_local, partido.goles_visita = gl, gv
                partido.save(update_fields=['goles_local', 'goles_visita'])
                return f"Cambió el marcador {antes} → {gl}-{gv}"
            _con_registro(request, partido, accion)
            return redirect(f"/programar/?torneo={partido.torneo.id}")
        wo = request.POST.get('wo')
        if wo == 'on':
            partido.estado = 'WO'
            partido.goles_local = 3
            partido.goles_visita = 0
            partido.ganador_wo = partido.equipo_local
        else:
            try:
                partido.goles_local = max(0, int(request.POST.get('goles_local')))
                partido.goles_visita = max(0, int(request.POST.get('goles_visita')))
            except (TypeError, ValueError):
                messages.error(request, "⛔ Marcador inválido.")
                return redirect('registrar_resultado', partido_id=partido.id)
            partido.estado = 'JUG'

        partido.save()
        cerrar_partido(partido)
        messages.success(request, f'Resultado registrado: {partido.equipo_local} ({partido.goles_local}) - ({partido.goles_visita}) {partido.equipo_visita}')
        return redirect(f"/programar/?torneo={partido.torneo.id}")
    return render(request, 'core/registrar_resultado.html', {'partido': partido})

@login_required
@user_passes_test(es_vocal_o_admin)
def gestionar_vocalia(request, partido_id):
    partido = get_object_or_404(Partido.objects.select_related('torneo', 'torneo__complejo', 'equipo_local', 'equipo_visita'), id=partido_id)
    if not verificar_acceso_partido(request.user, partido): return redirect('dashboard')

    def jugadores_con_conteo(equipo):
        return Jugador.objects.filter(equipo=equipo).annotate(
            goles_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='GOL')),
            ta_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='TA')),
            tr_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='TR')),
            da_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='DA')),
            star_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='STAR'))
        ).order_by('dorsal')

    jugadores_local = jugadores_con_conteo(partido.equipo_local)
    jugadores_visita = jugadores_con_conteo(partido.equipo_visita)

    deudas_pendientes = Sancion.objects.filter(
        equipo__in=[partido.equipo_local, partido.equipo_visita],
        pagada=False
    ).select_related('equipo', 'jugador').order_by('equipo__nombre')

    asistencias_ids = list(DetallePartido.objects.filter(partido=partido, tipo='ASIS').values_list('jugador_id', flat=True))
    multas = Sancion.objects.filter(partido=partido, tipo='ADMIN').select_related('equipo').order_by('-id')
    if request.method == 'POST':
        if 'cobrar_deuda' in request.POST:
            sancion = get_object_or_404(Sancion, id=request.POST.get('sancion_id'), torneo=partido.torneo,
                                        equipo__in=[partido.equipo_local, partido.equipo_visita])
            abono = _monto_abono(request, sancion)
            if abono is None:
                messages.error(request, f"⛔ Monto inválido. Debe ser mayor a $0 y máximo ${sancion.saldo}.")
                return redirect('gestionar_vocalia', partido_id=partido.id)
            with transaction.atomic():
                sancion.monto_pagado += abono
                if sancion.monto_pagado >= sancion.monto:
                    sancion.pagada = True
                    sancion.monto_pagado = sancion.monto
                    messages.success(request, f"✅ ¡Deuda de {sancion.equipo.nombre} cancelada en su totalidad!")
                else:
                    messages.success(request, f"✅ Abono de ${abono} registrado para {sancion.equipo.nombre}.")
                sancion.save()
                AbonoSancion.objects.create(sancion=sancion, monto=abono, partido=partido)
            return redirect('gestionar_vocalia', partido_id=partido.id)

        elif 'declarar_wo' in request.POST:
            if partido_bloqueado(request, partido):
                return redirect('gestionar_vocalia', partido_id=partido.id)
            if es_edicion_post_cierre(partido):
                messages.error(request, "⛔ El partido ya está finalizado. Para convertirlo en W.O. primero reinícialo desde el calendario.")
                return redirect('gestionar_vocalia', partido_id=partido.id)
            tipo_wo = request.POST.get('tipo_wo')
            if tipo_wo not in ('LOCAL', 'VISITA', 'DOBLE'):
                messages.error(request, "⛔ Elige a favor de quién es el W.O.")
                return redirect('gestionar_vocalia', partido_id=partido.id)
            if tipo_wo == 'DOBLE' and partido.llave_id:
                messages.error(request, "⛔ En una llave eliminatoria no puede haber doble W.O.: alguien debe avanzar. Declara el W.O. a favor del equipo que se presentó.")
                return redirect('gestionar_vocalia', partido_id=partido.id)
            with transaction.atomic():
                partido.estado = 'WO'
                if tipo_wo == 'LOCAL':
                    partido.goles_local, partido.goles_visita, partido.ganador_wo = 3, 0, partido.equipo_local
                elif tipo_wo == 'VISITA':
                    partido.goles_local, partido.goles_visita, partido.ganador_wo = 0, 3, partido.equipo_visita
                else:
                    partido.goles_local, partido.goles_visita, partido.ganador_wo = 0, 0, None
                partido.validado_local = True
                partido.validado_visita = True
                partido.sanciones_aplicadas = True
                partido.save()
                motor.procesar_partido_cerrado(partido)
            messages.success(request, '🚨 Partido finalizado por W.O. exitosamente.')
            return redirect(f"/programar/?torneo={partido.torneo.id}")

        elif 'guardar_informe' in request.POST:
            if partido_bloqueado(request, partido):
                return redirect('gestionar_vocalia', partido_id=partido.id)
            if es_edicion_post_cierre(partido):
                return _editar_acta_cerrada(request, partido)
            partido.informe_vocal = (request.POST.get('informe_vocal') or '')[:4000]
            partido.informe_arbitro = (request.POST.get('informe_arbitro') or '')[:4000]

            # Firmas: se comprimen (recorte + blanco y negro) => ~3 KB c/u
            for campo, clave in (('firma_local_base64', 'firma_local_base64'), ('firma_visita_base64', 'firma_visita_base64')):
                valor = request.POST.get(clave)
                if valor and valor != getattr(partido, campo):
                    setattr(partido, campo, comprimir_firma(valor))
            partido.validado_local = bool(partido.firma_local_base64) and request.POST.get('validado_local') == 'on'
            partido.validado_visita = bool(partido.firma_visita_base64) and request.POST.get('validado_visita') == 'on'

            if partido.etapa in Partido.ETAPAS_ELIMINATORIAS:
                try:
                    p_local = max(0, int(request.POST.get('penales_local') or 0))
                    p_visita = max(0, int(request.POST.get('penales_visita') or 0))
                except ValueError:
                    p_local = p_visita = 0
                if p_local > 0 or p_visita > 0:
                    partido.hubo_penales = True
                    partido.penales_local = p_local
                    partido.penales_visita = p_visita
                else:
                    partido.hubo_penales = False
                    partido.penales_local = 0
                    partido.penales_visita = 0

            quiere_finalizar = 'guardar_y_volver' not in request.POST
            finalizar = quiere_finalizar and partido.validado_local and partido.validado_visita
            if quiere_finalizar and not finalizar:
                partido.estado = 'ACTA'
                partido.save()
                messages.warning(request, '⚠️ Faltan las firmas de ambos capitanes para finalizar el partido. El acta quedó guardada.')
                return redirect('gestionar_vocalia', partido_id=partido.id)
            if finalizar and partido.llave_id:
                # Una llave no puede quedar empatada: si es el último partido
                # de la llave y hay empate global, se exigen penales.
                otros = [p for p in partido.llave.partidos.all() if p.id != partido.id]
                if all(p.estado in ('JUG', 'WO') for p in otros):
                    a = partido.llave.equipo_a_id
                    goles = {partido.equipo_local_id: partido.goles_local, partido.equipo_visita_id: partido.goles_visita}
                    for p in otros:
                        goles[p.equipo_local_id] += p.goles_local
                        goles[p.equipo_visita_id] += p.goles_visita
                    if len(set(goles.values())) == 1 and (not partido.hubo_penales or partido.penales_local == partido.penales_visita):
                        partido.estado = 'ACTA'
                        partido.save()
                        messages.error(request, "⚖️ La llave está empatada en el global: registra el resultado de los penales para poder finalizar.")
                        return redirect('gestionar_vocalia', partido_id=partido.id)

            if finalizar:
                partido.estado = 'JUG'
            else:
                partido.estado = 'ACTA'
            partido.save()

            if partido.estado == 'JUG':
                with transaction.atomic():
                    cerrar_partido(partido)
                messages.success(request, '✅ Acta firmada por ambos equipos. Partido Finalizado y Sanciones aplicadas.')
                return redirect(f"/programar/?torneo={partido.torneo.id}")
            messages.info(request, '📋 Partido guardado en Actas. (Aún no se ha finalizado).')
            return redirect(f"/programar/?torneo={partido.torneo.id}")

        elif 'nueva_multa' in request.POST:
            equipo_id = request.POST.get('equipo_multa')
            motivo = (request.POST.get('motivo_multa') or '').strip()[:200]
            try:
                monto = Decimal(request.POST.get('monto_multa') or '0')
            except Exception:
                monto = Decimal('0')
            equipo_valido = equipo_id and str(equipo_id) in (str(partido.equipo_local_id), str(partido.equipo_visita_id))
            if equipo_valido and motivo and Decimal('0') < monto <= Decimal('1000'):
                Sancion.objects.create(
                    torneo=partido.torneo, equipo_id=equipo_id, partido=partido,
                    tipo='ADMIN', monto=monto, descripcion=motivo, pagada=False
                )
                messages.success(request, "Multa aplicada.")
            else:
                messages.error(request, "⛔ Revisa la multa: equipo del partido, motivo y un monto entre $0.01 y $1000.")
            return redirect('gestionar_vocalia', partido_id=partido_id)

    return render(request, 'core/gestionar_vocalia.html', {
        'partido': partido,
        'jugadores_local': jugadores_local,
        'jugadores_visita': jugadores_visita,
        'asistencias_ids': asistencias_ids,
        'multas': multas,
        'deudas_pendientes': deudas_pendientes,
        'cerrado': partido.estado in ('JUG', 'WO'),
        'ediciones': partido.ediciones.select_related('usuario'),
        'es_admin_cancha': rol_en_complejo(request.user, partido.torneo.complejo) == 'ORG',
    })

def _marcador(partido):
    return f"{partido.goles_local}-{partido.goles_visita}"


def _con_registro(request, partido, accion):
    """Ejecuta una modificación del partido. Si ya estaba finalizado (solo
    llega aquí el administrador) recalcula sanciones/llaves y registra qué se
    cambió. `accion` devuelve el texto de lo que hizo (o None si no hizo nada)."""
    cerrado = es_edicion_post_cierre(partido)
    try:
        with transaction.atomic():
            if cerrado:
                preparar_edicion(partido, request.user)
            detalle = accion()
            if cerrado and detalle:
                cerrar_edicion(request, partido, detalle)
            elif cerrado:
                transaction.set_rollback(True)
    except motor.CampeonatoError as e:
        messages.error(request, f"⛔ No se aplicó el cambio: {e}")


@login_required
@user_passes_test(es_vocal_o_admin)
@require_POST
def registrar_incidencia(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    if not verificar_acceso_partido(request.user, partido): return redirect('dashboard')
    if partido_bloqueado(request, partido):
        return redirect('gestionar_vocalia', partido_id=partido.id)

    jugador_id = request.POST.get('jugador_id')
    tipo_evento = request.POST.get('tipo') 
    minuto = request.POST.get('minuto', 0)
    try:
        minuto = max(0, min(int(minuto or 0), 200))
    except ValueError:
        minuto = 0
    
    jugador = get_object_or_404(
        Jugador, id=jugador_id,
        equipo__in=[partido.equipo_local, partido.equipo_visita],
    )
    if not DetallePartido.objects.filter(partido=partido, jugador=jugador, tipo='ASIS').exists():
        messages.error(request, f"⛔ {jugador.nombres} no está en cancha. Ingrésalo primero desde la banca.")
        return redirect('gestionar_vocalia', partido_id=partido.id)

    def accion():
        p = Partido.objects.select_for_update().get(id=partido.id)
        quien = f"{jugador.nombres} ({jugador.equipo.nombre})"
        texto = None
        if tipo_evento == 'TA':
            amarilla_previa = DetallePartido.objects.filter(partido=p, jugador=jugador, tipo='TA').first()
            if amarilla_previa:
                amarilla_previa.delete()
                DetallePartido.objects.create(partido=p, jugador=jugador, tipo='DA', minuto=minuto, observacion="Roja por Acum.", equipo_incidencia=jugador.equipo)
                messages.error(request, f'🟥 ¡ROJA POR ACUMULACIÓN para {jugador.nombres}!')
                texto = f"Agregó 2ª amarilla (roja por acumulación) a {quien}"
            else:
                DetallePartido.objects.create(partido=p, jugador=jugador, tipo='TA', minuto=minuto, equipo_incidencia=jugador.equipo)
                messages.warning(request, f'🟨 Tarjeta Amarilla registrada a {jugador.nombres}.')
                texto = f"Agregó tarjeta amarilla a {quien}"
        elif tipo_evento == 'TR':
            DetallePartido.objects.create(partido=p, jugador=jugador, tipo='TR', minuto=minuto, equipo_incidencia=jugador.equipo)
            messages.error(request, f'🟥 ¡ROJA DIRECTA para {jugador.nombres}!')
            texto = f"Agregó roja directa a {quien}"
        elif tipo_evento == 'GOL':
            antes = _marcador(p)
            DetallePartido.objects.create(partido=p, jugador=jugador, tipo='GOL', minuto=minuto, equipo_incidencia=jugador.equipo)
            if jugador.equipo_id == p.equipo_local_id:
                p.goles_local += 1
            else:
                p.goles_visita += 1
            messages.success(request, f'⚽ ¡Gol de {jugador.nombres}!')
            texto = f"Agregó gol de {quien}. Marcador {antes} → {_marcador(p)}"
        elif tipo_evento == 'STAR':
            if DetallePartido.objects.filter(partido=p, tipo='STAR').count() >= 2:
                messages.error(request, '⭐ Error: Solo se pueden asignar máximo 2 figuras por partido.')
            else:
                DetallePartido.objects.create(partido=p, jugador=jugador, tipo='STAR', equipo_incidencia=jugador.equipo)
                messages.success(request, f'⭐ ¡{jugador.nombres} fue elegido como Figura del Partido!')
                texto = f"Marcó como figura a {quien}"
        if p.estado == 'PROG':
            p.estado = 'VIVO'
        p.save()
        return texto

    _con_registro(request, partido, accion)
    return redirect('gestionar_vocalia', partido_id=partido.id)


def _quitar_evento(partido, evento):
    """Borra un evento (ajustando el marcador si era gol) y devuelve el texto."""
    antes = _marcador(partido)
    if evento.tipo == 'GOL':
        if evento.equipo_incidencia_id == partido.equipo_local_id:
            partido.goles_local = max(0, partido.goles_local - 1)
        else:
            partido.goles_visita = max(0, partido.goles_visita - 1)
        partido.save(update_fields=['goles_local', 'goles_visita'])
    texto = f"Quitó {evento.get_tipo_display()} de {evento.jugador.nombres}"
    if evento.tipo == 'GOL':
        texto += f". Marcador {antes} → {_marcador(partido)}"
    evento.delete()
    return texto


@login_required
@user_passes_test(es_vocal_o_admin)
@require_POST
def eliminar_evento_ultimo(request, partido_id, jugador_id, tipo):
    partido = get_object_or_404(Partido, id=partido_id)
    if not verificar_acceso_partido(request.user, partido): return redirect('dashboard')
    if partido_bloqueado(request, partido):
        return redirect('gestionar_vocalia', partido_id=partido.id)

    def accion():
        if tipo == 'TA':
            evento_da = DetallePartido.objects.filter(partido_id=partido_id, jugador_id=jugador_id, tipo='DA').last()
            if evento_da:
                jugador_obj = evento_da.jugador
                evento_da.delete()
                DetallePartido.objects.create(partido_id=partido_id, jugador_id=jugador_id, tipo='TA', equipo_incidencia=jugador_obj.equipo)
                messages.success(request, "Corrección: Roja por Acumulación anulada. Se restauró 1 Amarilla.")
                return f"Anuló la roja por acumulación de {jugador_obj.nombres} (queda con 1 amarilla)"
        evento = DetallePartido.objects.filter(partido_id=partido_id, jugador_id=jugador_id, tipo=tipo).last()
        if evento:
            nombre = evento.jugador.nombres
            texto = _quitar_evento(partido, evento)
            messages.warning(request, f"Corrección: Se eliminó el último registro de {evento.get_tipo_display()} para {nombre}.")
            return texto
        return None

    _con_registro(request, partido, accion)
    return redirect('gestionar_vocalia', partido_id=partido_id)

@login_required
@user_passes_test(es_vocal_o_admin)
@require_POST
def eliminar_evento(request, evento_id):
    evento = get_object_or_404(DetallePartido, id=evento_id)
    partido = evento.partido
    if not verificar_acceso_partido(request.user, partido): return redirect('dashboard')
    if partido_bloqueado(request, partido):
        return redirect('gestionar_vocalia', partido_id=partido.id)
    _con_registro(request, partido, lambda: _quitar_evento(partido, evento))
    messages.success(request, 'Corrección realizada: Evento eliminado.')
    return redirect('gestionar_vocalia', partido_id=partido.id)


@login_required
@user_passes_test(es_vocal_o_admin)
@require_POST
def eliminar_multa(request, multa_id):
    sancion = get_object_or_404(Sancion, id=multa_id)
    if not verificar_acceso_complejo(request.user, sancion.torneo.complejo):
        return redirect('dashboard')

    partido_id = sancion.partido.id if sancion.partido else None
    if sancion.monto_pagado > 0:
        messages.error(request, "⛔ Esta multa ya tiene cobros. Primero reversa los abonos y luego podrás eliminarla.")
    else:
        origen = 'VOCALIA' if rol_en_complejo(request.user, sancion.torneo.complejo) == 'VOC' else 'FINANZAS'
        with transaction.atomic():
            registrar_anulaciones([sancion], request.user, "Multa eliminada", origen=origen)
            sancion.delete()
        messages.success(request, 'Sanción administrativa eliminada (queda registrada en la trazabilidad financiera).')

    if partido_id:
        return redirect('gestionar_vocalia', partido_id=partido_id)
    return redirect('gestionar_finanzas')


@login_required
@user_passes_test(es_vocal_o_admin)
@require_POST
def toggle_asistencia(request, partido_id, jugador_id):
    partido = get_object_or_404(Partido, id=partido_id)
    if not verificar_acceso_partido(request.user, partido): return redirect('dashboard')
    if partido_bloqueado(request, partido):
        return redirect('gestionar_vocalia', partido_id=partido.id)
    # 🔥 Solo jugadores de los DOS equipos de este partido
    jugador = get_object_or_404(Jugador, id=jugador_id, equipo__in=[partido.equipo_local, partido.equipo_visita])

    asistencia = DetallePartido.objects.filter(partido=partido, jugador=jugador, tipo='ASIS').first()
    if not asistencia and not jugador.esta_habilitado:
        messages.error(request, f"⛔ {jugador.nombres} no puede jugar: {jugador.motivo_inhabilitacion}.")
        return redirect('gestionar_vocalia', partido_id=partido.id)

    def accion():
        if asistencia:
            antes = _marcador(partido)
            goles_jugador = DetallePartido.objects.filter(partido=partido, jugador=jugador, tipo='GOL').count()
            if goles_jugador > 0:
                if jugador.equipo_id == partido.equipo_local_id:
                    partido.goles_local = max(0, partido.goles_local - goles_jugador)
                else:
                    partido.goles_visita = max(0, partido.goles_visita - goles_jugador)
                partido.save()
            DetallePartido.objects.filter(partido=partido, jugador=jugador).delete()
            messages.warning(request, f'Se retiró a {jugador.nombres}. Historial del partido limpiado.')
            texto = f"Sacó de la planilla a {jugador.nombres} ({jugador.equipo.nombre}) y borró sus eventos"
            if goles_jugador:
                texto += f". Marcador {antes} → {_marcador(partido)}"
            return texto
        DetallePartido.objects.create(partido=partido, jugador=jugador, tipo='ASIS', equipo_incidencia=jugador.equipo)
        messages.success(request, f'{jugador.nombres} ingresó a la cancha.')
        return f"Agregó a la planilla a {jugador.nombres} ({jugador.equipo.nombre})"

    _con_registro(request, partido, accion)
    return redirect('gestionar_vocalia', partido_id=partido.id)

# =========================================================
# 4. REPORTES Y ESTADÍSTICAS
# =========================================================

def tabla_posiciones(request, torneo_id):
    torneo = get_object_or_404(Torneo, id=torneo_id)
    if torneo.formato != 'CLASICO':
        return redirect('ver_campeonato', torneo_id=torneo.id)
    tabla_ordenada = motor.tabla_liga(torneo, 'F1')
    fase2_ya_generada = Equipo.objects.filter(torneo=torneo, estado_inscripcion='APROBADO', grupo_fase2__in=['A', 'B']).exists()

    return render(request, 'core/tabla_posiciones.html', {
        'torneo': torneo, 
        'tabla': tabla_ordenada, 
        'fase': 1,
        'fase2_ya_generada': fase2_ya_generada,
        'es_org': rol_en_complejo(request.user, torneo.complejo) == 'ORG',
    })

@login_required
@user_passes_test(es_organizador)
def generar_fase2(request, torneo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    torneo = get_object_or_404(Torneo, id=torneo_id, complejo=mi_complejo)
    if torneo.formato != 'CLASICO':
        messages.error(request, "⛔ Este torneo usa el nuevo sistema de campeonato. Usa «Empezar campeonato» y la vista de grupos y llaves.")
        return redirect('ver_campeonato', torneo_id=torneo.id)
    equipos = Equipo.objects.filter(torneo=torneo, estado_inscripcion='APROBADO')
    
    ida_y_vuelta = request.POST.get('ida_y_vuelta') == 'on'
    torneo.fase2_ida_vuelta = ida_y_vuelta
    torneo.save()

    excluidos = _excluidos_post(request, torneo)
    tabla_ordenada = obtener_clasificados_fase1(torneo, excluidos)

    with transaction.atomic():
        Equipo.objects.filter(id__in=excluidos).update(grupo_fase2=None, puntos_bonificacion=0)
        for index, fila in enumerate(tabla_ordenada):
            equipo = fila['equipo']
            posicion = index + 1
            equipo.puntos_bonificacion = 0 
            
            if posicion == 1:
                equipo.puntos_bonificacion = 2
            elif posicion == 2:
                equipo.puntos_bonificacion = 1

            if posicion % 2 != 0:
                equipo.grupo_fase2 = 'A'
            else:
                equipo.grupo_fase2 = 'B'
            equipo.save()

    formato_texto = "Ida y Vuelta Acumulativa" if ida_y_vuelta else "Solo Ida"
    messages.success(request, f'✅ Fase 2 generada en formato: {formato_texto}. Equipos divididos y bonos asignados.')
    return redirect('tabla_posiciones_f2', torneo_id=torneo.id)

def tabla_posiciones_f2(request, torneo_id):
    torneo = get_object_or_404(Torneo, id=torneo_id)
    if torneo.formato != 'CLASICO':
        return redirect('ver_campeonato', torneo_id=torneo.id)
    equipos = list(Equipo.objects.filter(torneo=torneo, estado_inscripcion='APROBADO', grupo_fase2__in=['A', 'B']))
    partidos = list(Partido.objects.filter(torneo=torneo, etapa='F2'))
    tabla_a = motor.calcular_tabla([e for e in equipos if e.grupo_fase2 == 'A'], partidos, con_bono=True)
    tabla_b = motor.calcular_tabla([e for e in equipos if e.grupo_fase2 == 'B'], partidos, con_bono=True)
    cuartos_generados = Partido.objects.filter(torneo=torneo, etapa='4TOS').exists()
    es_org = rol_en_complejo(request.user, torneo.complejo) == 'ORG'

    return render(request, 'core/tabla_posiciones_f2.html', {
        'torneo': torneo, 
        'tabla_a': tabla_a, 
        'tabla_b': tabla_b,
        'fase': 2,
        'cuartos_generados': cuartos_generados,
        'es_organizador': es_org
    })

@login_required
def seleccionar_reporte(request):
    mi_complejo = obtener_mi_complejo(request.user)
    if not mi_complejo:
        return redirect('dashboard')
        
    # 🔥 AISLAMIENTO: Solo trae torneos de ESTA cancha
    torneos_activos = Torneo.objects.filter(activo=True, complejo=mi_complejo).order_by('categoria__nombre', '-fecha_inicio')
    torneos_finalizados = Torneo.objects.filter(activo=False, complejo=mi_complejo).order_by('-fecha_inicio')
    
    return render(request, 'core/seleccionar_reporte.html', {
        'torneos_activos': torneos_activos, 
        'torneos_finalizados': torneos_finalizados
    })

@login_required
def reporte_estadisticas(request, torneo_id):
    torneo = get_object_or_404(Torneo.objects.select_related('complejo'), id=torneo_id)
    # 🔥 El rol se mide EN LA CANCHA DEL TORNEO (ser vocal en otra cancha no
    # da acceso a los datos de esta).
    rol = rol_en_complejo(request.user, torneo.complejo) or 'FAN'

    hay_fase2 = Partido.objects.filter(torneo=torneo, etapa='F2').exists()
    hay_llaves = Partido.objects.filter(torneo=torneo, etapa__in=Partido.ETAPAS_ELIMINATORIAS).exists()

    fase_forzada = request.GET.get('fase')
    if rol == 'ORG' and fase_forzada in ('1', '2'):
        fase_actual = int(fase_forzada)
    else:
        fase_actual = 2 if (hay_fase2 or (hay_llaves and torneo.formato == 'CLASICO')) else 1

    tabla_fase1, tabla_a, tabla_b, tablas_grupos = [], [], [], {}
    if torneo.formato == 'GRUPOS':
        tablas_grupos = motor.tablas_grupos(torneo)
    elif fase_actual == 1:
        tabla_fase1 = motor.tabla_liga(torneo, 'F1')
    else:
        equipos = list(Equipo.objects.filter(torneo=torneo, estado_inscripcion='APROBADO', grupo_fase2__in=['A', 'B']))
        partidos = list(Partido.objects.filter(torneo=torneo, etapa='F2'))
        tabla_a = motor.calcular_tabla([e for e in equipos if e.grupo_fase2 == 'A'], partidos, con_bono=True)
        tabla_b = motor.calcular_tabla([e for e in equipos if e.grupo_fase2 == 'B'], partidos, con_bono=True)

    equipos_todos = Equipo.objects.filter(torneo=torneo, estado_inscripcion='APROBADO')

    goleadores = DetallePartido.objects.filter(
        partido__torneo=torneo, tipo='GOL', equipo_incidencia=F('jugador__equipo')
    ).values('jugador__nombres', 'jugador__equipo__nombre', 'jugador__equipo__escudo').annotate(
        total_goles=Count('id')).order_by('-total_goles', 'jugador__nombres')[:15]

    top_mvps = DetallePartido.objects.filter(partido__torneo=torneo, tipo='STAR').values(
        'jugador__nombres', 'jugador__equipo__nombre', 'jugador__equipo__escudo'
    ).annotate(total_stars=Count('id')).order_by('-total_stars')[:15]

    # Jugadores que NO pueden jugar (por cualquier motivo) con su razón
    sancionados_activos = []
    hoy = timezone.localdate()
    inhabilitados = Jugador.objects.filter(equipo__in=equipos_todos).filter(
        Q(partidos_suspension__gt=0) | Q(bloqueado_por_cuota=True) | Q(expulsado_torneo=True) |
        Q(rojas_directas_acumuladas__gte=3) | Q(sancionado_hasta__gte=hoy)
    ).select_related('equipo').distinct()
    for j in inhabilitados:
        if j.expulsado_torneo or j.rojas_directas_acumuladas >= 3:
            motivo, restantes = "Expulsado del Torneo", "Definitivo"
        elif j.bloqueado_por_cuota:
            motivo, restantes = "No cumplió el mínimo de partidos jugados", "Inhabilitado"
        elif j.sancionado_hasta and j.sancionado_hasta >= hoy:
            motivo, restantes = "Sanción administrativa", f"Hasta {j.sancionado_hasta:%d/%m/%Y}"
        else:
            motivo, restantes = "Suspensión disciplinaria", f"Debe {j.partidos_suspension} fecha(s)"
        if j.motivo_suspension:
            motivo = f"{motivo} · {j.motivo_suspension}"
        sancionados_activos.append({'jugador': j, 'motivo': motivo, 'restantes': restantes})

    if rol in ['ORG', 'VOC']:
        equipos_permitidos = equipos_todos
    elif rol == 'DIR':
        equipos_permitidos = Equipo.objects.filter(torneo=torneo, dirigente=request.user, estado_inscripcion='APROBADO')
    else:
        equipos_permitidos = Equipo.objects.none()

    equipo_id = request.GET.get('equipo')
    jugadores_detalle = []
    equipo_seleccionado = None
    if not equipo_id and rol == 'DIR' and equipos_permitidos.count() == 1:
        equipo_seleccionado = equipos_permitidos.first()
    elif equipo_id and equipo_id.isdigit():
        equipo_seleccionado = equipos_permitidos.filter(id=equipo_id).first()

    if equipo_seleccionado:
        actuales = set(Jugador.objects.filter(equipo=equipo_seleccionado).values_list('id', flat=True))
        # Estadísticas de todo el plantel en UNA consulta agrupada
        stats = DetallePartido.objects.filter(partido__torneo=torneo, equipo_incidencia=equipo_seleccionado).values(
            'jugador_id').annotate(
            pj=Count('id', filter=Q(tipo='ASIS')), ta=Count('id', filter=Q(tipo='TA')),
            da=Count('id', filter=Q(tipo='DA')), tr=Count('id', filter=Q(tipo='TR')),
            goles=Count('id', filter=Q(tipo='GOL')), stars=Count('id', filter=Q(tipo='STAR')))
        por_jugador = {r['jugador_id']: r for r in stats}
        for j in Jugador.objects.filter(id__in=actuales | set(por_jugador)).order_by('dorsal', 'nombres'):
            r = por_jugador.get(j.id, {})
            jugadores_detalle.append({
                'nombre': j.nombres + ("" if j.id in actuales else " (Transferido)"),
                'pj': r.get('pj', 0), 'ta': r.get('ta', 0) % 4, 'da': r.get('da', 0),
                'tr': r.get('tr', 0), 'goles': r.get('goles', 0), 'stars': r.get('stars', 0),
                'habilitado': j.esta_habilitado,
            })

    return render(request, 'core/reporte_estadisticas.html', {
        'torneo': torneo, 
        'fase_actual': fase_actual,
        'tabla_fase1': tabla_fase1,
        'tabla_a': tabla_a,
        'tabla_b': tabla_b,
        'tablas_grupos': tablas_grupos,
        'goleadores': goleadores, 
        'equipos_permitidos': equipos_permitidos, 
        'equipo_seleccionado': equipo_seleccionado, 
        'jugadores_detalle': jugadores_detalle, 
        'sancionados_activos': sancionados_activos, 
        'rol': rol,
        'hay_llaves': hay_llaves,
        'top_mvps': top_mvps
    })

def tabla_goleadores(request, torneo_id):
    torneo = get_object_or_404(Torneo, id=torneo_id)
    
    goleadores = DetallePartido.objects.filter(
        partido__torneo=torneo, 
        tipo='GOL',
        equipo_incidencia=F('jugador__equipo') 
    ).values(
        'jugador__nombres', 'jugador__equipo__nombre', 'jugador__equipo__escudo'
    ).annotate(
        total_goles=Count('id')
    ).order_by('-total_goles', 'jugador__nombres')[:15]
    
    return render(request, 'core/tabla_goleadores.html', {
        'torneo': torneo,
        'goleadores': goleadores
    })
    
# =========================================================
# 5. GENERACIÓN DE PDF (ACTA) (ACCESO VOCAL Y ADMIN)
# =========================================================

def _pdf_link_callback(uri, rel):
    """Permite a xhtml2pdf cargar escudos/logos guardados en local o en la nube."""
    if uri.startswith(('http://', 'https://', 'data:')):
        return uri
    if settings.MEDIA_URL and uri.startswith(settings.MEDIA_URL):
        ruta = os.path.join(settings.MEDIA_ROOT, uri[len(settings.MEDIA_URL):])
        return ruta if os.path.isfile(ruta) else ''
    if uri.startswith(settings.STATIC_URL):
        from django.contrib.staticfiles import finders
        return finders.find(uri[len(settings.STATIC_URL):]) or ''
    return uri


def _planilla_equipo(equipo, detalles):
    """Una fila por jugador del equipo en el partido: goles, tarjetas y figura."""
    filas = {}
    for d in detalles:
        if d.equipo_incidencia_id != equipo.id and not (d.equipo_incidencia_id is None and d.jugador.equipo_id == equipo.id):
            continue
        f = filas.setdefault(d.jugador_id, {
            'jugador': d.jugador, 'presente': False, 'goles': 0,
            'ta': 0, 'tr': 0, 'da': 0, 'otras': [], 'figura': False,
        })
        if d.tipo == 'ASIS':
            f['presente'] = True
        elif d.tipo == 'GOL':
            f['goles'] += 1
        elif d.tipo == 'TA':
            f['ta'] += 1
        elif d.tipo == 'TR':
            f['tr'] += 1
        elif d.tipo == 'DA':
            f['da'] += 1
        elif d.tipo == 'STAR':
            f['figura'] = True
        elif d.tipo in ('AZUL', 'EBRI'):
            f['otras'].append('Uniforme' if d.tipo == 'AZUL' else 'Ebrio')
    return sorted(filas.values(), key=lambda f: (f['jugador'].dorsal is None, f['jugador'].dorsal or 0, f['jugador'].nombres))


def _escudo_iniciales(nombre, color='#166534'):
    """Escudo redondo con iniciales (data URI) para equipos sin logo."""
    import base64, io
    from PIL import Image, ImageDraw, ImageFont
    palabras = [p for p in (nombre or '').split() if p[:1].isalnum()]
    iniciales = ''.join(p[0] for p in palabras[:2]).upper() or '?'
    t = 240
    img = Image.new('RGBA', (t, t), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, t - 4, t - 4), fill='#FFFFFF')
    d.ellipse((18, 18, t - 18, t - 18), fill=color)
    fuente = None
    for nombre_fuente in ('DejaVuSans-Bold.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 'arialbd.ttf'):
        try:
            fuente = ImageFont.truetype(nombre_fuente, 92)
            break
        except OSError:
            continue
    if fuente is None:
        try:
            fuente = ImageFont.load_default(size=92)
        except TypeError:
            fuente = ImageFont.load_default()
    d.text((t / 2, t / 2), iniciales, fill='#FFFFFF', font=fuente, anchor='mm')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


def _escudo_pdf(equipo, color, alto=74):
    """(src, ancho, alto) del escudo respetando su proporción; iniciales si no tiene."""
    if equipo.escudo:
        try:
            ancho = round(alto * equipo.escudo.width / equipo.escudo.height)
            return equipo.escudo.url, max(20, min(ancho, alto * 2)), alto
        except Exception:
            pass
    return _escudo_iniciales(equipo.nombre, color), alto, alto


@login_required
@user_passes_test(es_vocal_o_admin)
def generar_acta_pdf(request, partido_id):
    partido = get_object_or_404(
        Partido.objects.select_related('torneo__complejo', 'torneo__categoria', 'equipo_local', 'equipo_visita', 'ganador_wo'),
        id=partido_id)
    if not verificar_acceso_partido(request.user, partido): return redirect('dashboard')

    detalles = list(DetallePartido.objects.filter(partido=partido).select_related('jugador'))
    planilla_local = _planilla_equipo(partido.equipo_local, detalles)
    planilla_visita = _planilla_equipo(partido.equipo_visita, detalles)
    tarjetas = [d for d in detalles if d.tipo in ('TA', 'TR', 'DA', 'AZUL', 'EBRI')]
    abonos = AbonoSancion.objects.filter(partido=partido).select_related('sancion__equipo')
    multas = Sancion.objects.filter(partido=partido, tipo='ADMIN').select_related('equipo')

    if partido.estado == 'WO' and partido.ganador_wo_id:
        ganador = partido.ganador_wo.nombre
    elif partido.goles_local != partido.goles_visita:
        ganador = (partido.equipo_local if partido.goles_local > partido.goles_visita else partido.equipo_visita).nombre
    elif partido.hubo_penales and (partido.penales_local or 0) != (partido.penales_visita or 0):
        ganador = (partido.equipo_local if (partido.penales_local or 0) > (partido.penales_visita or 0) else partido.equipo_visita).nombre
    else:
        ganador = None

    categoria = partido.torneo.categoria
    filas = []
    for i in range(max(len(planilla_local), len(planilla_visita))):
        filas.append((planilla_local[i] if i < len(planilla_local) else None,
                      planilla_visita[i] if i < len(planilla_visita) else None))
    context = {
        'partido': partido,
        'complejo': partido.torneo.complejo,
        'color': (categoria.color_carnet if categoria and categoria.color_carnet else '#15803D'),
        'filas': filas,
        'escudo_local': _escudo_pdf(partido.equipo_local, '#15803D'),
        'escudo_visita': _escudo_pdf(partido.equipo_visita, '#1E3A8A'),
        'presentes_local': sum(1 for f in planilla_local if f['presente']),
        'presentes_visita': sum(1 for f in planilla_visita if f['presente']),
        'tarjetas_obs': [t for t in tarjetas if t.observacion],
        'total_tarjetas': len(tarjetas),
        'abonos': abonos, 'multas': multas, 'ganador': ganador,
        'es_eliminatoria': partido.etapa in Partido.ETAPAS_ELIMINATORIAS,
        'ediciones': partido.ediciones.select_related('usuario'),
        'generado': timezone.localtime(timezone.now()),
    }

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="Acta_{partido.id}.pdf"'
    html = get_template('core/acta_partido_pdf.html').render(context)
    pisa_status = pisa.CreatePDF(html, dest=response, link_callback=_pdf_link_callback)
    if pisa_status.err:
        return HttpResponse('Error al generar PDF <pre>' + html + '</pre>')
    return response

# =========================================================
# 6. FINANZAS Y PAGOS
# =========================================================

@login_required
@user_passes_test(es_organizador)
def registrar_pago(request):
    mi_complejo = obtener_mi_complejo(request.user)
    equipo_id = request.GET.get('equipo')
    equipo = get_object_or_404(Equipo, id=equipo_id, torneo__complejo=mi_complejo) if equipo_id else None

    if request.method == 'POST':
        form = PagoForm(request.POST, request.FILES)
        form.fields['equipo'].queryset = Equipo.objects.filter(torneo__complejo=mi_complejo, estado_inscripcion='APROBADO')

        if form.is_valid():
            pago = form.save(commit=False)
            if equipo:
                pago.equipo = equipo
                
            pago.save() 
            messages.success(request, f'🤑 Pago de ${pago.monto} registrado para {pago.equipo.nombre}')
            return redirect('gestionar_finanzas')
        else:
            messages.error(request, "Error en el formulario. Revisa los campos.")
            
    else:
        initial_data = {'equipo': equipo} if equipo else {}
        form = PagoForm(initial=initial_data)
        form.fields['equipo'].queryset = Equipo.objects.filter(torneo__complejo=mi_complejo, estado_inscripcion='APROBADO')

    return render(request, 'core/registrar_pago.html', {
        'form': form, 
        'equipo': equipo 
    })


@login_required
@user_passes_test(es_organizador)
def historial_pagos_equipo(request, equipo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    equipo = get_object_or_404(Equipo, id=equipo_id, torneo__complejo=mi_complejo)
    pagos = Pago.objects.filter(equipo=equipo).order_by('-fecha', '-id')
    
    return render(request, 'core/historial_pagos.html', {
        'equipo': equipo,
        'pagos': pagos
    })

@login_required
def generar_recibo_pago_pdf(request, pago_id):
    pago = get_object_or_404(Pago, id=pago_id)

    es_admin_de_esta_cancha = pago.equipo.torneo.complejo == obtener_mi_complejo(request.user)
    es_dueno_del_equipo = request.user == pago.equipo.dirigente
    if not (es_admin_de_esta_cancha or es_dueno_del_equipo):
        messages.error(request, "⛔ Acceso denegado a este recibo.")
        return redirect('dashboard')
    # Lógica PDF
    template_path = 'core/acta_pago_pdf.html'
    context = {'pago': pago}
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'filename="Recibo_Pago_{pago.id}_{pago.equipo.nombre}.pdf"'
    
    template = get_template(template_path)
    html = template.render(context)
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    
    if pisa_status.err:
        return HttpResponse('Error al generar el PDF <pre>' + html + '</pre>')
    return response

# =========================================================
# 7. REGISTRO PÚBLICO Y SOLICITUDES
# =========================================================

def registro_publico(request):
    if request.method == 'POST':
        form = RegistroPublicoForm(request.POST) 
        
        if form.is_valid():
            usuario = form.save()
            
            # Obtenemos el teléfono ingresado en el formulario
            telefono_ingresado = form.cleaned_data.get('telefono')
            
            # Creamos o actualizamos el perfil con el teléfono
            perfil, created = Perfil.objects.get_or_create(usuario=usuario)
            perfil.telefono = telefono_ingresado
            perfil.save()
            
            login(request, usuario)
            from django.contrib import messages
            messages.success(request, f'Bienvenido. Tu cuenta ha sido creada y ya estás dentro.')
            return redirect('dashboard') 
    else:
        form = RegistroPublicoForm()
        
    return render(request, 'registration/registro_publico.html', {'form': form})


def google_login_callback(request):
    """Recibe el ID token que entrega Google Identity Services desde el
    botón "Iniciar sesión con Google" del login. Solo acepta POST — nunca
    inicia sesión a partir de un GET/link (evita ataques de login CSRF)."""
    if request.method != 'POST':
        return redirect('login')

    token = request.POST.get('credential')
    if not token:
        messages.error(request, "⛔ No se recibió el token de Google. Intenta de nuevo.")
        return redirect('login')

    try:
        info = verificar_token_google(token)
    except GoogleTokenInvalido as e:
        messages.error(request, f"⛔ No se pudo iniciar sesión con Google: {e}")
        return redirect('login')

    usuario, creado = obtener_o_crear_usuario_de_google(info)
    if not usuario.is_active:
        messages.error(request, "⛔ Esta cuenta está desactivada. Contacta a soporte.")
        return redirect('login')

    login(request, usuario, backend='core.backends.UsuarioOCedulaBackend')
    nombre_mostrado = usuario.first_name or usuario.username
    if creado:
        messages.success(request, f'✅ ¡Bienvenido, {nombre_mostrado}! Tu cuenta se creó con Google.')
    else:
        messages.success(request, f'✅ Bienvenido de nuevo, {nombre_mostrado}.')
    return redirect('dashboard')


def ver_torneos_activos(request):
    # 🔥 AISLAMIENTO: Si el dirigente entra, solo le mostramos los torneos
    # de los complejos donde él ya tiene un equipo o ha jugado.
    mis_complejos = []
    if request.user.is_authenticated:
        # Canchas donde el usuario ya pertenece (como aficionado, dirigente...)
        mis_complejos = set(Equipo.objects.filter(dirigente=request.user).values_list('torneo__complejo_id', flat=True))
        mis_complejos |= set(RolComplejo.objects.filter(usuario=request.user).values_list('complejo_id', flat=True))
    
    # Filtramos la vista global para que no salgan todos los clientes mezclados
    torneos_activos = Torneo.objects.filter(activo=True, complejo_id__in=mis_complejos).order_by('categoria__nombre', 'fecha_inicio')
    torneos_finalizados = Torneo.objects.filter(activo=False, complejo_id__in=mis_complejos).order_by('-fecha_inicio')
    
    mis_torneos_ids = []
    if request.user.is_authenticated:
        mis_torneos_ids = list(Equipo.objects.filter(dirigente=request.user).values_list('torneo_id', flat=True))

    return render(request, 'core/ver_torneos_activos.html', {
        'torneos_activos': torneos_activos,
        'torneos_finalizados': torneos_finalizados,
        'mis_torneos_ids': mis_torneos_ids 
    })

@login_required
def solicitar_inscripcion(request, torneo_id):
    torneo = get_object_or_404(Torneo, id=torneo_id, activo=True, complejo__activo=True)
    
    if not torneo.inscripcion_abierta or torneo.campeonato_iniciado:
        messages.error(request, f'Lo sentimos, las inscripciones para el torneo {torneo.nombre} ya están cerradas.')
        return redirect('ver_torneos_activos')
    
    ya_inscrito = Equipo.objects.filter(torneo=torneo, dirigente=request.user).exists()
    if ya_inscrito:
        messages.warning(request, 'Ya tienes un equipo inscrito o en proceso para este torneo.')
        return redirect('ver_torneos_activos')

    if request.method == 'POST':
        form = EquipoSolicitudForm(request.POST, request.FILES) 
        if form.is_valid():
            equipo = form.save(commit=False)
            equipo.torneo = torneo
            equipo.dirigente = request.user
            equipo.estado_inscripcion = 'PENDIENTE' 
            equipo.save()

            if not torneo.cobro_por_jugador:
                costo_inscripcion = getattr(torneo, 'costo_inscripcion', Decimal('50.00')) 

                Sancion.objects.get_or_create(
                    equipo=equipo,
                    torneo=torneo,
                    descripcion=f"Inscripción - {torneo.nombre}",
                    defaults={
                        'tipo': 'ADMIN',
                        'monto': costo_inscripcion,
                        'monto_pagado': Decimal('0.00'),
                        'pagada': False
                    }
                )
            
            asegurar_rol_dirigente(request.user, torneo.complejo)
            
            # --- INICIO DEL NUEVO BLOQUE DE CORREO Y WHATSAPP ---
            try:
                from django.core.mail import send_mail
                from django.conf import settings
                
                # Obtenemos los datos EXCLUSIVOS del dueño de esta cancha
                email_organizador = torneo.complejo.organizador.email
                
                # Extraemos el teléfono personal del dirigente desde su Perfil
                telefono_dirigente = request.user.perfil.telefono if hasattr(request.user, 'perfil') and request.user.perfil.telefono else 'No registrado en perfil'
                
                asunto = f"NUEVA SOLICITUD: {equipo.nombre} quiere unirse a {torneo.nombre}"
                mensaje_correo = (
                    f"Hola {torneo.complejo.organizador.first_name},\n\n"
                    f"Se ha registrado una nueva solicitud de inscripción en tu complejo '{torneo.complejo.nombre}'.\n\n"
                    f"--- DATOS DE LA SOLICITUD ---\n"
                    f"Torneo: {torneo.nombre}\n"
                    f"Categoría: {torneo.categoria.nombre if torneo.categoria else 'Libre'}\n"
                    f"Equipo: {equipo.nombre}\n"
                    f"Dirigente: {request.user.first_name} {request.user.last_name} ({request.user.username})\n"
                    f"Celular Personal del Dirigente: {telefono_dirigente}\n"
                    f"Teléfono de Respaldo del Equipo: {equipo.telefono_contacto}\n"
                    f"Estado actual: PENDIENTE DE APROBACIÓN\n\n"
                    f"Por favor, ingresa al sistema NEXUS SPORTOPS para aprobar o rechazar esta solicitud.\n"
                )
                
                # Se envía al correo independiente del organizador de la cancha
                send_mail(
                    subject=asunto,
                    message=mensaje_correo,
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=[email_organizador],
                    fail_silently=True 
                )
            except Exception as e:
                print("Error enviando email:", e)

            # Generar enlace de WhatsApp para el dirigente
            import urllib.parse
            from django.utils.safestring import mark_safe
            
            # Obtenemos el número de la cancha específica
            telefono_organizador = torneo.complejo.telefono_contacto
            
            if telefono_organizador:
                mensaje_wa = f"Hola, acabo de enviar la solicitud de mi equipo '{equipo.nombre}' para el torneo '{torneo.nombre}'. Mi usuario es {request.user.username}. Quedo atento a la aprobación."
                mensaje_wa_codificado = urllib.parse.quote(mensaje_wa)
                url_whatsapp = f"https://wa.me/{telefono_organizador}?text={mensaje_wa_codificado}"
                
                texto_exito = mark_safe(
                    f"Solicitud enviada con éxito. Tu equipo está PENDIENTE de aprobación. "
                    f"<br><br><a href='{url_whatsapp}' target='_blank' style='background-color:#25D366; color:white; padding:10px 15px; text-decoration:none; border-radius:5px; display:inline-block; font-weight:bold; margin-top:10px;'>Notificar al Organizador por WhatsApp</a>"
                )
            else:
                texto_exito = "Solicitud enviada con éxito. Tu equipo está PENDIENTE de aprobación y el organizador fue notificado por correo."
                
            messages.success(request, texto_exito)
            return redirect('ver_torneos_activos') 
            # --- FIN DEL BLOQUE ---
            # --- FIN DEL NUEVO BLOQUE ---

    else:
        # Se ejecuta cuando el método es GET (cuando recién entras a la página)
        form = EquipoSolicitudForm()

    # ¡ESTA ES LA LÍNEA QUE FALTABA O SE BORRÓ! Siempre debe retornar algo al final.
    return render(request, 'core/solicitar_inscripcion.html', {'form': form, 'torneo': torneo})


@login_required
@user_passes_test(es_organizador)
def gestionar_solicitudes(request):
    mi_complejo = obtener_mi_complejo(request.user)
    solicitudes = Equipo.objects.filter(torneo__complejo=mi_complejo, estado_inscripcion='PENDIENTE').select_related('torneo', 'dirigente')
    
    if request.method == 'POST':
        equipo_id = request.POST.get('equipo_id')
        accion = request.POST.get('accion') 
        equipo = get_object_or_404(Equipo, id=equipo_id, torneo__complejo=mi_complejo)
        
        if accion == 'APROBAR' and equipo.torneo.campeonato_iniciado:
            messages.error(request, f'⛔ El campeonato "{equipo.torneo.nombre}" ya empezó: no se pueden sumar equipos nuevos (alteraría el fixture).')
            return redirect('gestionar_solicitudes')
        if accion == 'APROBAR':
            equipo.estado_inscripcion = 'APROBADO'
            equipo.save()
            asegurar_rol_dirigente(equipo.dirigente, mi_complejo)
            
            # Notificación de aprobación
            try:
                from django.core.mail import send_mail
                from django.conf import settings
                asunto = f"Solicitud APROBADA: {equipo.nombre} en {equipo.torneo.nombre}"
                mensaje = (
                    f"Hola {equipo.dirigente.first_name},\n\n"
                    f"Buenas noticias. Tu equipo '{equipo.nombre}' ha sido APROBADO para participar en el torneo '{equipo.torneo.nombre}' del complejo '{mi_complejo.nombre}'.\n\n"
                    f"Ya puedes ingresar al sistema para gestionar tu plantilla de jugadores.\n"
                )
                send_mail(asunto, mensaje, settings.EMAIL_HOST_USER, [equipo.dirigente.email], fail_silently=True)
            except Exception as e:
                print("Error enviando email de aprobacion:", e)

            messages.success(request, f'El equipo {equipo.nombre} ha sido APROBADO.')
            
        elif accion == 'RECHAZAR':
            equipo.estado_inscripcion = 'RECHAZADO'
            equipo.save()
            
            # Notificación de rechazo
            try:
                from django.core.mail import send_mail
                from django.conf import settings
                asunto = f"Solicitud RECHAZADA: {equipo.nombre} en {equipo.torneo.nombre}"
                mensaje = (
                    f"Hola {equipo.dirigente.first_name},\n\n"
                    f"Lamentamos informarte que la solicitud de tu equipo '{equipo.nombre}' para el torneo '{equipo.torneo.nombre}' ha sido RECHAZADA por el organizador.\n\n"
                    f"Para más detalles, comunícate directamente con la administración del complejo '{mi_complejo.nombre}'.\n"
                )
                send_mail(asunto, mensaje, settings.EMAIL_HOST_USER, [equipo.dirigente.email], fail_silently=True)
            except Exception as e:
                print("Error enviando email de rechazo:", e)

            messages.warning(request, f'Solicitud de {equipo.nombre} rechazada.')

        return redirect('gestionar_solicitudes')

    return render(request, 'core/gestionar_solicitudes.html', {'solicitudes': solicitudes})

@login_required
def cancelar_inscripcion_equipo(request, equipo_id):
    equipo = get_object_or_404(Equipo, id=equipo_id)
    rol_principal = obtener_rol_principal(request.user)
    es_admin_de_esta_cancha = (
        rol_principal == 'ORG' and equipo.torneo.complejo == obtener_mi_complejo(request.user)
    )

    if request.user != equipo.dirigente and not es_admin_de_esta_cancha:
        return redirect('dashboard')

    precio_inscripcion = float(equipo.torneo.costo_inscripcion)
    
    if equipo.estado_inscripcion == 'APROBADO':
        multa = precio_inscripcion * 0.25
        mensaje = "⚠️ Equipo ya aprobado. Se retiene el 25% por gastos administrativos."
    else:
        multa = 0
        mensaje = "✅ Solicitud cancelada antes de aprobación. Sin costo."

    reembolso = precio_inscripcion - multa

    if request.method == 'POST':
        equipo.estado_inscripcion = 'RECHAZADO' 
        equipo.monto_reembolso = reembolso
        equipo.save()
        messages.info(request, f"Inscripción Cancelada. {mensaje} Reembolso: ${reembolso}")
        return redirect('ver_torneos_activos')

    return render(request, 'core/confirmar_cancelacion.html', {
        'objeto': equipo,
        'tipo': f"Inscripción Equipo {equipo.nombre}",
        'multa': multa,
        'reembolso': reembolso,
        'extra_info': "Estado actual: " + equipo.get_estado_inscripcion_display()
    })

@login_required
@user_passes_test(es_organizador)
def cobrar_sancion(request, sancion_id):
    mi_complejo = obtener_mi_complejo(request.user)
    sancion = get_object_or_404(Sancion, id=sancion_id, torneo__complejo=mi_complejo)
    
    if request.method == 'POST':
        abono = _monto_abono(request, sancion)
        if abono is None:
            messages.error(request, f"⛔ Monto inválido. Debe ser mayor a $0 y máximo ${sancion.saldo}.")
            return redirect(request.META.get('HTTP_REFERER', 'gestionar_finanzas'))
        with transaction.atomic():
            sancion.monto_pagado += abono
            if sancion.monto_pagado >= sancion.monto:
                sancion.pagada = True
                sancion.monto_pagado = sancion.monto 
                messages.success(request, f"¡Deuda de {sancion.equipo.nombre} cancelada en su totalidad!")
            else:
                messages.success(request, f"Abono de ${abono} registrado. Saldo pendiente: ${sancion.saldo}")
            sancion.save()
            AbonoSancion.objects.create(sancion=sancion, monto=abono)
        
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))


@login_required
@user_passes_test(es_organizador)
def gestionar_finanzas(request):
    mi_complejo = obtener_mi_complejo(request.user)
        
    if request.method == 'POST' and 'agregar_sancion_manual' in request.POST:
        form_sancion = SancionManualForm(request.POST)
        form_sancion.fields['torneo'].queryset = Torneo.objects.filter(complejo=mi_complejo)
        form_sancion.fields['equipo'].queryset = Equipo.objects.filter(torneo__complejo=mi_complejo)
        
        if form_sancion.is_valid() and form_sancion.cleaned_data['equipo'].torneo_id != form_sancion.cleaned_data['torneo'].id:
            messages.error(request, "⛔ El equipo no pertenece a ese torneo.")
            return redirect('gestionar_finanzas')
        if form_sancion.is_valid() and form_sancion.cleaned_data['monto'] <= 0:
            messages.error(request, "⛔ El monto debe ser mayor a $0.")
            return redirect('gestionar_finanzas')
        if form_sancion.is_valid():
            nueva_sancion = form_sancion.save(commit=False)
            nueva_sancion.tipo = 'ADMIN'
            nueva_sancion.pagada = False
            from decimal import Decimal
            nueva_sancion.monto_pagado = Decimal('0.00')
            nueva_sancion.save()
            messages.success(request, f'✅ Sanción agregada a {nueva_sancion.equipo.nombre}.')
            return redirect('gestionar_finanzas')

    if request.method == 'POST' and 'generar_inscripciones_viejas' in request.POST:
        equipos_aprobados = Equipo.objects.filter(torneo__complejo=mi_complejo, estado_inscripcion='APROBADO')
        agregados = 0
        from decimal import Decimal
        for eq in equipos_aprobados:
            ya_cobrado = Sancion.objects.filter(equipo=eq, descripcion__icontains='Inscripci').exists()
            if not ya_cobrado and not eq.torneo.cobro_por_jugador:
                Sancion.objects.create(
                    torneo=eq.torneo, equipo=eq, tipo='ADMIN',
                    monto=getattr(eq.torneo, 'costo_inscripcion', Decimal('50.00')),
                    monto_pagado=Decimal('0.00'), descripcion=f"Inscripción al Torneo {eq.torneo.nombre}", pagada=False
                )
                agregados += 1
        messages.success(request, f'✅ Se generaron {agregados} recibos de inscripción.')
        return redirect('gestionar_finanzas')

    form_sancion = SancionManualForm()
    form_sancion.fields['torneo'].queryset = Torneo.objects.filter(complejo=mi_complejo)
    form_sancion.fields['equipo'].queryset = Equipo.objects.filter(torneo__complejo=mi_complejo)

    from decimal import Decimal
    inscripciones = Sancion.objects.filter(torneo__complejo=mi_complejo, descripcion__icontains='Inscripci')
    inscripciones_pagadas_totalmente = inscripciones.filter(pagada=True).aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
    abonos_inscripciones = inscripciones.filter(pagada=False).aggregate(Sum('monto_pagado'))['monto_pagado__sum'] or Decimal('0.00')
    dinero_real_inscripciones = inscripciones_pagadas_totalmente + abonos_inscripciones
    inscripciones_pendientes = inscripciones.filter(pagada=False).aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
    saldo_real_inscripciones = inscripciones_pendientes - abonos_inscripciones
    
    multas = Sancion.objects.filter(torneo__complejo=mi_complejo).exclude(descripcion__icontains='Inscripci')
    multas_pagadas_totalmente = multas.filter(pagada=True).aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
    abonos_multas = multas.filter(pagada=False).aggregate(Sum('monto_pagado'))['monto_pagado__sum'] or Decimal('0.00')
    dinero_real_multas = multas_pagadas_totalmente + abonos_multas
    multas_pendientes = multas.filter(pagada=False).aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
    saldo_real_multas = multas_pendientes - abonos_multas
    
    lista_sanciones = Sancion.objects.filter(torneo__complejo=mi_complejo).select_related('equipo', 'torneo').order_by('pagada', '-id')

    query = request.GET.get('q')
    if query:
        lista_sanciones = lista_sanciones.filter(equipo__nombre__icontains=query)

    torneo_filtro_id = request.GET.get('torneo')
    if torneo_filtro_id and torneo_filtro_id.isdigit():
        lista_sanciones = lista_sanciones.filter(torneo_id=torneo_filtro_id)

    torneos_lista = Torneo.objects.filter(complejo=mi_complejo)

    paginator_sanciones = Paginator(lista_sanciones, 20)
    lista_sanciones = paginator_sanciones.get_page(request.GET.get('page'))

    ctx = {
        'form_sancion': form_sancion,
        'torneos_lista': torneos_lista,
        'ingreso_canchas': 0.00,
        'inscripciones_pagadas': float(dinero_real_inscripciones),
        'inscripciones_pendientes': float(saldo_real_inscripciones),
        'multas_pagadas': float(dinero_real_multas),
        'multas_pendientes': float(saldo_real_multas),
        'total_caja': float(dinero_real_inscripciones + dinero_real_multas),
        'sanciones': lista_sanciones
    }
    return render(request, 'core/gestionar_finanzas.html', ctx)

@login_required
@user_passes_test(es_organizador)
def trazabilidad_financiera(request):
    """Historial completo de movimientos de dinero de ESTA cancha: quién
    cobró, quién reversó, qué multa se borró y desde dónde (mesa o finanzas)."""
    mi_complejo = obtener_mi_complejo(request.user)
    movimientos = MovimientoFinanciero.objects.filter(complejo=mi_complejo).select_related('usuario', 'torneo', 'partido')

    f = {k: request.GET.get(k, '') for k in ('tipo', 'origen', 'usuario', 'torneo', 'desde', 'hasta', 'q')}
    if f['tipo'] in dict(MovimientoFinanciero.TIPOS):
        movimientos = movimientos.filter(tipo=f['tipo'])
    if f['origen'] in dict(MovimientoFinanciero.ORIGENES):
        movimientos = movimientos.filter(origen=f['origen'])
    if f['usuario'].isdigit():
        movimientos = movimientos.filter(usuario_id=f['usuario'])
    if f['torneo'].isdigit():
        movimientos = movimientos.filter(torneo_id=f['torneo'])
    for clave, lookup in (('desde', 'fecha__date__gte'), ('hasta', 'fecha__date__lte')):
        try:
            if f[clave]:
                movimientos = movimientos.filter(**{lookup: datetime.strptime(f[clave], '%Y-%m-%d').date()})
        except ValueError:
            f[clave] = ''
    if f['q']:
        movimientos = movimientos.filter(Q(equipo_nombre__icontains=f['q']) | Q(descripcion__icontains=f['q']))

    totales = {r['tipo']: r['total'] for r in movimientos.values('tipo').annotate(total=Sum('monto'))}
    cobrado = (totales.get('ABONO') or 0) + (totales.get('PAGO') or 0)
    reversado = totales.get('REVERSO') or 0

    pagina = Paginator(movimientos, 30).get_page(request.GET.get('page'))
    usuarios = User.objects.filter(id__in=MovimientoFinanciero.objects.filter(complejo=mi_complejo).exclude(
        usuario=None).values('usuario_id').distinct()).order_by('username')
    query_sin_pagina = request.GET.copy()
    query_sin_pagina.pop('page', None)
    return render(request, 'core/trazabilidad_financiera.html', {
        'movimientos': pagina, 'f': f, 'totales': totales,
        'cobrado': cobrado, 'reversado': reversado, 'neto': cobrado - reversado,
        'cargos': totales.get('CARGO') or 0, 'anulado': totales.get('ANULACION') or 0,
        'tipos': MovimientoFinanciero.TIPOS, 'origenes': MovimientoFinanciero.ORIGENES,
        'usuarios': usuarios, 'torneos': Torneo.objects.filter(complejo=mi_complejo).order_by('-id'),
        'query_string': query_sin_pagina.urlencode(),
    })


@login_required
@user_passes_test(es_organizador)
def notificar_equipo_whatsapp(request, equipo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    equipo = get_object_or_404(Equipo, id=equipo_id, torneo__complejo=mi_complejo)

    numero = equipo.telefono_contacto or (equipo.dirigente.perfil.telefono if hasattr(equipo.dirigente, 'perfil') else None)
    if not numero:
        messages.error(request, f"⚠️ El equipo {equipo.nombre} no tiene un número de celular registrado.")
        return redirect(request.META.get('HTTP_REFERER', 'gestionar_finanzas'))

    sanciones = equipo.sanciones.all().order_by('-fecha_creacion')

    total_pagado = Decimal('0.00')
    total_pendiente = Decimal('0.00')
    lineas_deuda = []
    lineas_pagos = []

    for s in sanciones:
        total_pagado += s.monto_pagado
        if s.pagada:
            lineas_pagos.append(f"✅ {s.descripcion}: ${s.monto}")
        else:
            total_pendiente += s.saldo
            lineas_deuda.append(f"🔸 {s.descripcion}: ${s.saldo}")
            if s.monto_pagado > 0:
                lineas_pagos.append(f"✅ Abono a \"{s.descripcion}\": ${s.monto_pagado}")

    detalle_deuda = "\n".join(lineas_deuda) if lineas_deuda else "Sin deudas pendientes."
    detalle_pagos = "\n".join(lineas_pagos) if lineas_pagos else "Sin pagos registrados."

    mensaje = (
        "Estimado/a dirigente:\n\n"
        f"Reciba un cordial saludo de parte de {mi_complejo.nombre}.\n\n"
        f"Por medio del presente le informamos el estado de cuenta de su equipo *{equipo.nombre}*:\n\n"
        f"*Total de pagos realizados:* ${total_pagado}\n"
        f"*Saldo pendiente:* ${total_pendiente}\n\n"
        "Detalle de lo que debe:\n"
        f"{detalle_deuda}\n\n"
        "Detalle de pagos realizados:\n"
        f"{detalle_pagos}\n\n"
        "Agradecemos realizar los pagos pendientes dentro de los plazos establecidos.\n\n"
        f"*{mi_complejo.nombre}*"
    )

    numero_limpio = numero.strip().replace(" ", "").replace("-", "")
    if numero_limpio.startswith("0"):
        numero_limpio = "593" + numero_limpio[1:]
    elif not numero_limpio.startswith("593"):
        numero_limpio = "593" + numero_limpio

    mensaje_codificado = urllib.parse.quote(mensaje)
    return redirect(f"https://wa.me/{numero_limpio}?text={mensaje_codificado}")

@login_required
@user_passes_test(es_organizador)
def cierre_diario_caja(request):
    """Cierre de caja diaria: agrupa los movimientos financieros de UNA
    fecha, siempre acotados a la cancha del organizador que consulta."""
    mi_complejo = obtener_mi_complejo(request.user)

    fecha_get = request.GET.get('fecha')
    if fecha_get:
        try:
            fecha_consulta = datetime.strptime(fecha_get, '%Y-%m-%d').date()
        except ValueError:
            fecha_consulta = timezone.localtime(timezone.now()).date()
    else:
        fecha_consulta = timezone.localtime(timezone.now()).date()

    # 1. Inscripciones cobradas el día (abonos + pagos directos vía Sancion)
    abonos_inscripcion_dia = AbonoSancion.objects.filter(
        fecha__date=fecha_consulta,
        sancion__torneo__complejo=mi_complejo,
        sancion__descripcion__icontains='Inscripci',
    ).select_related('sancion', 'sancion__equipo')

    inscripciones_cobradas = []
    total_inscripciones = Decimal('0.00')
    for abono in abonos_inscripcion_dia:
        inscripciones_cobradas.append({
            'equipo': abono.sancion.equipo,
            'descripcion': abono.sancion.descripcion,
            'monto': abono.monto,
        })
        total_inscripciones += abono.monto

    inscripciones_pagadas_directas = Sancion.objects.filter(
        torneo__complejo=mi_complejo,
        fecha_creacion__date=fecha_consulta,
        descripcion__icontains='Inscripci',
        pagada=True,
    ).select_related('equipo')

    for s in inscripciones_pagadas_directas:
        if s.monto_pagado > 0 and not abonos_inscripcion_dia.filter(sancion=s).exists():
            inscripciones_cobradas.append({
                'equipo': s.equipo,
                'descripcion': s.descripcion,
                'monto': s.monto_pagado,
            })
            total_inscripciones += s.monto_pagado

    # 2. Multas cobradas el día (amarillas, rojas, administrativas)
    abonos_multas_dia = AbonoSancion.objects.filter(
        fecha__date=fecha_consulta,
        sancion__torneo__complejo=mi_complejo,
    ).exclude(
        sancion__descripcion__icontains='Inscripci'
    ).select_related('sancion', 'sancion__equipo', 'sancion__jugador', 'sancion__partido')

    multas_cobradas = []
    total_multas = Decimal('0.00')
    for abono in abonos_multas_dia:
        multas_cobradas.append({
            'equipo': abono.sancion.equipo,
            'descripcion': abono.sancion.descripcion,
            'monto': abono.monto,
            'tipo': abono.sancion.get_tipo_display(),
            'jugador': abono.sancion.jugador,
        })
        total_multas += abono.monto

    # 3. Pagos directos de equipos el día
    pagos_dia = Pago.objects.filter(
        equipo__torneo__complejo=mi_complejo,
        fecha=fecha_consulta,
    ).select_related('equipo')

    pagos_lista = []
    total_pagos_directos = Decimal('0.00')
    for pago in pagos_dia:
        pagos_lista.append({
            'equipo': pago.equipo,
            'monto': pago.monto,
            'observacion': pago.observacion or 'Abono general',
        })
        total_pagos_directos += pago.monto

    total_ingresos = total_inscripciones + total_multas + total_pagos_directos

    ctx = {
        'fecha_seleccionada': fecha_consulta,
        'fecha_hoy': timezone.localtime(timezone.now()).date(),
        'inscripciones_cobradas': inscripciones_cobradas,
        'total_inscripciones': float(total_inscripciones),
        'multas_cobradas': multas_cobradas,
        'total_multas': float(total_multas),
        'pagos_directos': pagos_lista,
        'total_pagos_directos': float(total_pagos_directos),
        'total_ingresos': float(total_ingresos),
    }
    return render(request, 'core/cierre_diario_caja.html', ctx)

@login_required
@user_passes_test(es_organizador)
def admin_gestion_jugadores(request):
    mi_complejo = obtener_mi_complejo(request.user)
    query = request.GET.get('q')
    jugadores = Jugador.objects.filter(equipo__torneo__complejo=mi_complejo).select_related('equipo').order_by('equipo', 'dorsal')
    
    if query:
        jugadores = jugadores.filter(
            Q(nombres__icontains=query) |  
            Q(equipo__nombre__icontains=query) |
            Q(cedula__icontains=query)
        )

    return render(request, 'core/admin_jugadores.html', {'jugadores': jugadores})

@login_required
@user_passes_test(es_organizador)
def admin_gestion_usuarios(request):
    # Esto ya se cubre con gestionar_usuarios, pero si tienes una ruta separada:
    return redirect('gestionar_usuarios')

# =========================================================
# VISTAS RESTAURADAS (Medios y Próxima Jornada)
# =========================================================

@login_required
@user_passes_test(es_organizador)
def gestionar_medios(request):
    mi_complejo = obtener_mi_complejo(request.user)
    fotos = FotoGaleria.objects.filter(complejo=mi_complejo).order_by('orden', '-id')

    if request.method == 'POST':
        if 'btn_foto' in request.POST:
            imagenes = request.FILES.getlist('imagen')
            if imagenes:
                titulo = request.POST.get('titulo', '')
                orden_str = request.POST.get('orden', '0')
                orden = int(orden_str) if orden_str.isdigit() else 0
                activa = request.POST.get('activa') == 'on'

                for imagen in imagenes:
                    FotoGaleria.objects.create(
                        complejo=mi_complejo, imagen=imagen,
                        titulo=titulo, orden=orden, activa=activa,
                    )
                messages.success(request, f'📸 Se han subido {len(imagenes)} fotos a la galería con éxito.')
            else:
                messages.error(request, '⚠️ Debes seleccionar al menos una imagen para subir.')
            return redirect('gestionar_medios')

    form_foto = FotoGaleriaForm()
    return render(request, 'core/gestionar_medios.html', {
        'fotos': fotos, 'form_foto': form_foto
    })

@login_required
@user_passes_test(es_organizador)
@require_POST
def eliminar_foto(request, foto_id):
    mi_complejo = obtener_mi_complejo(request.user)
    foto = get_object_or_404(FotoGaleria, id=foto_id, complejo=mi_complejo)
    foto.delete()
    messages.warning(request, "🗑️ Foto eliminada.")
    return redirect('gestionar_medios')

@login_required
@user_passes_test(es_organizador)
def generar_horarios_imagen(request):
    mi_complejo = obtener_mi_complejo(request.user)
    ahora = timezone.localtime(timezone.now())

    partidos = Partido.objects.filter(
        torneo__complejo=mi_complejo,
        estado='PROG',
        fecha_hora__gte=ahora,
    ).select_related('equipo_local', 'equipo_visita', 'torneo', 'torneo__categoria').order_by('fecha_hora')

    for p in partidos:
        p.fecha_local = timezone.localtime(p.fecha_hora).date()

    return render(request, 'core/horarios_imagen.html', {
        'complejo': mi_complejo,
        'partidos': partidos,
        'generado_en': ahora,
    })

@login_required
def mis_finanzas_equipo(request):
    mis_equipos = Equipo.objects.filter(dirigente=request.user)
    equipo_simulado = obtener_equipo_simulado(request)
    equipo_id = request.GET.get('equipo') or (equipo_simulado.id if equipo_simulado else None)
    # 🔥 Si el ID pedido no es un equipo propio (ajeno o inexistente), cae
    # de vuelta al primer equipo propio en vez de mostrar la pantalla vacía.
    mi_equipo = (mis_equipos.filter(id=equipo_id).first() if equipo_id else None) or mis_equipos.first()

    if mi_equipo:
        mis_sanciones = Sancion.objects.filter(equipo=mi_equipo).order_by('-id')
        total_deuda = sum(s.saldo for s in mis_sanciones if not s.pagada)
        total_pagado = sum(s.monto_pagado for s in mis_sanciones)
    else:
        mis_sanciones = []
        total_deuda = 0
        total_pagado = 0

    return render(request, 'core/mis_finanzas_equipo.html', {
        'equipo': mi_equipo,
        'mis_equipos': mis_equipos,
        'sanciones': mis_sanciones,
        'total_deuda': total_deuda,
        'total_pagado': total_pagado,
    })


def proxima_jornada(request, torneo_id):
    torneo = get_object_or_404(Torneo, id=torneo_id)
    partidos_futuros = Partido.objects.filter(torneo=torneo, estado='PROG').exclude(fecha_hora__isnull=True).order_by('fecha_hora')
    partidos_mostrar = []
    jornada_num = None
    etapa_nombre = None

    if partidos_futuros.exists():
        prox_partido = partidos_futuros.first()
        jornada_num = prox_partido.numero_fecha
        etapa_nombre = prox_partido.get_etapa_display()
        partidos_mostrar = Partido.objects.filter(torneo=torneo, etapa=prox_partido.etapa, numero_fecha=jornada_num).order_by('fecha_hora')
    else:
        partidos_pendientes = Partido.objects.filter(torneo=torneo, estado='PROG').order_by('etapa', 'numero_fecha')
        if partidos_pendientes.exists():
            prox_partido = partidos_pendientes.first()
            jornada_num = prox_partido.numero_fecha
            etapa_nombre = prox_partido.get_etapa_display()
            partidos_mostrar = Partido.objects.filter(torneo=torneo, etapa=prox_partido.etapa, numero_fecha=jornada_num).order_by('id')
            
    return render(request, 'core/proxima_jornada.html', {'torneo': torneo, 'partidos': partidos_mostrar, 'jornada': jornada_num, 'etapa': etapa_nombre})


# =========================================================
# 8. GENERADOR AUTOMÁTICO DE FIXTURES (IDA Y VUELTA)
# =========================================================

@login_required
@user_passes_test(es_organizador)
def generar_fixture(request, torneo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    torneo = get_object_or_404(Torneo, id=torneo_id, complejo=mi_complejo)
    if torneo.formato != 'CLASICO':
        messages.error(request, "⛔ Este torneo usa el nuevo sistema de campeonato. Usa «Empezar campeonato» y la vista de grupos y llaves.")
        return redirect('ver_campeonato', torneo_id=torneo.id)
    equipos = list(Equipo.objects.filter(torneo=torneo, estado_inscripcion='APROBADO'))
    
    if len(equipos) < 2:
        messages.error(request, "Necesitas al menos 2 equipos APROBADOS para generar un fixture.")
        return redirect('gestionar_torneos')

    if len(equipos) % 2 != 0:
        equipos.append(None) 
    
    n = len(equipos)
    fixture = []
    equipos_rotacion = equipos.copy()

    for fecha in range(1, n):
        partidos_fecha = []
        for i in range(n // 2):
            local = equipos_rotacion[i]
            visita = equipos_rotacion[n - 1 - i]
            if local is not None and visita is not None:
                if i == 0 and fecha % 2 == 0: partidos_fecha.append({'local': visita, 'visita': local})
                else: partidos_fecha.append({'local': local, 'visita': visita})
        
        fixture.append({'numero_fecha': fecha, 'partidos': partidos_fecha})
        equipos_rotacion.insert(1, equipos_rotacion.pop())

    if request.method == 'POST':
        accion = request.POST.get('accion')
        
        ida_y_vuelta_activado = request.POST.get('ida_y_vuelta_f1') == 'on'
        torneo.fase1_ida_vuelta = ida_y_vuelta_activado
        torneo.save()

        if torneo.fase1_ida_vuelta:
            n_fechas_ida = len(fixture)
            fixture_vuelta = []
            for j in fixture:
                partidos_vuelta = [{'local': p['visita'], 'visita': p['local']} for p in j['partidos']]
                fixture_vuelta.append({'numero_fecha': j['numero_fecha'] + n_fechas_ida, 'partidos': partidos_vuelta})
            fixture.extend(fixture_vuelta)

        if accion == 'guardar_db':
            partidos_creados = 0
            with transaction.atomic():
                for jornada in fixture:
                    num_fecha = jornada['numero_fecha']
                    for p in jornada['partidos']:
                        existe = Partido.objects.filter(torneo=torneo, etapa='F1', equipo_local=p['local'], equipo_visita=p['visita']).exists()
                        if not existe:
                            Partido.objects.create(
                                torneo=torneo, etapa='F1', numero_fecha=num_fecha, 
                                equipo_local=p['local'], equipo_visita=p['visita'], 
                                estado='PROG', fecha_hora=None
                            )
                            partidos_creados += 1
            
            formato_texto = "IDA Y VUELTA" if torneo.fase1_ida_vuelta else "SOLO IDA"
            messages.success(request, f'✅ Fixture generado en formato {formato_texto}: {partidos_creados} partidos agregados al calendario.')
            return redirect(f"/programar/?torneo={torneo.id}")
            
        elif accion == 'descargar_pdf':
            template_path = 'core/fixture_pdf.html'
            context = {'torneo': torneo, 'fixture': fixture}
            response = HttpResponse(content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="Fixture_{torneo.nombre}.pdf"'
            template = get_template(template_path)
            html = template.render(context)
            pisa_status = pisa.CreatePDF(html, dest=response)
            if pisa_status.err: return HttpResponse('Error al generar PDF <pre>' + html + '</pre>')
            return response

    return render(request, 'core/generar_fixture.html', {'torneo': torneo, 'fixture': fixture, 'total_equipos': len(equipos) if None not in equipos else (len(equipos) - 1)})


# =========================================================
# 9. MAGIA: TRANSICIONES Y LLAVES ELIMINATORIAS 
# =========================================================

def obtener_clasificados_fase1(torneo, excluidos=frozenset()):
    tabla = [f for f in motor.tabla_liga(torneo, 'F1') if f['equipo'].id not in excluidos]
    for i, f in enumerate(tabla, start=1):
        f['pos'] = i
    return tabla


def _excluidos_post(request, torneo):
    """Equipos que el organizador saca de la siguiente fase (formato clásico)."""
    validos = set(Equipo.objects.filter(torneo=torneo).values_list('id', flat=True))
    return {int(x) for x in request.POST.getlist('excluir') if x.isdigit() and int(x) in validos}

def obtener_clasificados_fase2(torneo, letra_grupo):
    equipos = list(Equipo.objects.filter(torneo=torneo, grupo_fase2=letra_grupo, estado_inscripcion='APROBADO'))
    partidos = list(Partido.objects.filter(torneo=torneo, etapa='F2'))
    return motor.calcular_tabla(equipos, partidos, con_bono=True)[:4]

def obtener_ganador_llave(torneo, etapa, eq1, eq2):
    partidos = Partido.objects.filter(torneo=torneo, etapa=etapa, equipo_local__in=[eq1, eq2], equipo_visita__in=[eq1, eq2])
    if not partidos.exists(): return None
    for p in partidos:
        if p.estado not in ['JUG', 'WO', 'FINALIZADO']: return None

    goles_eq1 = 0; goles_eq2 = 0; penales_eq1 = 0; penales_eq2 = 0
    for p in partidos:
        if p.equipo_local == eq1:
            goles_eq1 += p.goles_local; goles_eq2 += p.goles_visita
            if p.hubo_penales: penales_eq1 += p.penales_local; penales_eq2 += p.penales_visita
        else:
            goles_eq1 += p.goles_visita; goles_eq2 += p.goles_local
            if p.hubo_penales: penales_eq1 += p.penales_visita; penales_eq2 += p.penales_local

    if goles_eq1 > goles_eq2: return eq1
    elif goles_eq2 > goles_eq1: return eq2
    else:
        if penales_eq1 > penales_eq2: return eq1
        elif penales_eq2 > penales_eq1: return eq2
    return None 

# =========================================================
# VISTAS DE TRANSICIÓN DIRECTA (CON FIXTURE)
# =========================================================

@login_required
@user_passes_test(es_organizador)
def generar_cuartos_directos(request, torneo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    torneo = get_object_or_404(Torneo, id=torneo_id, complejo=mi_complejo)
    if torneo.formato != 'CLASICO':
        messages.error(request, "⛔ Este torneo usa el nuevo sistema de campeonato. Usa «Empezar campeonato» y la vista de grupos y llaves.")
        return redirect('ver_campeonato', torneo_id=torneo.id)
    if 'ida_y_vuelta' in request.POST and request.POST.get('accion') not in ('guardar_db', 'descargar_pdf'):
        torneo.fase3_ida_vuelta = request.POST.get('ida_y_vuelta') == 'on'
        torneo.save(update_fields=['fase3_ida_vuelta'])
    elif request.POST.get('accion') is None and request.method == 'POST':
        torneo.fase3_ida_vuelta = False
        torneo.save(update_fields=['fase3_ida_vuelta'])
    excluidos = _excluidos_post(request, torneo)
    clasificados = obtener_clasificados_fase1(torneo, excluidos)
    
    if len(clasificados) < 8:
        messages.error(request, "⚠️ Mínimo 8 equipos registrados con resultados para hacer Cuartos de Final.")
        return redirect('tabla_posiciones', torneo_id=torneo.id)
    
    cruces = [
        (clasificados[0]['equipo'], clasificados[7]['equipo']),
        (clasificados[1]['equipo'], clasificados[6]['equipo']),
        (clasificados[2]['equipo'], clasificados[5]['equipo']),
        (clasificados[3]['equipo'], clasificados[4]['equipo']),
    ]

    fixture = []
    fixture.append({'numero_fecha': 'IDA (Cuartos)', 'partidos': [{'local': c[0], 'visita': c[1]} for c in cruces]})
    if torneo.fase3_ida_vuelta:
        fixture.append({'numero_fecha': 'VUELTA (Cuartos)', 'partidos': [{'local': c[1], 'visita': c[0]} for c in cruces]})

    if request.method == 'POST' and request.POST.get('accion') == 'guardar_db':
        with transaction.atomic():
            for local, visita in cruces:
                Partido.objects.create(torneo=torneo, equipo_local=local, equipo_visita=visita, etapa='4TOS', numero_fecha=1)
                if torneo.fase3_ida_vuelta:
                    Partido.objects.create(torneo=torneo, equipo_local=visita, equipo_visita=local, etapa='4TOS', numero_fecha=2)

        formato = "Ida y Vuelta" if torneo.fase3_ida_vuelta else "Partido Único"
        messages.success(request, f"✅ Cuartos de final ({formato}) generados y guardados en el calendario.")
        return redirect('llaves_eliminatorias', torneo_id=torneo.id)
    if request.POST.get('accion') == 'descargar_pdf':
        return _pdf_fixture(torneo, [{'titulo': j['numero_fecha'], 'partidos': j['partidos']} for j in fixture], 'Cuartos de final', f"Cuartos_{torneo.nombre}")

    return render(request, 'core/generar_fixture.html', {'torneo': torneo, 'fixture': fixture, 'total_equipos': 8, 'excluidos': excluidos})

@login_required
@user_passes_test(es_organizador)
def generar_semis_directas(request, torneo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    torneo = get_object_or_404(Torneo, id=torneo_id, complejo=mi_complejo)
    if torneo.formato != 'CLASICO':
        messages.error(request, "⛔ Este torneo usa el nuevo sistema de campeonato. Usa «Empezar campeonato» y la vista de grupos y llaves.")
        return redirect('ver_campeonato', torneo_id=torneo.id)
    
    if Partido.objects.filter(torneo=torneo, etapa='SEMI').exists():
        messages.error(request, "Las Semifinales ya fueron generadas.")
        return redirect(f"/programar/?torneo={torneo.id}")

    if request.method == 'POST' and request.POST.get('accion') not in ('guardar_db', 'descargar_pdf'):
        torneo.fase3_ida_vuelta = request.POST.get('ida_y_vuelta') == 'on'
        torneo.save()

    excluidos = _excluidos_post(request, torneo)
    clasificados = obtener_clasificados_fase1(torneo, excluidos)
    if len(clasificados) < 4:
        messages.error(request, "⚠️ Mínimo 4 equipos con resultados para generar Semifinales.")
        return redirect('tabla_posiciones', torneo_id=torneo.id)

    cruces = [
        (clasificados[0]['equipo'], clasificados[3]['equipo']),
        (clasificados[1]['equipo'], clasificados[2]['equipo']),
    ]

    fixture = []
    fixture.append({'numero_fecha': 'IDA (Semifinal)', 'partidos': [{'local': c[0], 'visita': c[1]} for c in cruces]})
    if torneo.fase3_ida_vuelta:
        fixture.append({'numero_fecha': 'VUELTA (Semifinal)', 'partidos': [{'local': c[1], 'visita': c[0]} for c in cruces]})

    if request.method == 'POST' and request.POST.get('accion') == 'guardar_db':
        with transaction.atomic():
            for local, visita in cruces:
                Partido.objects.create(torneo=torneo, equipo_local=local, equipo_visita=visita, etapa='SEMI', numero_fecha=1)
                if torneo.fase3_ida_vuelta:
                    Partido.objects.create(torneo=torneo, equipo_local=visita, equipo_visita=local, etapa='SEMI', numero_fecha=2)

        formato = "Ida y Vuelta" if torneo.fase3_ida_vuelta else "Partido Único"
        messages.success(request, f"✅ Semifinales ({formato}) generadas y guardadas en el calendario.")
        return redirect('llaves_eliminatorias', torneo_id=torneo.id)
    if request.POST.get('accion') == 'descargar_pdf':
        return _pdf_fixture(torneo, [{'titulo': j['numero_fecha'], 'partidos': j['partidos']} for j in fixture], 'Semifinales', f"Semifinales_{torneo.nombre}")
        
    return render(request, 'core/generar_fixture.html', {'torneo': torneo, 'fixture': fixture, 'total_equipos': 4, 'excluidos': excluidos})


@login_required
@user_passes_test(es_organizador)
def generar_cuartos_final(request, torneo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    torneo = get_object_or_404(Torneo, id=torneo_id, complejo=mi_complejo)
    if torneo.formato != 'CLASICO':
        messages.error(request, "⛔ Este torneo usa el nuevo sistema de campeonato. Usa «Empezar campeonato» y la vista de grupos y llaves.")
        return redirect('ver_campeonato', torneo_id=torneo.id)
    
    if Partido.objects.filter(torneo=torneo, etapa='4TOS').exists():
        messages.error(request, "Los Cuartos de Final ya fueron generados.")
        return redirect(f"/programar/?torneo={torneo.id}")

    if 'ida_y_vuelta' in request.POST and request.POST.get('accion') != 'guardar_db':
        torneo.fase3_ida_vuelta = request.POST.get('ida_y_vuelta') == 'on'
        torneo.save()

    clasificados_a = obtener_clasificados_fase2(torneo, 'A')
    clasificados_b = obtener_clasificados_fase2(torneo, 'B')

    if len(clasificados_a) < 4 or len(clasificados_b) < 4:
        messages.error(request, "Aún no hay 4 equipos clasificados en cada grupo de la Fase 2.")
        return redirect('tabla_posiciones_f2', torneo_id=torneo.id)

    cruces = [
        (clasificados_a[0]['equipo'], clasificados_b[3]['equipo']), 
        (clasificados_a[1]['equipo'], clasificados_b[2]['equipo']), 
        (clasificados_a[2]['equipo'], clasificados_b[1]['equipo']), 
        (clasificados_a[3]['equipo'], clasificados_b[0]['equipo'])  
    ]

    fixture = []
    fixture.append({'numero_fecha': 'IDA (Cuartos Cross-Grupos)', 'partidos': [{'local': c[0], 'visita': c[1]} for c in cruces]})
    if torneo.fase3_ida_vuelta:
        fixture.append({'numero_fecha': 'VUELTA (Cuartos Cross-Grupos)', 'partidos': [{'local': c[1], 'visita': c[0]} for c in cruces]})

    if request.method == 'POST' and request.POST.get('accion') == 'guardar_db':
        with transaction.atomic():
            for local, visita in cruces:
                Partido.objects.create(torneo=torneo, etapa='4TOS', numero_fecha=1, equipo_local=local, equipo_visita=visita)
                if torneo.fase3_ida_vuelta:
                    Partido.objects.create(torneo=torneo, etapa='4TOS', numero_fecha=2, equipo_local=visita, equipo_visita=local)

        formato_texto = "Ida y Vuelta" if torneo.fase3_ida_vuelta else "Partido Único"
        messages.success(request, f'✅ Cuartos de Final ({formato_texto}) generados con éxito.')
        return redirect(f"/programar/?torneo={torneo.id}")

    return render(request, 'core/generar_fixture.html', {'torneo': torneo, 'fixture': fixture, 'total_equipos': 8})


@login_required
@user_passes_test(es_organizador)
def generar_semifinales(request, torneo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    torneo = get_object_or_404(Torneo, id=torneo_id, complejo=mi_complejo)
    if torneo.formato != 'CLASICO':
        messages.error(request, "⛔ Este torneo usa el nuevo sistema de campeonato. Usa «Empezar campeonato» y la vista de grupos y llaves.")
        return redirect('ver_campeonato', torneo_id=torneo.id)
    
    if Partido.objects.filter(torneo=torneo, etapa='SEMI').exists():
        messages.error(request, "Las Semifinales ya fueron generadas.")
        return redirect(f"/programar/?torneo={torneo.id}")
    
    if 'ida_y_vuelta' in request.POST and request.POST.get('accion') != 'guardar_db':
        torneo.fase3_ida_vuelta = request.POST.get('ida_y_vuelta') == 'on'
        torneo.save()

    clas_a = obtener_clasificados_fase2(torneo, 'A')
    clas_b = obtener_clasificados_fase2(torneo, 'B')
    
    g_s1 = obtener_ganador_llave(torneo, '4TOS', clas_a[0]['equipo'], clas_b[3]['equipo']) 
    g_s2 = obtener_ganador_llave(torneo, '4TOS', clas_a[1]['equipo'], clas_b[2]['equipo']) 
    g_s3 = obtener_ganador_llave(torneo, '4TOS', clas_a[2]['equipo'], clas_b[1]['equipo']) 
    g_s4 = obtener_ganador_llave(torneo, '4TOS', clas_a[3]['equipo'], clas_b[0]['equipo']) 

    if not (g_s1 and g_s2 and g_s3 and g_s4):
        messages.error(request, "Aún no terminan los Cuartos, o hay empates globales sin definir por penales en el Acta.")
        return redirect(f"/programar/?torneo={torneo.id}")

    cruces = [(g_s1, g_s3), (g_s4, g_s2)]

    fixture = []
    fixture.append({'numero_fecha': 'IDA (Semifinal Cross)', 'partidos': [{'local': c[0], 'visita': c[1]} for c in cruces]})
    if torneo.fase3_ida_vuelta:
        fixture.append({'numero_fecha': 'VUELTA (Semifinal Cross)', 'partidos': [{'local': c[1], 'visita': c[0]} for c in cruces]})

    if request.method == 'POST' and request.POST.get('accion') == 'guardar_db':
        with transaction.atomic():
            for local, visita in cruces:
                Partido.objects.create(torneo=torneo, etapa='SEMI', numero_fecha=1, equipo_local=local, equipo_visita=visita)
                if torneo.fase3_ida_vuelta:
                    Partido.objects.create(torneo=torneo, etapa='SEMI', numero_fecha=2, equipo_local=visita, equipo_visita=local)

        formato_texto = "Ida y Vuelta" if torneo.fase3_ida_vuelta else "Partido Único"
        messages.success(request, f'✅ Semifinales ({formato_texto}) generadas con éxito.')
        return redirect(f"/programar/?torneo={torneo.id}")

    return render(request, 'core/generar_fixture.html', {'torneo': torneo, 'fixture': fixture, 'total_equipos': 4})


@login_required
@user_passes_test(es_organizador)
def generar_finales(request, torneo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    torneo = get_object_or_404(Torneo, id=torneo_id, complejo=mi_complejo)
    if torneo.formato != 'CLASICO':
        messages.error(request, "⛔ Este torneo usa el nuevo sistema de campeonato. Usa «Empezar campeonato» y la vista de grupos y llaves.")
        return redirect('ver_campeonato', torneo_id=torneo.id)
    
    if Partido.objects.filter(torneo=torneo, etapa='FINAL').exists():
        messages.error(request, "Las Finales ya fueron generadas.")
        return redirect(f"/programar/?torneo={torneo.id}")

    semis_ida = Partido.objects.filter(torneo=torneo, etapa='SEMI', numero_fecha=1)
    if semis_ida.count() != 2:
        messages.error(request, "Faltan datos de las semifinales.")
        return redirect(f"/programar/?torneo={torneo.id}")

    ganadores = []; perdedores = []
    for s in semis_ida:
        g_semi = obtener_ganador_llave(torneo, 'SEMI', s.equipo_local, s.equipo_visita)
        if not g_semi:
            messages.error(request, f"La llave de {s.equipo_local} vs {s.equipo_visita} no se ha decidido.")
            return redirect(f"/programar/?torneo={torneo.id}")
            
        ganadores.append(g_semi)
        perdedores.append(s.equipo_visita if s.equipo_local == g_semi else s.equipo_local)

    fixture = [
        {'numero_fecha': 'TERCER LUGAR (Partido Único)', 'partidos': [{'local': perdedores[0], 'visita': perdedores[1]}]},
        {'numero_fecha': 'GRAN FINAL (Partido Único)', 'partidos': [{'local': ganadores[0], 'visita': ganadores[1]}]}
    ]

    if request.method == 'POST' and request.POST.get('accion') == 'guardar_db':
        with transaction.atomic():
            Partido.objects.create(torneo=torneo, etapa='TERC', equipo_local=perdedores[0], equipo_visita=perdedores[1], numero_fecha=1)
            Partido.objects.create(torneo=torneo, etapa='FINAL', equipo_local=ganadores[0], equipo_visita=ganadores[1], numero_fecha=1)

        messages.success(request, '🏆 ¡Gran Final y 3er Lugar generados a Partido Único!')
        return redirect(f"/programar/?torneo={torneo.id}")
        
    return render(request, 'core/generar_fixture.html', {'torneo': torneo, 'fixture': fixture, 'total_equipos': 4})


# =========================================================
# ✨ CAMPEONATO: MODALIDADES, GRUPOS Y LLAVES TRANSPARENTES
# =========================================================

def _leer_config_campeonato(post):
    def entero(clave):
        try:
            return max(0, int(post.get(clave) or 0))
        except ValueError:
            return 0
    return {
        'formato': post.get('formato', ''),
        'ida_vuelta_liga': post.get('ida_vuelta_liga') == 'on',
        'num_grupos': entero('num_grupos'),
        'clasifican': entero('clasifican'),
        'mejores': entero('mejores'),
        'clasifican_liga': entero('clasifican_liga'),
        'ida_vuelta_llaves': post.get('ida_vuelta_llaves') == 'on',
        'final_ida_vuelta': post.get('final_ida_vuelta') == 'on',
        'tercer_lugar': post.get('tercer_lugar') == 'on',
    }


@login_required
@user_passes_test(es_organizador)
def iniciar_campeonato(request, torneo_id):
    """Asistente "Empezar campeonato": 1) elegir modalidad, 2) ver la vista
    previa (grupos sorteados con semilla visible + cuadro de llaves con los
    cruces fijos), 3) confirmar. Nada se crea hasta confirmar."""
    mi_complejo = obtener_mi_complejo(request.user)
    torneo = get_object_or_404(Torneo, id=torneo_id, complejo=mi_complejo)
    if torneo.campeonato_iniciado:
        messages.info(request, "Este campeonato ya está en marcha.")
        return redirect('ver_campeonato', torneo_id=torneo.id)

    equipos = motor.equipos_participantes(torneo)
    pendientes = Equipo.objects.filter(torneo=torneo, estado_inscripcion='PENDIENTE').count()
    cfg = _leer_config_campeonato(request.POST) if request.method == 'POST' else {
        'formato': '', 'ida_vuelta_liga': False, 'num_grupos': 0, 'clasifican': 2, 'mejores': 0,
        'clasifican_liga': 4, 'ida_vuelta_llaves': False, 'final_ida_vuelta': False, 'tercer_lugar': True}
    ctx = {'torneo': torneo, 'equipos': equipos, 'n_equipos': len(equipos), 'pendientes': pendientes,
           'cfg': cfg, 'sugerencias': motor.sugerencias_grupos(len(equipos)),
           'formatos': [f for f in Torneo.FORMATOS if f[0] != 'CLASICO'], 'letras': motor.LETRAS}

    if request.method == 'POST':
        errores, resumen = motor.validar_configuracion(
            cfg['formato'], len(equipos), cfg['num_grupos'], cfg['clasifican'], cfg['mejores'],
            cfg['clasifican_liga'], cfg['ida_vuelta_liga'])
        ctx.update({'errores': errores, 'resumen': resumen})
        if errores:
            return render(request, 'core/iniciar_campeonato.html', ctx)

        try:
            semilla = int(request.POST.get('semilla') or 0)
        except ValueError:
            semilla = 0
        if not semilla or request.POST.get('accion') == 'resortear':
            import random as _random
            semilla = _random.SystemRandom().randint(1000, 999999)

        grupos_manual = None
        if cfg['formato'] == 'GRUPOS' and request.POST.get('ajuste_manual') == '1' and request.POST.get('accion') != 'resortear':
            grupos_manual = {}
            for e in equipos:
                letra = (request.POST.get(f'grupo_{e.id}') or '').upper()
                if letra:
                    grupos_manual[e.id] = letra

        if request.POST.get('accion') == 'confirmar':
            try:
                motor.iniciar_campeonato(
                    torneo, cfg['formato'], ida_vuelta_liga=cfg['ida_vuelta_liga'], num_grupos=cfg['num_grupos'],
                    clasifican=cfg['clasifican'], mejores=cfg['mejores'], clasifican_liga=cfg['clasifican_liga'],
                    ida_vuelta_llaves=cfg['ida_vuelta_llaves'], final_ida_vuelta=cfg['final_ida_vuelta'],
                    tercer_lugar=cfg['tercer_lugar'], semilla=semilla, grupos_manual=grupos_manual)
            except motor.CampeonatoError as e:
                ctx['errores'] = [str(e)]
                ctx['semilla'] = semilla
                return render(request, 'core/iniciar_campeonato.html', ctx)
            messages.success(request, f"🏆 ¡Campeonato iniciado! Modalidad: {dict(Torneo.FORMATOS)[cfg['formato']]}. Ya puedes programar fechas y horas de cada partido.")
            return redirect('ver_campeonato', torneo_id=torneo.id)

        # --- Vista previa (no guarda nada) ---
        ctx['semilla'] = semilla
        if request.POST.get('accion') == 'pdf':
            return _pdf_preview_inicio(torneo, cfg, equipos, semilla, grupos_manual)
        if cfg['formato'] == 'GRUPOS':
            try:
                grupos = motor.armar_grupos(equipos, cfg['num_grupos'], semilla, grupos_manual)
            except motor.CampeonatoError as e:
                ctx['errores'] = [str(e)]
                grupos = motor.sortear_grupos(equipos, cfg['num_grupos'], semilla)
            ctx['grupos_preview'] = [
                {'letra': l, 'equipos': m, 'jornadas': motor.round_robin(m, cfg['ida_vuelta_liga'])}
                for l, m in grupos.items()]
            ctx['ajuste_manual'] = bool(grupos_manual)
            slots = motor.semillas_grupos(cfg['num_grupos'], cfg['clasifican'], cfg['mejores'])
        elif cfg['formato'] == 'LIGA_PLAYOFF':
            slots = motor.semillas_liga(cfg['clasifican_liga'])
        elif cfg['formato'] == 'ELIMINACION':
            import random as _random
            orden = sorted(equipos, key=lambda e: e.id)
            _random.Random(semilla).shuffle(orden)
            slots = [(f"E{e.id}", e.nombre) for e in orden]
        else:
            slots = []
        if cfg['formato'] in ('LIGA', 'LIGA_PLAYOFF'):
            ctx['jornadas_preview'] = motor.round_robin(equipos, cfg['ida_vuelta_liga'])
        if slots:
            ctx['cuadro_preview'] = _preview_cuadro(slots, cfg)
        ctx['preview'] = True
    return render(request, 'core/iniciar_campeonato.html', ctx)


def _pdf_preview_inicio(torneo, cfg, equipos, semilla, grupos_manual):
    """PDF del fixture de la PRIMERA fase tal como se va a guardar."""
    fixture = []
    if cfg['formato'] == 'GRUPOS':
        try:
            grupos = motor.armar_grupos(equipos, cfg['num_grupos'], semilla, grupos_manual)
        except motor.CampeonatoError:
            grupos = motor.sortear_grupos(equipos, cfg['num_grupos'], semilla)
        por_fecha = {}
        for letra, miembros in grupos.items():
            for n, jornada in enumerate(motor.round_robin(miembros, cfg['ida_vuelta_liga']), start=1):
                por_fecha.setdefault(n, []).extend({'local': a, 'visita': b, 'detalle': f"Grupo {letra}"} for a, b in jornada)
        fixture = [{'titulo': f"FECHA {n}", 'partidos': ps} for n, ps in sorted(por_fecha.items())]
        titulo = 'Fase de grupos'
    elif cfg['formato'] in ('LIGA', 'LIGA_PLAYOFF'):
        fixture = [{'titulo': f"FECHA {n}", 'partidos': [{'local': a, 'visita': b} for a, b in j]}
                   for n, j in enumerate(motor.round_robin(equipos, cfg['ida_vuelta_liga']), start=1)]
        titulo = 'Fase regular (liga)'
    else:
        import random as _random
        orden = sorted(equipos, key=lambda e: e.id)
        _random.Random(semilla).shuffle(orden)
        rondas = _preview_cuadro([(f"E{e.id}", e.nombre) for e in orden], cfg)
        fixture = [{'titulo': rondas[0]['nombre'].upper(), 'partidos': [{'local': c['a'], 'visita': c['b']} for c in rondas[0]['cruces']]}]
        titulo = rondas[0]['nombre']
    return _pdf_fixture(torneo, fixture, f"{titulo} · Sorteo #{semilla}", f"Fixture_{torneo.nombre}_{titulo}".replace(' ', '_'))


def _preview_cuadro(slots, cfg):
    """Cuadro de llaves solo para mostrar (sin guardar)."""
    tam = motor.siguiente_potencia_2(len(slots))
    slots = list(slots) + [('BYE', 'Pase directo')] * (tam - len(slots))
    orden = motor.orden_semillas(tam)
    rondas = []
    m, idx = tam, 0
    while m >= 2:
        codigo = motor.RONDA_POR_EQUIPOS[m]
        cruces = []
        for i in range(m // 2):
            if idx == 0:
                a, b = slots[orden[2 * i] - 1][1], slots[orden[2 * i + 1] - 1][1]
            else:
                previa = motor.NOMBRE_RONDA[rondas[-1]['codigo']]
                a, b = f"Ganador {previa} {2 * i + 1}", f"Ganador {previa} {2 * i + 2}"
            cruces.append({'numero': i + 1, 'a': a, 'b': b})
        rondas.append({'codigo': codigo, 'nombre': motor.NOMBRE_RONDA[codigo], 'cruces': cruces})
        m //= 2
        idx += 1
    return rondas


def ver_campeonato(request, torneo_id):
    """Vista pública del campeonato: tablas de grupos/liga con zonas de
    clasificación, cuadro de llaves completo y fixture por jornada."""
    torneo = get_object_or_404(Torneo.objects.select_related('complejo', 'categoria'), id=torneo_id)
    complejo = torneo.complejo
    rol = rol_en_complejo(request.user, complejo) if request.user.is_authenticated else None
    if complejo and complejo.es_demo and rol != 'ORG' and not request.user.is_superuser:
        raise Http404()
    ctx = {'torneo': torneo, 'es_admin': rol == 'ORG', 'rol': rol}
    if torneo.formato == 'CLASICO':
        return redirect('reporte_estadisticas', torneo_id=torneo.id)

    if torneo.formato == 'GRUPOS':
        tablas = motor.tablas_grupos(torneo)
        k, m = torneo.clasifican_por_grupo, torneo.mejores_extra
        mejores_ids = {f['equipo'].id for f in motor.ranking_mejores(tablas, k + 1)[:m]} if m else set()
        for tabla in tablas.values():
            for f in tabla:
                f['zona'] = 'clasifica' if f['pos'] <= k else ('mejor' if f['equipo'].id in mejores_ids else '')
        ctx['tablas_grupos'] = tablas
        if m:
            ranking = motor.ranking_mejores(tablas, k + 1)
            for i, f in enumerate(ranking, start=1):
                f['rank'] = i
                f['zona'] = 'mejor' if i <= m else ''
            ctx['ranking_mejores'] = ranking
            ctx['posicion_mejores'] = k + 1
    elif torneo.formato in ('LIGA', 'LIGA_PLAYOFF'):
        tabla = motor.tabla_liga(torneo)
        for f in tabla:
            f['zona'] = 'clasifica' if torneo.formato == 'LIGA_PLAYOFF' and f['pos'] <= torneo.clasifican_liga else ''
        ctx['tabla_liga'] = tabla
        if torneo.formato == 'LIGA' and torneo.fase_regular_cerrada and tabla:
            ctx['campeon_liga'] = tabla[0]['equipo']

    if torneo.formato in ('LIGA_PLAYOFF', 'GRUPOS', 'ELIMINACION'):
        ctx['cuadro'] = motor.datos_cuadro(torneo)

    etapa = motor.etapa_regular(torneo) if torneo.formato else None
    if etapa and torneo.formato != 'ELIMINACION':
        jornadas = {}
        for p in Partido.objects.filter(torneo=torneo, etapa=etapa).select_related('equipo_local', 'equipo_visita').order_by('numero_fecha', 'equipo_local__grupo', 'id'):
            jornadas.setdefault(p.numero_fecha, []).append(p)
        ctx['jornadas'] = sorted(jornadas.items())
    if torneo.campeonato_iniciado:
        ctx['puede_cerrar_fase'] = (rol == 'ORG' and torneo.formato in ('LIGA', 'LIGA_PLAYOFF', 'GRUPOS')
                                    and not torneo.fase_regular_cerrada and motor.fase_regular_completa(torneo))
        ctx['puede_reiniciar'] = rol == 'ORG' and not motor.hay_partidos_jugados(torneo)
        etapa_q = Partido.objects.filter(torneo=torneo, etapa=etapa) if etapa else Partido.objects.none()
        ctx['avance'] = {'jugados': etapa_q.filter(estado__in=['JUG', 'WO']).count(), 'total': etapa_q.count()}
    return render(request, 'core/campeonato.html', ctx)


def _pdf_fixture(torneo, fixture, fase_titulo, nombre_archivo):
    """PDF del fixture de UNA fase (para imprimir o mandar por WhatsApp)."""
    html = get_template('core/fixture_pdf.html').render({'torneo': torneo, 'fixture': fixture, 'fase_titulo': fase_titulo})
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}.pdf"'
    if pisa.CreatePDF(html, dest=response).err:
        return HttpResponse('Error al generar el PDF', status=500)
    return response


def _fixture_cruces(titulo, cruces):
    return [{'titulo': titulo, 'partidos': [
        {'local': c['a'] or c['etiqueta_a'], 'visita': c['b'] or c['etiqueta_b']} for c in cruces]}]


def fixture_pdf_campeonato(request, torneo_id):
    """Descarga el fixture de una fase ya guardada: ?fase=regular o el código
    de la ronda (8VOS, 4TOS, SEMI, FINAL...)."""
    torneo = get_object_or_404(Torneo, id=torneo_id)
    if torneo.complejo and torneo.complejo.es_demo and rol_en_complejo(request.user, torneo.complejo) != 'ORG':
        raise Http404()
    fase = request.GET.get('fase', 'regular')
    if fase == 'regular':
        etapa = motor.etapa_regular(torneo)
        jornadas = {}
        for p in Partido.objects.filter(torneo=torneo, etapa=etapa).select_related('equipo_local', 'equipo_visita').order_by('numero_fecha', 'equipo_local__grupo', 'id'):
            jornadas.setdefault(p.numero_fecha, []).append({
                'local': p.equipo_local, 'visita': p.equipo_visita,
                'detalle': ' · '.join(x for x in [f"Grupo {p.equipo_local.grupo}" if p.equipo_local.grupo else '',
                                                  timezone.localtime(p.fecha_hora).strftime('%d/%m %H:%M') if p.fecha_hora else ''] if x)})
        fixture = [{'titulo': f"FECHA {n}", 'partidos': ps} for n, ps in sorted(jornadas.items())]
        titulo = 'Fase de grupos' if etapa == 'GRP' else 'Fase regular (liga)'
    elif fase in motor.NOMBRE_RONDA:
        datos = motor.datos_cuadro(torneo)
        rondas = [r for r in datos['rondas'] if r['codigo'] == fase]
        if fase == 'TERC' and datos['tercer']:
            cruces = [datos['tercer']]
        elif rondas:
            cruces = rondas[0]['llaves']
        else:
            raise Http404()
        fixture = []
        for c in cruces:
            partidos = c['partidos'] or [None]
            for p in partidos:
                fixture.append({
                    'local': (p.equipo_local if p else c['a']) or c['etiqueta_a'],
                    'visita': (p.equipo_visita if p else c['b']) or c['etiqueta_b'],
                    'detalle': ' · '.join(x for x in [f"Llave {c['numero']}", ('Vuelta' if p and p.numero_fecha == 2 else ('Ida' if p and len(c['partidos']) > 1 else '')),
                                                      timezone.localtime(p.fecha_hora).strftime('%d/%m %H:%M') if p and p.fecha_hora else ''] if x)})
        fixture = [{'titulo': motor.NOMBRE_RONDA[fase].upper(), 'partidos': fixture}]
        titulo = motor.NOMBRE_RONDA[fase]
    else:
        raise Http404()
    return _pdf_fixture(torneo, fixture, titulo, f"Fixture_{torneo.nombre}_{titulo}".replace(' ', '_'))


@login_required
@user_passes_test(es_organizador)
def cerrar_fase_regular(request, torneo_id):
    """Paso a la siguiente fase en 3 pasos: revisar los cruces, excluir
    equipos si hace falta (sancionados/retirados: sube el siguiente de la
    tabla) y luego guardar en el sistema o descargar el PDF."""
    mi_complejo = obtener_mi_complejo(request.user)
    torneo = get_object_or_404(Torneo, id=torneo_id, complejo=mi_complejo)
    if torneo.fase_regular_cerrada:
        messages.info(request, "La fase regular ya fue cerrada.")
        return redirect('ver_campeonato', torneo_id=torneo.id)
    if not motor.fase_regular_completa(torneo):
        messages.error(request, "⛔ Aún hay partidos de la fase regular sin finalizar.")
        return redirect('ver_campeonato', torneo_id=torneo.id)

    participantes = motor.equipos_participantes(torneo)
    ids_validos = {e.id for e in participantes}
    excluidos = {int(x) for x in request.POST.getlist('excluir') if x.isdigit() and int(x) in ids_validos}
    accion = request.POST.get('accion') if request.method == 'POST' else None

    if torneo.formato == 'LIGA':
        if accion == 'confirmar':
            motor.cerrar_fase_regular(torneo)
            messages.success(request, "🏆 Liga cerrada. ¡Ya tenemos campeón!")
            return redirect('ver_campeonato', torneo_id=torneo.id)
        return render(request, 'core/cerrar_fase.html', {'torneo': torneo, 'es_liga': True,
                                                          'tabla': motor.tabla_liga(torneo)})

    if len(excluidos) >= len(participantes) - 1:
        messages.error(request, "⛔ No puedes excluir a casi todos los equipos.")
        excluidos = set()
    cruces = motor.previa_siguiente_fase(torneo, excluidos)
    ronda = cruces[0]['llave'].ronda if cruces else ''
    nombre_ronda = motor.NOMBRE_RONDA.get(ronda, 'Eliminatorias')

    if accion == 'pdf':
        return _pdf_fixture(torneo, _fixture_cruces(nombre_ronda.upper(), cruces), nombre_ronda,
                            f"Fixture_{torneo.nombre}_{nombre_ronda}".replace(' ', '_'))
    if accion == 'confirmar':
        try:
            motor.cerrar_fase_regular(torneo, excluidos)
        except motor.CampeonatoError as e:
            messages.error(request, f"⛔ {e}")
            return redirect('cerrar_fase_regular', torneo_id=torneo.id)
        nombres = ", ".join(e.nombre for e in participantes if e.id in excluidos)
        messages.success(request, f"✅ {nombre_ronda} generada y guardada en el sistema." + (f" Equipos excluidos: {nombres}." if nombres else ""))
        return redirect('ver_campeonato', torneo_id=torneo.id)

    if torneo.formato == 'GRUPOS':
        tablas = motor.tablas_grupos(torneo)
    else:
        tablas = {'Liga': motor.tabla_liga(torneo)}
    clasificados_ids = {c['a'].id for c in cruces if c['a']} | {c['b'].id for c in cruces if c['b']}
    return render(request, 'core/cerrar_fase.html', {
        'torneo': torneo, 'cruces': cruces, 'nombre_ronda': nombre_ronda, 'tablas': tablas,
        'excluidos': excluidos, 'clasificados_ids': clasificados_ids,
    })


@login_required
@user_passes_test(es_organizador)
@require_POST
def retirar_equipo_llave(request, llave_id, equipo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    llave = get_object_or_404(Llave, id=llave_id, torneo__complejo=mi_complejo)
    equipo = get_object_or_404(Equipo, id=equipo_id, torneo=llave.torneo)
    try:
        rival = motor.retirar_equipo_de_llave(llave, equipo)
    except motor.CampeonatoError as e:
        messages.error(request, f"⛔ {e}")
    else:
        messages.warning(request, f"{equipo.nombre} fue retirado de la llave. {rival.nombre} avanza por W.O.")
    return redirect('ver_campeonato', torneo_id=llave.torneo_id)


@login_required
@user_passes_test(es_organizador)
@require_POST
def reiniciar_campeonato(request, torneo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    torneo = get_object_or_404(Torneo, id=torneo_id, complejo=mi_complejo)
    if request.POST.get('confirmacion', '').strip().upper() != 'REINICIAR':
        messages.error(request, "Escribe REINICIAR para confirmar.")
        return redirect('ver_campeonato', torneo_id=torneo.id)
    try:
        motor.reiniciar_campeonato(torneo)
    except motor.CampeonatoError as e:
        messages.error(request, f"⛔ {e}")
        return redirect('ver_campeonato', torneo_id=torneo.id)
    messages.warning(request, "🔄 Campeonato reiniciado. Puedes elegir la modalidad otra vez.")
    return redirect('iniciar_campeonato', torneo_id=torneo.id)


def llaves_eliminatorias(request, torneo_id):
    torneo = get_object_or_404(Torneo, id=torneo_id)
    if torneo.formato != 'CLASICO':
        return redirect('ver_campeonato', torneo_id=torneo.id)
    cuartos = Partido.objects.filter(torneo=torneo, etapa='4TOS').order_by('numero_fecha', 'id')
    semis = Partido.objects.filter(torneo=torneo, etapa='SEMI').order_by('numero_fecha', 'id')
    tercer = Partido.objects.filter(torneo=torneo, etapa='TERC').first()
    final = Partido.objects.filter(torneo=torneo, etapa='FINAL').first()
    return render(request, 'core/llaves_eliminatorias.html', {
        'torneo': torneo, 'cuartos': cuartos, 'semis': semis, 'tercer': tercer, 'final': final
    })

@login_required
def importar_equipo_existente(request, torneo_nuevo_id):
    torneo_nuevo = get_object_or_404(Torneo, id=torneo_nuevo_id)
    
    # 🔥 AISLAMIENTO: Solo permite importar equipos históricos de la MISMA CANCHA
    mis_equipos_historicos = Equipo.objects.filter(
        dirigente=request.user,
        torneo__activo=False,
        torneo__categoria=torneo_nuevo.categoria,
        torneo__complejo=torneo_nuevo.complejo # ¡ESTA ES LA LÍNEA CLAVE!
    ).exclude(torneo=torneo_nuevo)

    if not mis_equipos_historicos.exists():
        cat_nombre = torneo_nuevo.categoria.nombre if torneo_nuevo.categoria else "Sin Categoría"
        messages.warning(request, f"No tienes equipos en torneos finalizados de la categoría '{cat_nombre}' listos para importar.")
        return redirect('ver_torneos_activos')

    if request.method == 'POST':
        equipo_viejo_id = request.POST.get('equipo_id')
        equipo_viejo = get_object_or_404(Equipo, id=equipo_viejo_id, dirigente=request.user)

        if Equipo.objects.filter(torneo=torneo_nuevo, nombre=equipo_viejo.nombre).exists():
            messages.error(request, f"El equipo '{equipo_viejo.nombre}' ya está inscrito (o en proceso) en este torneo.")
            return redirect('ver_torneos_activos')

        try:
            with transaction.atomic():
                nuevo_equipo = Equipo.objects.create(
                    torneo=torneo_nuevo,
                    dirigente=request.user,
                    nombre=equipo_viejo.nombre,
                    escudo=equipo_viejo.escudo, 
                    telefono_contacto=equipo_viejo.telefono_contacto,
                    nombre_suplente_1=equipo_viejo.nombre_suplente_1,
                    nombre_suplente_2=equipo_viejo.nombre_suplente_2,
                    estado_inscripcion='PENDIENTE'
                )

                # 🔥 MULTI-TENANCY: fuerza rol='DIR' en la nueva cancha aunque
                # ya tuviera otro rol — ver nota en gestionar_equipos.
                asegurar_rol_dirigente(request.user, torneo_nuevo.complejo)

                costo_inscripcion = getattr(torneo_nuevo, 'costo_inscripcion', Decimal('0.00')) 
                if not torneo_nuevo.cobro_por_jugador:
                    Sancion.objects.create(
                        torneo=torneo_nuevo, 
                        equipo=nuevo_equipo, 
                        tipo='ADMIN', 
                        monto=costo_inscripcion, 
                        descripcion=f"Inscripción - {torneo_nuevo.nombre}", 
                        pagada=False
                    )

                jugadores_viejos = Jugador.objects.filter(equipo=equipo_viejo, expulsado_torneo=False)
                jugadores_importados = 0

                for j in jugadores_viejos:
                    if not getattr(j, 'esta_sancionado', False):
                        j.pk = None
                        j.equipo = nuevo_equipo
                        j.rojas_directas_acumuladas = 0
                        j.partidos_suspension = 0
                        j.expulsado_torneo = False
                        j.sancionado_hasta = None 
                        j.save()
                        jugadores_importados += 1

            messages.success(request, f"✅ ¡Renovación Exitosa! '{nuevo_equipo.nombre}' importado con {jugadores_importados} jugadores. Estado: PENDIENTE DE APROBACIÓN.")
            return redirect('ver_torneos_activos')
            
        except Exception as e:
            messages.error(request, f"Ocurrió un error al importar: {str(e)}")
            return redirect('ver_torneos_activos')

    return render(request, 'core/importar_equipo.html', {
        'torneo': torneo_nuevo, 
        'equipos_previos': mis_equipos_historicos
    })

@login_required
@user_passes_test(es_organizador)
def revertir_transicion(request, torneo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    torneo = get_object_or_404(Torneo, id=torneo_id, complejo=mi_complejo)
    if torneo.formato != 'CLASICO':
        messages.error(request, "⛔ Este torneo usa el nuevo sistema de campeonato. Usa «Empezar campeonato» y la vista de grupos y llaves.")
        return redirect('ver_campeonato', torneo_id=torneo.id)
    
    with transaction.atomic():
        Partido.objects.filter(torneo=torneo, etapa__in=['F2', '4TOS', 'SEMI', 'TERC', 'FINAL']).delete()
        Equipo.objects.filter(torneo=torneo).update(grupo_fase2="", puntos_bonificacion=0)
        
        torneo.fase2_ida_vuelta = False
        torneo.fase3_ida_vuelta = False
        torneo.save()
    
    messages.success(request, "🔄 ¡Rebobinado exitoso! La Fase 2 y eliminatorias fueron borradas. Has vuelto a la Fase 1.")
    return redirect('tabla_posiciones', torneo_id=torneo.id)


@login_required
@user_passes_test(es_organizador)
def activar_vuelta_f1(request, torneo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    torneo = get_object_or_404(Torneo, id=torneo_id, complejo=mi_complejo)
    if torneo.formato != 'CLASICO':
        messages.error(request, "⛔ Este torneo usa el nuevo sistema de campeonato. Usa «Empezar campeonato» y la vista de grupos y llaves.")
        return redirect('ver_campeonato', torneo_id=torneo.id)
    torneo.fase1_ida_vuelta = True
    torneo.save()
    messages.success(request, "🔄 Formato actualizado: Ahora puedes programar partidos de Vuelta en la Fase 1.")
    return redirect(f"/programar/?torneo={torneo.id}")

@login_required
@user_passes_test(es_organizador)
def cambiar_formato_fase1(request, torneo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    torneo = get_object_or_404(Torneo, id=torneo_id, complejo=mi_complejo)
    if torneo.formato != 'CLASICO':
        messages.error(request, "⛔ Este torneo usa el nuevo sistema de campeonato. Usa «Empezar campeonato» y la vista de grupos y llaves.")
        return redirect('ver_campeonato', torneo_id=torneo.id)
    
    if torneo.fase1_ida_vuelta:
        total_equipos = Equipo.objects.filter(torneo=torneo, estado_inscripcion='APROBADO').count()
        fechas_ida = total_equipos - 1 if total_equipos % 2 == 0 else total_equipos
        hay_vuelta = Partido.objects.filter(torneo=torneo, etapa='F1', numero_fecha__gt=fechas_ida).exists()
        
        if hay_vuelta:
            messages.error(request, "⛔ No puedes volver a 'Solo Ida' porque ya tienes partidos de VUELTA programados. Debes eliminarlos primero.")
        else:
            torneo.fase1_ida_vuelta = False
            torneo.save()
            messages.success(request, "✅ Formato restaurado a: SOLO IDA.")
    else:
        torneo.fase1_ida_vuelta = True
        torneo.save()
        messages.success(request, "🔄 Formato actualizado: Ahora se permiten partidos de VUELTA.")

    return redirect(f"/programar/?torneo={torneo.id}")

@login_required
def buscar_jugador_api(request, cedula):
    # Buscamos los IDs de los complejos donde este usuario tiene algún rol (ya sea Dueño, Dirigente, etc.)
    mis_complejos_ids = RolComplejo.objects.filter(usuario=request.user).values_list('complejo_id', flat=True)
    
    # 🔥 AISLAMIENTO: Solo autocompletará el nombre si el jugador ya jugó en alguna de las canchas del usuario
    jugador = Jugador.objects.filter(
        cedula=cedula, 
        equipo__torneo__complejo_id__in=mis_complejos_ids
    ).order_by('-id').first()
    
    if jugador:
        return JsonResponse({
            'encontrado': True,
            'nombres': jugador.nombres,
        })
    else:
        return JsonResponse({'encontrado': False}) 
    
# =========================================================
# GESTIÓN DE CATEGORÍAS
# =========================================================

@login_required
@user_passes_test(es_organizador)
def gestionar_categorias(request):
    mi_complejo = obtener_mi_complejo(request.user)
    
    # 1. LEER LÍMITES DEL PLAN SAAS
    limite_categorias = mi_complejo.plan.max_categorias_por_torneo if mi_complejo.plan else 1
    categorias_actuales = Categoria.objects.filter(complejo=mi_complejo).count()
    puede_crear = categorias_actuales < limite_categorias
    
    if request.method == 'POST':
        # 2. APLICAR CANDADO
        if not puede_crear:
            messages.error(request, f"⛔ Límite alcanzado: Tu plan actual solo permite {limite_categorias} categorías. Contacta a NEXUS para mejorar tu plan.")
            return redirect('gestionar_categorias')
            
        nombre_categoria = request.POST.get('nombre')
        color_elegido = request.POST.get('color_carnet') 
        
        if nombre_categoria:
            if not Categoria.objects.filter(nombre__iexact=nombre_categoria, complejo=mi_complejo).exists():
                Categoria.objects.create(nombre=nombre_categoria, color_carnet=color_elegido, complejo=mi_complejo)
                messages.success(request, f"✅ Categoría '{nombre_categoria}' creada exitosamente.")
            else:
                messages.error(request, f"⛔ La categoría '{nombre_categoria}' ya existe en tu complejo.")
        else:
            messages.error(request, "⛔ El nombre de la categoría no puede estar vacío.")
            
        return redirect('gestionar_categorias')
        
    categorias = Categoria.objects.filter(complejo=mi_complejo).order_by('nombre')
    return render(request, 'core/gestionar_categorias.html', {
        'categorias': categorias,
        'puede_crear': puede_crear, 
        'limite': limite_categorias, 
        'actuales': categorias_actuales
    })

@login_required
@user_passes_test(es_organizador)
def editar_categoria(request, categoria_id):
    mi_complejo = obtener_mi_complejo(request.user)
    categoria = get_object_or_404(Categoria, id=categoria_id, complejo=mi_complejo) # 🔥 Bloquea acceso ajeno
    
    if request.method == 'POST':
        nuevo_nombre = request.POST.get('nombre')
        nuevo_color = request.POST.get('color_carnet') 
        
        if nuevo_nombre:
            if not Categoria.objects.filter(nombre__iexact=nuevo_nombre, complejo=mi_complejo).exclude(id=categoria.id).exists():
                categoria.nombre = nuevo_nombre
                if nuevo_color:
                    categoria.color_carnet = nuevo_color
                categoria.save()
                messages.success(request, f"✅ Categoría actualizada a '{nuevo_nombre}'.")
            else:
                messages.error(request, f"⛔ Ya existe otra categoría con el nombre '{nuevo_nombre}'.")
        else:
            messages.error(request, "⛔ El nombre no puede estar vacío.")
            
        return redirect('gestionar_categorias')
        
    return render(request, 'core/editar_categoria.html', {'categoria': categoria})

@login_required
@user_passes_test(es_organizador)
@require_POST
def eliminar_categoria(request, categoria_id):
    mi_complejo = obtener_mi_complejo(request.user)
    categoria = get_object_or_404(Categoria, id=categoria_id, complejo=mi_complejo) # 🔥 Bloquea acceso ajeno
    try:
        categoria.delete()
        messages.success(request, "✅ Categoría eliminada correctamente.")
    except Exception as e:
        messages.error(request, "⛔ No se pudo eliminar la categoría porque ya tiene torneos o equipos vinculados.")
        
    return redirect('gestionar_categorias')

# =========================================================
# GENERADOR DE CARNETS
# =========================================================
@login_required
def imprimir_carnets(request, equipo_id):
    equipo = get_object_or_404(Equipo, id=equipo_id)

    es_admin_de_esta_cancha = equipo.torneo.complejo == obtener_mi_complejo(request.user)
    es_dueno_del_equipo = request.user == equipo.dirigente
    if not (es_admin_de_esta_cancha or es_dueno_del_equipo):
        messages.error(request, "⛔ Acceso denegado a los carnets de este equipo.")
        return redirect('dashboard')

    jugadores = Jugador.objects.filter(equipo=equipo, expulsado_torneo=False).order_by('dorsal')
    
    color_cat = "#1D4ED8" 
    nombre_cat = "Libre"
    
    if equipo.torneo and equipo.torneo.categoria:
        nombre_cat = equipo.torneo.categoria.nombre
        if hasattr(equipo.torneo.categoria, 'color_carnet'):
            color_cat = equipo.torneo.categoria.color_carnet

    return render(request, 'core/carnets_equipo.html', {
        'equipo': equipo,
        'jugadores': jugadores,
        'color_categoria': color_cat,
        'nombre_categoria': nombre_cat,
        'iniciales_equipo': ''.join(p[0] for p in equipo.nombre.split()[:2]).upper(),
    })


@login_required
@user_passes_test(es_organizador)
def gestionar_configuracion(request):
    mi_complejo = obtener_mi_complejo(request.user)
    # El superadmin edita la configuración GLOBAL (complejo=None), que es la que
    # se muestra en la barra de navegación, login, inicio y registro.
    if request.user.is_superuser:
        config, created = Configuracion.objects.get_or_create(complejo=None)
    else:
        config, created = Configuracion.objects.get_or_create(complejo=mi_complejo)
    
    if request.method == 'POST':
        form = ConfiguracionForm(request.POST, request.FILES, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, '✅ Configuración actualizada correctamente.')
            return redirect('dashboard')
    else:
        form = ConfiguracionForm(instance=config)
        
    return render(request, 'core/gestionar_configuracion.html', {'form': form})

@login_required
@require_POST
def revertir_cobro_sancion(request, sancion_id):
    sancion = get_object_or_404(Sancion, id=sancion_id)
    if not verificar_acceso_complejo(request.user, sancion.torneo.complejo):
        messages.error(request, "No tienes permisos para realizar esta acción.")
        return redirect('dashboard')

    if request.method == 'POST':
        try:
            with transaction.atomic():
                ultimo_abono = sancion.historial_abonos.order_by('-fecha', '-id').first()
                
                if ultimo_abono:
                    monto_a_reversar = ultimo_abono.monto
                    sancion.monto_pagado -= monto_a_reversar
                    
                    if sancion.monto_pagado < Decimal('0.00'):
                        sancion.monto_pagado = Decimal('0.00')
                        
                    sancion.pagada = False
                    sancion.save()
                    registrar_movimiento(
                        complejo=sancion.torneo.complejo, tipo='REVERSO', monto=monto_a_reversar,
                        usuario=request.user, sancion=sancion, partido=ultimo_abono.partido,
                        descripcion=f"Reverso del abono del {timezone.localtime(ultimo_abono.fecha):%d/%m/%Y %H:%M}: {sancion.descripcion}",
                        origen='VOCALIA' if rol_en_complejo(request.user, sancion.torneo.complejo) == 'VOC' else 'FINANZAS')
                    ultimo_abono.delete()
                    
                    messages.success(request, f"🔄 Reverso exitoso: Se anuló el último abono de ${monto_a_reversar} para {sancion.equipo.nombre}.")
                else:
                    messages.warning(request, "⚠️ No se encontraron abonos para reversar en esta cuenta.")
                    
        except Exception as e:
            messages.error(request, f"Error al intentar reversar el pago: {str(e)}")
            
    return redirect(request.META.get('HTTP_REFERER', 'gestionar_finanzas'))

# ---------------------------------------------------------
# IMPORTANTE: VISTAS SAAS (PORTAL PÚBLICO)
# ---------------------------------------------------------

def landing_principal(request):
    """ El inicio global de NEXUS SPORTOPS donde salen todas las canchas """
    canchas = ComplejoDeportivo.objects.filter(activo=True, es_demo=False)
    config = Configuracion.objects.first() # Para sacar tu logo de NEXUS si lo subiste
    
    return render(request, 'core/landing_principal.html', {
        'canchas': canchas, 
        'config': config
    })

def portal_complejo(request, slug_complejo):
    """ El inicio específico de CADA CANCHA (Público, sin login) """
    complejo = get_object_or_404(ComplejoDeportivo, slug=slug_complejo)

    # Las canchas demo (entornos de prueba) no son visibles al público: solo
    # su propio dueño (para probarlas) o un superusuario pueden verlas.
    if complejo.es_demo and request.user != complejo.organizador and not request.user.is_superuser:
        raise Http404()

    # Si la cancha no pagó, bloqueamos la vista (excepto para ti que eres superadmin)
    if not complejo.esta_al_dia() and not request.user.is_superuser:
        return render(request, 'core/suspendido.html', {'complejo': complejo})
        
    torneos_activos = complejo.torneos.filter(activo=True).order_by('categoria__nombre', '-fecha_inicio')
    
    # Preparamos el botón de WhatsApp del Organizador
    url_whatsapp = None
    if complejo.telefono_contacto:
        mensaje = f"Hola {complejo.nombre}, vengo de NEXUS SPORTOPS y quisiera información sobre los torneos."
        mensaje_codificado = urllib.parse.quote(mensaje)
        url_whatsapp = f"https://wa.me/{complejo.telefono_contacto}?text={mensaje_codificado}"

    es_miembro = request.user.is_authenticated and (
        complejo.organizador_id == request.user.id or
        RolComplejo.objects.filter(usuario=request.user, complejo=complejo).exists())
    return render(request, 'core/portal_publico.html', {
        'complejo': complejo, 
        'torneos': torneos_activos,
        'url_whatsapp': url_whatsapp,
        'es_miembro': es_miembro or complejo.es_demo,
    })

from django.core.mail import send_mail
from django.conf import settings

# =========================================================
# PANEL SAAS (SÚPER ADMINISTRADOR)
# =========================================================

def superadmin_requerido(vista):
    """Solo el dueño de NEXUS SPORTOPS (superusuario) entra al panel SaaS."""
    from functools import wraps

    @wraps(vista)
    @login_required
    def envoltura(request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(request, "Acceso denegado. Solo el dueño de NEXUS SPORTOPS puede entrar aquí.")
            return redirect('dashboard')
        return vista(request, *args, **kwargs)
    return envoltura


DIAS_AVISO_VENCIMIENTO = 7


def _estado_suscripcion(cancha, hoy):
    """Estado comercial de una cancha: (código, etiqueta)."""
    if not cancha.activo:
        return 'suspendida', 'Suspendida'
    if not cancha.fecha_vencimiento:
        return 'sin-fecha', 'Sin fecha de corte'
    if cancha.fecha_vencimiento < hoy:
        return 'vencida', 'Vencida'
    if cancha.fecha_vencimiento <= hoy + timedelta(days=DIAS_AVISO_VENCIMIENTO):
        return 'por-vencer', 'Por vencer'
    return 'al-dia', 'Al día'


def _marcar_estados(canchas, hoy):
    for c in canchas:
        c.estado_codigo, c.estado_texto = _estado_suscripcion(c, hoy)
        c.dias_restantes = (c.fecha_vencimiento - hoy).days if c.fecha_vencimiento else None
        c.dias_vencida = -c.dias_restantes if c.dias_restantes is not None and c.dias_restantes < 0 else 0
    return canchas


def _paginar(request, queryset, por_pagina, parametro='page'):
    paginador = Paginator(queryset, por_pagina)
    try:
        return paginador.page(request.GET.get(parametro))
    except PageNotAnInteger:
        return paginador.page(1)
    except EmptyPage:
        return paginador.page(paginador.num_pages)


@superadmin_requerido
def dashboard_saas(request):
    hoy = timezone.localdate()
    canchas_list = (ComplejoDeportivo.objects.select_related('organizador', 'plan')
                    .filter(es_demo=False).order_by('fecha_vencimiento', 'nombre'))
    limite_aviso = hoy + timedelta(days=DIAS_AVISO_VENCIMIENTO)
    canchas_por_vencer = canchas_list.filter(activo=True, fecha_vencimiento__lte=limite_aviso)
    canchas_vencidas = canchas_list.filter(activo=True, fecha_vencimiento__lt=hoy)

    if request.method == 'POST':
        if 'enviar_recordatorios' in request.POST:
            enviados = 0
            for c in canchas_por_vencer:
                if not c.organizador.email:
                    continue
                send_mail(f"Vencimiento próximo: {c.nombre}",
                          f"La suscripción de {c.nombre} a NEXUS SPORTOPS vence el {c.fecha_vencimiento:%d/%m/%Y}.",
                          settings.EMAIL_HOST_USER, [c.organizador.email], fail_silently=True)
                enviados += 1
            messages.success(request, f"📧 Recordatorio enviado a {enviados} cancha(s).")
            return redirect('dashboard_saas')

        if 'suspender_morosos' in request.POST:
            contador = 0
            for c in canchas_vencidas:
                c.activo = False
                c.save(update_fields=['activo'])
                if c.organizador.email:
                    send_mail(f"SUSPENSIÓN: {c.nombre}", "Tu servicio fue suspendido por falta de pago.",
                              settings.EMAIL_HOST_USER, [c.organizador.email], fail_silently=True)
                contador += 1
            messages.warning(request, f"🚫 Se suspendieron {contador} cancha(s) vencidas.")
            return redirect('dashboard_saas')

    pagos = PagoSuscripcionSaaS.objects.filter(complejo__es_demo=False)
    ingresos_total = pagos.aggregate(t=Sum('monto'))['t'] or 0
    ingresos_mes = pagos.filter(fecha_pago__year=hoy.year, fecha_pago__month=hoy.month).aggregate(t=Sum('monto'))['t'] or 0
    # Lo que se debería cobrar cada mes con las canchas activas y su plan actual
    ingreso_mensual_esperado = canchas_list.filter(activo=True, plan__isnull=False).aggregate(t=Sum('plan__precio_mensual'))['t'] or 0

    canchas = _paginar(request, canchas_list, 8)
    _marcar_estados(canchas, hoy)
    alertas = _marcar_estados(list(canchas_por_vencer), hoy)

    planes = (PlanSuscripcion.objects.exclude(nombre=NOMBRE_PLAN_DEMO)
              .annotate(num_canchas=Count('complejodeportivo', filter=Q(complejodeportivo__es_demo=False)))
              .filter(num_canchas__gt=0).order_by('-num_canchas', 'nombre'))

    return render(request, 'core/dashboard_saas.html', {
        'seccion_saas': 'resumen',
        'canchas': canchas,
        'total_canchas': canchas_list.count(),
        'total_ingresos': ingresos_total,
        'ingresos_mes': ingresos_mes,
        'ingreso_mensual_esperado': ingreso_mensual_esperado,
        'canchas_activas': canchas_list.filter(activo=True).count(),
        'canchas_suspendidas': canchas_list.filter(activo=False).count(),
        'canchas_por_vencer': alertas,
        'num_vencidas': canchas_vencidas.count(),
        'planes': planes,
        'ultimos_pagos': pagos.select_related('complejo').order_by('-fecha_pago', '-id')[:6],
        'dias_aviso': DIAS_AVISO_VENCIMIENTO,
        'hoy': hoy,
    })


@superadmin_requerido
def gestionar_canchas_saas(request):
    hoy = timezone.localdate()
    if request.method == 'POST':
        form = ComplejoDeportivoForm(request.POST, request.FILES)
        if form.is_valid():
            cancha = form.save()
            # 🔥 MULTI-TENANCY: el dueño queda como ORGANIZADOR de su cancha
            RolComplejo.objects.get_or_create(usuario=cancha.organizador, complejo=cancha, defaults={'rol': 'ORG'})
            messages.success(request, f"✅ Cancha registrada. {cancha.organizador.username} ahora es Organizador Oficial de {cancha.nombre}.")
            return redirect('gestionar_canchas_saas')
    else:
        form = ComplejoDeportivoForm()

    canchas = ComplejoDeportivo.objects.filter(es_demo=False).select_related('organizador', 'plan').order_by('nombre')
    q = request.GET.get('q', '').strip()
    if q:
        canchas = canchas.filter(Q(nombre__icontains=q) | Q(slug__icontains=q) | Q(organizador__username__icontains=q))
    filtro = request.GET.get('estado', '')
    canchas = _marcar_estados(list(canchas), hoy)
    conteo = {'total': len(canchas)}
    for c in canchas:
        clave = c.estado_codigo.replace('-', '_')
        conteo[clave] = conteo.get(clave, 0) + 1
    if filtro:
        canchas = [c for c in canchas if c.estado_codigo == filtro]

    return render(request, 'core/saas_gestionar_canchas.html', {
        'seccion_saas': 'canchas', 'form': form, 'canchas': canchas,
        'q': q, 'filtro': filtro, 'conteo': conteo,
        'abrir_formulario': request.method == 'POST' or 'nueva' in request.GET,
    })


@superadmin_requerido
def editar_cancha_saas(request, cancha_id):
    cancha = get_object_or_404(ComplejoDeportivo, id=cancha_id)
    if request.method == 'POST':
        form = ComplejoDeportivoForm(request.POST, request.FILES, instance=cancha)
        if form.is_valid():
            cancha_actualizada = form.save()
            # 🔥 MULTI-TENANCY: asegurar el rol si cambió el dueño
            RolComplejo.objects.get_or_create(usuario=cancha_actualizada.organizador, complejo=cancha_actualizada, defaults={'rol': 'ORG'})
            messages.success(request, f"✅ Datos de {cancha_actualizada.nombre} actualizados.")
            return redirect('gestionar_canchas_saas')
    else:
        form = ComplejoDeportivoForm(instance=cancha)

    hoy = timezone.localdate()
    _marcar_estados([cancha], hoy)
    return render(request, 'core/saas_editar_cancha.html', {
        'seccion_saas': 'canchas', 'form': form, 'cancha': cancha,
        'pagos': cancha.pagos_saas.order_by('-fecha_pago', '-id')[:10],
        'total_pagado': cancha.pagos_saas.aggregate(t=Sum('monto'))['t'] or 0,
    })


@superadmin_requerido
def registrar_pago_saas(request):
    if request.method == 'POST':
        form = PagoSaaSForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                pago = form.save()
                cancha = pago.complejo
                # Si la cancha sigue vigente, los meses se suman a su fecha de corte;
                # si ya venció, empiezan a contar desde el día del pago.
                if cancha.fecha_vencimiento and cancha.fecha_vencimiento >= pago.fecha_pago:
                    fecha_base = cancha.fecha_vencimiento
                else:
                    fecha_base = pago.fecha_pago
                cancha.fecha_vencimiento = fecha_base + timedelta(days=30 * pago.meses_pagados)
                cancha.activo = True  # el pago reactiva la cancha
                cancha.save(update_fields=['fecha_vencimiento', 'activo'])
            messages.success(request, f"💰 Pago registrado. {cancha.nombre} queda activa hasta el {cancha.fecha_vencimiento:%d/%m/%Y}.")
            return redirect('registrar_pago_saas')
    else:
        form = PagoSaaSForm(initial={'complejo': request.GET.get('cancha') or None})

    pagos = PagoSuscripcionSaaS.objects.filter(complejo__es_demo=False).select_related('complejo', 'complejo__plan').order_by('-fecha_pago', '-id')
    cancha_filtro = request.GET.get('ver', '')
    if cancha_filtro.isdigit():
        pagos = pagos.filter(complejo_id=cancha_filtro)
    total_filtrado = pagos.aggregate(t=Sum('monto'))['t'] or 0

    precios = {
        str(c.id): {'precio': str(c.plan.precio_mensual if c.plan else ''), 'plan': c.plan.nombre if c.plan else '',
                    'vence': c.fecha_vencimiento.strftime('%d/%m/%Y') if c.fecha_vencimiento else ''}
        for c in form.fields['complejo'].queryset
    }
    return render(request, 'core/saas_registrar_pago.html', {
        'seccion_saas': 'pagos', 'form': form, 'pagos': _paginar(request, pagos, 15),
        'total_filtrado': total_filtrado, 'cancha_filtro': cancha_filtro,
        'canchas_filtro': ComplejoDeportivo.objects.filter(es_demo=False).order_by('nombre'),
        'precios': precios,
    })


@superadmin_requerido
@require_POST
def revertir_pago_saas(request, pago_id):
    """Anula un pago SaaS y descuenta los días que había dado a la cancha."""
    pago = get_object_or_404(PagoSuscripcionSaaS, id=pago_id)
    cancha = pago.complejo
    try:
        with transaction.atomic():
            if cancha.fecha_vencimiento:
                cancha.fecha_vencimiento -= timedelta(days=30 * pago.meses_pagados)
                if cancha.fecha_vencimiento < timezone.localdate():
                    cancha.activo = False
                cancha.save(update_fields=['fecha_vencimiento', 'activo'])
            meses = pago.meses_pagados
            pago.delete()
        estado = "ACTIVA" if cancha.activo else "SUSPENDIDA"
        vence = f"{cancha.fecha_vencimiento:%d/%m/%Y}" if cancha.fecha_vencimiento else "sin fecha"
        messages.success(request, f"🔄 Pago anulado: se descontaron {meses} mes(es). {cancha.nombre} vence el {vence} y queda {estado}.")
    except Exception as e:
        messages.error(request, f"Error al reversar: {e}")

    destino = request.POST.get('next', '')
    if destino.startswith('/nexus-admin/'):
        return redirect(destino)
    return redirect('registrar_pago_saas')


# =========================================================
# PLANES Y PRECIOS (SAAS)
# =========================================================

def precios_publicos(request):
    """Vista pública con los planes que el súper admin decidió publicar."""
    planes = (PlanSuscripcion.objects.filter(visible_publico=True)
              .exclude(nombre=NOMBRE_PLAN_DEMO).order_by('precio_mensual', 'nombre'))
    return render(request, 'core/precios_publicos.html', {'planes': planes})


def _render_planes(request, form, plan_editando=None):
    planes = (PlanSuscripcion.objects.exclude(nombre=NOMBRE_PLAN_DEMO)
              .annotate(num_canchas=Count('complejodeportivo', filter=Q(complejodeportivo__es_demo=False)))
              .order_by('precio_mensual', 'nombre'))
    return render(request, 'core/saas_gestionar_planes.html', {
        'seccion_saas': 'planes', 'form': form, 'planes': planes, 'plan_editando': plan_editando,
        'num_publicos': sum(1 for p in planes if p.visible_publico),
    })


@superadmin_requerido
def gestionar_planes_saas(request):
    if request.method == 'POST':
        form = PlanSuscripcionForm(request.POST)
        if form.is_valid():
            plan = form.save()
            visible = "visible en la página de precios" if plan.visible_publico else "oculto (solo para asignar)"
            messages.success(request, f"✅ Plan «{plan.nombre}» creado y {visible}.")
            return redirect('gestionar_planes_saas')
    else:
        form = PlanSuscripcionForm()
    return _render_planes(request, form)


@superadmin_requerido
def editar_plan_saas(request, plan_id):
    plan = get_object_or_404(PlanSuscripcion.objects.exclude(nombre=NOMBRE_PLAN_DEMO), id=plan_id)
    if request.method == 'POST':
        form = PlanSuscripcionForm(request.POST, instance=plan)
        if form.is_valid():
            form.save()
            messages.success(request, f"✅ Plan «{plan.nombre}» actualizado.")
            return redirect('gestionar_planes_saas')
    else:
        form = PlanSuscripcionForm(instance=plan)
    return _render_planes(request, form, plan_editando=plan)


@superadmin_requerido
@require_POST
def alternar_visibilidad_plan(request, plan_id):
    plan = get_object_or_404(PlanSuscripcion.objects.exclude(nombre=NOMBRE_PLAN_DEMO), id=plan_id)
    plan.visible_publico = not plan.visible_publico
    plan.save(update_fields=['visible_publico'])
    if plan.visible_publico:
        messages.success(request, f"👁️ «{plan.nombre}» ahora se muestra en la página de precios.")
    else:
        messages.info(request, f"🙈 «{plan.nombre}» quedó oculto: ya no aparece en la página de precios.")
    return redirect('gestionar_planes_saas')


@superadmin_requerido
@require_POST
def eliminar_plan_saas(request, plan_id):
    plan = get_object_or_404(PlanSuscripcion.objects.exclude(nombre=NOMBRE_PLAN_DEMO), id=plan_id)
    en_uso = ComplejoDeportivo.objects.filter(plan=plan).count()
    if en_uso:
        messages.error(request, f"⛔ No se puede eliminar «{plan.nombre}»: lo usan {en_uso} cancha(s). Ocúltalo o cámbiales el plan primero.")
    else:
        nombre = plan.nombre
        plan.delete()
        messages.success(request, f"🗑️ Plan «{nombre}» eliminado.")
    return redirect('gestionar_planes_saas')


def automatizacion_diaria_saas(request):
    """
    URL para ejecutar la automatización. En localhost la visitarás tú, en producción la visitará un bot.
    """
    import hmac
    token_enviado = request.GET.get('token', '')
    token_real = settings.CRON_SECRET_TOKEN

    if not hmac.compare_digest(token_enviado, token_real):
        return HttpResponse("Acceso denegado. Token inválido.", status=403)

    hoy = timezone.localtime(timezone.now()).date()
    log_acciones = []
    
    # 1. ENVIAR RECORDATORIOS (A los que les faltan exactamente 3 días)
    limite_aviso = hoy + timedelta(days=3)
    canchas_por_vencer = ComplejoDeportivo.objects.filter(fecha_vencimiento=limite_aviso, activo=True)
    
    for c in canchas_por_vencer:
        asunto = f"Aviso de Vencimiento: Tu suscripción a NEXUS SPORTOPS vence en 3 días"
        texto = f"Hola {c.organizador.first_name},\nTe recordamos que la suscripción de {c.nombre} vence el {c.fecha_vencimiento}."
        send_mail(asunto, texto, settings.EMAIL_HOST_USER, [c.organizador.email], fail_silently=True)
        log_acciones.append(f"Aviso enviado a: {c.nombre}")

    # 2. SUSPENDER MOROSOS AUTOMÁTICAMENTE
    canchas_vencidas = ComplejoDeportivo.objects.filter(fecha_vencimiento__lt=hoy, activo=True)
    
    for c in canchas_vencidas:
        c.activo = False
        c.save()
        asunto_susp = f"🚫 SUSPENSIÓN DE CUENTA: {c.nombre}"
        text_susp = f"Hola {c.organizador.first_name}, tu acceso a NEXUS SPORTOPS ha sido suspendido por falta de pago."
        send_mail(asunto_susp, text_susp, settings.EMAIL_HOST_USER, [c.organizador.email], fail_silently=True)
        log_acciones.append(f"Cancha SUSPENDIDA: {c.nombre}")

    if not log_acciones:
        log_acciones.append("Todo al día. Ninguna cancha suspendida ni por vencer en 3 días.")

    resultado = "\n".join(log_acciones)
    return HttpResponse(f"REVISIÓN COMPLETADA EXITOSAMENTE:\n{resultado}", content_type="text/plain")


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
            except IntegrityError:
                messages.error(request, "⛔ No se pudo crear el entorno de prueba: ya existe una cancha con un nombre en conflicto. Intenta de nuevo o contacta soporte.")
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

    return render(request, 'core/gestionar_roles_prueba.html', {
        'seccion_saas': 'pruebas', 'filas': filas,
        'num_en_prueba': sum(1 for f in filas if f['tiene_prueba']),
    })


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
def prueba_activar_dirigente(request, equipo_id):
    mi_complejo_demo = obtener_mi_complejo_demo(request.user)
    equipo = get_object_or_404(
        Equipo, id=equipo_id, dirigente=request.user, torneo__complejo=mi_complejo_demo,
    )
    if request.method == 'POST':
        request.session['equipo_simulado_id'] = equipo.id
        messages.success(request, f"🧪 Ahora estás viendo el sistema como el Dirigente de {equipo.nombre}.")
    return redirect('dashboard')


@login_required
def prueba_salir_modo_dirigente(request):
    if request.method == 'POST':
        request.session.pop('equipo_simulado_id', None)
    return redirect('dashboard')
