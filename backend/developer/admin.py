from django.contrib import admin, messages
from django.utils import timezone

from core.admin_utils import ReadOnlyAdmin, badge, masked

from .models import ApiKey, WebhookDelivery, WebhookEndpoint


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    """Keys are shown once when made in the dashboard; only the prefix is kept readable."""

    list_display = ["name", "company", "integration", "prefix", "state", "last_used_at", "created_at"]
    list_filter = ["integration", "company"]
    search_fields = ["name", "prefix", "company__slug"]
    list_select_related = ["company"]
    exclude = ["key_hash"]
    readonly_fields = ["company", "prefix", "created_at", "last_used_at", "revoked_at"]
    raw_id_fields = ["sms_account"]
    actions = ["revoke"]

    def has_add_permission(self, request):
        return False  # issued from the dashboard, which shows the key once

    @admin.display(description="State")
    def state(self, obj):
        return badge("revoked", "muted") if obj.revoked_at else badge("active", "ok")

    @admin.action(description="Revoke these keys")
    def revoke(self, request, queryset):
        n = queryset.filter(revoked_at=None).update(revoked_at=timezone.now())
        self.message_user(request, f"Revoked {n} key(s).", messages.SUCCESS)


@admin.register(WebhookEndpoint)
class WebhookEndpointAdmin(admin.ModelAdmin):
    list_display = ["url", "company", "label", "is_enabled", "events", "created_at"]
    list_filter = ["is_enabled", "label", "company"]
    search_fields = ["url", "company__slug"]
    list_editable = ["is_enabled"]
    exclude = ["secret"]
    readonly_fields = ["secret_masked", "created_at"]

    @admin.display(description="Signing secret")
    def secret_masked(self, obj):
        return masked(obj.secret)


@admin.register(WebhookDelivery)
class WebhookDeliveryAdmin(ReadOnlyAdmin):
    list_display = ["created_at", "endpoint", "event", "result", "status_code", "attempts", "delivered_at"]
    list_filter = ["event", "endpoint__company"]
    search_fields = ["event", "endpoint__url", "error"]
    date_hierarchy = "created_at"
    list_select_related = ["endpoint"]
    actions = ["redeliver"]

    @admin.display(description="Result")
    def result(self, obj):
        if obj.delivered_at:
            return badge("delivered", "ok")
        return badge("failing", "bad") if obj.attempts else badge("queued", "warn")

    @admin.action(description="Deliver again")
    def redeliver(self, request, queryset):
        from .tasks import deliver_webhook

        ids = list(queryset.filter(delivered_at=None).values_list("pk", flat=True))
        for pk in ids:
            deliver_webhook.delay(pk)
        self.message_user(request, f"Queued {len(ids)} delivery(ies).", messages.SUCCESS)
