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