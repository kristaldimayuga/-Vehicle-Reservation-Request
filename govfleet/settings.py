"""
Django settings for the GovFleet project.

All secrets and environment-specific values are read from environment
variables (loaded from a local, git-ignored `.env` file in development).
See `.env.example` for the required keys.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, []),
    # 127.0.0.1, not "localhost": on Windows "localhost" resolves to ::1
    # first, so every failed connection is attempted (and times out) twice.
    DB_HOST=(str, "127.0.0.1"),
    DB_PORT=(int, 5432),
    DB_CONNECT_TIMEOUT=(int, 5),
    THROTTLE_RESERVATION_CREATE=(str, "30/hour"),
)
environ.Env.read_env(BASE_DIR / ".env")

# --- Core / security ---------------------------------------------------------

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # Frontend JS reads the CSRF token from the cookie.
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# --- Applications ------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "reservations",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Last, so its process_exception runs first: DB outage -> clean 503.
    "govfleet.middleware.DatabaseUnavailableMiddleware",
]

ROOT_URLCONF = "govfleet.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

WSGI_APPLICATION = "govfleet.wsgi.application"

# --- Database (PostgreSQL only: exclusion constraints require it) -----------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME"),
        "USER": env("DB_USER"),
        "PASSWORD": env("DB_PASSWORD"),
        "HOST": env("DB_HOST"),
        "PORT": env("DB_PORT"),
        "CONN_MAX_AGE": 60,
        # Drop a stale persistent connection instead of failing the request.
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            # Fail fast when PostgreSQL is down instead of hanging the request.
            "connect_timeout": env("DB_CONNECT_TIMEOUT"),
        },
    }
}

# --- Authentication ----------------------------------------------------------
# Temporary: Django session login. Will be replaced by Firebase JWT
# middleware in a later phase without touching the service layer.

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "reservations:calendar"
LOGOUT_REDIRECT_URL = "login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Django REST Framework ---------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "reservations.api.authentication.SessionAuthentication401",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "EXCEPTION_HANDLER": "reservations.api.exceptions.api_exception_handler",
    # Applied per view via ScopedRateThrottle (see ReservationCreateView).
    # Counters live in the default cache (per process); move to Redis later.
    "DEFAULT_THROTTLE_RATES": {
        "reservation_create": env("THROTTLE_RESERVATION_CREATE"),
    },
}

# --- Logging -----------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
    },
    "loggers": {
        "govfleet": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# --- Internationalization ----------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Manila"
USE_I18N = True
USE_TZ = True

# --- Static files ------------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
