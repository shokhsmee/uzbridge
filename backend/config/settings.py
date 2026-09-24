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
# "subdomain" (acme.<domain>) or "path" (<domain>/acme/), see core/tenancy.py.
TENANCY = env("TENANCY", default="subdomain")
# Names a company can't take: our subdomains in one mode, our top-level paths in the other.
RESERVED_SUBDOMAINS = {
    "app", "api", "www", "admin", "static", "mail", "docs",
    "assets", "auth", "login", "oauth", "cb", "p", "d", "s", "g", "pay", "widget", "favicon.ico",
}

ALLOWED_HOSTS = env("ALLOWED_HOSTS") or [BASE_DOMAIN, f".{BASE_DOMAIN}"]

INSTALLED_APPS = [
    "jazzmin",  # admin theme; must come before django.contrib.admin
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
    "sms",
    "developer",
    "billing",
    "audit",
    "documents",
    "realty",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "audit.middleware.CallbackGuard",
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

# Documents: LibreOffice makes PDFs (and Word from site-built templates).
SOFFICE_BIN = env.str("SOFFICE_BIN", default="soffice")
SOFFICE_TIMEOUT = env.int("SOFFICE_TIMEOUT", default=90)
STATICFILES_DIRS = [BASE_DIR / "static"]  # brand/ (the logo) for the admin
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
    "billing-renew": {"task": "billing.tasks.renew_due", "schedule": 900.0},
    "amocrm-automations": {"task": "amocrm.tasks.run_due_automations", "schedule": 60.0},
    "realty-bookings": {"task": "realty.tasks.expire_bookings", "schedule": 300.0},
    "realty-sheets": {"task": "realty.tasks.pull_all_sheets", "schedule": 300.0},
}

# Google Sheets for Shaxmatka: one OAuth client for the platform (Google Cloud console,
# redirect https://<domain>/oauth/google/callback, scope drive.file). Empty = off.
GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID", default="")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET", default="")

# amoCRM: each company's integration is created by the connect button and its
# keys live on AmoConnection, so there are no platform-wide amoCRM keys.
AMOCRM_RATE_PER_SECOND = 7

# The platform's own company (its Payme/Click take balance top-ups).
PLATFORM_COMPANY_SLUG = env("PLATFORM_COMPANY_SLUG", default="uzbridge")

# Payment providers.
PAYME_CHECKOUT_URL = "https://checkout.paycom.uz"
PAYME_TEST_CHECKOUT_URL = "https://test.paycom.uz"
PAYME_ALLOWED_IPS = env.list("PAYME_ALLOWED_IPS", default=[])  # empty = don't check
# Callback allowlists per source (empty = open). Accounts in test mode are never blocked.
CALLBACK_ALLOWED_IPS = {
    "payme": PAYME_ALLOWED_IPS,
    "click": env.list("CLICK_ALLOWED_IPS", default=[]),
    "uzum": env.list("UZUM_ALLOWED_IPS", default=[]),
    "eskiz": env.list("ESKIZ_ALLOWED_IPS", default=[]),
    "playmobile": env.list("PLAYMOBILE_ALLOWED_IPS", default=[]),
}
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

# Shared cache (rate limits) in Redis; tests and dev without Redis fall back to memory.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache" if not CELERY_TASK_ALWAYS_EAGER else
        "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": CELERY_BROKER_URL,
    }
}


# ------------------------------------------------ admin (django-jazzmin)
JAZZMIN_SETTINGS = {
    "site_title": "uzbridge admin",
    "site_header": "uzbridge",
    "site_brand": "uzbridge",
    "welcome_sign": "uzbridge — platform admin",
    "site_logo": "brand/n-mark.svg",
    "login_logo": "brand/n-mark.svg",
    "site_logo_classes": "",
    "site_icon": "brand/n-mark-128.png",
    "copyright": "uzbridge",
    "search_model": ["accounts.Company", "accounts.User", "payments.Invoice"],
    "user_avatar": None,
    "topmenu_links": [
        {"name": "Dashboard", "url": "/", "new_window": True},
        {"model": "accounts.Company"},
        {"model": "payments.Invoice"},
        {"model": "billing.LedgerEntry"},
        {"model": "billing.TariffPrice"},
    ],
    "show_sidebar": True,
    "navigation_expanded": True,
    "hide_apps": ["auth"],
    "order_with_respect_to": [
        "accounts",
        "accounts.Company",
        "accounts.User",
        "accounts.Membership",
        "billing",
        "payments",
        "payments.Invoice",
        "payments.ProviderAccount",
        "sms",
        "amocrm",
        "developer",
        "audit",
    ],
    "icons": {
        "accounts.Company": "fas fa-building",
        "accounts.User": "fas fa-user",
        "accounts.Membership": "fas fa-user-tag",
        "accounts.UserSession": "fas fa-laptop",
        "accounts.HandoffToken": "fas fa-key",
        "billing.LedgerEntry": "fas fa-wallet",
        "billing.TariffPrice": "fas fa-tags",
        "billing.CompanyTariff": "fas fa-handshake",
        "payments.Invoice": "fas fa-file-invoice-dollar",
        "payments.ProviderAccount": "fas fa-cash-register",
        "payments.ProviderTransaction": "fas fa-exchange-alt",
        "payments.FiscalDefaults": "fas fa-receipt",
        "sms.SmsAccount": "fas fa-sim-card",
        "sms.SmsTemplate": "fas fa-comment-dots",
        "sms.SmsVariable": "fas fa-code",
        "sms.SmsSettings": "fas fa-sliders-h",
        "sms.SmsMessage": "fas fa-sms",
        "amocrm.AmoConnection": "fas fa-plug",
        "amocrm.AmoAutomationJob": "fas fa-robot",
        "amocrm.AmoInstall": "fas fa-hourglass-half",
        "developer.ApiKey": "fas fa-key",
        "developer.WebhookEndpoint": "fas fa-satellite-dish",
        "developer.WebhookDelivery": "fas fa-paper-plane",
        "audit.CallbackLog": "fas fa-shield-alt",
        "documents.DocTemplate": "fas fa-file-signature",
        "documents.GeneratedDoc": "fas fa-file-alt",
        "realty.Project": "fas fa-city",
        "realty.Unit": "fas fa-door-open",
        "realty.UnitEvent": "fas fa-history",
        "realty.GoogleAccount": "fab fa-google",
    },
    "default_icon_parents": "fas fa-chevron-circle-right",
    "default_icon_children": "fas fa-circle",
    "related_modal_active": True,
    "changeform_format": "horizontal_tabs",
    "changeform_format_overrides": {"auth.user": "collapsible", "accounts.user": "collapsible"},
    "use_google_fonts_cdn": True,
    "show_ui_builder": False,
    "language_chooser": False,
}
# Same look as the Ziedas Dental admin: white top bar, dark sidebar, flatly,
# light/dark following the operator's system.
JAZZMIN_UI_TWEAKS = {
    "navbar_small_text": False,
    "footer_small_text": False,
    "body_small_text": False,
    "brand_small_text": False,
    "brand_colour": False,
    "accent": "accent-info",
    "navbar": "navbar-white navbar-light",
    "no_navbar_border": False,
    "navbar_fixed": True,
    "layout_boxed": False,
    "footer_fixed": False,
    "sidebar_fixed": True,
    "sidebar": "sidebar-dark-primary",
    "sidebar_nav_small_text": False,
    "sidebar_disable_expand": False,
    "sidebar_nav_child_indent": True,
    "sidebar_nav_compact_style": False,
    "sidebar_nav_legacy_style": False,
    "sidebar_nav_flat_style": True,
    "theme": "flatly",
    "default_theme_mode": "auto",
    "actions_sticky_top": True,
    "button_classes": {
        "primary": "btn-primary",
        "secondary": "btn-secondary",
        "info": "btn-info",
        "warning": "btn-warning",
        "danger": "btn-danger",
        "success": "btn-success",
    },
}
