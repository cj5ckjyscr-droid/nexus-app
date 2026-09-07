# core/context_processors.py
from .models import ComplejoDeportivo, Configuracion

def configuracion_global(request):
    config = Configuracion.objects.first()
    es_entorno_prueba = False
    if request.user.is_authenticated:
        es_entorno_prueba = ComplejoDeportivo.objects.filter(
            organizador=request.user, es_demo=True
        ).exists()
    return {'config_global': config, 'es_entorno_prueba': es_entorno_prueba}