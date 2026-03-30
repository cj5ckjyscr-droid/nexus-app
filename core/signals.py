from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import Perfil

@receiver(post_save, sender=User)
def crear_perfil(sender, instance, created, **kwargs):
    if created:
        # Si el usuario es un administrador creado por consola (superuser)
        if instance.is_superuser:
            Perfil.objects.create(usuario=instance, rol='ORG')
        else:
            # Si es un usuario normal que se registra en la web, nace como Dirigente
            Perfil.objects.create(usuario=instance, rol='DIR')

@receiver(post_save, sender=User)
def guardar_perfil(sender, instance, **kwargs):
    # Validamos que el perfil exista antes de guardarlo para evitar errores
    if hasattr(instance, 'perfil'):
        instance.perfil.save()