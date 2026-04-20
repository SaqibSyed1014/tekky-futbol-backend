"""
Test settings — fast, isolated, no external dependencies.

Uses SQLite in-memory so tests run without a PostgreSQL server.
"""
from .base import *  # noqa: F401, F403

# ---------------------------------------------------------------------------
# Database — SQLite in-memory for speed and isolation
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# ---------------------------------------------------------------------------
# Speed optimisations
# ---------------------------------------------------------------------------
# Bcrypt is intentionally slow; MD5 is fine for tests.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Disable logging noise during test runs
LOGGING = {
    "version": 1,
    "disable_existing_loggers": True,
    "handlers": {},
    "root": {"handlers": []},
}

# CORS — not tested here; avoid env-var lookups
CORS_ALLOW_ALL_ORIGINS = True
