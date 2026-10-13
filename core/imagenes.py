"""Compresión de imágenes y firmas para ahorrar almacenamiento y BD.

- Fotos subidas (jugadores, escudos, galería, comprobantes, logos): se
  reducen al tamaño útil y se re-codifican (JPEG; PNG si tienen
  transparencia). Una foto de celular de 4 MB queda en ~60-150 KB.
- Firmas del acta: se recortan al trazo, se reducen y se guardan en
  blanco y negro (1 bit). Pasan de ~150 KB a ~2-5 KB en la BD.
"""
import base64
import binascii
import io
import os

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

MAX_FIRMA_BYTES = 3 * 1024 * 1024  # entrada máxima aceptada (data URL)


def comprimir_imagen_campo(instance, campo, max_lado, calidad=78):
    archivo = getattr(instance, campo, None)
    if not archivo or getattr(archivo, '_committed', True):
        return  # nada nuevo que comprimir
    try:
        archivo.seek(0)
        img = Image.open(archivo)
        img.load()
    except Exception:
        return  # no es una imagen válida: que la validación del campo decida
    img = ImageOps.exif_transpose(img)
    img.thumbnail((max_lado, max_lado), Image.LANCZOS)

    tiene_alpha = img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info)
    buffer = io.BytesIO()
    base = os.path.splitext(os.path.basename(archivo.name))[0][:60] or 'imagen'
    if tiene_alpha:
        img.convert('RGBA').save(buffer, format='PNG', optimize=True)
        nombre = f"{base}.png"
    else:
        img.convert('RGB').save(buffer, format='JPEG', quality=calidad, optimize=True, progressive=True)
        nombre = f"{base}.jpg"
    setattr(instance, campo, ContentFile(buffer.getvalue(), name=nombre))


def comprimir_firma(data_url):
    """Recibe 'data:image/png;base64,...' y devuelve una versión mínima, o
    None si no es una imagen válida."""
    if not data_url or len(data_url) > MAX_FIRMA_BYTES:
        return None
    data_url = data_url.strip().replace(' ', '+')
    if not data_url.startswith('data:image/'):
        return None
    try:
        crudo = base64.b64decode(data_url.split(',', 1)[1], validate=False)
        img = Image.open(io.BytesIO(crudo))
        img.load()
    except (IndexError, binascii.Error, OSError, ValueError):
        return None
    fondo = Image.new('RGBA', img.size, (255, 255, 255, 255))
    fondo.alpha_composite(img.convert('RGBA'))
    gris = fondo.convert('L')
    caja = ImageOps.invert(gris).getbbox()
    if not caja:
        return None  # firma vacía
    margen = 8
    caja = (max(caja[0] - margen, 0), max(caja[1] - margen, 0),
            min(caja[2] + margen, gris.width), min(caja[3] + margen, gris.height))
    gris = gris.crop(caja)
    gris.thumbnail((480, 180), Image.LANCZOS)
    bn = gris.point(lambda v: 255 if v > 170 else 0, mode='1')
    buffer = io.BytesIO()
    bn.save(buffer, format='PNG', optimize=True)
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')
