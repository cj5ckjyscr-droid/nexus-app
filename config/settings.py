"""
Django settings for config project.
"""

from pathlib import Path
import os
import environ # Librería para leer el archivo .env en producción
import dj_database_url
from dotenv import load_dotenv

# 1. INICIALIZAR ENVIROMENT
env = environ.Env(
    DEBUG=(bool, True) # Por defecto True para evitar errores en la computadora local
)

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Leer el archivo .env si existe (creado en la consola)
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY', 'una-clave-super-secreta-para-desarrollo')

# Será False en Koyeb para que no salgan pantallas amarillas de error al usuario
DEBUG = os.getenv('DEBUG', 'True') == 'True'

# Hosts permitidos (Solo los locales para desarrollo)
ALLOWED_HOSTS = ['*']

# Token secreto para el endpoint de automatización diaria del SaaS
# (/api/cron/revision-diaria/). En producción, definir CRON_SECRET_TOKEN
# como variable de entorno con un valor propio.
CRON_SECRET_TOKEN = os.getenv('CRON_SECRET_TOKEN', 'NEXUS_SECRETO_2026')

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # --- LIBRERÍAS DE UTILIDAD ---
    'django.contrib.humanize', # ¡IMPORTANTE! Para formatear dinero ($1,200.00)

    # --- MIS APPS ---
    'core',

    # --- ESTILOS Y FORMULARIOS ---
    'crispy_forms',
    'crispy_bootstrap5',
    'cloudinary',
    'cloudinary_storage',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'], # Busca plantillas en la carpeta global
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.configuracion_global',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
DATABASES = {
    'default': dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# Permite iniciar sesión con usuario o con cédula (ver core/backends.py)
AUTHENTICATION_BACKENDS = [
    'core.backends.UsuarioOCedulaBackend',
]

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization (CONFIGURACIÓN PARA ECUADOR)
LANGUAGE_CODE = 'es' # Español
TIME_ZONE = 'America/Guayaquil' # Hora de Ecuador
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
# Usa os.path.join para evitar problemas de rutas en diferentes sistemas operativos
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'core', 'static')]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Media files (Fotos de Jugadores, Escudos)
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Configuración de Archivos Estáticos (CSS, JS) para Producción
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Configuración de Fotos (Si existe la variable en Koyeb, usa Cloudinary)
if os.getenv('CLOUDINARY_URL'):
    DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'


DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- REDIRECCIONES DE LOGIN ---
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'

# --- GOOGLE SIGN-IN ---
# Crear en https://console.cloud.google.com/apis/credentials (tipo "ID de
# cliente de OAuth" > "Aplicación web"). El botón de Google se oculta solo
# si esta variable no está configurada.
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID', '')

# Django activa por defecto la cabecera "Cross-Origin-Opener-Policy: same-origin",
# que corta la referencia window.opener entre la ventana emergente de Google y
# esta página. Sin ella, el script de Google Sign-In no puede hacer postMessage
# de vuelta y la ventana emergente se queda en blanco con un error en consola
# ("Cannot read properties of null (reading 'postMessage')"). Este valor sigue
# protegiendo contra ataques de otras páginas, pero permite que las ventanas
# emergentes que ESTA página abre (como la de Google) mantengan la conexión.
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin-allow-popups"

# --- SEGURIDAD: RECUPERACIÓN DE CONTRASEÑA ---
# El link de "olvidé mi contraseña" expira en 1 hora (Django trae 3 días
# por defecto) — una ventana más corta reduce el riesgo si el correo del
# usuario queda expuesto o el link se comparte por error.
PASSWORD_RESET_TIMEOUT = 3600

# --- SEGURIDAD: COOKIES Y HTTPS (solo en producción, DEBUG=False) ---
# En desarrollo local (sin HTTPS) estas banderas romperían el login, por
# eso solo se activan cuando DEBUG está apagado.
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    # Render (y la mayoría de PaaS) están detrás de un proxy que termina el
    # TLS y reenvía por HTTP interno — sin esto Django cree que todo es
    # HTTP y entra en un loop de redirects con SECURE_SSL_REDIRECT activo.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# --- CRISPY FORMS (BOOTSTRAP 5) ---
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# ==========================================
# CONFIGURACIÓN PARA ENVIAR CORREOS (GMAIL)
# ==========================================
# 🔒 Nunca hardcodear credenciales reales aquí — SIEMPRE por variable de
# entorno. Si EMAIL_HOST_PASSWORD no está configurada, se usa la consola
# (los correos se imprimen en la terminal, no se envían de verdad) para
# que el proyecto siga siendo usable en desarrollo sin exponer nada.
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', 'deyvi2413@gmail.com')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
if EMAIL_HOST_PASSWORD:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = 'smtp.gmail.com'
    EMAIL_PORT = 587
    EMAIL_USE_TLS = True
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = f'NEXUS SPORTOPS <{EMAIL_HOST_USER}>'

# 💻 CONFIGURACIÓN EN COMPUTADORA LOCAL (DESARROLLO)
# Si existe CLOUDINARY_URL, los archivos (logos, fotos) se suben a Cloudinary
# para que persistan en producción (Render plan gratis usa sqlite en memoria).
# Si no existe la variable, se usan los archivos locales del sistema.
if os.getenv('CLOUDINARY_URL'):
    STORAGES = {
        "default": {
            "BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
else:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }