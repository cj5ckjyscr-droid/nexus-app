from django.conf import settings
from django.contrib.auth.models import User
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

EMISORES_VALIDOS = ('accounts.google.com', 'https://accounts.google.com')


class GoogleTokenInvalido(Exception):
    """El ID token de Google no es válido, expiró, o no corresponde a
    este servidor — nunca se debe iniciar sesión con él."""


def verificar_token_google(token):
    """Verifica criptográficamente un ID token emitido por Google
    Identity Services contra nuestro GOOGLE_CLIENT_ID. Lanza
    GoogleTokenInvalido en cualquier caso dudoso — nunca confía en el
    contenido del token sin antes validar su firma, emisor y audiencia."""
    if not settings.GOOGLE_CLIENT_ID:
        raise GoogleTokenInvalido("Google Sign-In no está configurado en este servidor.")
    try:
        info = id_token.verify_oauth2_token(token, google_requests.Request(), settings.GOOGLE_CLIENT_ID)
    except ValueError as e:
        raise GoogleTokenInvalido(str(e)) from e

    if info.get('iss') not in EMISORES_VALIDOS:
        raise GoogleTokenInvalido("Emisor de token no reconocido.")
    if not info.get('email_verified'):
        raise GoogleTokenInvalido("El correo de esa cuenta de Google no está verificado.")
    if not info.get('email'):
        raise GoogleTokenInvalido("Google no devolvió un correo electrónico.")
    return info


def obtener_o_crear_usuario_de_google(info_token):
    """Busca un User existente por correo (permite a alguien que ya se
    registró con usuario/contraseña iniciar sesión con Google si usa el
    mismo correo), o crea una cuenta nueva sin contraseña utilizable —
    solo podrá entrar por Google hasta que use "Olvidé mi contraseña"."""
    email = info_token['email']
    usuario = User.objects.filter(email__iexact=email).first()
    if usuario:
        return usuario, False

    base_username = (email.split('@')[0] or 'usuario')[:25]
    username = base_username
    sufijo = 1
    while User.objects.filter(username=username).exists():
        sufijo += 1
        username = f"{base_username}{sufijo}"[:30]

    usuario = User.objects.create_user(
        username=username,
        email=email,
        first_name=info_token.get('given_name', '')[:150],
        last_name=info_token.get('family_name', '')[:150],
    )
    usuario.set_unusable_password()
    usuario.save()
    return usuario, True
