# core/context_processors.py
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
        rol_nav_efectivo = request.user.perfil.rol_principal
        if obtener_equipo_simulado(request):
            rol_nav_efectivo = 'DIR'
    return {
        'config_global': config,
        'es_entorno_prueba': es_entorno_prueba,
        'rol_nav_efectivo': rol_nav_efectivo,
    }
