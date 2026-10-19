from django import template
from django.core.files.storage import default_storage

register = template.Library()


@register.filter
def url_archivo(nombre):
    """URL pública de un archivo guardado (sirve con almacenamiento local o
    Cloudinary) a partir de su nombre, p. ej. el escudo que llega en un
    .values(). Vacío si no hay archivo."""
    if not nombre:
        return ''
    try:
        return default_storage.url(str(nombre))
    except Exception:
        return ''


@register.filter
def iniciales(nombre):
    partes = str(nombre or '').split()
    return ''.join(p[0] for p in partes[:2]).upper()
