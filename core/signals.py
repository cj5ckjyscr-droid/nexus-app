from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import Perfil

@receiver(post_save, sender=User)
def crear_perfil(sender, instance, created, **kwargs):
    if created:
        # Ya no asignamos el 'rol' aquí porque ahora los roles dependen
        # de cada cancha (modelo RolComplejo). Solo creamos el perfil base.
        Perfil.objects.get_or_create(usuario=instance)

@receiver(post_save, sender=User)
def guardar_perfil(sender, instance, **kwargs):
    # Validamos que el perfil exista antes de guardarlo para evitar errores
    if hasattr(instance, 'perfil'):
        instance.perfil.save()

# =====================================================
# TRAZABILIDAD FINANCIERA AUTOMÁTICA
# (las eliminaciones y reversos se registran en cada vista, porque al borrar
#  en cascada no es seguro crear filas que apunten a lo que se está borrando)
# =====================================================
from .middleware import request_actual
from .models import Sancion, AbonoSancion, Pago


def _contexto():
    request = request_actual()
    if request is None:
        return None, 'SISTEMA'
    path = request.path or ''
    if path.startswith('/vocalia/'):
        origen = 'VOCALIA'
    elif 'inscripcion' in path or 'importar-equipo' in path:
        origen = 'INSCRIPCION'
    else:
        origen = 'FINANZAS'
    return getattr(request, 'user', None), origen


@receiver(post_save, sender=Sancion)
def registrar_cargo(sender, instance, created, **kwargs):
    if not created:
        return
    from .services.finanzas import registrar_movimiento
    usuario, origen = _contexto()
    registrar_movimiento(complejo=instance.torneo.complejo, tipo='CARGO', monto=instance.monto,
                         usuario=usuario, sancion=instance, origen=origen)


@receiver(post_save, sender=AbonoSancion)
def registrar_abono(sender, instance, created, **kwargs):
    if not created:
        return
    from .services.finanzas import registrar_movimiento
    usuario, origen = _contexto()
    s = instance.sancion
    registrar_movimiento(complejo=s.torneo.complejo, tipo='ABONO', monto=instance.monto, usuario=usuario,
                         sancion=s, partido=instance.partido or s.partido,
                         descripcion=f"Cobro: {s.descripcion}", origen=origen)


@receiver(post_save, sender=Pago)
def registrar_pago_directo(sender, instance, created, **kwargs):
    if not created:
        return
    from .services.finanzas import registrar_movimiento
    usuario, origen = _contexto()
    registrar_movimiento(complejo=instance.equipo.torneo.complejo, tipo='PAGO', monto=instance.monto,
                         usuario=usuario, equipo=instance.equipo, torneo=instance.equipo.torneo,
                         descripcion=instance.observacion or 'Pago directo', origen=origen)


# =====================================================
# COMPRESIÓN AUTOMÁTICA DE IMÁGENES (ahorro de almacenamiento)
# =====================================================
from django.db.models.signals import pre_save
from .imagenes import comprimir_imagen_campo
from .models import Jugador, Equipo, FotoGaleria, ComplejoDeportivo, Configuracion

_CAMPOS_IMAGEN = {
    Jugador: [('foto', 600)],
    Equipo: [('escudo', 400)],
    FotoGaleria: [('imagen', 1600)],
    Pago: [('comprobante', 1400)],
    Perfil: [('foto', 500)],
    ComplejoDeportivo: [('logo', 500)],
    Configuracion: [('logo_sistema', 500)],
}


def _comprimir(sender, instance, **kwargs):
    for campo, lado in _CAMPOS_IMAGEN.get(sender, []):
        comprimir_imagen_campo(instance, campo, lado)


for _modelo in _CAMPOS_IMAGEN:
    pre_save.connect(_comprimir, sender=_modelo, dispatch_uid=f"comprimir_{_modelo.__name__}")
