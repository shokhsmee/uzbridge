from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")

# Companies live on {slug}.{BASE_DOMAIN}; "app", "api" and "www" are ours.
BASE_DOMAIN = env("BASE_DOMAIN", default="localhost")
PUBLIC_SCHEME = env("PUBLIC_SCHEME", default="http")
# Port the browser uses, only needed locally where the SPA runs on :5173.
PUBLIC_PORT = env("PUBLIC_PORT", default="")
RESERVED_SUBDOMAINS = {"app", "api", "www", "admin", "static", "mail", "docs"}

ALLOWED_HOSTS = env("ALLOWED_HOSTS") or [BASE_DOMAIN, f".{BASE_DOMAIN}"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "core",
    "accounts",
    "integrations",
    "payments",
    "amocrm",
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
    "core.tenancy.TenantMiddleware",
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

DATABASES = {"default": env.db("DATABASE_URL", default="postgres:///uzbridge")}
DATABASES["default"]["ATOMIC_REQUESTS"] = False

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "ru"
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Sessions and CSRF stay per host, so one company's cookie never reaches another subdomain.
SESSION_COOKIE_DOMAIN = None
CSRF_COOKIE_DOMAIN = None
SESSION_COOKIE_SECURE = PUBLIC_SCHEME == "https"
CSRF_COOKIE_SECURE = PUBLIC_SCHEME == "https"
if PUBLIC_SCHEME == "https":
    # nginx terminates TLS and sets X-Forwarded-Proto.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Production only: each company subdomain needs its own TLS certificate. The
# app touches CERT_REQUEST_FILE after a signup; a root systemd path unit then
# runs deploy/sync-certs.sh, which writes the hosts it has certificates for
# to HOSTS_READY_FILE. Empty = no certificate step (dev).
CERT_REQUEST_FILE = env("CERT_REQUEST_FILE", default="")
HOSTS_READY_FILE = env("HOSTS_READY_FILE", default="")

CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=[f"{PUBLIC_SCHEME}://*.{BASE_DOMAIN}{':' + PUBLIC_PORT if PUBLIC_PORT else ''}"],
)

# The amoCRM widget calls the widget API from the account's own domain.
CORS_ALLOWED_ORIGIN_REGEXES = [r"^https://[a-z0-9-]+\.amocrm\.(ru|com)$", r"^https://[a-z0-9-]+\.kommo\.com$"]
CORS_URLS_REGEX = r"^/api/widget/.*$"
CORS_ALLOW_HEADERS = ["content-type", "x-auth-token"]

# MultiFernet: first key encrypts, all keys decrypt (rotate by prepending a new one).
FIELD_ENCRYPTION_KEYS = env.list("FIELD_ENCRYPTION_KEYS")

CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = None
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TASK_ACKS_LATE = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "amocrm-refresh-tokens": {"task": "amocrm.tasks.refresh_expiring_tokens", "schedule": 3600.0},
}

# amoCRM external integration (one for the whole platform, created in our own amoCRM account).
AMOCRM_CLIENT_ID = env("AMOCRM_CLIENT_ID", default="")
AMOCRM_CLIENT_SECRET = env("AMOCRM_CLIENT_SECRET", default="")
AMOCRM_REDIRECT_URI = env("AMOCRM_REDIRECT_URI", default="")
AMOCRM_RATE_PER_SECOND = 7

# Payment providers.
PAYME_CHECKOUT_URL = "https://checkout.paycom.uz"
PAYME_TEST_CHECKOUT_URL = "https://test.paycom.uz"
PAYME_ALLOWED_IPS = env.list("PAYME_ALLOWED_IPS", default=[])  # empty = don't check
CLICK_PAY_URL = "https://my.click.uz/services/pay"
CLICK_API_URL = "https://api.click.uz/v2/merchant"
UZUM_CHECKOUT_URL = env("UZUM_CHECKOUT_URL", default="https://chk-api.uzumcheckout.uz")
UZUM_TEST_CHECKOUT_URL = "https://test-chk-api.uzumcheckout.uz"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
