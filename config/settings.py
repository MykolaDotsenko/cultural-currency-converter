"""
Django settings for Cultural Currency Converter.

Security-sensitive deployment configuration is loaded through the validated
runtime boundary in config.environment.
"""

import os
from pathlib import Path

from config.ai import load_ai_config
from config.cache import load_cache_config
from config.csp import load_csp_config
from config.database import load_database_config
from config.environment import HttpsMode, load_runtime_config
from config.storage import load_media_storage_config

BASE_DIR = Path(__file__).resolve().parent.parent
RUNTIME_CONFIG = load_runtime_config()

APP_ENV = RUNTIME_CONFIG.environment.value
SECRET_KEY = RUNTIME_CONFIG.secret_key
DEBUG = RUNTIME_CONFIG.debug
ALLOWED_HOSTS = list(RUNTIME_CONFIG.allowed_hosts)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_htmx",
    "template_partials",
    "apps.common",
    "apps.accounts",
    "apps.countries",
    "apps.culture",
    "apps.exchange",
    "apps.media",
    "apps.travel",
]

MIDDLEWARE = [
    "apps.common.middleware.RequestContextMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "apps.common.security.ContentSecurityPolicyMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASE_CONFIG = load_database_config(
    environ=os.environ,
    environment=RUNTIME_CONFIG.environment,
    base_dir=BASE_DIR,
)
DATABASES = {"default": DATABASE_CONFIG.as_django_settings()}

CACHE_CONFIG = load_cache_config(
    environ=os.environ,
    environment=RUNTIME_CONFIG.environment,
)
CACHES = {"default": CACHE_CONFIG.as_django_settings()}

CSP_CONFIG = load_csp_config(
    environ=os.environ,
    environment=RUNTIME_CONFIG.environment,
)
CONTENT_SECURITY_POLICY_HEADER = CSP_CONFIG.header_name

AI_CONFIG = load_ai_config(os.environ)
AI_PROVIDER = AI_CONFIG.provider
AI_TEXT_MODEL = AI_CONFIG.text_model
AI_CAMERA_MODEL = AI_CONFIG.camera_model
AI_RUNTIME_EXPLANATION_ENABLED = AI_CONFIG.runtime_explanation_enabled
AI_CAMERA_EXTRACTION_ENABLED = AI_CONFIG.camera_extraction_enabled
AI_EDITORIAL_GENERATION_ENABLED = AI_CONFIG.editorial_generation_enabled
AI_IMAGE_GENERATION_ENABLED = AI_CONFIG.image_generation_enabled
AI_FALLBACK_MODE = AI_CONFIG.fallback_mode
AI_TIMEOUT_SECONDS = AI_CONFIG.timeout_seconds
AI_MAX_ATTEMPTS = AI_CONFIG.max_attempts
GEMINI_API_KEY = AI_CONFIG.gemini_api_key

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "profile"
LOGOUT_REDIRECT_URL = "converter"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_STORAGE_CONFIG = load_media_storage_config(
    environ=os.environ,
    environment=RUNTIME_CONFIG.environment,
    base_dir=BASE_DIR,
)
STORAGES = {
    "default": MEDIA_STORAGE_CONFIG.as_django_storage(),
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if RUNTIME_CONFIG.is_deployed
            else "django.contrib.staticfiles.storage.StaticFilesStorage"
        ),
    },
}

MEDIA_URL = MEDIA_STORAGE_CONFIG.media_url
MEDIA_ROOT = MEDIA_STORAGE_CONFIG.media_root
MEDIA_STORAGE_PUBLIC_ORIGIN = MEDIA_STORAGE_CONFIG.public_origin

VITE_DEV_SERVER_ENABLED = APP_ENV == "local" and DEBUG
VITE_DEV_SERVER_ORIGIN = "http://127.0.0.1:5173"
VITE_MANIFEST_PATH = BASE_DIR / "static" / "build" / ".vite" / "manifest.json"

SESSION_COOKIE_SECURE = RUNTIME_CONFIG.is_deployed
CSRF_COOKIE_SECURE = RUNTIME_CONFIG.is_deployed
SECURE_SSL_REDIRECT = RUNTIME_CONFIG.is_deployed
SECURE_PROXY_SSL_HEADER = (
    ("HTTP_X_FORWARDED_PROTO", "https") if RUNTIME_CONFIG.https_mode is HttpsMode.PROXY else None
)
SECURE_HSTS_SECONDS = RUNTIME_CONFIG.hsts_seconds
SECURE_HSTS_INCLUDE_SUBDOMAINS = RUNTIME_CONFIG.hsts_include_subdomains
SECURE_HSTS_PRELOAD = RUNTIME_CONFIG.hsts_preload
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "apps.common.observability.JsonFormatter",
        }
    },
    "handlers": {
        "console_json": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        }
    },
    "loggers": {
        "cultural_currency.access": {
            "handlers": ["console_json"],
            "level": "INFO",
            "propagate": False,
        },
        "cultural_currency.health": {
            "handlers": ["console_json"],
            "level": "INFO",
            "propagate": False,
        },
        "cultural_currency.exchange": {
            "handlers": ["console_json"],
            "level": "INFO",
            "propagate": False,
        },
        "cultural_currency.ai": {
            "handlers": ["console_json"],
            "level": "INFO",
            "propagate": False,
        },
        "cultural_currency.culture": {
            "handlers": ["console_json"],
            "level": "INFO",
            "propagate": False,
        },
        "cultural_currency.security": {
            "handlers": ["console_json"],
            "level": "WARNING",
            "propagate": False,
        },
        "django": {
            "handlers": ["console_json"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
