# core/context_processors.py
from .models import Configuracion

def configuracion_global(request):
    config = Configuracion.objects.filter(complejo__isnull=True).first()
    return {'config': config}