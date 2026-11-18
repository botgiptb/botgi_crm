import os
import sys
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables
load_dotenv(BASE_DIR.parent / ".env")
load_dotenv(BASE_DIR / ".env")

# Add apps folder to Python path
sys.path.insert(0, str(BASE_DIR / "apps"))

# Security
SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-shopcrm-change-me-in-production-env-variable")
DEBUG = os.getenv("DEBUG", "True").lower() in ("true", "1")
ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0").split(",")
    if h.strip()
]

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt",
    # Local apps
    "apps.accounts",
    "apps.leads",
    "apps.activities",
    "apps.integrations_meta",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database Configuration
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    import urllib.parse

    _db_url = urllib.parse.urlparse(DATABASE_URL)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": _db_url.path.lstrip("/"),
            "USER": _db_url.username or "postgres",
            "PASSWORD": _db_url.password or "",
            "HOST": _db_url.hostname or "localhost",
            "PORT": str(_db_url.port or 5432),
        }
    }
else:
    DB_ENGINE = os.getenv("DB_ENGINE", "django.db.backends.sqlite3")
    if DB_ENGINE == "django.db.backends.postgresql" or (
        os.getenv("DB_HOST") and DB_ENGINE != "django.db.backends.sqlite3"
    ):
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": os.getenv("DB_NAME", "shopcrm"),
                "USER": os.getenv("DB_USER", "shopcrm"),
                "PASSWORD": os.getenv("DB_PASSWORD", "shopcrm_password"),
                "HOST": os.getenv("DB_HOST", "localhost"),
                "PORT": os.getenv("DB_PORT", "5432"),
            }
        }
    else:
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": BASE_DIR / os.getenv("DB_NAME", "db.sqlite3"),
            }
        }

# Custom User Model
AUTH_USER_MODEL = "accounts.User"

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Reverse Proxy (Nginx)
NUM_PROXIES = int(os.getenv("NUM_PROXIES", "1"))

# Django REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DATETIME_FORMAT": "%Y-%m-%dT%H:%M:%SZ",
    "NUM_PROXIES": NUM_PROXIES,
}

# SimpleJWT Settings
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# CORS Configuration
CORS_ALLOW_ALL_ORIGINS = os.getenv("CORS_ALLOW_ALL_ORIGINS", "False").lower() in ("true", "1")
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOWED_ORIGINS", "http://localhost:4200,http://127.0.0.1:4200"
    ).split(",")
    if origin.strip()
]

# Celery Configuration
from celery.schedules import crontab  # noqa: E402

CELERY_TIMEZONE = "Asia/Kolkata"
CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True

if "pytest" in sys.modules or os.getenv("TESTING", "False").lower() in ("true", "1"):
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CELERY_BEAT_SCHEDULE = {
    "notify-overdue-followups-every-15-mins": {
        "task": "apps.activities.tasks.notify_overdue_followups",
        "schedule": crontab(minute="*/15"),
    },
    "daily-morning-summary-at-9am": {
        "task": "apps.activities.tasks.send_daily_summary",
        "schedule": crontab(hour=9, minute=0),
    },
    "check-stale-leads-daily-at-830am": {
        "task": "apps.activities.tasks.check_and_flag_stale_leads",
        "schedule": crontab(hour=8, minute=30),
    },
    "sweep-stuck-meta-webhooks-every-5-mins": {
        "task": "apps.integrations_meta.tasks.sweep_stuck_meta_webhooks",
        "schedule": crontab(minute="*/5"),
    },
    "cleanup-old-meta-logs-daily-at-2am": {
        "task": "apps.integrations_meta.tasks.cleanup_old_meta_webhook_logs",
        "schedule": crontab(hour=2, minute=0),
    },
}

# Stale lead detection threshold
STALE_LEAD_THRESHOLD_DAYS = int(os.getenv("STALE_LEAD_THRESHOLD_DAYS", "3"))

# Meta Graph API and Lead Ads Integration
META_GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v22.0")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "")
META_PAGE_ACCESS_TOKEN = os.getenv("META_PAGE_ACCESS_TOKEN", "")
META_PAGE_ID = os.getenv("META_PAGE_ID", "")
META_WEBHOOK_MAX_BYTES = int(os.getenv("META_WEBHOOK_MAX_BYTES", str(1024 * 1024)))  # 1 MB

if not DEBUG and not (
    "pytest" in sys.modules or os.getenv("TESTING", "False").lower() in ("true", "1")
):
    import logging

    _meta_logger = logging.getLogger(__name__)
    if not META_APP_SECRET or not META_VERIFY_TOKEN:
        _meta_logger.error(
            "CRITICAL: Meta integration secrets (META_APP_SECRET, META_VERIFY_TOKEN) "
            "are not configured in production!"
        )

# Email Configuration
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 587))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True").lower() in ("true", "1")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "Shop CRM <noreply@shopcrm.local>")
