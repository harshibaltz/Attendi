"""
FET Platform - Django settings.

Environment-driven configuration (12-factor). Secrets are never committed.
"""
import os
import sys
import hashlib
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(key, default=None):
    return os.environ.get(key, default)


def env_bool(key, default=False):
    return str(os.environ.get(key, default)).lower() in ("1", "true", "yes")


def env_int(key, default):
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-secret-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
IS_PRODUCTION = not DEBUG
ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]

# Originating app hosts allowed to submit CSRF-protected forms (Django admin).
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in env(
        "CSRF_TRUSTED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",") if o.strip()
]

LOGIN_URL = env("DJANGO_LOGIN_URL", "/admin/login/")
LOGIN_REDIRECT_URL = env("DJANGO_LOGIN_REDIRECT_URL", "/admin/")
LOGOUT_REDIRECT_URL = env("DJANGO_LOGOUT_REDIRECT_URL", "/admin/login/")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third party
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    # FET platform apps
    "apps.core",
    "apps.accounts",
    "apps.academics",
    "apps.attendance",
    "apps.learning",
    "apps.announcements",
    "apps.projects",
    "apps.notifications",
    "apps.audit",
    "apps.dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.security.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"

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

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# Database - PostgreSQL in production, SQLite fallback for local development.
# ---------------------------------------------------------------------------
DATABASE_URL = env("DATABASE_URL", "")


def parse_database_url(url):
    """Minimal postgres://user:pass@host:port/name?sslmode=... parser."""
    from urllib.parse import parse_qs, unquote, urlparse

    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    sslmode = (params.get("sslmode") or params.get("ssl_mode") or ["prefer"])[0]
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "localhost",
        "PORT": str(parsed.port or 5432),
        "OPTIONS": {"sslmode": sslmode} if sslmode else {},
    }


if DATABASE_URL.startswith(("postgres://", "postgresql://")):
    DATABASES = {"default": parse_database_url(DATABASE_URL)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", "Africa/Lagos")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = (
    "whitenoise.storage.CompressedManifestStaticFilesStorage" if IS_PRODUCTION
    else "django.contrib.staticfiles.storage.StaticFilesStorage"
)
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", BASE_DIR / "media"))

# ---------------------------------------------------------------------------
# File upload policy (BR-182 allowed types, BR-183 max sizes; API Spec doc 07 §35).
# Actual files live outside the relational DB in private storage (BR-180).
# ---------------------------------------------------------------------------
FILE_MAX_SIZE_MB = env_int("FILE_MAX_SIZE_MB", 25)
FILE_MAX_SIZE_BYTES = FILE_MAX_SIZE_MB * 1024 * 1024
ALLOWED_FILE_MIME_TYPES = [
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/zip",
    "application/x-zip-compressed",
    "text/plain",
    "text/csv",
    "text/markdown",
]
ALLOWED_FILE_EXTENSIONS = {
    "pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "zip", "txt", "csv", "md",
    "png", "jpg", "jpeg", "gif", "webp",
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Cache - shared storage for temporary data (QR tokens, rate limits).
#
# Preference order:
#   1. Redis when REDIS_URL is set.
#   2. In production, the PostgreSQL database cache (shared across serverless
#      instances without an extra service). Create the table once with
#      `python manage.py createcachetable`.
#   3. Local memory cache for development.
# Production requires a *shared* cache (enforced by apps/core/checks.py).
# ---------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", "")
REQUIRE_REDIS_FOR_TRAFFIC = env_bool("REQUIRE_REDIS_FOR_TRAFFIC", False)
if REQUIRE_REDIS_FOR_TRAFFIC and not REDIS_URL:
    raise ImproperlyConfigured(
        "REDIS_URL is required for attendance traffic; refusing database or per-worker cache fallback."
    )
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "TIMEOUT": env_int("CACHE_TIMEOUT", 300),
            "OPTIONS": {
                "socket_connect_timeout": 2,
                "socket_timeout": 2,
            },
        }
    }
elif IS_PRODUCTION and DATABASE_URL.startswith(("postgres://", "postgresql://")):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.db.DatabaseCache",
            "LOCATION": env("DB_CACHE_TABLE", "fet_cache_table"),
            "TIMEOUT": env_int("CACHE_TIMEOUT", 300),
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "fet-attendance",
        }
    }

# Read-only polling *rate-limit counters* use a separate cache. Never use
# DatabaseCache for these counters: every rejected poll would otherwise still
# hit PostgreSQL. Redis makes limits shared across workers; local memory is a
# useful per-worker backstop for development and existing deployments without
# Redis. Attendance read values use the shared "default" cache instead (see
# apps/attendance/read_cache.py) so every instance serves the same snapshot.
CACHES["polling"] = (
    {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {"socket_connect_timeout": 2, "socket_timeout": 2},
    }
    if REDIS_URL else
    {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "fet-polling"}
)

# ---------------------------------------------------------------------------
# Security (HTTPS, cookies, headers). Enforced when DJANGO_DEBUG is false.
# ---------------------------------------------------------------------------
COOKIE_SECURE = env_bool("COOKIE_SECURE", IS_PRODUCTION)
COOKIE_SAMESITE = env("COOKIE_SAMESITE", "Lax")

# Same-site cookie auth requires the SPA and the API to share an origin. The
# frontend's vercel.json rewrites /api/* here, so the browser sees a single
# origin and these stay first-party cookies. If you ever move the API back to a
# separate domain, `SameSite=None` is NOT enough on iOS: Safari drops
# third-party cookies outright (ITP), so sign-in silently fails on iPhones.
COOKIE_DOMAIN = env("COOKIE_DOMAIN", "") or None

# CHIPS (Cookies Having Independent Partitioned State). Auto-enables only in the
# cross-site case, where it is the one attribute Safari 17+/iOS 17+ honours for
# third-party cookies. Same-site deployments keep Lax and change nothing.
COOKIE_PARTITIONED = env_bool("COOKIE_PARTITIONED", str(COOKIE_SAMESITE).lower() == "none")

if IS_PRODUCTION:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = COOKIE_SAMESITE
    CSRF_COOKIE_SECURE = True
    CSRF_COOKIE_SAMESITE = COOKIE_SAMESITE
    SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 31536000)  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# Extra hardening available in any environment.
X_FRAME_OPTIONS = env("X_FRAME_OPTIONS", "DENY")

# ---------------------------------------------------------------------------
# Password reset (6-digit emailed OTP, see apps/core/emailing.py).
# ---------------------------------------------------------------------------
# Base URL of the SPA (kept for links that may be added to messages later).
FRONTEND_URL = env("FRONTEND_URL", "https://fet-platform.vercel.app")
# How long an emailed OTP stays valid, and how many wrong guesses are allowed
# before the code is burned and a fresh one must be requested.
PASSWORD_RESET_OTP_TTL_MINUTES = env_int("PASSWORD_RESET_OTP_TTL_MINUTES", 10)
PASSWORD_RESET_OTP_MAX_ATTEMPTS = env_int("PASSWORD_RESET_OTP_MAX_ATTEMPTS", 5)

# ---------------------------------------------------------------------------
# Outbound email (SMTP). Leave EMAIL_HOST empty and messages are logged instead
# of sent. Works with any provider (Gmail app password, Brevo, Mailgun, ...).
# ---------------------------------------------------------------------------
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "FET Platform <no-reply@fet-platform.vercel.app>")

# ---------------------------------------------------------------------------
# DRF - consistent JSON envelope, JWT auth from httpOnly cookie or header.
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.accounts.authentication.CookieJWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "apps.core.rendering.SuccessRenderer",
    ],
    "EXCEPTION_HANDLER": "apps.core.rendering.enveloped_exception_handler",
    "DEFAULT_PAGINATION_CLASS": "apps.core.rendering.EnvelopedPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/minute",
        "login": "30/minute",
        "register": "10/minute",
        # Attendance-specific abuse protection.
        "attendance_scan": "60/minute",      # per-user scan cap
        "attendance_start": "10/minute",     # launching sessions
        "attendance_admin": "20/minute",     # tokens, checkpoints, corrections
        # Password reset abuse protection (3 requests / 15 min per IP).
        "password_reset": "3/15min",
        # Separate read limits keep refresh loops from consuming the write quota.
        "attendance_station_poll": env("ATTENDANCE_STATION_POLL_RATE", "12/minute"),
        "attendance_live_poll": env("ATTENDANCE_LIVE_POLL_RATE", "30/minute"),
        "attendance_history_poll": env("ATTENDANCE_HISTORY_POLL_RATE", "12/minute"),
        "attendance_station_token": env("ATTENDANCE_STATION_TOKEN_RATE", "12/minute"),
        "attendance_sync": env("ATTENDANCE_SYNC_RATE", "30/minute"),
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env_int("ACCESS_TOKEN_MINUTES", 120)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env_int("REFRESH_TOKEN_DAYS", 7)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

COOKIE_NAME_ACCESS = "fet_access"
COOKIE_NAME_REFRESH = "fet_refresh"
COOKIE_MAX_AGE_ACCESS = env_int("ACCESS_TOKEN_MINUTES", 120) * 60
COOKIE_MAX_AGE_REFRESH = env_int("REFRESH_TOKEN_DAYS", 7) * 24 * 60 * 60

# Attendance configuration (Business Rules BR-035 / BR-036 - configurable)
ATTENDANCE_TOKEN_TTL_SECONDS = env_int("ATTENDANCE_TOKEN_TTL_SECONDS", 5)
ATTENDANCE_SCANS_PER_STATION = env_int("ATTENDANCE_SCANS_PER_STATION", 20)
ATTENDANCE_TOKEN_VERSION = env_int("ATTENDANCE_TOKEN_VERSION", 2)
ATTENDANCE_TOKEN_HMAC_KEY = env("ATTENDANCE_TOKEN_HMAC_KEY", "") or (
    hashlib.sha256(f"fet-attendance-dev:{SECRET_KEY}".encode()).hexdigest() if DEBUG else ""
)
ATTENDANCE_OFFLINE_GRACE_SECONDS = env_int("ATTENDANCE_OFFLINE_GRACE_SECONDS", 86400)
ATTENDANCE_OFFLINE_SYNC_MAX_CAPTURES = env_int("ATTENDANCE_OFFLINE_SYNC_MAX_CAPTURES", 100)
ATTENDANCE_SESSION_DEFAULT_SECONDS = env_int("ATTENDANCE_SESSION_SECONDS", 300)
ATTENDANCE_SESSION_MAX_SECONDS = env_int("ATTENDANCE_SESSION_MAX_SECONDS", 10800)
ATTENDANCE_MAX_CHECKPOINTS = env_int("ATTENDANCE_MAX_CHECKPOINTS", 10)
ATTENDANCE_AUTO_MIN_VERIFIED = env_int("ATTENDANCE_AUTO_MIN_VERIFIED", 15)

CORS_ALLOWED_ORIGINS = [
    o.strip() for o in env(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3002,http://127.0.0.1:3002",
    ).split(",") if o.strip()
]
CORS_ALLOW_CREDENTIALS = True

if "test" in sys.argv or "pytest" in sys.modules:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    # Default: an isolated in-memory SQLite, never the configured DB. Set
    # FET_TEST_DATABASE_URL to a throwaway PostgreSQL to exercise the
    # SELECT ... FOR UPDATE concurrency tests (row locking is a no-op on SQLite).
    _test_url = env("FET_TEST_DATABASE_URL", "")
    if _test_url.startswith(("postgres://", "postgresql://")):
        DATABASES = {"default": parse_database_url(_test_url)}
    else:
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": ":memory:",
            }
        }
