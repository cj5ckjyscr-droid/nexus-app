# core/context_processors.py
from .models import Configuracion

def configuracion_global(request):
    config = Configuracion.objects.first()
    return {'config_global': config}