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
from .forms import ConfiguracionForm


# Importamos Modelos y Formularios Unificados
from .models import (
    Configuracion, Torneo, Equipo, Jugador, Partido, 
    DetallePartido, Pago, Perfil, Sancion, ReservaCancha, Cupon, HorarioCancha,
    FotoGaleria, Publicidad, AbonoSancion
)
from .forms import (
    RegistroUsuarioForm, TorneoForm, EquipoForm, JugadorForm, 
    ProgramarPartidoForm, PagoForm, RegistroPublicoForm,
    ReservaCanchaForm, EquipoSolicitudForm, HorarioCanchaForm,
    FotoGaleriaForm, PublicidadForm,
    TraspasoJugadorForm, AsignarCuposForm, SancionListaNegraForm, SancionManualForm
)
from .utils import validar_cedula_ecuador, consultar_sri

# =========================================================
# --- FUNCIONES DE CONTROL DE ACCESO (PERMISOS) ---
# =========================================================

def es_organizador(user):
    return user.is_authenticated and hasattr(user, 'perfil') and user.perfil.rol == 'ORG'

def es_vocal_o_admin(user):
    return user.is_authenticated and hasattr(user, 'perfil') and user.perfil.rol in ['ORG', 'VOC']

def es_dirigente_o_admin(user):
    return user.is_authenticated and hasattr(user, 'perfil') and user.perfil.rol in ['ORG', 'DIR']

# =========================================================
# 1. VISTAS GENERALES Y DE GESTIÓN (CRUD)
# =========================================================

@login_required
def dashboard(request):
    ctx = {}
    ahora = timezone.now()
    
    ctx['torneos'] = Torneo.objects.filter(activo=True).order_by('-id')
    torneo_id = request.GET.get('torneo')
    if torneo_id:
        ctx['torneo_actual'] = int(torneo_id)
        
    partidos_qs = Partido.objects.filter(
        estado='PROG',
        fecha_hora__gte=ahora
    ).select_related('equipo_local', 'equipo_visita', 'torneo').order_by('fecha_hora')[:10]

    for p in partidos_qs:
        p.fecha_local = timezone.localtime(p.fecha_hora).date()
        
    ctx['proximos_partidos'] = partidos_qs

    ctx['fotos_galeria'] = FotoGaleria.objects.filter(activa=True).order_by('orden', '-id')
    ctx['publicidades'] = Publicidad.objects.filter(activa=True).order_by('-id')

    if request.user.is_authenticated and hasattr(request.user, 'perfil'):
        rol = request.user.perfil.rol

        if rol == 'ORG':
            deudas_pendientes = Sancion.objects.filter(pagada=False).exclude(descripcion__icontains='Inscripci').select_related('equipo', 'torneo', 'partido', 'jugador').order_by('-partido__fecha_hora', '-id')
            total = deudas_pendientes.aggregate(Sum('monto'))['monto__sum'] or 0
            
            inscripciones_pendientes = Sancion.objects.filter(pagada=False, descripcion__icontains='Inscripci').aggregate(Sum('monto'))['monto__sum'] or 0
            abonos_inscripciones = Sancion.objects.filter(pagada=False, descripcion__icontains='Inscripci').aggregate(Sum('monto_pagado'))['monto_pagado__sum'] or 0
            saldo_inscripciones = inscripciones_pendientes - abonos_inscripciones
            
            reservas_pendientes = ReservaCancha.objects.filter(estado='PENDIENTE').select_related('usuario').order_by('fecha', 'hora_inicio')
            
            # 👇 AÑADIDO PARA EL CENTRO DE SOLICITUDES 👇
            equipos_pendientes = Equipo.objects.filter(estado_inscripcion='PENDIENTE')
            
            ctx['deudas'] = deudas_pendientes
            ctx['total_por_cobrar'] = total + saldo_inscripciones 
            ctx['reservas_pendientes'] = reservas_pendientes 
            ctx['equipos_pendientes'] = equipos_pendientes 

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
            partidos_pendientes = Partido.objects.filter(
                estado__in=['PROG', 'VIVO']
            ).select_related('equipo_local', 'equipo_visita', 'torneo').order_by('fecha_hora')[:10]
            
            actas_pendientes = Partido.objects.filter(
                estado='ACTA'
            ).select_related('equipo_local', 'equipo_visita', 'torneo').order_by('fecha_hora')[:10]
            
            ctx['partidos_vocal'] = partidos_pendientes
            ctx['actas_pendientes'] = actas_pendientes

    return render(request, 'core/dashboard.html', ctx)

@login_required
@user_passes_test(es_organizador)
def crear_usuario(request):
    if request.method == 'POST':
        form = RegistroUsuarioForm(request.POST)
        if form.is_valid():
            u = form.save()
            u.perfil.rol = form.cleaned_data['rol']
            u.perfil.save()
            messages.success(request, f'Usuario "{u.username}" creado.')
            return redirect('dashboard')
    else:
        form = RegistroUsuarioForm()
    return render(request, 'core/crear_usuario.html', {'form': form})

@login_required
@user_passes_test(es_organizador)
def gestionar_usuarios(request):
    perfiles = Perfil.objects.all().exclude(usuario=request.user).select_related('usuario').order_by('-id')
    if request.method == 'POST':
        perfil_id = request.POST.get('perfil_id')
        nuevo_rol = request.POST.get('nuevo_rol')
        if perfil_id and nuevo_rol:
            p = Perfil.objects.get(id=perfil_id)
            p.rol = nuevo_rol
            p.save()
            messages.success(request, f'Rol de {p.usuario.username} actualizado a {p.get_rol_display()}')
            return redirect('gestionar_usuarios')
    return render(request, 'core/gestionar_usuarios.html', {'perfiles': perfiles})

@login_required
@user_passes_test(es_organizador)
def gestionar_torneos(request):
    torneos = Torneo.objects.all().order_by('categoria__nombre', '-fecha_inicio')
    if request.method == 'POST':
        form = TorneoForm(request.POST)
        if form.is_valid():
            t = form.save(commit=False)
            t.organizador = request.user
            t.save()
            messages.success(request, f'✅ Torneo "{t.nombre}" creado exitosamente.')
            return redirect('gestionar_torneos')
        else:
            for campo, errores in form.errors.items():
                for error in errores:
                    messages.error(request, f"❌ Error en {campo}: {error}")
    else:
        form = TorneoForm()
    return render(request, 'core/gestionar_torneos.html', {'form': form, 'torneos': torneos})

@login_required
@user_passes_test(es_organizador)
def editar_torneo(request, torneo_id):
    torneo = get_object_or_404(Torneo, id=torneo_id)
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
        'form': form, 'torneos': Torneo.objects.all().order_by('-id'), 'editando': True, 'torneo_edit': torneo
    })

@login_required
@user_passes_test(es_organizador)
def eliminar_torneo(request, torneo_id):
    torneo = get_object_or_404(Torneo, id=torneo_id)
    nombre_torneo = torneo.nombre
    torneo.delete()
    messages.success(request, f'🗑️ El torneo "{nombre_torneo}" ha sido eliminado completamente.')
    return redirect('gestionar_torneos')

@login_required
@user_passes_test(es_organizador)
def gestionar_equipos(request):
    # 🔥 1. Filtramos SOLO torneos activos y ORDENAMOS para que la agrupación funcione perfecto
    equipos = Equipo.objects.filter(torneo__activo=True).select_related(
        'torneo', 'torneo__categoria', 'dirigente'
    ).order_by('torneo__categoria__nombre', 'torneo__nombre', 'nombre')
    
    if request.method == 'POST':
        form = EquipoForm(request.POST, request.FILES)
        if form.is_valid():
            nuevo_equipo = form.save()
            if not nuevo_equipo.torneo.cobro_por_jugador:
                costo_inscripcion = getattr(nuevo_equipo.torneo, 'costo_inscripcion', Decimal('0.00')) 
                Sancion.objects.create(
                    torneo=nuevo_equipo.torneo,
                    equipo=nuevo_equipo,
                    tipo='ADMIN',
                    monto=costo_inscripcion,
                    monto_pagado=Decimal('0.00'),
                    descripcion=f"Inscripción al Torneo {nuevo_equipo.torneo.nombre}",
                    pagada=False
                )
            messages.success(request, '¡Equipo inscrito correctamente!')
            return redirect('gestionar_equipos')
    else:
        form = EquipoForm()
        
    # 🔥 2. Limitamos el formulario para que solo se puedan inscribir en torneos activos
    form.fields['torneo'].queryset = Torneo.objects.filter(activo=True).order_by('categoria__nombre', 'nombre')
        
    return render(request, 'core/gestionar_equipos.html', {'form': form, 'equipos': equipos})

@login_required
@user_passes_test(es_organizador)
def editar_equipo(request, equipo_id):
    equipo = get_object_or_404(Equipo, id=equipo_id)
    if request.method == 'POST':
        form = EquipoForm(request.POST, request.FILES, instance=equipo)
        if form.is_valid():
            form.save()
            messages.success(request, 'Equipo actualizado correctamente.')
            return redirect('gestionar_equipos')
    else:
        form = EquipoForm(instance=equipo)
        
    form.fields['torneo'].queryset = Torneo.objects.filter(activo=True).order_by('categoria__nombre', 'nombre')
    
    equipos = Equipo.objects.filter(torneo__activo=True).select_related(
        'torneo', 'torneo__categoria', 'dirigente'
    ).order_by('torneo__categoria__nombre', 'torneo__nombre', 'nombre')
    
    return render(request, 'core/gestionar_equipos.html', {'form': form, 'equipos': equipos, 'editando': True})


@login_required
@user_passes_test(es_organizador)
def editar_equipo(request, equipo_id):
    equipo = get_object_or_404(Equipo, id=equipo_id)
    if request.method == 'POST':
        form = EquipoForm(request.POST, request.FILES, instance=equipo)
        if form.is_valid():
            form.save()
            messages.success(request, 'Equipo actualizado correctamente.')
            return redirect('gestionar_equipos')
    else:
        form = EquipoForm(instance=equipo)
    return render(request, 'core/gestionar_equipos.html', {'form': form, 'equipos': Equipo.objects.all(), 'editando': True})

@login_required
@user_passes_test(es_organizador)
def eliminar_equipo(request, equipo_id):
    equipo = get_object_or_404(Equipo, id=equipo_id)
    equipo.delete()
    messages.success(request, 'Equipo eliminado. Los jugadores quedaron libres.')
    return redirect('gestionar_equipos')


# =========================================================
# ✨ LÓGICA BLINDADA: GESTIÓN DE JUGADORES Y CUPOS ✨
# =========================================================

@login_required
def gestionar_jugadores(request):
    perfil = request.user.perfil
    puede_fichar = True 
    
    if perfil.rol == 'DIR':
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
                
                # 1. Buscamos TODAS las fichas activas de esa cédula
                jugadores_activos_bd = Jugador.objects.filter(cedula=cedula_ingresada, equipo__torneo__activo=True)
                
                # 2. ¿Ya juega en ESTA MISMA CATEGORÍA?
                misma_categoria = None
                if mi_equipo.torneo.categoria:
                    misma_categoria = jugadores_activos_bd.filter(equipo__torneo__categoria=mi_equipo.torneo.categoria).first()
                else:
                    misma_categoria = jugadores_activos_bd.filter(equipo__torneo=mi_equipo.torneo).first()

                if misma_categoria:
                    if misma_categoria.equipo != mi_equipo:
                        # 🔒 EL CANDADO: Bloquea si ya juega en la MISMA categoría pero en OTRO equipo
                        messages.error(request, f"⛔ ¡ALERTA! Este jugador ya compite en el equipo '{misma_categoria.equipo.nombre}' en esta misma categoría.")
                        return redirect(f"{request.path}?equipo={mi_equipo.id}")
                    else:
                        # 🔄 Está actualizando la foto/dorsal de su propio jugador
                        misma_categoria.nombres = form.cleaned_data.get('nombres')
                        misma_categoria.dorsal = form.cleaned_data.get('dorsal')
                        if form.cleaned_data.get('foto'):
                            misma_categoria.foto = form.cleaned_data.get('foto')
                        misma_categoria.save()
                        messages.success(request, f'¡Datos de {misma_categoria.nombres} actualizados!')
                else:
                    # 🟢 NO JUEGA EN ESTA CATEGORÍA (Se permite inscribir en Múltiples Categorías)
                    jugador_historial = Jugador.objects.filter(cedula=cedula_ingresada).last()
                    nuevo_jugador = form.save(commit=False)
                    nuevo_jugador.equipo = mi_equipo
                    
                    if jugador_historial:
                        # Heredar foto si no subió una nueva
                        if not form.cleaned_data.get('foto') and jugador_historial.foto:
                            nuevo_jugador.foto = jugador_historial.foto
                        
                        # Limpiar castigos porque es una categoría completamente nueva
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

    elif perfil.rol == 'ORG':
        # Lógica para Organizador
        equipos_activos = Equipo.objects.filter(torneo__activo=True).order_by('torneo__categoria__nombre', 'torneo__nombre', 'nombre')
        equipo_id = request.GET.get('equipo')
        mi_equipo = Equipo.objects.filter(id=equipo_id).first() if equipo_id else equipos_activos.first()
            
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

    # 🔥 MAGIA VISUAL: Anexamos los otros equipos en los que juega esta persona
    if jugadores:
        for j in jugadores:
            j.otros_equipos = Jugador.objects.filter(
                cedula=j.cedula,
                equipo__torneo__activo=True
            ).exclude(id=j.id)

    return render(request, 'core/gestionar_jugadores.html', {
        'form': form, 'jugadores': jugadores, 
        'equipos_activos': equipos_activos if perfil.rol == 'ORG' else mis_equipos.filter(torneo__activo=True).order_by('torneo__categoria__nombre', 'torneo__nombre', 'nombre'), 
        'equipo_seleccionado': equipo_seleccionado, 'es_dirigente': (perfil.rol == 'DIR'),
        'puede_fichar': puede_fichar,
        'equipo_obj': mi_equipo 
    })

@login_required
def editar_jugador(request, jugador_id):
    jugador = get_object_or_404(Jugador, id=jugador_id)
    
    # 1. REGLA ESTRICTA: Solo el Organizador puede editar a un jugador ya inscrito
    if request.user.perfil.rol != 'ORG':
        messages.error(request, "⛔ Solo el Organizador puede editar los datos de un jugador ya inscrito.")
        return redirect(f"/jugadores/?equipo={jugador.equipo.id}")

    if request.method == 'POST':
        # Al pasar instance=jugador actualiza sin borrar historial
        form = JugadorForm(request.POST, request.FILES, instance=jugador)
        
        if form.is_valid():
            form.save()
            messages.success(request, f'✅ Datos de {jugador.nombres} actualizados correctamente.')
            return redirect(f"/jugadores/?equipo={jugador.equipo.id}")
        else:
            messages.error(request, "❌ Revisa los campos del formulario.")
    else:
        form = JugadorForm(instance=jugador)

    # Necesitamos enviar todos los equipos activos para que el filtro de la izquierda siga funcionando
    equipos_activos = Equipo.objects.filter(torneo__activo=True).order_by('torneo__categoria__nombre', 'torneo__nombre', 'nombre')

    return render(request, 'core/gestionar_jugadores.html', {
        'form': form, 
        'jugadores': Jugador.objects.filter(equipo=jugador.equipo).order_by('dorsal'), 
        'equipos_activos': equipos_activos, 
        'editando': True, 
        'es_dirigente': False, # Es falso porque ya validamos arriba que solo entra el ORG
        'equipo_seleccionado': jugador.equipo.id,
        'equipo_obj': jugador.equipo, # 🔥 LA CLAVE: Esto hace que aparezca el formulario a la derecha
        'puede_fichar': True # Mantiene el botón desbloqueado para el Organizador
    })

@login_required
def eliminar_jugador(request, jugador_id):
    jugador = get_object_or_404(Jugador, id=jugador_id)
    es_admin = request.user.perfil.rol == 'ORG'
    es_dueno = (request.user.perfil.rol == 'DIR' and jugador.equipo.dirigente == request.user)

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
    equipo = get_object_or_404(Equipo, id=equipo_id)
    cupos_anteriores = equipo.cupos_pagados # 🧠 Guardamos cuántos tenía antes de que los edites

    if request.method == 'POST':
        form = AsignarCuposForm(request.POST, instance=equipo)
        if form.is_valid():
            equipo_actualizado = form.save(commit=False)
            nuevos_cupos = equipo_actualizado.cupos_pagados
            
            # Calculamos la diferencia
            diferencia = nuevos_cupos - cupos_anteriores
            equipo_actualizado.save()
            
            # Si la diferencia es positiva, aumentaste cupos -> Facturamos
            if diferencia > 0 and equipo.torneo.cobro_por_jugador:
                costo_adicional = diferencia * equipo.torneo.costo_inscripcion_jugador
                Sancion.objects.create(
                    torneo=equipo.torneo, equipo=equipo, tipo='ADMIN',
                    monto=costo_adicional, descripcion=f"Ampliación: {diferencia} cupo(s) extra", pagada=False
                )
                messages.success(request, f'✅ Límite ampliado a {nuevos_cupos} cupos. Se generó factura por ${costo_adicional}.')
            
            # Si la diferencia es negativa, estabas corrigiendo un error -> Solo reducimos el límite
            elif diferencia < 0:
                messages.warning(request, f'⚠️ Límite corregido y reducido a {nuevos_cupos} cupos. (Revisa Finanzas si necesitas anular cobros incorrectos previos).')
            
            else:
                messages.info(request, "No se hicieron cambios en el número de cupos.")
                
            return redirect('gestionar_equipos')
    else:
        # Carga el formulario con el número exacto que tiene actualmente
        form = AsignarCuposForm(instance=equipo)
        
    return render(request, 'core/asignar_cupos.html', {'form': form, 'equipo': equipo})

@login_required
@user_passes_test(es_organizador)
def sancionar_equipo(request, equipo_id):
    equipo = get_object_or_404(Equipo, id=equipo_id)
    if request.method == 'POST':
        form = SancionListaNegraForm(request.POST, instance=equipo)
        if form.is_valid():
            equipo = form.save()
            if equipo.sancionado_hasta:
                # Aplicamos la sanción a todos
                equipo.dirigente.perfil.sancionado_hasta = equipo.sancionado_hasta
                equipo.dirigente.perfil.save()
                Jugador.objects.filter(equipo=equipo).update(sancionado_hasta=equipo.sancionado_hasta)
                messages.error(request, f'🚨 EQUIPO SANCIONADO: {equipo.nombre} ha sido ingresado a la Lista Negra hasta {equipo.sancionado_hasta}.')
            else:
                # 🛠️ CORRECCIÓN AQUÍ: Si quitamos la fecha, limpiamos también al dirigente y a los jugadores
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
    # 🔥 CAMBIO 1: Filtramos para que solo traiga los torneos activos
    torneos = Torneo.objects.filter(activo=True).order_by('-fecha_inicio')
    torneo_id_get = request.GET.get('torneo')
    torneo_obj = None
    partidos = []

    # 1. CARGA DE DATOS Y LÓGICA VISUAL (GET)
    if torneo_id_get:
        torneo_obj = get_object_or_404(Torneo, id=torneo_id_get)
        
        partidos_qs = Partido.objects.filter(torneo=torneo_obj)\
            .select_related('equipo_local', 'equipo_visita')\
            .order_by('etapa', 'numero_fecha', 'fecha_hora')
            
        partidos_lista = list(partidos_qs)
        
        # LÓGICA PARA DETECTAR LA VUELTA AUTOMÁTICAMENTE
        total_equipos = Equipo.objects.filter(torneo=torneo_obj, estado_inscripcion='APROBADO').count()
        if total_equipos > 0:
            fechas_ida = total_equipos - 1 if total_equipos % 2 == 0 else total_equipos
            
            for p in partidos_lista:
                if p.etapa == 'F1' and p.numero_fecha and p.numero_fecha > fechas_ida:
                    p.es_vuelta_visual = True
                else:
                    p.es_vuelta_visual = False
        partidos = partidos_lista

    # 2. PROCESAMIENTO DEL FORMULARIO (POST)
    if request.method == 'POST' and es_organizador(request.user):
        form = ProgramarPartidoForm(request.POST)
        
        # 🔥 CAMBIO 2: Blindamos el formulario POST para que solo acepte torneos activos
        if 'torneo' in form.fields:
            form.fields['torneo'].queryset = Torneo.objects.filter(activo=True)
            
        if form.is_valid():
            t_form = form.cleaned_data['torneo']
            equipo_local = form.cleaned_data['equipo_local']
            equipo_visita = form.cleaned_data['equipo_visita']
            etapa_seleccionada = form.cleaned_data.get('etapa', 'F1')
            
            # REGLA 1: NO JUGAR CONTRA SÍ MISMO
            if equipo_local == equipo_visita:
                messages.error(request, "⛔ Error: Un equipo no puede jugar contra sí mismo.")
                return redirect(f"{request.path}?torneo={t_form.id}")

            # REGLA 2: VALIDACIÓN INTELIGENTE DE FASE 1
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

            # REGLA 3: VALIDACIÓN DE GRUPOS EN FASE 2
            if etapa_seleccionada == 'F2':
                if not equipo_local.grupo_fase2 or not equipo_visita.grupo_fase2:
                    messages.error(request, "⛔ Error: Ambos equipos deben tener un grupo asignado (A o B) para la Fase 2.")
                    return redirect(f"{request.path}?torneo={t_form.id}")
                
                if equipo_local.grupo_fase2 != equipo_visita.grupo_fase2:
                    messages.error(request, f"⛔ Regla de Grupos: {equipo_local.nombre} (Grupo {equipo_local.grupo_fase2}) no puede jugar contra {equipo_visita.nombre} (Grupo {equipo_visita.grupo_fase2}).")
                    return redirect(f"{request.path}?torneo={t_form.id}")
            
            # REGLA 4: CHEQUEO DE DEUDAS
            if equipo_local.tiene_deudas():
                messages.warning(request, f"⚠️ Aviso: {equipo_local.nombre} tiene deudas pendientes.")
            if equipo_visita.tiene_deudas():
                messages.warning(request, f"⚠️ Aviso: {equipo_visita.nombre} tiene deudas pendientes.")
            
            # GUARDADO ATÓMICO
            try:
                with transaction.atomic():
                    partido = form.save()
                    duracion = 2 
                    hora_fin_estimada = (partido.fecha_hora + timedelta(hours=duracion)).time()
                    
                    from core.models import ReservaCancha
                    ReservaCancha.objects.create(
                        fecha=partido.fecha_hora.date(),
                        hora_inicio=partido.fecha_hora.time(),
                        hora_fin=hora_fin_estimada,
                        es_torneo=True,
                        motivo_bloqueo=f"⚽ {partido.equipo_local} vs {partido.equipo_visita}",
                        partido=partido,
                        usuario=request.user,
                        estado='ACTIVA',
                        pagado=True
                    )

                messages.success(request, '✅ Partido agendado y cancha bloqueada con éxito.')
                return redirect(f"{request.path}?torneo={t_form.id}")
            
            except ValidationError:
                messages.error(request, '⛔ La cancha ya tiene una reserva externa en ese horario.')
            except Exception as e:
                messages.error(request, f'Error al agendar: {str(e)}')
        else:
            messages.error(request, "Formulario inválido. Revisa los campos.")
            
    else:
        # Carga inicial del formulario
        form = ProgramarPartidoForm(initial={'torneo': torneo_id_get})
        
        # 🔥 CAMBIO 3: Filtramos el dropdown del formulario en el GET para que no salgan los inactivos
        if 'torneo' in form.fields:
            form.fields['torneo'].queryset = Torneo.objects.filter(activo=True).order_by('-fecha_inicio')
            
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
    torneo_id = partido.torneo.id
    partido.delete()
    messages.warning(request, 'Partido eliminado del calendario.')
    return redirect(f"/programar/?torneo={torneo_id}")

@login_required
@user_passes_test(es_organizador)
def reiniciar_partido(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
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

@login_required
@user_passes_test(es_vocal_o_admin)
def registrar_resultado(request, partido_id):
    partido = Partido.objects.get(id=partido_id)
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
    
    # 1. Anotaciones de estadísticas locales, INCLUYENDO ESTRELLAS
    jugadores_local = Jugador.objects.filter(equipo=partido.equipo_local).annotate(
        goles_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='GOL')),
        ta_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='TA')),
        tr_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='TR')),
        da_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='DA')),
        star_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='STAR')) # NUEVO
    ).order_by('dorsal')

    # 2. Anotaciones de estadísticas visita, INCLUYENDO ESTRELLAS
    jugadores_visita = Jugador.objects.filter(equipo=partido.equipo_visita).annotate(
        goles_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='GOL')),
        ta_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='TA')),
        tr_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='TR')),
        da_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='DA')),
        star_match=Count('detallepartido', filter=Q(detallepartido__partido=partido, detallepartido__tipo='STAR')) # NUEVO
    ).order_by('dorsal')

    # 3. Consultar Deudas Pendientes de ambos equipos para mostrarlas en mesa
    deudas_pendientes = Sancion.objects.filter(
        equipo__in=[partido.equipo_local, partido.equipo_visita], 
        pagada=False
    ).order_by('equipo__nombre')

    asistencias_ids = list(DetallePartido.objects.filter(partido=partido, tipo='ASIS').values_list('jugador_id', flat=True))
    multas = Sancion.objects.filter(partido=partido).order_by('-id')

    if request.method == 'POST':
        
        # 👇 NUEVA LÓGICA DE COBRO EN MESA 👇
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
            
            # Guardamos el abono vinculándolo al partido actual
            AbonoSancion.objects.create(sancion=sancion, monto=abono, partido=partido)
            return redirect('gestionar_vocalia', partido_id=partido.id)

        # 👇 NUEVA LÓGICA DE W.O. 👇
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
                partido.ganador_wo = None # Significa que ambos pierden
            
            # Firmamos por ellos y blindamos
            partido.validado_local = True
            partido.validado_visita = True
            partido.sanciones_aplicadas = True 
            partido.save()
            messages.success(request, '🚨 Partido finalizado por W.O. exitosamente.')
            return redirect(f"/programar/?torneo={partido.torneo.id}")

        # 👇 GUARDAR ACTA NORMAL 👇
        elif 'guardar_informe' in request.POST:
            estado_anterior = partido.estado

            partido.informe_vocal = request.POST.get('informe_vocal')
            partido.informe_arbitro = request.POST.get('informe_arbitro')
            partido.validado_local = request.POST.get('validado_local') == 'on'
            partido.validado_visita = request.POST.get('validado_visita') == 'on'
            
            # LÓGICA DE PENALES PARA FASES ELIMINATORIAS
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

            # CIERRE ESTRICTO: ¿Están las DOS firmas?
            if partido.validado_local and partido.validado_visita:
                partido.estado = 'JUG'
            else:
                partido.estado = 'ACTA' # Limbo de Actas
            
            partido.save()

            # 🔥 LÓGICA DE SANCIONES BLINDADA CONTRA DUPLICADOS 🔥
            if partido.estado == 'JUG' and not partido.sanciones_aplicadas:
                
                # 1. Reducir partidos de suspensión a los inactivos
                jugadores_ambos_equipos = Jugador.objects.filter(equipo__in=[partido.equipo_local, partido.equipo_visita], partidos_suspension__gt=0)
                detalles = DetallePartido.objects.filter(partido=partido)
                
                for j in jugadores_ambos_equipos:
                    if not detalles.filter(jugador=j, tipo__in=['DA', 'TR']).exists():
                        j.partidos_suspension -= 1
                        j.save()

                # 2. Generar multas y nuevas suspensiones (INCLUYE 3 ROJAS DIRECTAS = EXPULSIÓN)
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
                        
                        # REGLA DE LAS 4 AMARILLAS (REINICIO POR FASE)
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

                # BLOQUEAR LAS SANCIONES PARA QUE NO SE REPITAN NUNCA MÁS
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
        
        # 👇 NUEVA MULTA MANUAL 👇
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
        'deudas_pendientes': deudas_pendientes # Pasamos la variable al HTML
    })

@login_required
@user_passes_test(es_vocal_o_admin)
def registrar_incidencia(request, partido_id):
    partido = get_object_or_404(Partido, id=partido_id)
    
    if request.user.perfil.rol not in ['VOC', 'ORG']:
        messages.error(request, "No tienes permiso para realizar esta acción.")
        return redirect('dashboard')

    if request.method == 'POST':
        jugador_id = request.POST.get('jugador_id')
        tipo_evento = request.POST.get('tipo') 
        minuto = request.POST.get('minuto', 0)
        
        jugador = get_object_or_404(Jugador, id=jugador_id)

        # Usamos equipo_incidencia=jugador.equipo para que el evento se quede con el equipo actual
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
            # Verificamos que no haya más de 2 estrellas en TODO el partido
            estrellas_actuales = DetallePartido.objects.filter(partido=partido, tipo='STAR').count()
            if estrellas_actuales >= 2:
                messages.error(request, '⭐ Error: Solo se pueden asignar máximo 2 figuras (estrellas) por partido.')
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
        partido = evento.partido
        if tipo == 'GOL':
            # Verificamos mediante equipo_incidencia a quién restarle el gol
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

@login_required
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
            
            # 👇 NUEVA LÓGICA DE PUNTOS QUE CONTEMPLA EL W.O. 👇
            if p.estado == 'WO':
                if p.ganador_wo == equipo:
                    pg += 1  # Gana el partido por WO
                else:
                    pp += 1  # Pierde por WO (ya sea en contra, o Doble WO donde ambos pierden)
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
    torneo = get_object_or_404(Torneo, id=torneo_id)
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

@login_required
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

    return render(request, 'core/tabla_posiciones_f2.html', {
        'torneo': torneo, 
        'tabla_a': tabla_a, 
        'tabla_b': tabla_b,
        'fase': 2,
        'cuartos_generados': cuartos_generados,
        'es_organizador': request.user.perfil.rol == 'ORG'
    })

def seleccionar_reporte(request):
    # Separamos y ordenamos: Activos por Categoría, Finalizados por Año
    torneos_activos = Torneo.objects.filter(activo=True).order_by('categoria__nombre', '-fecha_inicio')
    torneos_finalizados = Torneo.objects.filter(activo=False).order_by('-fecha_inicio')
    
    return render(request, 'core/seleccionar_reporte.html', {
        'torneos_activos': torneos_activos, 
        'torneos_finalizados': torneos_finalizados
    })

@login_required
def reporte_estadisticas(request, torneo_id):
    torneo = get_object_or_404(Torneo, id=torneo_id)
    user_perfil = request.user.perfil if hasattr(request.user, 'perfil') else None
    rol = user_perfil.rol if user_perfil else 'FAN'

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
        equipo_incidencia=F('jugador__equipo') # 🛡️ LA REGLA DE ORO: El gol debe coincidir con su equipo actual
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
        # ✨ MAGIA NEXT LEVEL: Obtenemos a los jugadores actuales Y a los que ya fueron traspasados pero dejaron goles/historial aquí
        jugadores_actuales = list(Jugador.objects.filter(equipo=equipo_seleccionado).values_list('id', flat=True))
        jugadores_historicos = list(DetallePartido.objects.filter(equipo_incidencia=equipo_seleccionado).values_list('jugador_id', flat=True))
        
        ids_unicos = set(jugadores_actuales + jugadores_historicos)
        roster = Jugador.objects.filter(id__in=ids_unicos)

        for j in roster:
            # 🛡️ Filtramos las estadísticas SOLO por lo que hizo con la camiseta de ESTE equipo
            stats = DetallePartido.objects.filter(
                jugador=j, 
                partido__torneo=torneo, 
                equipo_incidencia=equipo_seleccionado
            )
            
            # Si el jugador ya no está en el equipo actual, le agregamos una etiqueta para que el dirigente sepa
            nota_transferido = "" if j.id in jugadores_actuales else " (Transferido)"

            total_ta = stats.filter(tipo='TA').count()
            ta_mostrar = total_ta % 4 
            
            # Solo agregamos a la lista si tiene alguna estadística o si sigue en el equipo actual
            if j.id in jugadores_actuales or stats.exists():
                jugadores_detalle.append({
                    'nombre': j.nombres + nota_transferido, 
                    'pj': stats.filter(tipo='ASIS').count(), 
                    'ta': ta_mostrar, 
                    'da': stats.filter(tipo='DA').count(),
                    'tr': stats.filter(tipo='TR').count(), 
                    'goles': stats.filter(tipo='GOL').count(),
                    'stars': stats.filter(tipo='STAR').count() # NUEVO
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

@login_required
def tabla_goleadores(request, torneo_id):
    torneo = Torneo.objects.get(id=torneo_id)
    goleadores = DetallePartido.objects.filter(
        partido__torneo=torneo, 
        tipo='GOL',
        equipo_incidencia=F('jugador__equipo') # 🛡️ LA REGLA DE ORO: El gol debe coincidir con su equipo actual
    ).values(
        'jugador__nombres', 'jugador__equipo__nombre', 'jugador__equipo__escudo'
    ).annotate(
        total_goles=Count('id')
    ).order_by('-total_goles', 'jugador__nombres')[:15]
# =========================================================
# 5. GENERACIÓN DE PDF (ACTA) (ACCESO VOCAL Y ADMIN)
# =========================================================

@login_required
@user_passes_test(es_vocal_o_admin)
def generar_acta_pdf(request, partido_id):
    partido = Partido.objects.get(id=partido_id)
    detalles = DetallePartido.objects.filter(partido=partido).select_related('jugador')
    
    asistencias_local = detalles.filter(tipo='ASIS', equipo_incidencia=partido.equipo_local)
    asistencias_visita = detalles.filter(tipo='ASIS', equipo_incidencia=partido.equipo_visita)
    goles = detalles.filter(tipo='GOL')
    tarjetas = detalles.filter(tipo__in=['TA', 'TR', 'DA', 'AZUL', 'EBRI'])
    estrellas = detalles.filter(tipo='STAR') 
    abonos = AbonoSancion.objects.filter(partido=partido) 
    
    # 👇 NUEVO: Traemos las multas administrativas creadas en este partido
    multas = Sancion.objects.filter(partido=partido, tipo='ADMIN')

    template_path = 'core/acta_partido_pdf.html'
    context = {
        'partido': partido, 'asistencias_local': asistencias_local,
        'asistencias_visita': asistencias_visita, 'goles': goles,
        'tarjetas': tarjetas, 'estrellas': estrellas, 'abonos': abonos,
        'multas': multas # 👇 NUEVO: Añadimos las multas al contexto del PDF
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
    equipo_id = request.GET.get('equipo')
    equipo = get_object_or_404(Equipo, id=equipo_id) if equipo_id else None

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
        form.fields['equipo'].queryset = Equipo.objects.filter(estado_inscripcion='APROBADO')

    return render(request, 'core/registrar_pago.html', {
        'form': form, 
        'equipo': equipo 
    })


@login_required
@user_passes_test(es_organizador)
def historial_pagos_equipo(request, equipo_id):
    equipo = get_object_or_404(Equipo, id=equipo_id)
    pagos = Pago.objects.filter(equipo=equipo).order_by('-fecha', '-id')
    
    return render(request, 'core/historial_pagos.html', {
        'equipo': equipo,
        'pagos': pagos
    })

def generar_recibo_pago_pdf(request, pago_id):
    pago = get_object_or_404(Pago, id=pago_id)
    
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
# 7. REGISTRO PÚBLICO Y RESERVAS
# =========================================================

def registro_publico(request):
    if request.method == 'POST':
        form = RegistroPublicoForm(request.POST) 
        
        if form.is_valid():
            usuario = form.save()
            login(request, usuario)
            messages.success(request, f'¡Bienvenido crack! Tu cuenta ha sido creada y ya estás dentro.')
            return redirect('dashboard') 
    else:
        form = RegistroPublicoForm()
        
    return render(request, 'registration/registro_publico.html', {'form': form})

def reservar_cancha(request):
    manana = timezone.now().date() + timedelta(days=1)
    
    fecha_str = request.GET.get('fecha')
    if fecha_str:
        try:
            fecha_consulta = datetime.strptime(fecha_str, '%Y-%m-%d').date()
            if fecha_consulta <= timezone.now().date():
                messages.warning(request, "Recuerda: Solo se puede reservar con al menos 1 día de anticipación.")
                fecha_consulta = manana
        except ValueError:
            fecha_consulta = manana
    else:
        fecha_consulta = manana

    horarios_disponibles = []
    
    horarios_db = HorarioCancha.objects.filter(activo=True).order_by('hora_inicio')
    reservas_del_dia = ReservaCancha.objects.filter(fecha=fecha_consulta).exclude(estado='CANCELADA')
    partidos_del_dia = Partido.objects.filter(fecha_hora__date=fecha_consulta).exclude(estado='WO')

    for tarifa in horarios_db:
        hora_actual = tarifa.hora_inicio
        hora_final = tarifa.hora_fin
        
        while hora_actual < hora_final:
            dummy_date = datetime.today()
            dt_actual = datetime.combine(dummy_date, hora_actual)
            dt_siguiente = dt_actual + timedelta(hours=1)
            hora_siguiente = dt_siguiente.time()
            
            if hora_siguiente > hora_final and hora_siguiente != time(0, 0):
                hora_siguiente = hora_final 

            ocupado = False
            estado = 'LIBRE'

            for r in reservas_del_dia:
                if r.hora_inicio < hora_siguiente and r.hora_fin > hora_actual:
                    ocupado = True
                    estado = 'PENDIENTE' if r.estado == 'PENDIENTE' else 'OCUPADO'
                    break
            
            if not ocupado:
                for p in partidos_del_dia:
                    if p.fecha_hora:
                        p_inicio = p.fecha_hora.time()
                        p_fin = (p.fecha_hora + timedelta(hours=2)).time()
                        
                        if p_inicio < hora_siguiente and p_fin > hora_actual:
                            ocupado = True
                            estado = 'TORNEO'
                            break

            # 🟢 CÁLCULO DE DESCUENTO 50% PARA DIRIGENTES
            precio_mostrar = float(tarifa.precio)
            if hasattr(request.user, 'perfil') and request.user.perfil.rol == 'DIR':
                precio_mostrar = precio_mostrar * 0.60

            horarios_disponibles.append({
                'hora_mostrar': f"{hora_actual.strftime('%H:%M')} - {hora_siguiente.strftime('%H:%M')}",
                'valor_inicio': hora_actual.strftime('%H:%M'),
                'valor_fin': hora_siguiente.strftime('%H:%M'),
                'precio': precio_mostrar,
                'estado': estado
            })

            hora_actual = hora_siguiente

    if request.method == 'POST':
        hora_inicio_str = request.POST.get('hora_inicio')
        hora_fin_str = request.POST.get('hora_fin')
        fecha_str_post = request.POST.get('fecha')
        # 🔥 CAPTURAMOS EL PRECIO REAL DESDE EL HTML (El que sumó JavaScript)
        precio_total_post = request.POST.get('precio_total')
        codigo_cupon = request.POST.get('codigo_cupon', '') # Opcional
        
        if hora_inicio_str and hora_fin_str and fecha_str_post and precio_total_post:
            
            # Convierte el string a float para asegurarnos de que es un número
            try:
                precio_base = float(precio_total_post)
            except ValueError:
                messages.error(request, "⚠️ Error: El precio total no es válido.")
                return redirect(f"{request.path}?fecha={fecha_str_post}")

            # 🟢 Aplicar descuento DIRIGENTE si corresponde (Aplica sobre el total sumado)
            precio_final = str(precio_base)
            
            # Guardamos todo el paquete exacto en la sesión para el checkout
            request.session['reserva_pendiente'] = {
                'fecha': fecha_str_post,
                'hora_inicio': hora_inicio_str,
                'hora_fin': hora_fin_str,
                'precio_fijo': precio_final, # ¡Aquí viaja el valor correcto!
                'cupon': codigo_cupon
            }
            return redirect('checkout_pago')
        else:
            messages.error(request, "⚠️ Error: Faltan datos en la selección o no se calculó el precio.")
            
    else:
        form = ReservaCanchaForm(initial={'fecha': fecha_consulta})

    return render(request, 'core/reservar_cancha.html', {
        'form': form, 
        'horarios': horarios_disponibles,
        'fecha_seleccionada': fecha_consulta, 
        'manana': manana 
    })

@login_required
def checkout_pago(request):
    reserva_data = request.session.get('reserva_pendiente')
    if not reserva_data:
        messages.warning(request, "No tienes ninguna reserva en proceso.")
        return redirect('reservar_cancha')

    if request.method == 'POST':
        h_inicio = str(reserva_data['hora_inicio'])
        h_fin = str(reserva_data['hora_fin'])
        
        if len(h_inicio) == 5: h_inicio += ':00'
        if len(h_fin) == 5: h_fin += ':00'

        precio_final = reserva_data.get('precio_total', reserva_data.get('precio_fijo', 5))

        reserva = ReservaCancha.objects.create(
            usuario=request.user,
            fecha=reserva_data['fecha'],
            hora_inicio=h_inicio,
            hora_fin=h_fin,
            precio_total=precio_final,
            estado='PENDIENTE'
        )

        del request.session['reserva_pendiente']

        telefono_cliente = request.user.perfil.telefono if hasattr(request.user, 'perfil') and request.user.perfil.telefono else "No registrado"
        nombre_cliente = f"{request.user.first_name} {request.user.last_name}".strip()
        if not nombre_cliente:
            nombre_cliente = request.user.username

        # ENVIAR CORREO AL ORGANIZADOR
        try:
            from django.core.mail import send_mail
            from django.conf import settings
            
            asunto = f"📅 NUEVA RESERVA: Cancha el {reserva_data['fecha']}"
            mensaje_correo = f"""
¡Hola Organizador!
Alguien acaba de agendar un turno en la cancha.
Cliente: {nombre_cliente}
Celular: {telefono_cliente}
Fecha: {reserva_data['fecha']}
Horario: {reserva_data['hora_inicio']} a {reserva_data['hora_fin']}
Total a cobrar: ${reserva.precio_total}  
            """
            send_mail(
                subject=asunto, 
                message=mensaje_correo,
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=['deyvi2413@gmail.com'], 
                fail_silently=True
            )
        except Exception as e:
            print("Error enviando email de reserva:", e)

        mensaje = (
            f" *NUEVA RESERVA - NEXT LEVEL* \n\n"
            f" *Cliente:* {nombre_cliente}\n"
            f" *Celular:* {telefono_cliente}\n"
            f" *Fecha:* {reserva_data['fecha']}\n"
            f" *Horario:* {reserva_data['hora_inicio']} a {reserva_data['hora_fin']}\n"
            f" *Total a pagar:* ${reserva.precio_total}\n\n"
            f"Hola, adjunto el comprobante de transferencia para confirmar mi turno."
        )

        numero_organizador = "593963395614" 
        mensaje_codificado = urllib.parse.quote(mensaje)
        url_whatsapp = f"https://wa.me/{numero_organizador}?text={mensaje_codificado}"

        return render(request, 'core/reserva_exitosa.html', {'url_whatsapp': url_whatsapp, 'reserva': reserva})

    return render(request, 'core/checkout_pago.html', {'reserva': reserva_data})


@login_required
def aprobar_reserva_admin(request, reserva_id):
    if request.user.perfil.rol != 'ORG':
        messages.error(request, 'No tienes permisos para realizar esta acción.')
        return redirect('dashboard')
        
    reserva = get_object_or_404(ReservaCancha, id=reserva_id)
    reserva.estado = 'ACTIVA'
    reserva.pagado = True 
    reserva.save()
    
    messages.success(request, f'✅ Turno de {reserva.usuario.first_name} aprobado y confirmado exitosamente.')
    return redirect('dashboard')

@login_required
def mis_reservas(request):
    reservas = ReservaCancha.objects.filter(usuario=request.user).order_by('-fecha')
    return render(request, 'core/mis_reservas.html', {'reservas': reservas})

def ver_torneos_activos(request):
    # 🔥 ORDENAMOS POR CATEGORÍA DESDE LA BASE DE DATOS
    torneos_activos = Torneo.objects.filter(activo=True).order_by('categoria__nombre', 'fecha_inicio')
    torneos_finalizados = Torneo.objects.filter(activo=False).order_by('-fecha_inicio')
    
    mis_torneos_ids = []
    if request.user.is_authenticated and hasattr(request.user, 'perfil') and request.user.perfil.rol == 'DIR':
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
            
            if hasattr(request.user, 'perfil') and request.user.perfil.rol == 'FAN':
                request.user.perfil.rol = 'DIR'
                request.user.perfil.save()
            
            try:
                from django.core.mail import send_mail
                from django.conf import settings
                
                asunto = f"🏆 NUEVA SOLICITUD: {equipo.nombre} quiere unirse"
                # ... (texto del mensaje) ...
                
                send_mail(
                    subject=asunto,
                    message=mensaje,
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=['deyvi2413@gmail.com'], # ¡Aquí está tu correo!
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
    solicitudes = Equipo.objects.filter(estado_inscripcion='PENDIENTE').select_related('torneo', 'dirigente')
    
    if request.method == 'POST':
        equipo_id = request.POST.get('equipo_id')
        accion = request.POST.get('accion') 
        
        equipo = get_object_or_404(Equipo, id=equipo_id)
        
        if accion == 'APROBAR':
            equipo.estado_inscripcion = 'APROBADO'
            equipo.save()
            messages.success(request, f'✅ {equipo.nombre} APROBADO.')

        elif accion == 'RECHAZAR':
            equipo.estado_inscripcion = 'RECHAZADO'
            equipo.save()
            messages.warning(request, f'Solicitud de {equipo.nombre} rechazada.')
            
        return redirect('gestionar_solicitudes')

    return render(request, 'core/gestionar_solicitudes.html', {'solicitudes': solicitudes})

def ver_carrito(request):
    reserva_session = request.session.get('reserva_pendiente')
    
    if not reserva_session:
        messages.info(request, "Tu carrito está vacío.")
        return redirect('reservar_cancha')

    ctx = {
        'fecha': reserva_session.get('fecha'),
        'inicio': reserva_session.get('hora_inicio'),
        'fin': reserva_session.get('hora_fin'),
    }
    return render(request, 'core/carrito.html', ctx)


@login_required
def cancelar_reserva(request, reserva_id):
    reserva = get_object_or_404(ReservaCancha, id=reserva_id)
    
    if request.user != reserva.usuario and request.user.perfil.rol != 'ORG':
        messages.error(request, "No tienes permiso para cancelar esta reserva.")
        return redirect('mis_reservas')

    fecha_reserva = reserva.fecha 
    fecha_hoy = timezone.now().date()
    dias_faltantes = (fecha_reserva - fecha_hoy).days
    
    if dias_faltantes <= 2:
        multa = float(reserva.precio_total) * 0.50
        mensaje = f"⚠️ Cancelación tardía (faltan {dias_faltantes} días). Se aplicó multa del 50%."
    else:
        multa = 0
        mensaje = "✅ Cancelación a tiempo. Reembolso completo."

    reembolso = float(reserva.precio_total) - multa

    if request.method == 'POST':
        reserva.estado = 'CANCELADA'
        reserva.monto_reembolso = reembolso
        reserva.save()
        messages.info(request, f"Reserva Cancelada. {mensaje} Reembolso: ${reembolso}")
        return redirect('mis_reservas')

    return render(request, 'core/confirmar_cancelacion.html', {
        'objeto': reserva, 
        'tipo': 'Reserva de Cancha',
        'multa': multa,
        'reembolso': reembolso,
        'dias': dias_faltantes
    })

@login_required
def cancelar_inscripcion_equipo(request, equipo_id):
    equipo = get_object_or_404(Equipo, id=equipo_id)
    
    if request.user != equipo.dirigente and request.user.perfil.rol != 'ORG':
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
def cobrar_sancion(request, sancion_id):
    if request.user.perfil.rol != 'ORG':
        return redirect('dashboard')
        
    sancion = get_object_or_404(Sancion, id=sancion_id)
    
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
def gestionar_finanzas(request):
    if request.user.perfil.rol != 'ORG':
        return redirect('dashboard')
        
    # --- 1. LÓGICA PARA NUEVA DEUDA MANUAL ---
    if request.method == 'POST' and 'agregar_sancion_manual' in request.POST:
        form_sancion = SancionManualForm(request.POST)
        if form_sancion.is_valid():
            nueva_sancion = form_sancion.save(commit=False)
            nueva_sancion.tipo = 'ADMIN' # Tipo administrativo
            nueva_sancion.pagada = False
            from decimal import Decimal
            nueva_sancion.monto_pagado = Decimal('0.00')
            nueva_sancion.save()
            messages.success(request, f'✅ Sanción de ${nueva_sancion.monto} agregada a {nueva_sancion.equipo.nombre} ({nueva_sancion.descripcion}).')
            return redirect('gestionar_finanzas')
        else:
            messages.error(request, '❌ Error al agregar la deuda. Revisa los campos.')

    # --- 2. LÓGICA EXISTENTE PARA GENERAR INSCRIPCIONES ---
    if request.method == 'POST' and 'generar_inscripciones_viejas' in request.POST:
        equipos_aprobados = Equipo.objects.filter(estado_inscripcion='APROBADO')
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
        messages.success(request, f'✅ Se generaron {agregados} recibos de inscripción para los equipos.')
        return redirect('gestionar_finanzas')

    # Instanciamos el formulario vacío para mandarlo al HTML
    form_sancion = SancionManualForm()

    # --- CÁLCULOS MATEMÁTICOS EXISTENTES ---
    from decimal import Decimal
    total_reservas = ReservaCancha.objects.filter(estado='ACTIVA', es_torneo=False).aggregate(Sum('precio_total'))['precio_total__sum'] or Decimal('0.00')
    
    inscripciones = Sancion.objects.filter(descripcion__icontains='Inscripci')
    inscripciones_pagadas_totalmente = inscripciones.filter(pagada=True).aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
    abonos_inscripciones = inscripciones.filter(pagada=False).aggregate(Sum('monto_pagado'))['monto_pagado__sum'] or Decimal('0.00')
    dinero_real_inscripciones = inscripciones_pagadas_totalmente + abonos_inscripciones
    inscripciones_pendientes = inscripciones.filter(pagada=False).aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
    saldo_real_inscripciones = inscripciones_pendientes - abonos_inscripciones
    
    multas = Sancion.objects.exclude(descripcion__icontains='Inscripci')
    multas_pagadas_totalmente = multas.filter(pagada=True).aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
    abonos_multas = multas.filter(pagada=False).aggregate(Sum('monto_pagado'))['monto_pagado__sum'] or Decimal('0.00')
    dinero_real_multas = multas_pagadas_totalmente + abonos_multas
    multas_pendientes = multas.filter(pagada=False).aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
    saldo_real_multas = multas_pendientes - abonos_multas
    
    lista_sanciones = Sancion.objects.all().select_related('equipo').order_by('pagada', '-id')

    ctx = {
        'form_sancion': form_sancion, # <--- ENVIAMOS EL FORMULARIO AL HTML
        'ingreso_canchas': float(total_reservas),
        'inscripciones_pagadas': float(dinero_real_inscripciones),
        'inscripciones_pendientes': float(saldo_real_inscripciones),
        'multas_pagadas': float(dinero_real_multas),
        'multas_pendientes': float(saldo_real_multas),
        'total_caja': float(total_reservas + dinero_real_inscripciones + dinero_real_multas),
        'sanciones': lista_sanciones
    }
    return render(request, 'core/gestionar_finanzas.html', ctx)

@login_required
def admin_gestion_jugadores(request):
    if request.user.perfil.rol != 'ORG':
        return redirect('dashboard')
        
    query = request.GET.get('q')
    jugadores = Jugador.objects.all().select_related('equipo').order_by('equipo', 'dorsal')
    
    if query:
        jugadores = jugadores.filter(
            Q(nombres__icontains=query) |  
            Q(equipo__nombre__icontains=query) |
            Q(cedula__icontains=query)
        )

    return render(request, 'core/admin_jugadores.html', {'jugadores': jugadores})

@login_required
def admin_gestion_usuarios(request):
    if request.user.perfil.rol != 'ORG':
        return redirect('dashboard')

    if request.method == 'POST':
        perfil_id = request.POST.get('perfil_id')
        nuevo_rol = request.POST.get('nuevo_rol')
        
        if perfil_id and nuevo_rol:
            perfil_usuario = get_object_or_404(Perfil, id=perfil_id)
            
            if perfil_usuario.usuario == request.user:
                messages.error(request, "No puedes cambiar tu propio rol aquí.")
            else:
                perfil_usuario.rol = nuevo_rol
                perfil_usuario.save()
                messages.success(request, f'Rol de "{perfil_usuario.usuario.username}" actualizado a {perfil_usuario.get_rol_display()}.')
            
            return redirect('admin_gestion_usuarios')

    usuarios = User.objects.all().select_related('perfil').order_by('-date_joined')
    
    return render(request, 'core/admin_usuarios.html', {'usuarios': usuarios})

# =========================================================
# VISTAS RESTAURADAS (Horarios, Medios y Próxima Jornada)
# =========================================================

@login_required
@user_passes_test(es_organizador)
def gestionar_horarios(request):
    horarios = HorarioCancha.objects.all().order_by('hora_inicio')
    if request.method == 'POST':
        form = HorarioCanchaForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, '✅ Horario y tarifa agregados correctamente.')
            return redirect('gestionar_horarios')
        else:
            for campo, errores in form.errors.items():
                for error in errores:
                    messages.error(request, f"❌ Error en {campo}: {error}")
    else:
        form = HorarioCanchaForm()
    return render(request, 'core/gestionar_horarios.html', {'form': form, 'horarios': horarios})

@login_required
@user_passes_test(es_organizador)
def eliminar_horario(request, horario_id):
    horario = get_object_or_404(HorarioCancha, id=horario_id)
    hora_str = horario.hora_inicio.strftime('%H:%M')
    horario.delete()
    messages.warning(request, f'🗑️ El bloque de las {hora_str} ha sido eliminado.')
    return redirect('gestionar_horarios')

@login_required
@user_passes_test(es_organizador)
def gestionar_medios(request):
    fotos = FotoGaleria.objects.all().order_by('orden', '-id')
    publicidades = Publicidad.objects.all().order_by('-id')

    if request.method == 'POST':
        if 'btn_foto' in request.POST:
            form_foto = FotoGaleriaForm(request.POST, request.FILES)
            if form_foto.is_valid():
                form_foto.save()
                messages.success(request, '📸 Foto agregada a la galería con éxito.')
                return redirect('gestionar_medios')
        elif 'btn_publi' in request.POST:
            form_publi = PublicidadForm(request.POST, request.FILES)
            if form_publi.is_valid():
                form_publi.save()
                messages.success(request, '📢 Publicidad agregada correctamente.')
                return redirect('gestionar_medios')

    form_foto = FotoGaleriaForm()
    form_publi = PublicidadForm()
    return render(request, 'core/gestionar_medios.html', {
        'fotos': fotos, 'publicidades': publicidades, 'form_foto': form_foto, 'form_publi': form_publi
    })

@login_required
@user_passes_test(es_organizador)
def eliminar_foto(request, foto_id):
    foto = get_object_or_404(FotoGaleria, id=foto_id)
    foto.delete()
    messages.warning(request, "🗑️ Foto eliminada.")
    return redirect('gestionar_medios')

@login_required
@user_passes_test(es_organizador)
def eliminar_publicidad(request, pub_id):
    pub = get_object_or_404(Publicidad, id=pub_id)
    pub.delete()
    messages.warning(request, "🗑️ Publicidad eliminada.")
    return redirect('gestionar_medios')

@login_required
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
# =========================================================
# 8. GENERADOR AUTOMÁTICO DE FIXTURES (FASE 1)
# =========================================================

@login_required
@user_passes_test(es_organizador)
def generar_fixture(request, torneo_id):
    torneo = get_object_or_404(Torneo, id=torneo_id)
    equipos = list(Equipo.objects.filter(torneo=torneo, estado_inscripcion='APROBADO'))
    
    if len(equipos) < 2:
        messages.error(request, "Necesitas al menos 2 equipos APROBADOS para generar un fixture.")
        return redirect('gestionar_torneos')

    if len(equipos) % 2 != 0:
        equipos.append(None) 
    
    n = len(equipos)
    fixture = []
    equipos_rotacion = equipos.copy()

    # 1. Generamos los partidos de IDA
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

    # 2. Si se mandó el formulario (Botón Guardar DB)
    if request.method == 'POST':
        accion = request.POST.get('accion')
        
        # Leemos el switch del HTML (¿Ida y Vuelta?)
        ida_y_vuelta_activado = request.POST.get('ida_y_vuelta_f1') == 'on'
        torneo.fase1_ida_vuelta = ida_y_vuelta_activado
        torneo.save()

        # Si es Ida y Vuelta, clonamos el fixture invirtiendo las localías
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

# --- FUNCIONES DE CÁLCULO MATEMÁTICO ---
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
    torneo = get_object_or_404(Torneo, id=torneo_id)
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
    torneo = get_object_or_404(Torneo, id=torneo_id)
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
    torneo = get_object_or_404(Torneo, id=torneo_id)
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
    torneo = get_object_or_404(Torneo, id=torneo_id)
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
    torneo = get_object_or_404(Torneo, id=torneo_id)
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
            # Finales y Tercer lugar se juegan a partido único SIEMPRE.
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
    torneo = get_object_or_404(Torneo, id=torneo_id)
    
    with transaction.atomic():
        # 1. Borrar todos los partidos que NO sean de Fase 1
        Partido.objects.filter(torneo=torneo, etapa__in=['F2', '4TOS', 'SEMI', 'TERC', 'FINAL']).delete()
        
        # 2. Resetear los grupos y bonificaciones de los equipos (Volver a Fase 1)
        Equipo.objects.filter(torneo=torneo).update(grupo_fase2="", puntos_bonificacion=0)
        
        # 3. Quitar los bloqueos de Ida y Vuelta de las fases eliminatorias
        torneo.fase2_ida_vuelta = False
        torneo.fase3_ida_vuelta = False
        torneo.save()
    
    messages.success(request, "🔄 ¡Rebobinado exitoso! La Fase 2 y eliminatorias fueron borradas. Has vuelto a la Fase 1.")
    return redirect('tabla_posiciones', torneo_id=torneo.id)


@login_required
@user_passes_test(es_organizador)
def activar_vuelta_f1(request, torneo_id):
    torneo = get_object_or_404(Torneo, id=torneo_id)
    torneo.fase1_ida_vuelta = True
    torneo.save()
    messages.success(request, "🔄 Formato actualizado: Ahora puedes programar partidos de Vuelta en la Fase 1.")
    return redirect(f"/programar/?torneo={torneo.id}")

@login_required
@user_passes_test(es_organizador)
def cambiar_formato_fase1(request, torneo_id):
    torneo = get_object_or_404(Torneo, id=torneo_id)
    
    # Si queremos DESACTIVAR la vuelta (volver a Solo Ida)
    if torneo.fase1_ida_vuelta:
        # 🛡️ PROTECCIÓN: Calculamos cuántas fechas son la ida
        total_equipos = Equipo.objects.filter(torneo=torneo, estado_inscripcion='APROBADO').count()
        fechas_ida = total_equipos - 1 if total_equipos % 2 == 0 else total_equipos
        
        # ¿Existen ya partidos de vuelta programados?
        hay_vuelta = Partido.objects.filter(torneo=torneo, etapa='F1', numero_fecha__gt=fechas_ida).exists()
        
        if hay_vuelta:
            messages.error(request, "⛔ No puedes volver a 'Solo Ida' porque ya tienes partidos de VUELTA programados. Debes eliminarlos primero.")
        else:
            torneo.fase1_ida_vuelta = False
            torneo.save()
            messages.success(request, "✅ Formato restaurado a: SOLO IDA.")
    
    # Si queremos ACTIVAR la vuelta
    else:
        torneo.fase1_ida_vuelta = True
        torneo.save()
        messages.success(request, "🔄 Formato actualizado: Ahora se permiten partidos de VUELTA.")

    return redirect(f"/programar/?torneo={torneo.id}")


def buscar_jugador_api(request, cedula):
    # Buscamos si existe algún jugador con esa cédula en la historia del sistema
    # Usamos .first() ordenado por id descendente para traer su registro más reciente
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
    from .models import Categoria 
    
    if request.method == 'POST':
        nombre_categoria = request.POST.get('nombre')
        color_elegido = request.POST.get('color_carnet') # <- Capturamos el color del formulario
        
        if nombre_categoria:
            # Validamos que no exista una con el mismo nombre
            if not Categoria.objects.filter(nombre__iexact=nombre_categoria).exists():
                # 🔥 Guardamos la categoría junto con su color
                Categoria.objects.create(nombre=nombre_categoria, color_carnet=color_elegido)
                messages.success(request, f"✅ Categoría '{nombre_categoria}' creada exitosamente.")
            else:
                messages.error(request, f"⛔ La categoría '{nombre_categoria}' ya existe.")
        else:
            messages.error(request, "⛔ El nombre de la categoría no puede estar vacío.")
            
        return redirect('gestionar_categorias')
        
    categorias = Categoria.objects.all().order_by('nombre')
    
    return render(request, 'core/gestionar_categorias.html', {
        'categorias': categorias
    })

@login_required
@user_passes_test(es_organizador)
def editar_categoria(request, categoria_id):
    from .models import Categoria
    categoria = get_object_or_404(Categoria, id=categoria_id)
    
    if request.method == 'POST':
        nuevo_nombre = request.POST.get('nombre')
        nuevo_color = request.POST.get('color_carnet') # Capturamos el color del formulario
        
        if nuevo_nombre:
            if not Categoria.objects.filter(nombre__iexact=nuevo_nombre).exclude(id=categoria.id).exists():
                categoria.nombre = nuevo_nombre
                
                # Guardamos el nuevo color si viene en el formulario
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
    from .models import Categoria
    categoria = get_object_or_404(Categoria, id=categoria_id)
    
    try:
        categoria.delete()
        messages.success(request, "✅ Categoría eliminada correctamente.")
    except Exception as e:
        # Esto nos protege por si intentas borrar una categoría que ya tiene torneos asignados
        messages.error(request, "⛔ No se pudo eliminar la categoría porque ya tiene torneos o equipos vinculados.")
        
    return redirect('gestionar_categorias')

# =========================================================
# GENERADOR DE CARNETS
# =========================================================
@login_required
def imprimir_carnets(request, equipo_id):
    from .models import Equipo, Jugador
    
    equipo = get_object_or_404(Equipo, id=equipo_id)
    # 🔥 AQUI ESTÁ EL CAMBIO: cambiamos 'numero' por 'dorsal'
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
    # Obtenemos la configuración principal (el ID 1) o la creamos si no existe
    config, created = Configuracion.objects.get_or_create(id=1) 
    
    if request.method == 'POST':
        # El parámetro request.FILES es vital para procesar imágenes
        form = ConfiguracionForm(request.POST, request.FILES, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, '✅ Configuración y Logo actualizados correctamente.')
            return redirect('dashboard')
    else:
        form = ConfiguracionForm(instance=config)
        
    return render(request, 'core/gestionar_configuracion.html', {'form': form})

@login_required
def rechazar_reserva_admin(request, reserva_id):
    # Por seguridad, verificamos que solo el Organizador pueda hacer esto
    if request.user.perfil.rol != 'ORG':
        messages.error(request, 'No tienes permisos para realizar esta acción.')
        return redirect('dashboard')
        
    reserva = get_object_or_404(ReservaCancha, id=reserva_id)
    
    # Eliminamos la reserva de la base de datos
    reserva.delete()
    
    messages.success(request, '❌ Reserva rechazada y eliminada correctamente.')
    
    # Lo regresamos a la pantalla donde estaba (al Dashboard o a Solicitudes)
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

@login_required
def revertir_cobro_sancion(request, sancion_id):
    # Verificamos que sea Organizador o Vocal
    if request.user.perfil.rol not in ['ORG', 'VOC']:
        messages.error(request, "No tienes permisos para realizar esta acción.")
        return redirect('dashboard')
        
    sancion = get_object_or_404(Sancion, id=sancion_id)
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                # 1. Buscamos SOLAMENTE el último abono registrado para esta sanción
                ultimo_abono = sancion.historial_abonos.order_by('-fecha', '-id').first()
                
                if ultimo_abono:
                    monto_a_reversar = ultimo_abono.monto
                    
                    # 2. Le restamos ese dinero a lo que ya había pagado
                    sancion.monto_pagado -= monto_a_reversar
                    
                    # Si por seguridad matemática queda en negativo, lo forzamos a 0
                    if sancion.monto_pagado < Decimal('0.00'):
                        sancion.monto_pagado = Decimal('0.00')
                        
                    # 3. Como le quitamos dinero, la deuda lógicamente ya no está 100% pagada
                    sancion.pagada = False
                    sancion.save()
                    
                    # 4. Eliminamos SOLO ese último registro de abono
                    ultimo_abono.delete()
                    
                    messages.success(request, f"🔄 Reverso exitoso: Se anuló el último abono de ${monto_a_reversar} para {sancion.equipo.nombre}.")
                else:
                    messages.warning(request, "⚠️ No se encontraron abonos para reversar en esta cuenta.")
                    
        except Exception as e:
            messages.error(request, f"Error al intentar reversar el pago: {str(e)}")
            
    # Redirige a la misma página donde estaba el usuario
    return redirect(request.META.get('HTTP_REFERER', 'gestionar_finanzas'))