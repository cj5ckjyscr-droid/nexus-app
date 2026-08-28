from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from .models import Perfil


class UsuarioOCedulaBackend(ModelBackend):
    """Permite iniciar sesión con el username de siempre O con la cédula
    guardada en Perfil.cedula, sin cambiar nada más del login estándar."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(get_user_model().USERNAME_FIELD)
        if username is None or password is None:
            return None

        UserModel = get_user_model()
        try:
            user = UserModel._default_manager.get_by_natural_key(username)
        except UserModel.DoesNotExist:
            perfil = Perfil.objects.filter(cedula=username).select_related('usuario').first()
            user = perfil.usuario if perfil else None

        if user is None:
            # Ejecuta el hasher de todos modos para no filtrar por tiempo
            # de respuesta si el usuario/cédula existe o no.
            UserModel().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
