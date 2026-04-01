from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db.models import Count, Q, Sum, F
from django.template.loader import get_template
from django.db import transaction 
from xhtml2pdf import pisa 
from django.contrib.auth.models import User
from django.utils import timezone  
from datetime import datetime, time, timedelta, date
from django.core.exceptions import ValidationError
from urllib.parse import quote
import urllib.parse
from decimal import Decimal
from django.contrib.auth import login

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
    PagoSuscripcionSaaS, RolComplejo
)

from .utils import validar_cedula_ecuador, consultar_sri

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
            mis_equipos = Equipo.objects.filter(dirigente=request.user)
            if mis_equipos.exists():
                ctx['mi_equipo'] = mis_equipos.first() 
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
            Perfil.objects.get_or_create(usuario=u)
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
        if rol_cancha_id and nuevo_rol:
            rc = RolComplejo.objects.get(id=rol_cancha_id, complejo=mi_complejo)
            rc.rol = nuevo_rol
            rc.save()
            messages.success(request, f'Rol de {rc.usuario.username} actualizado a {rc.get_rol_display()} en esta cancha.')
            return redirect('gestionar_usuarios')
            
    return render(request, 'core/gestionar_usuarios.html', {'perfiles': roles_cancha})

@login_required
@user_passes_test(es_organizador)
def gestionar_torneos(request):
    mi_complejo = obtener_mi_complejo(request.user)
    torneos = Torneo.objects.filter(complejo=mi_complejo).order_by('categoria__nombre', '-fecha_inicio')
    
    if request.method == 'POST':
        form = TorneoForm(request.POST)
        if form.is_valid():
            t = form.save(commit=False)
            t.organizador = request.user
            t.complejo = mi_complejo # Asigna el torneo automáticamente a SU cancha
            t.save()
            messages.success(request, f'✅ Torneo "{t.nombre}" creado en {mi_complejo.nombre}.')
            return redirect('gestionar_torneos')
        else:
            messages.error(request, "Error al crear el torneo.")
    else:
        form = TorneoForm()
    return render(request, 'core/gestionar_torneos.html', {'form': form, 'torneos': torneos})

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
    return render(request, 'core/gestionar_torneos.html', {
        'form': form, 'torneos': Torneo.objects.filter(complejo=mi_complejo).order_by('-id'), 'editando': True, 'torneo_edit': torneo
    })

@login_required
@user_passes_test(es_organizador)
def eliminar_torneo(request, torneo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    torneo = get_object_or_404(Torneo, id=torneo_id, complejo=mi_complejo)
    nombre_torneo = torneo.nombre
    torneo.delete()
    messages.success(request, f'🗑️ El torneo "{nombre_torneo}" ha sido eliminado completamente.')
    return redirect('gestionar_torneos')

@login_required
@user_passes_test(es_organizador)
def gestionar_equipos(request):
    mi_complejo = obtener_mi_complejo(request.user)
    equipos = Equipo.objects.filter(torneo__complejo=mi_complejo, torneo__activo=True).select_related(
        'torneo', 'torneo__categoria', 'dirigente'
    ).order_by('torneo__categoria__nombre', 'torneo__nombre', 'nombre')
    
    if request.method == 'POST':
        form = EquipoForm(request.POST, request.FILES)
        if form.is_valid():
            nuevo_equipo = form.save()
            
            # 🔥 MULTI-TENANCY: Aseguramos que el dirigente tenga rol DIR en esta cancha
            RolComplejo.objects.get_or_create(
                usuario=nuevo_equipo.dirigente,
                complejo=mi_complejo,
                defaults={'rol': 'DIR'}
            )
            
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
        
    form.fields['torneo'].queryset = Torneo.objects.filter(complejo=mi_complejo, activo=True).order_by('categoria__nombre', 'nombre')
    return render(request, 'core/gestionar_equipos.html', {'form': form, 'equipos': equipos})

@login_required
@user_passes_test(es_organizador)
def editar_equipo(request, equipo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    equipo = get_object_or_404(Equipo, id=equipo_id, torneo__complejo=mi_complejo)
    if request.method == 'POST':
        form = EquipoForm(request.POST, request.FILES, instance=equipo)
        if form.is_valid():
            form.save()
            # 🔥 MULTI-TENANCY: Actualiza RolComplejo por si se cambió el dirigente
            RolComplejo.objects.get_or_create(
                usuario=equipo.dirigente,
                complejo=mi_complejo,
                defaults={'rol': 'DIR'}
            )
            messages.success(request, 'Equipo actualizado correctamente.')
            return redirect('gestionar_equipos')
    else:
        form = EquipoForm(instance=equipo)
        
    form.fields['torneo'].queryset = Torneo.objects.filter(complejo=mi_complejo, activo=True).order_by('categoria__nombre', 'nombre')
    equipos = Equipo.objects.filter(torneo__complejo=mi_complejo, torneo__activo=True).select_related(
        'torneo', 'torneo__categoria', 'dirigente'
    ).order_by('torneo__categoria__nombre', 'torneo__nombre', 'nombre')
    
    return render(request, 'core/gestionar_equipos.html', {'form': form, 'equipos': equipos, 'editando': True})

@login_required
@user_passes_test(es_organizador)
def eliminar_equipo(request, equipo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    equipo = get_object_or_404(Equipo, id=equipo_id, torneo__complejo=mi_complejo)
    equipo.delete()
    messages.success(request, 'Equipo eliminado. Los jugadores quedaron libres.')
    return redirect('gestionar_equipos')

# =========================================================
# ✨ LÓGICA BLINDADA: GESTIÓN DE JUGADORES Y CUPOS ✨
# =========================================================

@login_required
def gestionar_jugadores(request):
    rol_principal = obtener_rol_principal(request.user)
    puede_fichar = True 
    
    if rol_principal == 'DIR':
        mis_equipos = Equipo.objects.filter(dirigente=request.user)
        if not mis_equipos.exists():
            messages.error(request, 'No tienes un equipo inscrito. Inscríbete a un torneo primero.')
            return redirect('ver_torneos_activos')

        equipos_activos = mis_equipos.filter(torneo__activo=True).order_by('torneo__categoria__nombre', 'torneo__nombre', 'nombre')
        equipo_id = request.GET.get('equipo')
        mi_equipo = mis_equipos.filter(id=equipo_id).first() if equipo_id else (equipos_activos.first() or mis_equipos.first())
        
        jugadores = Jugador.objects.filter(equipo=mi_equipo).order_by('dorsal')
        equipo_seleccionado = mi_equipo.id
        
        if mi_equipo.esta_sancionado:
            puede_fichar = False
            messages.error(request, f'⛔ TU EQUIPO ESTÁ SANCIONADO HASTA {mi_equipo.sancionado_hasta}.')
        else:
            puede_fichar = mi_equipo.puede_fichar
        
        if request.method == 'POST':
            if not puede_fichar:
                messages.error(request, '⛔ Fichajes cerrados o límite alcanzado.')
                return redirect(f"{request.path}?equipo={mi_equipo.id}")
                
            form = JugadorForm(request.POST, request.FILES)
            form.fields['equipo'].queryset = mis_equipos 
            
            if form.is_valid():
                cedula_ingresada = form.cleaned_data.get('cedula')
                jugadores_activos_bd = Jugador.objects.filter(cedula=cedula_ingresada, equipo__torneo__activo=True)
                
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
                else:
                    jugador_historial = Jugador.objects.filter(cedula=cedula_ingresada).last()
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
            form = JugadorForm(initial={'equipo': mi_equipo})
            form.fields['equipo'].queryset = mis_equipos 

    elif rol_principal == 'ORG':
        mi_complejo = obtener_mi_complejo(request.user)
        equipos_activos = Equipo.objects.filter(torneo__complejo=mi_complejo, torneo__activo=True).order_by('torneo__categoria__nombre', 'torneo__nombre', 'nombre')
        equipo_id = request.GET.get('equipo')
        mi_equipo = Equipo.objects.filter(id=equipo_id, torneo__complejo=mi_complejo).first() if equipo_id else equipos_activos.first()
            
        if mi_equipo:
            jugadores = Jugador.objects.filter(equipo=mi_equipo).order_by('dorsal')
            equipo_seleccionado = mi_equipo.id
        else:
            jugadores = Jugador.objects.none()
            equipo_seleccionado = None
            
        if request.method == 'POST':
            form = JugadorForm(request.POST, request.FILES)
            if form.is_valid():
                cedula_ingresada = form.cleaned_data.get('cedula')
                equipo_destino = form.cleaned_data.get('equipo')
                
                jugadores_activos_bd = Jugador.objects.filter(cedula=cedula_ingresada, equipo__torneo__activo=True)
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
                    else:
                        jugador_historial = Jugador.objects.filter(cedula=cedula_ingresada).last()
                        nuevo_jugador = form.save(commit=False)
                        if jugador_historial and not nuevo_jugador.foto and jugador_historial.foto:
                            nuevo_jugador.foto = jugador_historial.foto
                            nuevo_jugador.rojas_directas_acumuladas = 0
                            nuevo_jugador.partidos_suspension = 0
                            nuevo_jugador.expulsado_torneo = False
                        nuevo_jugador.save()
                        messages.success(request, 'Jugador registrado en nueva categoría por Administración.')
                        
                return redirect(f"{request.path}?equipo={form.cleaned_data['equipo'].id}")
        else:
            form = JugadorForm()
    else:
        messages.error(request, "Acceso denegado.")
        return redirect('dashboard')

    if jugadores:
        for j in jugadores:
            j.otros_equipos = Jugador.objects.filter(
                cedula=j.cedula,
                equipo__torneo__activo=True
            ).exclude(id=j.id)

    return render(request, 'core/gestionar_jugadores.html', {
        'form': form, 'jugadores': jugadores, 
        'equipos_activos': equipos_activos if rol_principal == 'ORG' else mis_equipos.filter(torneo__activo=True).order_by('torneo__categoria__nombre', 'torneo__nombre', 'nombre'), 
        'equipo_seleccionado': equipo_seleccionado, 'es_dirigente': (rol_principal == 'DIR'),
        'puede_fichar': puede_fichar,
        'equipo_obj': mi_equipo 
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

    if request.method == 'POST':
        form = JugadorForm(request.POST, request.FILES, instance=jugador)
        if form.is_valid():
            form.save()
            messages.success(request, f'✅ Datos de {jugador.nombres} actualizados correctamente.')
            return redirect(f"/jugadores/?equipo={jugador.equipo.id}")
        else:
            messages.error(request, "❌ Revisa los campos del formulario.")
    else:
        form = JugadorForm(instance=jugador)

    equipos_activos = Equipo.objects.filter(torneo__complejo=mi_complejo, torneo__activo=True).order_by('torneo__categoria__nombre', 'torneo__nombre', 'nombre')

    return render(request, 'core/gestionar_jugadores.html', {
        'form': form, 
        'jugadores': Jugador.objects.filter(equipo=jugador.equipo).order_by('dorsal'), 
        'equipos_activos': equipos_activos, 
        'editando': True, 
        'es_dirigente': False,
        'equipo_seleccionado': jugador.equipo.id,
        'equipo_obj': jugador.equipo, 
        'puede_fichar': True 
    })

@login_required
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
    mis_canchas_ids = RolComplejo.objects.filter(usuario=request.user, rol__in=['ORG', 'VOC']).values_list('complejo_id', flat=True)
    if request.user.is_superuser:
        torneos = Torneo.objects.filter(activo=True).order_by('-fecha_inicio')
    else:
        torneos = Torneo.objects.filter(activo=True, complejo_id__in=mis_canchas_ids).order_by('-fecha_inicio')
        
    torneo_id_get = request.GET.get('torneo')
    torneo_obj = None
    partidos = []

    if torneo_id_get:
        torneo_obj = get_object_or_404(Torneo, id=torneo_id_get)
        if not request.user.is_superuser and torneo_obj.complejo.id not in mis_canchas_ids:
            messages.error(request, "Acceso denegado a este complejo.")
            return redirect('dashboard')
            
        partidos_qs = Partido.objects.filter(torneo=torneo_obj)\
            .select_related('equipo_local', 'equipo_visita')\
            .order_by('etapa', 'numero_fecha', 'fecha_hora')
            
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
                    messages.error(request, f"⛔ Regla de Grupos: {equipo_local.nombre} no puede jugar contra {equipo_visita.nombre}.")
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

    return render(request, 'core/programar_partidos.html', {
        'partidos': partidos, 
        'form': form, 
        'torneos': torneos,
        'torneo_actual': int(torneo_id_get) if torneo_id_get else None,
        'torneo': torneo_obj
    })

@login_required
@user_passes_test(es_organizador)
def editar_partido(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    mi_complejo = obtener_mi_complejo(request.user)
    if partido.torneo.complejo != mi_complejo and not request.user.is_superuser:
        return redirect('dashboard')
        
    if request.method == 'POST':
        form = ProgramarPartidoForm(request.POST, instance=partido)
        if form.is_valid():
            form.save()
            messages.success(request, 'Datos del partido actualizados.')
            return redirect(f"/programar/?torneo={partido.torneo.id}")
    else:
        form = ProgramarPartidoForm(instance=partido)
    return render(request, 'core/editar_partido.html', {'form': form, 'partido': partido})

@login_required
@user_passes_test(es_organizador)
def eliminar_partido(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    mi_complejo = obtener_mi_complejo(request.user)
    if partido.torneo.complejo != mi_complejo and not request.user.is_superuser:
        return redirect('dashboard')
        
    torneo_id = partido.torneo.id
    partido.delete()
    messages.warning(request, 'Partido eliminado del calendario.')
    return redirect(f"/programar/?torneo={torneo_id}")

@login_required
@user_passes_test(es_organizador)
def reiniciar_partido(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    mi_complejo = obtener_mi_complejo(request.user)
    if partido.torneo.complejo != mi_complejo and not request.user.is_superuser:
        return redirect('dashboard')
        
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
    partido.save()
    
    messages.info(request, 'El partido ha sido reiniciado. Ahora está pendiente de juego.')
    return redirect(f"/programar/?torneo={partido.torneo.id}")

# =========================================================
# 3. JUEGO, VOCALÍA Y RESULTADOS (ACCESO VOCAL Y ADMIN)
# =========================================================

def verificar_acceso_partido(user, partido):
    if user.is_superuser: return True
    rc = RolComplejo.objects.filter(usuario=user, complejo=partido.torneo.complejo).first()
    if rc and rc.rol in ['ORG', 'VOC']: return True
    return False

@login_required
@user_passes_test(es_vocal_o_admin)
def registrar_resultado(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    if not verificar_acceso_partido(request.user, partido): return redirect('dashboard')

    if request.method == 'POST':
        goles_local = request.POST.get('goles_local')
        goles_visita = request.POST.get('goles_visita')
        wo = request.POST.get('wo')

        if wo == 'on':
            partido.estado = 'WO'
            partido.goles_local = 3
            partido.goles_visita = 0
        else:
            partido.goles_local = int(goles_local)
            partido.goles_visita = int(goles_visita)
            partido.estado = 'JUG' 

        partido.save()
        messages.success(request, f'Resultado registrado: {partido.equipo_local} ({partido.goles_local}) - ({partido.goles_visita}) {partido.equipo_visita}')
        return redirect(f"/programar/?torneo={partido.torneo.id}")
    return render(request, 'core/registrar_resultado.html', {'partido': partido})

@login_required
@user_passes_test(es_vocal_o_admin)
def gestionar_vocalia(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    if not verificar_acceso_partido(request.user, partido): return redirect('dashboard')
    
    jugadores_local = Jugador.objects.filter(equipo=partido.equipo_local).annotate(
        goles_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='GOL')),
        ta_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='TA')),
        tr_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='TR')),
        da_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='DA')),
        star_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='STAR'))
    ).order_by('dorsal')

    jugadores_visita = Jugador.objects.filter(equipo=partido.equipo_visita).annotate(
        goles_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='GOL')),
        ta_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='TA')),
        tr_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='TR')),
        da_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='DA')),
        star_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='STAR')) 
    ).order_by('dorsal')

    deudas_pendientes = Sancion.objects.filter(
        equipo__in=[partido.equipo_local, partido.equipo_visita], 
        pagada=False
    ).select_related('equipo', 'jugador').order_by('equipo__nombre')

    asistencias_ids = list(DetallePartido.objects.filter(partido=partido, tipo='ASIS').values_list('jugador_id', flat=True))
    multas = Sancion.objects.filter(partido=partido).order_by('-id')

    if request.method == 'POST':
        if 'cobrar_deuda' in request.POST:
            from decimal import Decimal
            sancion_id = request.POST.get('sancion_id')
            abono_str = request.POST.get('monto_abono')
            sancion = get_object_or_404(Sancion, id=sancion_id)
            abono = Decimal(abono_str) if abono_str else sancion.saldo
            
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
            tipo_wo = request.POST.get('tipo_wo')
            if tipo_wo == 'LOCAL':
                partido.estado = 'WO'
                partido.goles_local = 3
                partido.goles_visita = 0
                partido.ganador_wo = partido.equipo_local
            elif tipo_wo == 'VISITA':
                partido.estado = 'WO'
                partido.goles_local = 0
                partido.goles_visita = 3
                partido.ganador_wo = partido.equipo_visita
            elif tipo_wo == 'DOBLE':
                partido.estado = 'WO'
                partido.goles_local = 0
                partido.goles_visita = 0
                partido.ganador_wo = None
            
            partido.validado_local = True
            partido.validado_visita = True
            partido.sanciones_aplicadas = True 
            partido.save()
            messages.success(request, '🚨 Partido finalizado por W.O. exitosamente.')
            return redirect(f"/programar/?torneo={partido.torneo.id}")

        elif 'guardar_informe' in request.POST:
            partido.informe_vocal = request.POST.get('informe_vocal')
            partido.informe_arbitro = request.POST.get('informe_arbitro')
            partido.validado_local = request.POST.get('validado_local') == 'on'
            partido.validado_visita = request.POST.get('validado_visita') == 'on'
            
            if partido.etapa in ['4TOS', 'SEMI', 'TERC', 'FINAL']:
                p_local = request.POST.get('penales_local', 0)
                p_visita = request.POST.get('penales_visita', 0)
                p_local = int(p_local) if p_local else 0
                p_visita = int(p_visita) if p_visita else 0

                if p_local > 0 or p_visita > 0:
                    partido.hubo_penales = True
                    partido.penales_local = p_local
                    partido.penales_visita = p_visita
                else:
                    partido.hubo_penales = False
                    partido.penales_local = 0
                    partido.penales_visita = 0

            if partido.validado_local and partido.validado_visita:
                partido.estado = 'JUG'
            else:
                partido.estado = 'ACTA'
            
            partido.save()

            if partido.estado == 'JUG' and not partido.sanciones_aplicadas:
                jugadores_ambos_equipos = Jugador.objects.filter(equipo__in=[partido.equipo_local, partido.equipo_visita], partidos_suspension__gt=0)
                detalles = DetallePartido.objects.filter(partido=partido)
                
                for j in jugadores_ambos_equipos:
                    if not detalles.filter(jugador=j, tipo__in=['DA', 'TR']).exists():
                        j.partidos_suspension -= 1
                        j.save()

                jugadores_con_eventos = set([d.jugador for d in detalles])
                for j in jugadores_con_eventos:
                    eventos_j = detalles.filter(jugador=j)
                    ta_partido = eventos_j.filter(tipo='TA').count()
                    da_partido = eventos_j.filter(tipo='DA').count()
                    tr_partido = eventos_j.filter(tipo='TR').count()

                    if tr_partido > 0:
                        j.partidos_suspension += 2
                        j.rojas_directas_acumuladas += 1
                        
                        if j.rojas_directas_acumuladas >= 3:
                            j.expulsado_torneo = True
                            desc_roja = f"Expulsión Definitiva del Torneo (Límite 3 Rojas) - {j.nombres}"
                        else:
                            desc_roja = f"Roja Directa - {j.nombres}"
                            
                        j.save()
                        Sancion.objects.create(torneo=partido.torneo, equipo=j.equipo, jugador=j, partido=partido, tipo='ROJA', monto=partido.torneo.costo_roja, descripcion=desc_roja)
                    
                    if da_partido > 0:
                        j.partidos_suspension += 1
                        j.save()
                        Sancion.objects.create(torneo=partido.torneo, equipo=j.equipo, jugador=j, partido=partido, tipo='ROJA', monto=partido.torneo.costo_roja, descripcion=f"Roja por Acumulación - {j.nombres}")
                    
                    if ta_partido > 0:
                        Sancion.objects.create(torneo=partido.torneo, equipo=j.equipo, jugador=j, partido=partido, tipo='AMARILLA', monto=partido.torneo.costo_amarilla, descripcion=f"Tarjeta Amarilla - {j.nombres}")
                        
                        if partido.etapa == 'F1':
                            fases_validas = ['F1']
                        elif partido.etapa == 'F2':
                            fases_validas = ['F2']
                        else:
                            fases_validas = ['4TOS', 'SEMI', 'TERC', 'FINAL']
                        
                        total_ta_fase = DetallePartido.objects.filter(
                            jugador=j, 
                            partido__torneo=partido.torneo, 
                            partido__etapa__in=fases_validas,
                            tipo='TA'
                        ).count()
                        
                        if total_ta_fase > 0 and total_ta_fase % 4 == 0:
                            j.partidos_suspension += 1
                            j.save()

                partido.sanciones_aplicadas = True
                partido.save()

                messages.success(request, '✅ Acta firmada por ambos equipos. Partido Finalizado y Sanciones aplicadas.')
                return redirect(f"/programar/?torneo={partido.torneo.id}")
            
            else:
                if 'guardar_y_volver' in request.POST:
                    messages.info(request, '📋 Partido guardado en Actas. (Aún faltan firmas para cerrarlo).')
                    return redirect(f"/programar/?torneo={partido.torneo.id}")
                else:
                    if partido.estado == 'JUG':
                         messages.success(request, '✅ Acta actualizada con éxito (Evitando cobros duplicados).')
                         return redirect(f"/programar/?torneo={partido.torneo.id}")
                    else:
                         messages.warning(request, '⚠️ Faltan las firmas de ambos equipos para Finalizar el partido oficialmente.')
                         return redirect('gestionar_vocalia', partido_id=partido_id)
        
        elif 'nueva_multa' in request.POST:
            equipo_id = request.POST.get('equipo_multa')
            motivo = request.POST.get('motivo_multa')
            monto = request.POST.get('monto_multa')
            if equipo_id and motivo and monto:
                Sancion.objects.create(
                    torneo=partido.torneo, equipo_id=equipo_id, partido=partido,
                    tipo='ADMIN', monto=monto, descripcion=motivo, pagada=False
                )
            return redirect('gestionar_vocalia', partido_id=partido_id)

    return render(request, 'core/gestionar_vocalia.html', {
        'partido': partido,
        'jugadores_local': jugadores_local,
        'jugadores_visita': jugadores_visita,
        'asistencias_ids': asistencias_ids,
        'multas': multas,
        'deudas_pendientes': deudas_pendientes
    })

@login_required
@user_passes_test(es_vocal_o_admin)
def registrar_incidencia(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    if not verificar_acceso_partido(request.user, partido): return redirect('dashboard')

    if request.method == 'POST':
        jugador_id = request.POST.get('jugador_id')
        tipo_evento = request.POST.get('tipo') 
        minuto = request.POST.get('minuto', 0)
        
        jugador = get_object_or_404(Jugador, id=jugador_id)

        if tipo_evento == 'TA':
            amarilla_previa = DetallePartido.objects.filter(partido=partido, jugador=jugador, tipo='TA').first()
            if amarilla_previa:
                amarilla_previa.delete()
                DetallePartido.objects.create(partido=partido, jugador=jugador, tipo='DA', observacion="Roja por Acum.", equipo_incidencia=jugador.equipo)
                messages.error(request, f'🟥 ¡ROJA POR ACUMULACIÓN para {jugador.nombres}!')
            else:
                DetallePartido.objects.create(partido=partido, jugador=jugador, tipo='TA', minuto=int(minuto) if minuto else 0, equipo_incidencia=jugador.equipo)
                messages.warning(request, f'🟨 Tarjeta Amarilla registrada a {jugador.nombres}.')

        elif tipo_evento == 'TR':
            DetallePartido.objects.create(partido=partido, jugador=jugador, tipo='TR', minuto=int(minuto) if minuto else 0, equipo_incidencia=jugador.equipo)
            messages.error(request, f'🟥 ¡ROJA DIRECTA para {jugador.nombres}!')

        elif tipo_evento == 'GOL':
            DetallePartido.objects.create(partido=partido, jugador=jugador, tipo='GOL', minuto=int(minuto) if minuto else 0, equipo_incidencia=jugador.equipo)
            if jugador.equipo == partido.equipo_local:
                partido.goles_local += 1
            else:
                partido.goles_visita += 1
            messages.success(request, f'⚽ ¡Gol de {jugador.nombres}!')

        elif tipo_evento == 'STAR':
            estrellas_actuales = DetallePartido.objects.filter(partido=partido, tipo='STAR').count()
            if estrellas_actuales >= 2:
                messages.error(request, '⭐ Error: Solo se pueden asignar máximo 2 figuras por partido.')
            else:
                DetallePartido.objects.create(partido=partido, jugador=jugador, tipo='STAR', equipo_incidencia=jugador.equipo)
                messages.success(request, f'⭐ ¡{jugador.nombres} fue elegido como Figura del Partido!')
        
        if partido.estado == 'PROG':
            partido.estado = 'VIVO'
        
        partido.save()

    return redirect('gestionar_vocalia', partido_id=partido.id)

@login_required
@user_passes_test(es_vocal_o_admin)
def eliminar_evento_ultimo(request, partido_id, jugador_id, tipo):
    partido = get_object_or_404(Partido, id=partido_id)
    if not verificar_acceso_partido(request.user, partido): return redirect('dashboard')
    
    if tipo == 'TA':
        evento_da = DetallePartido.objects.filter(partido_id=partido_id, jugador_id=jugador_id, tipo='DA').last()
        if evento_da:
            jugador_obj = evento_da.jugador
            evento_da.delete()
            DetallePartido.objects.create(partido_id=partido_id, jugador_id=jugador_id, tipo='TA', equipo_incidencia=jugador_obj.equipo)
            messages.success(request, "Corrección: Roja por Acumulación anulada. Se restauró 1 Amarilla.")
            return redirect('gestionar_vocalia', partido_id=partido_id)

    evento = DetallePartido.objects.filter(
        partido_id=partido_id, 
        jugador_id=jugador_id, 
        tipo=tipo
    ).last()
    
    if evento:
        if tipo == 'GOL':
            if evento.equipo_incidencia == partido.equipo_local:
                partido.goles_local = max(0, partido.goles_local - 1)
            else:
                partido.goles_visita = max(0, partido.goles_visita - 1)
            partido.save()
        
        evento.delete()
        messages.warning(request, f"Corrección: Se eliminó el último registro de {tipo} para {evento.jugador.nombres}.")
    
    return redirect('gestionar_vocalia', partido_id=partido_id)

@login_required
@user_passes_test(es_vocal_o_admin)
def eliminar_evento(request, evento_id):
    evento = DetallePartido.objects.get(id=evento_id)
    partido = evento.partido
    if not verificar_acceso_partido(request.user, partido): return redirect('dashboard')
    
    if evento.tipo == 'GOL':
        if evento.equipo_incidencia == partido.equipo_local:
            partido.goles_local = max(0, partido.goles_local - 1)
        else:
            partido.goles_visita = max(0, partido.goles_visita - 1)
        partido.save()
    
    evento.delete()
    messages.success(request, 'Corrección realizada: Evento eliminado.')
    return redirect('gestionar_vocalia', partido_id=partido.id)


@login_required
@user_passes_test(es_vocal_o_admin)
def eliminar_multa(request, multa_id):
    sancion = get_object_or_404(Sancion, id=multa_id)
    partido = sancion.partido
    if partido and not verificar_acceso_partido(request.user, partido): return redirect('dashboard')
    
    partido_id = sancion.partido.id if sancion.partido else None
    sancion.delete()
    messages.success(request, 'Sanción administrativa eliminada correctamente.')
    
    if partido_id:
        return redirect('gestionar_vocalia', partido_id=partido_id)
    return redirect('dashboard')


@login_required
@user_passes_test(es_vocal_o_admin)
def toggle_asistencia(request, partido_id, jugador_id):
    partido = get_object_or_404(Partido, id=partido_id)
    if not verificar_acceso_partido(request.user, partido): return redirect('dashboard')
    jugador = get_object_or_404(Jugador, id=jugador_id)
    
    asistencia = DetallePartido.objects.filter(partido=partido, jugador=jugador, tipo='ASIS').first()
    
    if asistencia:
        with transaction.atomic():
            goles_jugador = DetallePartido.objects.filter(partido=partido, jugador=jugador, tipo='GOL').count()
            if goles_jugador > 0:
                if jugador.equipo == partido.equipo_local:
                    partido.goles_local = max(0, partido.goles_local - goles_jugador)
                else:
                    partido.goles_visita = max(0, partido.goles_visita - goles_jugador)
                partido.save()
                
            DetallePartido.objects.filter(partido=partido, jugador=jugador).delete()
            messages.warning(request, f'Se retiró a {jugador.nombres}. Historial del partido limpiado.')
    else:
        DetallePartido.objects.create(partido=partido, jugador=jugador, tipo='ASIS', equipo_incidencia=jugador.equipo)
        messages.success(request, f'{jugador.nombres} ingresó a la cancha.')
        
    return redirect('gestionar_vocalia', partido_id=partido.id)

# =========================================================
# 4. REPORTES Y ESTADÍSTICAS
# =========================================================

def tabla_posiciones(request, torneo_id):
    torneo = Torneo.objects.get(id=torneo_id)
    equipos = Equipo.objects.filter(torneo=torneo, estado_inscripcion='APROBADO')
    tabla = []

    for equipo in equipos:
        partidos = Partido.objects.filter(
            Q(equipo_local=equipo) | Q(equipo_visita=equipo),
            estado__in=['JUG', 'WO', 'FINALIZADO'], 
            etapa='F1' 
        )
        
        pj = 0; pg = 0; pe = 0; pp = 0; gf = 0; gc = 0
        
        for p in partidos:
            pj += 1
            es_local = (p.equipo_local == equipo)
            goles_propios = p.goles_local if es_local else p.goles_visita
            goles_rival = p.goles_visita if es_local else p.goles_local
            
            gf += goles_propios
            gc += goles_rival
            
            if p.estado == 'WO':
                if p.ganador_wo == equipo:
                    pg += 1  
                else:
                    pp += 1  
            else:
                if goles_propios > goles_rival: pg += 1
                elif goles_propios < goles_rival: pp += 1
                else: pe += 1
        
        puntos = (pg * 3) + (pe * 1)
        gol_diferencia = gf - gc
        
        tabla.append({
            'equipo': equipo,
            'pj': pj, 'pg': pg, 'pe': pe, 'pp': pp,
            'gf': gf, 'gc': gc, 'gd': gol_diferencia,
            'pts': puntos,
            'bono': 0
        })
    
    tabla_ordenada = sorted(tabla, key=lambda x: (x['pts'], x['gd'], x['gf']), reverse=True)
    fase2_ya_generada = equipos.filter(grupo_fase2__in=['A', 'B']).exists()

    return render(request, 'core/tabla_posiciones.html', {
        'torneo': torneo, 
        'tabla': tabla_ordenada, 
        'fase': 1,
        'fase2_ya_generada': fase2_ya_generada
    })

@login_required
@user_passes_test(es_organizador)
def generar_fase2(request, torneo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    torneo = get_object_or_404(Torneo, id=torneo_id, complejo=mi_complejo)
    equipos = Equipo.objects.filter(torneo=torneo, estado_inscripcion='APROBADO')
    
    ida_y_vuelta = request.POST.get('ida_y_vuelta') == 'on'
    torneo.fase2_ida_vuelta = ida_y_vuelta
    torneo.save()

    tabla = []
    for equipo in equipos:
        partidos = Partido.objects.filter(Q(equipo_local=equipo) | Q(equipo_visita=equipo), estado__in=['JUG', 'WO', 'FINALIZADO'], etapa='F1')
        puntos = 0; gf = 0; gc = 0
        for p in partidos:
            es_local = (p.equipo_local == equipo)
            goles_pro = p.goles_local if es_local else p.goles_visita
            goles_riv = p.goles_visita if es_local else p.goles_local
            gf += goles_pro; gc += goles_riv
            if goles_pro > goles_riv: puntos += 3
            elif goles_pro == goles_riv: puntos += 1
        gd = gf - gc
        tabla.append({'equipo': equipo, 'pts': puntos, 'gd': gd, 'gf': gf})

    tabla_ordenada = sorted(tabla, key=lambda x: (x['pts'], x['gd'], x['gf']), reverse=True)

    with transaction.atomic():
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
    torneo = Torneo.objects.get(id=torneo_id)
    
    def calcular_grupo(letra_grupo):
        equipos_grupo = Equipo.objects.filter(torneo=torneo, grupo_fase2=letra_grupo, estado_inscripcion='APROBADO')
        lista_tabla = []
        
        for equipo in equipos_grupo:
            partidos = Partido.objects.filter(
                Q(equipo_local=equipo) | Q(equipo_visita=equipo),
                estado__in=['JUG', 'WO', 'FINALIZADO'],
                etapa='F2' 
            )
            
            pj=0; pg=0; pe=0; pp=0; gf=0; gc=0
            for p in partidos:
                pj+=1
                es_local = (p.equipo_local == equipo)
                goles_pro = p.goles_local if es_local else p.goles_visita
                goles_rival = p.goles_visita if es_local else p.goles_local
                gf+=goles_pro; gc+=goles_rival
                
                if goles_pro > goles_rival: pg+=1
                elif goles_pro < goles_rival: pp+=1
                else: pe+=1
            
            puntos = (pg * 3) + (pe * 1) + equipo.puntos_bonificacion
            gd = gf - gc
            
            lista_tabla.append({
                'equipo': equipo, 
                'pj': pj, 'pg': pg, 'pe': pe, 'pp': pp,
                'gf': gf, 'gc': gc, 'gd': gd, 
                'pts': puntos,
                'bono': equipo.puntos_bonificacion
            })
        
        return sorted(lista_tabla, key=lambda x: (x['pts'], x['gd'], x['gf']), reverse=True)

    tabla_a = calcular_grupo('A')
    tabla_b = calcular_grupo('B')
    
    cuartos_generados = Partido.objects.filter(torneo=torneo, etapa='4TOS').exists()

    es_org = request.user.is_authenticated and obtener_rol_principal(request.user) == 'ORG'

    return render(request, 'core/tabla_posiciones_f2.html', {
        'torneo': torneo, 
        'tabla_a': tabla_a, 
        'tabla_b': tabla_b,
        'fase': 2,
        'cuartos_generados': cuartos_generados,
        'es_organizador': es_org
    })

def seleccionar_reporte(request):
    torneos_activos = Torneo.objects.filter(activo=True).order_by('categoria__nombre', '-fecha_inicio')
    torneos_finalizados = Torneo.objects.filter(activo=False).order_by('-fecha_inicio')
    
    return render(request, 'core/seleccionar_reporte.html', {
        'torneos_activos': torneos_activos, 
        'torneos_finalizados': torneos_finalizados
    })

@login_required
def reporte_estadisticas(request, torneo_id):
    torneo = get_object_or_404(Torneo, id=torneo_id)
    rol = obtener_rol_principal(request.user)

    hay_fase1 = Partido.objects.filter(torneo=torneo, etapa='F1').exists()
    hay_fase2 = Partido.objects.filter(torneo=torneo, etapa='F2').exists()
    hay_llaves = Partido.objects.filter(torneo=torneo, etapa__in=['4TOS', 'SEMI', 'TERC', 'FINAL']).exists()

    fase_forzada = request.GET.get('fase')
    fase_actual = 1

    if rol == 'ORG' and fase_forzada:
        fase_actual = int(fase_forzada)
    else:
        if hay_fase2 or hay_llaves:
            fase_actual = 2
        else:
            fase_actual = 1

    tabla_fase1 = []
    tabla_a = []
    tabla_b = []
    equipos_todos = Equipo.objects.filter(torneo=torneo, estado_inscripcion='APROBADO')

    if fase_actual == 1:
        for equipo in equipos_todos:
            partidos = Partido.objects.filter(
                Q(equipo_local=equipo) | Q(equipo_visita=equipo),
                estado__in=['JUG', 'WO', 'FINALIZADO'], etapa='F1'
            )
            pj=0; pg=0; pe=0; pp=0; gf=0; gc=0
            for p in partidos:
                pj += 1
                es_local = (p.equipo_local == equipo)
                goles_pro = p.goles_local if es_local else p.goles_visita
                goles_riv = p.goles_visita if es_local else p.goles_local
                gf += goles_pro; gc += goles_riv
                if goles_pro > goles_riv: pg += 1
                elif goles_pro < goles_riv: pp += 1
                else: pe += 1
            tabla_fase1.append({
                'equipo': equipo, 'pj': pj, 'pg': pg, 'pe': pe, 'pp': pp,
                'gf': gf, 'gc': gc, 'gd': gf - gc, 'pts': (pg * 3) + (pe * 1)
            })
        tabla_fase1 = sorted(tabla_fase1, key=lambda x: (x['pts'], x['gd'], x['gf']), reverse=True)

    elif fase_actual == 2:
        def calcular_grupo(letra_grupo):
            equipos_grupo = equipos_todos.filter(grupo_fase2=letra_grupo)
            lista_tabla = []
            for equipo in equipos_grupo:
                partidos = Partido.objects.filter(
                    Q(equipo_local=equipo) | Q(equipo_visita=equipo),
                    estado__in=['JUG', 'WO', 'FINALIZADO'], etapa='F2'
                )
                pj=0; pg=0; pe=0; pp=0; gf=0; gc=0
                for p in partidos:
                    pj+=1
                    es_local = (p.equipo_local == equipo)
                    goles_pro = p.goles_local if es_local else p.goles_visita
                    goles_riv = p.goles_visita if es_local else p.goles_local
                    gf+=goles_pro; gc+=goles_riv
                    if goles_pro > goles_riv: pg+=1
                    elif goles_pro < goles_riv: pp+=1
                    else: pe+=1
                pts = (pg * 3) + (pe * 1) + equipo.puntos_bonificacion
                lista_tabla.append({
                    'equipo': equipo, 'pj': pj, 'pg': pg, 'pe': pe, 'pp': pp,
                    'gf': gf, 'gc': gc, 'gd': gf-gc, 'pts': pts, 'bono': equipo.puntos_bonificacion
                })
            return sorted(lista_tabla, key=lambda x: (x['pts'], x['gd'], x['gf']), reverse=True)
        
        tabla_a = calcular_grupo('A')
        tabla_b = calcular_grupo('B')

    goleadores = DetallePartido.objects.filter(
        partido__torneo=torneo, 
        tipo='GOL',
        equipo_incidencia=F('jugador__equipo') 
    ).values(
        'jugador__nombres', 'jugador__equipo__nombre', 'jugador__equipo__escudo'
    ).annotate(
        total_goles=Count('id')
    ).order_by('-total_goles', 'jugador__nombres')[:15]

    sancionados_activos = []
    jugadores_suspendidos = Jugador.objects.filter(equipo__in=equipos_todos, partidos_suspension__gt=0)
    for j in jugadores_suspendidos:
        detalles = DetallePartido.objects.filter(jugador=j, partido__torneo=torneo).order_by('partido__fecha_hora')
        motivo = "Suspensión Disciplinaria"
        ultimo_fuerte = detalles.filter(tipo__in=['TR', 'DA', 'EBRI', 'AZUL']).last()
        amarillas_totales = detalles.filter(tipo='TA')
        cantidad_ta = amarillas_totales.count()
        
        ultima_amarilla_sancionable = None
        if cantidad_ta > 0 and cantidad_ta % 4 == 0:
            ultima_amarilla_sancionable = amarillas_totales.last()

        if ultima_amarilla_sancionable and ultimo_fuerte:
            if ultima_amarilla_sancionable.partido.fecha_hora > ultimo_fuerte.partido.fecha_hora: motivo = "Acumulación 4 Amarillas"
            else:
                if ultimo_fuerte.tipo == 'TR': motivo = "Roja Directa"
                elif ultimo_fuerte.tipo == 'DA': motivo = "Roja por Acumulación (DA)"
                else: motivo = f"Sanción Especial ({ultimo_fuerte.tipo})"
        elif ultima_amarilla_sancionable: motivo = "Acumulación 4 Amarillas"
        elif ultimo_fuerte:
            if ultimo_fuerte.tipo == 'TR': motivo = "Roja Directa"
            elif ultimo_fuerte.tipo == 'DA': motivo = "Roja por Acumulación (DA)"
            else: motivo = f"Sanción Especial ({ultimo_fuerte.tipo})"

        sancionados_activos.append({'jugador': j, 'motivo': motivo, 'restantes': f"Debe {j.partidos_suspension} fecha(s)"})

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
        try:
            equipo_seleccionado = equipos_permitidos.get(id=equipo_id)
        except Equipo.DoesNotExist:
            equipo_seleccionado = None

    if equipo_seleccionado:
        jugadores_actuales = list(Jugador.objects.filter(equipo=equipo_seleccionado).values_list('id', flat=True))
        jugadores_historicos = list(DetallePartido.objects.filter(equipo_incidencia=equipo_seleccionado).values_list('jugador_id', flat=True))
        
        ids_unicos = set(jugadores_actuales + jugadores_historicos)
        roster = Jugador.objects.filter(id__in=ids_unicos)

        for j in roster:
            stats = DetallePartido.objects.filter(
                jugador=j, 
                partido__torneo=torneo, 
                equipo_incidencia=equipo_seleccionado
            )
            
            nota_transferido = "" if j.id in jugadores_actuales else " (Transferido)"

            total_ta = stats.filter(tipo='TA').count()
            ta_mostrar = total_ta % 4 
            
            if j.id in jugadores_actuales or stats.exists():
                jugadores_detalle.append({
                    'nombre': j.nombres + nota_transferido, 
                    'pj': stats.filter(tipo='ASIS').count(), 
                    'ta': ta_mostrar, 
                    'da': stats.filter(tipo='DA').count(),
                    'tr': stats.filter(tipo='TR').count(), 
                    'goles': stats.filter(tipo='GOL').count(),
                    'stars': stats.filter(tipo='STAR').count()
                })
                
    return render(request, 'core/reporte_estadisticas.html', {
        'torneo': torneo, 
        'fase_actual': fase_actual,
        'tabla_fase1': tabla_fase1,
        'tabla_a': tabla_a,
        'tabla_b': tabla_b,
        'goleadores': goleadores, 
        'equipos_permitidos': equipos_permitidos, 
        'equipo_seleccionado': equipo_seleccionado, 
        'jugadores_detalle': jugadores_detalle, 
        'sancionados_activos': sancionados_activos, 
        'rol': rol,
        'hay_llaves': hay_llaves
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

@login_required
@user_passes_test(es_vocal_o_admin)
def generar_acta_pdf(request, partido_id):
    partido = Partido.objects.get(id=partido_id)
    if not verificar_acceso_partido(request.user, partido): return redirect('dashboard')
    
    detalles = DetallePartido.objects.filter(partido=partido).select_related('jugador')
    
    asistencias_local = detalles.filter(tipo='ASIS', equipo_incidencia=partido.equipo_local)
    asistencias_visita = detalles.filter(tipo='ASIS', equipo_incidencia=partido.equipo_visita)
    goles = detalles.filter(tipo='GOL')
    tarjetas = detalles.filter(tipo__in=['TA', 'TR', 'DA', 'AZUL', 'EBRI'])
    estrellas = detalles.filter(tipo='STAR') 
    abonos = AbonoSancion.objects.filter(partido=partido) 
    multas = Sancion.objects.filter(partido=partido, tipo='ADMIN')

    template_path = 'core/acta_partido_pdf.html'
    context = {
        'partido': partido, 'asistencias_local': asistencias_local,
        'asistencias_visita': asistencias_visita, 'goles': goles,
        'tarjetas': tarjetas, 'estrellas': estrellas, 'abonos': abonos,
        'multas': multas 
    }
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="Acta_{partido.id}.pdf"'
    
    template = get_template(template_path)
    html = template.render(context)
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    
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

def generar_recibo_pago_pdf(request, pago_id):
    pago = get_object_or_404(Pago, id=pago_id)
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
            Perfil.objects.get_or_create(usuario=usuario)
            login(request, usuario)
            messages.success(request, f'¡Bienvenido crack! Tu cuenta ha sido creada y ya estás dentro.')
            return redirect('dashboard') 
    else:
        form = RegistroPublicoForm()
        
    return render(request, 'registration/registro_publico.html', {'form': form})

def ver_torneos_activos(request):
    torneos_activos = Torneo.objects.filter(activo=True).order_by('categoria__nombre', 'fecha_inicio')
    torneos_finalizados = Torneo.objects.filter(activo=False).order_by('-fecha_inicio')
    
    mis_torneos_ids = []
    if request.user.is_authenticated:
        # Aunque tenga otro rol principal, si tiene equipos los mostramos
        mis_torneos_ids = list(Equipo.objects.filter(dirigente=request.user).values_list('torneo_id', flat=True))

    return render(request, 'core/ver_torneos_activos.html', {
        'torneos_activos': torneos_activos,
        'torneos_finalizados': torneos_finalizados,
        'mis_torneos_ids': mis_torneos_ids 
    })

@login_required
def solicitar_inscripcion(request, torneo_id):
    torneo = get_object_or_404(Torneo, id=torneo_id)
    
    if not torneo.inscripcion_abierta:
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
            
            # 🔥 MULTI-TENANCY: Al inscribirse, se crea RolComplejo de DIR en la cancha actual
            RolComplejo.objects.get_or_create(
                usuario=request.user, 
                complejo=torneo.complejo, 
                defaults={'rol': 'DIR'}
            )
            
            try:
                from django.core.mail import send_mail
                from django.conf import settings
                
                asunto = f"🏆 NUEVA SOLICITUD: {equipo.nombre} quiere unirse"
                mensaje = "Nueva solicitud registrada en el sistema."
                
                send_mail(
                    subject=asunto,
                    message=mensaje,
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=['deyvi2413@gmail.com'],
                    fail_silently=True 
                )
            except Exception as e:
                print("Error enviando email:", e)
                
            messages.success(request, '✅ Solicitud enviada con éxito. Tu equipo está PENDIENTE de aprobación y el organizador fue notificado.')
            return redirect('ver_torneos_activos') 
    else:
        form = EquipoSolicitudForm()

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
        
        if accion == 'APROBAR':
            equipo.estado_inscripcion = 'APROBADO'
            equipo.save()
            # Aseguramos el rol en caso de aprobación manual de importación
            RolComplejo.objects.get_or_create(usuario=equipo.dirigente, complejo=mi_complejo, defaults={'rol': 'DIR'})
            messages.success(request, f'✅ {equipo.nombre} APROBADO.')
        elif accion == 'RECHAZAR':
            equipo.estado_inscripcion = 'RECHAZADO'
            equipo.save()
            messages.warning(request, f'Solicitud de {equipo.nombre} rechazada.')
            
        return redirect('gestionar_solicitudes')

    return render(request, 'core/gestionar_solicitudes.html', {'solicitudes': solicitudes})

@login_required
def cancelar_inscripcion_equipo(request, equipo_id):
    equipo = get_object_or_404(Equipo, id=equipo_id)
    rol_principal = obtener_rol_principal(request.user)
    
    if request.user != equipo.dirigente and rol_principal != 'ORG':
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
        abono_str = request.POST.get('monto_abono')
        abono = Decimal(abono_str) if abono_str else sancion.saldo
        
        sancion.monto_pagado += abono
        
        if sancion.monto_pagado >= sancion.monto:
            sancion.pagada = True
            sancion.monto_pagado = sancion.monto 
            messages.success(request, f"¡Deuda de {sancion.equipo.nombre} cancelada en su totalidad!")
        else:
            messages.success(request, f"Abono de ${abono} registrado. Saldo pendiente: ${sancion.saldo}")
            
        sancion.save()

        AbonoSancion.objects.create(
            sancion=sancion,
            monto=abono
        )
        
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))


@login_required
@user_passes_test(es_organizador)
def gestionar_finanzas(request):
    mi_complejo = obtener_mi_complejo(request.user)
        
    if request.method == 'POST' and 'agregar_sancion_manual' in request.POST:
        form_sancion = SancionManualForm(request.POST)
        form_sancion.fields['equipo'].queryset = Equipo.objects.filter(torneo__complejo=mi_complejo)
        
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
    
    lista_sanciones = Sancion.objects.filter(torneo__complejo=mi_complejo).select_related('equipo').order_by('pagada', '-id')

    ctx = {
        'form_sancion': form_sancion,
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
    fotos = FotoGaleria.objects.all().order_by('orden', '-id')

    if request.method == 'POST':
        if 'btn_foto' in request.POST:
            form_foto = FotoGaleriaForm(request.POST, request.FILES)
            if form_foto.is_valid():
                form_foto.save()
                messages.success(request, '📸 Foto agregada a la galería con éxito.')
                return redirect('gestionar_medios')

    form_foto = FotoGaleriaForm()
    return render(request, 'core/gestionar_medios.html', {
        'fotos': fotos, 'form_foto': form_foto
    })

@login_required
@user_passes_test(es_organizador)
def eliminar_foto(request, foto_id):
    foto = get_object_or_404(FotoGaleria, id=foto_id)
    foto.delete()
    messages.warning(request, "🗑️ Foto eliminada.")
    return redirect('gestionar_medios')


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

def obtener_clasificados_fase1(torneo):
    equipos = Equipo.objects.filter(torneo=torneo, estado_inscripcion='APROBADO')
    lista_tabla = []
    for equipo in equipos:
        partidos = Partido.objects.filter(Q(equipo_local=equipo) | Q(equipo_visita=equipo), estado__in=['JUG', 'WO', 'FINALIZADO'], etapa='F1')
        pj=0; pg=0; pe=0; gf=0; gc=0
        for p in partidos:
            pj+=1
            es_local = (p.equipo_local == equipo)
            goles_pro = p.goles_local if es_local else p.goles_visita
            goles_rival = p.goles_visita if es_local else p.goles_local
            gf+=goles_pro; gc+=goles_rival
            if goles_pro > goles_rival: pg+=1
            elif goles_pro == goles_rival: pe+=1
        pts = (pg * 3) + (pe * 1)
        lista_tabla.append({'equipo': equipo, 'pts': pts, 'gd': gf-gc, 'gf': gf})
    return sorted(lista_tabla, key=lambda x: (x['pts'], x['gd'], x['gf']), reverse=True)

def obtener_clasificados_fase2(torneo, letra_grupo):
    equipos_grupo = Equipo.objects.filter(torneo=torneo, grupo_fase2=letra_grupo, estado_inscripcion='APROBADO')
    lista_tabla = []
    for equipo in equipos_grupo:
        partidos = Partido.objects.filter(Q(equipo_local=equipo) | Q(equipo_visita=equipo), estado__in=['JUG', 'WO', 'FINALIZADO'], etapa='F2')
        pj=0; pg=0; pe=0; gf=0; gc=0
        for p in partidos:
            pj+=1
            es_local = (p.equipo_local == equipo)
            goles_pro = p.goles_local if es_local else p.goles_visita
            goles_rival = p.goles_visita if es_local else p.goles_local
            gf+=goles_pro; gc+=goles_rival
            if goles_pro > goles_rival: pg+=1
            elif goles_pro == goles_rival: pe+=1
        pts = (pg * 3) + (pe * 1) + equipo.puntos_bonificacion
        lista_tabla.append({'equipo': equipo, 'pts': pts, 'gd': gf-gc, 'gf': gf})
    return sorted(lista_tabla, key=lambda x: (x['pts'], x['gd'], x['gf']), reverse=True)[:4]

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
    ida_y_vuelta = request.POST.get('ida_y_vuelta') == 'on'

    clasificados = obtener_clasificados_fase1(torneo) 
    
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

    return render(request, 'core/generar_fixture.html', {'torneo': torneo, 'fixture': fixture, 'total_equipos': 8})

@login_required
@user_passes_test(es_organizador)
def generar_semis_directas(request, torneo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    torneo = get_object_or_404(Torneo, id=torneo_id, complejo=mi_complejo)
    
    if Partido.objects.filter(torneo=torneo, etapa='SEMI').exists():
        messages.error(request, "Las Semifinales ya fueron generadas.")
        return redirect(f"/programar/?torneo={torneo.id}")

    if 'ida_y_vuelta' in request.POST and request.POST.get('accion') != 'guardar_db':
        torneo.fase3_ida_vuelta = request.POST.get('ida_y_vuelta') == 'on'
        torneo.save()

    clasificados = obtener_clasificados_fase1(torneo)
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
        
    return render(request, 'core/generar_fixture.html', {'torneo': torneo, 'fixture': fixture, 'total_equipos': 4})


@login_required
@user_passes_test(es_organizador)
def generar_cuartos_final(request, torneo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    torneo = get_object_or_404(Torneo, id=torneo_id, complejo=mi_complejo)
    
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


def llaves_eliminatorias(request, torneo_id):
    torneo = get_object_or_404(Torneo, id=torneo_id)
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
    
    mis_equipos_historicos = Equipo.objects.filter(
        dirigente=request.user,
        torneo__activo=False,
        torneo__categoria=torneo_nuevo.categoria  
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

                # 🔥 MULTI-TENANCY: Actualizamos o creamos RolComplejo en la nueva cancha
                RolComplejo.objects.get_or_create(usuario=request.user, complejo=torneo_nuevo.complejo, defaults={'rol': 'DIR'})

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
    torneo.fase1_ida_vuelta = True
    torneo.save()
    messages.success(request, "🔄 Formato actualizado: Ahora puedes programar partidos de Vuelta en la Fase 1.")
    return redirect(f"/programar/?torneo={torneo.id}")

@login_required
@user_passes_test(es_organizador)
def cambiar_formato_fase1(request, torneo_id):
    mi_complejo = obtener_mi_complejo(request.user)
    torneo = get_object_or_404(Torneo, id=torneo_id, complejo=mi_complejo)
    
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

def buscar_jugador_api(request, cedula):
    jugador = Jugador.objects.filter(cedula=cedula).order_by('-id').first()
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
    if request.method == 'POST':
        nombre_categoria = request.POST.get('nombre')
        color_elegido = request.POST.get('color_carnet') 
        
        if nombre_categoria:
            if not Categoria.objects.filter(nombre__iexact=nombre_categoria).exists():
                Categoria.objects.create(nombre=nombre_categoria, color_carnet=color_elegido)
                messages.success(request, f"✅ Categoría '{nombre_categoria}' creada exitosamente.")
            else:
                messages.error(request, f"⛔ La categoría '{nombre_categoria}' ya existe.")
        else:
            messages.error(request, "⛔ El nombre de la categoría no puede estar vacío.")
            
        return redirect('gestionar_categorias')
        
    categorias = Categoria.objects.all().order_by('nombre')
    return render(request, 'core/gestionar_categorias.html', {'categorias': categorias})

@login_required
@user_passes_test(es_organizador)
def editar_categoria(request, categoria_id):
    categoria = get_object_or_404(Categoria, id=categoria_id)
    
    if request.method == 'POST':
        nuevo_nombre = request.POST.get('nombre')
        nuevo_color = request.POST.get('color_carnet') 
        
        if nuevo_nombre:
            if not Categoria.objects.filter(nombre__iexact=nuevo_nombre).exclude(id=categoria.id).exists():
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
def eliminar_categoria(request, categoria_id):
    categoria = get_object_or_404(Categoria, id=categoria_id)
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
    })


@login_required
@user_passes_test(es_organizador)
def gestionar_configuracion(request):
    config, created = Configuracion.objects.get_or_create(id=1) 
    
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
def revertir_cobro_sancion(request, sancion_id):
    rol_principal = obtener_rol_principal(request.user)
    if rol_principal not in ['ORG', 'VOC']:
        messages.error(request, "No tienes permisos para realizar esta acción.")
        return redirect('dashboard')
        
    sancion = get_object_or_404(Sancion, id=sancion_id)
    
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
    canchas = ComplejoDeportivo.objects.filter(activo=True)
    config = Configuracion.objects.first() # Para sacar tu logo de NEXUS si lo subiste
    
    return render(request, 'core/landing_principal.html', {
        'canchas': canchas, 
        'config': config
    })

def portal_complejo(request, slug_complejo):
    """ El inicio específico de CADA CANCHA (Público, sin login) """
    complejo = get_object_or_404(ComplejoDeportivo, slug=slug_complejo)
    
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

    return render(request, 'core/portal_publico.html', {
        'complejo': complejo, 
        'torneos': torneos_activos,
        'url_whatsapp': url_whatsapp
    })

from django.core.mail import send_mail
from django.conf import settings

@login_required
def dashboard_saas(request):
    """ EL PANEL DE CONTROL ABSOLUTO DEL DUEÑO DEL SOFTWARE """
    if not request.user.is_superuser:
        messages.error(request, "Acceso denegado. Solo el dueño de NEXUS SPORTOPS puede entrar aquí.")
        return redirect('dashboard')

    canchas = ComplejoDeportivo.objects.all().order_by('fecha_vencimiento')
    
    # 1. Tu contabilidad personal
    total_ingresos_saas = PagoSuscripcionSaaS.objects.aggregate(Sum('monto'))['monto__sum'] or 0
    canchas_activas = canchas.filter(activo=True).count()
    canchas_suspendidas = canchas.filter(activo=False).count()

    # 2. LÓGICA DE RECORDATORIOS (Se ejecuta al entrar al dashboard)
    hoy = timezone.now().date()
    limite_aviso = hoy + timedelta(days=3)
    
    canchas_por_vencer = canchas.filter(fecha_vencimiento__lte=limite_aviso, activo=True)
    canchas_vencidas = canchas.filter(fecha_vencimiento__lt=hoy, activo=True)
    
    # Si le das al botón de "Enviar Correos de Cobro"
    if request.method == 'POST' and 'enviar_recordatorios' in request.POST:
        mensajes_enviados = 0
        for c in canchas_por_vencer:
            asunto = f"⚠️ ALERTA DE COBRO: {c.nombre} está por vencer"
            texto = f"""
            Hola Deyvi,
            
            El plan del organizador de la cancha "{c.nombre}" vence el {c.fecha_vencimiento}.
            
            Datos de contacto del Organizador:
            - Nombre: {c.organizador.first_name} {c.organizador.last_name} ({c.organizador.username})
            - Teléfono / Celular: {c.telefono_contacto}
            
            No olvides contactarlo para renovar su plan y registrar el pago en el sistema.
            """
            send_mail(asunto, texto, settings.EMAIL_HOST_USER, ['deyvi2413@gmail.com'], fail_silently=True)
            mensajes_enviados += 1
            
        messages.success(request, f"✉️ Se enviaron {mensajes_enviados} recordatorios a tu correo.")
        return redirect('dashboard_saas')

    # 3. Lógica para suspender automáticamente si ya venció la fecha
    if request.method == 'POST' and 'suspender_morosos' in request.POST:
        suspendidos = 0
        for c in canchas_vencidas:
            c.activo = False
            c.save()
            suspendidos += 1
        messages.warning(request, f"🚫 Se suspendió el acceso a {suspendidos} canchas por falta de pago.")
        return redirect('dashboard_saas')

    return render(request, 'core/dashboard_saas.html', {
        'canchas': canchas,
        'total_ingresos': total_ingresos_saas,
        'canchas_activas': canchas_activas,
        'canchas_suspendidas': canchas_suspendidas,
        'canchas_por_vencer': canchas_por_vencer
    })

@login_required
def gestionar_canchas_saas(request):
    if not request.user.is_superuser:
        return redirect('dashboard')
        
    canchas = ComplejoDeportivo.objects.all().order_by('-id')
    
    if request.method == 'POST':
        form = ComplejoDeportivoForm(request.POST, request.FILES)
        if form.is_valid():
            cancha = form.save()
            
            # 🔥 MULTI-TENANCY: Convertimos automáticamente al usuario en ORGANIZADOR (ORG) en la tabla RolComplejo
            RolComplejo.objects.get_or_create(
                usuario=cancha.organizador,
                complejo=cancha,
                defaults={'rol': 'ORG'}
            )
                
            messages.success(request, f"✅ Cancha registrada. {cancha.organizador.username} ahora es Organizador Oficial de {cancha.nombre}.")
            return redirect('gestionar_canchas_saas')
    else:
        form = ComplejoDeportivoForm()
        
    return render(request, 'core/saas_gestionar_canchas.html', {'form': form, 'canchas': canchas})

@login_required
def editar_cancha_saas(request, cancha_id):
    if not request.user.is_superuser:
        return redirect('dashboard')
        
    cancha = get_object_or_404(ComplejoDeportivo, id=cancha_id)
    
    if request.method == 'POST':
        form = ComplejoDeportivoForm(request.POST, request.FILES, instance=cancha)
        if form.is_valid():
            cancha_actualizada = form.save()
            
            # 🔥 MULTI-TENANCY: Asegurar rol si cambiaste de dueño de la cancha
            RolComplejo.objects.get_or_create(
                usuario=cancha_actualizada.organizador,
                complejo=cancha_actualizada,
                defaults={'rol': 'ORG'}
            )
                
            messages.success(request, f"✅ Datos de {cancha_actualizada.nombre} actualizados.")
            return redirect('dashboard_saas')
    else:
        form = ComplejoDeportivoForm(instance=cancha)
        
    return render(request, 'core/saas_editar_cancha.html', {'form': form, 'cancha': cancha})

@login_required
def registrar_pago_saas(request):
    if not request.user.is_superuser:
        return redirect('dashboard')
        
    if request.method == 'POST':
        form = PagoSaaSForm(request.POST)
        if form.is_valid():
            pago = form.save()
            
            cancha = pago.complejo
            from datetime import timedelta
            from django.utils import timezone
            
            fecha_base = cancha.fecha_vencimiento if cancha.fecha_vencimiento and cancha.fecha_vencimiento >= timezone.now().date() else timezone.now().date()
            dias_extra = 30 * pago.meses_pagados
            cancha.fecha_vencimiento = fecha_base + timedelta(days=dias_extra)
            cancha.activo = True # Reactivamos por si estaba suspendida
            cancha.save()
            
            messages.success(request, f"💰 Pago de ${pago.monto} registrado. {cancha.nombre} renovado hasta {cancha.fecha_vencimiento}.")
            return redirect('dashboard_saas')
    else:
        form = PagoSaaSForm()
        
    return render(request, 'core/saas_registrar_pago.html', {'form': form})

# =========================================================
# PLANES Y PRECIOS (SAAS)
# =========================================================

def precios_publicos(request):
    """ Vista pública para mostrar los planes a posibles clientes """
    planes = PlanSuscripcion.objects.all().order_by('precio_mensual')
    return render(request, 'core/precios_publicos.html', {'planes': planes})

@login_required
def gestionar_planes_saas(request):
    """ Vista privada para que el Súper Admin cree/edite planes """
    if not request.user.is_superuser:
        return redirect('dashboard')
        
    planes = PlanSuscripcion.objects.all().order_by('precio_mensual')
    
    if request.method == 'POST':
        from .forms import PlanSuscripcionForm # Lo importamos aquí rápido
        form = PlanSuscripcionForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "✅ Nuevo plan de suscripción creado con éxito.")
            return redirect('gestionar_planes_saas')
    else:
        from .forms import PlanSuscripcionForm
        form = PlanSuscripcionForm()
        
    return render(request, 'core/saas_gestionar_planes.html', {'form': form, 'planes': planes})