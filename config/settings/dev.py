from .base import *  # noqa: F401, F403

DEBUG = True

# Always print emails to the terminal in development — no SES calls, no cost.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Browsable API in development
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = (  # noqa: F405
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
)

# Allow all origins locally (overrides base CORS_ALLOWED_ORIGINS)
CORS_ALLOW_ALL_ORIGINS = True

# Django Extensions
INSTALLED_APPS += ["django_extensions"]  # noqa: F405

# Verbose SQL logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        "django.db.backends": {
            "handlers": ["console"],
            "level": "DEBUG",
        },
    },
}
