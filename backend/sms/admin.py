from django.contrib import admin, messages

from core.admin_utils import ReadOnlyAdmin, badge, masked

from .models import SmsAccount, SmsMessage, SmsSettings, SmsTemplate, SmsVariable

MSG_TONE = {"queued": "warn", "sent": "accent", "delivered": "ok", "failed": "bad"}
TPL_TONE = {
    "service": "ok",
    "reklama": "ok",
    "local": "ok",
    "moderation": "warn",
    "inproccess": "warn",
    "rejected": "bad",
}


@admin.register(SmsAccount)
class SmsAccountAdmin(admin.ModelAdmin):
    list_display = [
        "company",
        "provider",
        "label",
        "login",
        "sender",
        "is_enabled",
        "configured",
        "balance",
        "checked_at",
    ]
    list_filter = ["provider", "is_enabled", "company"]
    search_fields = ["company__slug", "label", "login", "sender"]
    list_select_related = ["company"]
    exclude = ["secret", "token"]
    readonly_fields = [
        "public_id",
        "secret_masked",
        "token_expires_at",
        "balance",
        "checked_at",
        "last_error",
        "created_at",
    ]
    actions = ["check_balance"]

    @admin.display(description="Login", boolean=True)
    def configured(self, obj):
        return obj.is_configured

    @admin.display(description="Password")
    def secret_masked(self, obj):
        return masked(obj.secret)

    @admin.action(description="Check Eskiz balance")
    def check_balance(self, request, queryset):
        from django.utils import timezone

        from . import gateways

        for a in queryset.filter(provider="eskiz"):
            try:
                a.balance, a.last_error = gateways.eskiz_balance(a), ""
            except gateways.SmsError as e:
                a.last_error = str(e)[:500]
                self.message_user(request, f"{a}: {e}", messages.ERROR)
            a.checked_at = timezone.now()
            a.save(update_fields=["balance", "last_error", "checked_at"])
        self.message_user(request, "Balances checked.", messages.SUCCESS)


@admin.register(SmsTemplate)
class SmsTemplateAdmin(admin.ModelAdmin):
    list_display = ["short_text", "company", "account", "status_col", "use_in_amocrm", "in_amocrm", "synced_at"]
    list_filter = ["status", "provider", "use_in_amocrm", "company"]
    search_fields = ["text", "company__slug", "external_id"]
    list_editable = ["use_in_amocrm"]
    list_select_related = ["company", "account"]
    readonly_fields = ["external_id", "amo_enum_id", "synced_at"]
    raw_id_fields = ["account"]

    @admin.display(description="Text")
    def short_text(self, obj):
        return obj.title

    @admin.display(description="Status", ordering="status")
    def status_col(self, obj):
        return badge(obj.status, TPL_TONE.get(obj.status, "muted"))

    @admin.display(description="In amoCRM field", boolean=True)
    def in_amocrm(self, obj):
        return bool(obj.amo_enum_id)


@admin.register(SmsVariable)
class SmsVariableAdmin(admin.ModelAdmin):
    list_display = ["key_col", "company", "integration", "source", "label"]
    list_filter = ["integration", "company"]
    search_fields = ["key", "source", "company__slug"]

    @admin.display(description="Keyword", ordering="key")
    def key_col(self, obj):
        return "{" + obj.key + "}"


@admin.register(SmsSettings)
class SmsSettingsAdmin(admin.ModelAdmin):
    list_display = ["company", "account", "link_template", "paid_template"]
    search_fields = ["company__slug"]
    raw_id_fields = ["account", "link_template", "paid_template"]


@admin.register(SmsMessage)
class SmsMessageAdmin(ReadOnlyAdmin):
    list_display = [
        "created_at",
        "company",
        "account",
        "phone",
        "short_text",
        "event",
        "status_col",
        "provider_status",
        "error",
    ]
    list_filter = ["status", "event", "provider", "company", "created_at"]
    search_fields = ["phone", "text", "provider_id", "external_ref", "company__slug"]
    date_hierarchy = "created_at"
    list_select_related = ["company", "account"]
    actions = ["resend"]

    @admin.display(description="Text")
    def short_text(self, obj):
        return obj.text if len(obj.text) <= 60 else obj.text[:57] + "…"

    @admin.display(description="Status", ordering="status")
    def status_col(self, obj):
        return badge(obj.get_status_display(), MSG_TONE.get(obj.status, "muted"))

    @admin.action(description="Send failed messages again")
    def resend(self, request, queryset):
        from .tasks import deliver

        failed = list(queryset.filter(status=SmsMessage.Status.FAILED).values_list("pk", flat=True))
        SmsMessage.objects.filter(pk__in=failed).update(status=SmsMessage.Status.QUEUED, error="")
        for pk in failed:
            deliver.delay(pk)
        self.message_user(request, f"Queued {len(failed)} message(s) again.", messages.SUCCESS)
