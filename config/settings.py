"""
Django settings for config project.
"""

from pathlib import Path
import os
import environ # Librería para leer el archivo .env en producción
import dj_database_url

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
DEBUG = env.bool('DEBUG', default=True)

# Hosts permitidos
ALLOWED_HOSTS = [
    'localhost', 
    '127.0.0.1', 
    '*', 
    'complejonextlevel.com', 
    'www.complejonextlevel.com'
]

# Permite que Django confíe en el enlace de Google para los formularios
CSRF_TRUSTED_ORIGINS = [
    'https://nextlevel-app-358951834786.us-east1.run.app',
    'https://complejonextlevel.com',
    'https://www.complejonextlevel.com',
]

# Application definition
INSTALLED_APPS = [
    'cloudinary',
    'cloudinary_storage',
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
    'whitenoise.middleware.WhiteNoiseMiddleware', # <-- OBLIGATORIO PARA PRODUCCIÓN (CSS)
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
STATICFILES_DIRS = [BASE_DIR / 'static'] # Carpeta para los CSS globales
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Media files (Fotos de Jugadores, Escudos)
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Credenciales de Cloudinary
CLOUDINARY_STORAGE = {
    'CLOUD_NAME': env('CLOUDINARY_CLOUD_NAME', default=''),
    'API_KEY': env('CLOUDINARY_API_KEY', default=''),
    'API_SECRET': env('CLOUDINARY_API_SECRET', default=''),
}

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
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'deyvi2413@gmail.com'  
EMAIL_HOST_PASSWORD = 'qjok ygwc hufa tlbm' 

# ==========================================
# SEGURIDAD Y ALMACENAMIENTO (LOCAL VS PRODUCCIÓN)
# ==========================================
if not DEBUG:
    # ☁️ CONFIGURACIÓN EN GOOGLE CLOUD (PRODUCCIÓN)
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

    # Usar Cloudinary para Media y WhiteNoise para Estáticos (Django 4.2+)
    STORAGES = {
        "default": {
            "BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
        },
    }
else:
    # 💻 CONFIGURACIÓN EN COMPUTADORA LOCAL (DESARROLLO)
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
        },
    }