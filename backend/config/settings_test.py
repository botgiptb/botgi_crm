from .settings import *  # noqa: F403

DEBUG = False
JWT_COOKIE_SECURE = False

# Fast password hasher to accelerate unit test suite
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Celery eager execution for synchronous test verification
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# In-memory cache for fast, isolated test execution
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "unique-test-cache",
    }
}

