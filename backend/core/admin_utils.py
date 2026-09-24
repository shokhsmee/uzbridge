"""Small helpers shared by the apps' admin pages."""

from django.contrib import admin
from django.utils.html import format_html

from .crypto import mask


def soum(tiyin: int | None) -> str:
    if tiyin is None:
        return "—"
    whole, frac = divmod(int(tiyin), 100)
    s = f"{whole:,}".replace(",", " ")
    return f"{s}.{frac:02d} soʻm" if frac else f"{s} soʻm"


def masked(value: str | None) -> str:
    """Secrets are never shown in the admin, only their last characters."""
    return mask(value) or "—"


BADGE_COLORS = {
    "ok": "#1d7a3a",
    "warn": "#9a6a00",
    "bad": "#a33b2b",
    "muted": "#5b6765",
    "accent": "#12877f",
}


def badge(text: str, tone: str = "muted"):
    color = BADGE_COLORS.get(tone, BADGE_COLORS["muted"])
    return format_html(
        '<span style="display:inline-block;padding:1px 8px;border-radius:99px;font-size:11px;font-weight:600;'
        'color:{};background:{}1f;white-space:nowrap">{}</span>',
        color,
        color,
        text,
    )


def link(url: str, text: str | None = None):
    if not url:
        return "—"
    return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', url, text or url)


class ReadOnlyAdmin(admin.ModelAdmin):
    """Logs and machine-written rows: browse and search, never edit by hand."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


class ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
