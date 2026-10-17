# core/context_processors.py
from django.conf import settings

from .ayuda import AYUDA_POR_PANTALLA, GUIAS_POR_SLUG
from .models import ComplejoDeportivo, Configuracion
from .services.pruebas import obtener_equipo_simulado

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
    # Guía que explica la pantalla actual (botón flotante de ayuda)
    pantalla = getattr(getattr(request, 'resolver_match', None), 'url_name', None)
    guia_pantalla = GUIAS_POR_SLUG.get(AYUDA_POR_PANTALLA.get(pantalla, ''))
    return {
        'guia_pantalla': guia_pantalla,
        'config_global': config,
        'es_entorno_prueba': es_entorno_prueba,
        'rol_nav_efectivo': rol_nav_efectivo,
        'google_client_id': settings.GOOGLE_CLIENT_ID,
    }
