# core/context_processors.py
from django.conf import settings

from .ayuda import AYUDA_POR_PANTALLA, GUIAS_POR_SLUG
from .models import ComplejoDeportivo, Configuracion, RolComplejo
from .services.pruebas import obtener_equipo_simulado

# Pantalla → grupo del menú superior que se marca como activo
SECCION_POR_PANTALLA = {
    'dashboard': 'inicio',
    'gestionar_torneos': 'competicion', 'editar_torneo': 'competicion', 'gestionar_categorias': 'competicion',
    'editar_categoria': 'competicion', 'programar_partidos': 'competicion', 'ver_campeonato': 'competicion',
    'iniciar_campeonato': 'competicion', 'cerrar_fase_regular': 'competicion', 'editar_partido': 'competicion',
    'gestionar_vocalia': 'competicion', 'seleccionar_reporte': 'competicion', 'reporte_estadisticas': 'competicion',
    'tabla_posiciones': 'competicion', 'tabla_goleadores': 'competicion',
    'gestionar_solicitudes': 'equipos', 'gestionar_equipos': 'equipos', 'editar_equipo': 'equipos',
    'admin_gestion_jugadores': 'equipos', 'gestionar_jugadores': 'equipos', 'traspasar_jugador': 'equipos',
    'asignar_cupos': 'equipos', 'sancionar_equipo': 'equipos',
    'gestionar_finanzas': 'finanzas', 'cierre_diario_caja': 'finanzas', 'trazabilidad_financiera': 'finanzas',
    'trazabilidad_cambios': 'finanzas', 'historial_pagos_equipo': 'finanzas', 'registrar_pago': 'finanzas', 'mis_finanzas_equipo': 'finanzas',
    'gestionar_usuarios': 'cancha', 'crear_usuario': 'cancha', 'credenciales_cuenta': 'cancha',
    'gestionar_medios': 'cancha', 'gestionar_configuracion': 'cancha',
    'ver_torneos_activos': 'inscribirse', 'solicitar_inscripcion': 'inscribirse',
    'centro_ayuda': 'ayuda', 'guia_ayuda': 'ayuda',
}


def configuracion_global(request):
    config = Configuracion.objects.first()
    es_entorno_prueba = False
    rol_nav_efectivo = None
    if request.user.is_authenticated:
        es_entorno_prueba = ComplejoDeportivo.objects.filter(
            organizador=request.user, es_demo=True
        ).exists()
        perfil = getattr(request.user, 'perfil', None)
        rol_nav_efectivo = perfil.rol_principal if perfil else 'FAN'
        if obtener_equipo_simulado(request):
            rol_nav_efectivo = 'DIR'
    # Modo soporte: el administrador general administra una cancha ajena
    complejo_soporte = None
    if request.user.is_authenticated and request.user.is_superuser:
        cid = request.session.get('complejo_soporte_id')
        if cid:
            complejo_soporte = ComplejoDeportivo.objects.filter(id=cid).first()
            if complejo_soporte:
                rol_nav_efectivo = 'ORG'

    # Cancha que se muestra en la barra superior (logo + nombre) del organizador
    cancha_nav = complejo_soporte
    if cancha_nav is None and request.user.is_authenticated and not request.user.is_superuser and rol_nav_efectivo == 'ORG':
        cancha_nav = ComplejoDeportivo.objects.filter(organizador=request.user).first()
        if cancha_nav is None:
            rc = RolComplejo.objects.filter(usuario=request.user, rol='ORG').select_related('complejo').first()
            cancha_nav = rc.complejo if rc else None

    # Guía que explica la pantalla actual (botón flotante de ayuda)
    pantalla = getattr(getattr(request, 'resolver_match', None), 'url_name', None)
    guia_pantalla = GUIAS_POR_SLUG.get(AYUDA_POR_PANTALLA.get(pantalla, ''))
    return {
        'guia_pantalla': guia_pantalla,
        'complejo_soporte': complejo_soporte,
        'cancha_nav': cancha_nav,
        'seccion_nav': SECCION_POR_PANTALLA.get(pantalla, ''),
        'config_global': config,
        'es_entorno_prueba': es_entorno_prueba,
        'rol_nav_efectivo': rol_nav_efectivo,
        'google_client_id': settings.GOOGLE_CLIENT_ID,
    }
