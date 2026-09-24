from django.contrib import admin

from core.admin_utils import ReadOnlyAdmin, badge

from .models import CallbackLog


@admin.register(CallbackLog)
class CallbackLogAdmin(ReadOnlyAdmin):
    """Every call to the public callbacks (Payme, Click, Uzum, SMS reports, amoCRM hooks)."""

    list_display = ["created_at", "source", "company", "result", "status_code", "ip", "note", "path"]
    list_filter = ["source", "ok", "blocked", "company", "created_at"]
    search_fields = ["path", "ip", "note", "company__slug"]
    date_hierarchy = "created_at"
    list_select_related = ["company"]

    @admin.display(description="Result")
    def result(self, obj):
        if obj.blocked:
            return badge("blocked", "bad")
        return badge("ok", "ok") if obj.ok else badge("error", "warn")
