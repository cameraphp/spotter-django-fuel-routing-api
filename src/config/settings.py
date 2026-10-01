import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'dev-insecure-change-me-in-production')

DEBUG = os.getenv('DJANGO_DEBUG', 'False').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = ['*'] if DEBUG else os.getenv('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost').split(',')



INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'rest_framework',
    'routing',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.common.CommonMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = []

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR.parent / os.getenv('DATABASE_URL', 'sqlite:///spotter_routing.sqlite3').replace('sqlite:///', ''),
    }
}

_db_url = os.getenv('DATABASE_URL', '')
if _db_url.startswith('sqlite:///'):
    _db_path = _db_url.replace('sqlite:///', '')
    if not os.path.isabs(_db_path):
        _db_path = BASE_DIR.parent / _db_path
    DATABASES['default']['NAME'] = _db_path

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = False
USE_TZ = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
    ],
    'UNAUTHENTICATED_USER': None,
}

NOMINATIM_URL = os.getenv('NOMINATIM_URL', 'https://nominatim.openstreetmap.org')
OSRM_URL = os.getenv('OSRM_URL', 'http://router.project-osrm.org')
NOMINATIM_USER_AGENT = os.getenv('NOMINATIM_USER_AGENT', 'spotter-backend-assessment-local-dev')
NOMINATIM_TIMEOUT_SECONDS = int(os.getenv('NOMINATIM_TIMEOUT_SECONDS', '10'))

try:
    ORIGIN_CATCHMENT_RADIUS_MILES = float(os.getenv('ORIGIN_CATCHMENT_RADIUS_MILES', '5'))
except (TypeError, ValueError):
    ORIGIN_CATCHMENT_RADIUS_MILES = 5.0

try:
    CORRIDOR_WIDTH_MILES = float(os.getenv('CORRIDOR_WIDTH_MILES', '25'))
except (TypeError, ValueError):
    CORRIDOR_WIDTH_MILES = 25.0
