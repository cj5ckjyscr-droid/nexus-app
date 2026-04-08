"""
Django settings for config project.
"""

from pathlib import Path
import os
import environ # Librería para leer el archivo .env en producción

# 1. INICIALIZAR ENVIROMENT
env = environ.Env(
    DEBUG=(bool, True) # Por defecto True para evitar errores en la computadora local
)

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Leer el archivo .env si existe (creado en la consola)
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('SECRET_KEY', default='django-insecure-zl*c8d(v%0z+$%ae!(74z1wwpt2=1qytc*-=pd#eh4%q*d=s!f')

# SECURITY WARNING: don't run with debug turned on in production!
# Forzado a True para desarrollo local
DEBUG = True

# Hosts permitidos (Solo los locales para desarrollo)
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '*']

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
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # Quitamos WhiteNoise temporalmente para desarrollo local puro
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
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

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


DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- REDIRECCIONES DE LOGIN ---
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'

# --- CRISPY FORMS (BOOTSTRAP 5) ---
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# ==========================================
# CONFIGURACIÓN PARA ENVIAR CORREOS (GMAIL)
# ==========================================
# Para pruebas locales, es mejor que los correos se impriman en la consola 
# en lugar de enviarlos de verdad, para evitar bloqueos por spam.
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'deyvi2413@gmail.com'  
EMAIL_HOST_PASSWORD = 'qjok ygwc hufa tlbm' 
DEFAULT_FROM_EMAIL = 'NEXUS SPORTOPS <deyvi2413@gmail.com>'

# 💻 CONFIGURACIÓN EN COMPUTADORA LOCAL (DESARROLLO)
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}