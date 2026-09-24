from django.contrib import admin, messages

from core.admin_utils import ReadOnlyAdmin, badge, link, masked

from .models import AmoAutomationJob, AmoConnection, AmoInstall

STATUS_TONE = {"active": "ok", "error": "bad", "disconnected": "muted"}


@admin.register(AmoConnection)
class AmoConnectionAdmin(admin.ModelAdmin):
    list_display = [
        "host",
        "company",
        "account_id",
        "status_col",
        "widget",
        "sms_enabled",
        "bills_enabled",
        "expires_at",
        "connected_at",
    ]
    list_filter = ["status", "sms_enabled", "bills_enabled", "company"]
    search_fields = ["company__slug", "host", "account_id", "client_id", "widget_client_id"]
    list_select_related = ["company"]
    # Tokens and secrets are never shown or edited here.
    exclude = ["access_token", "refresh_token", "client_secret", "widget_client_secret"]
    readonly_fields = [
        "account_id",
        "subdomain",
        "host_link",
        "client_id",
        "client_secret_masked",
        "widget_client_id",
        "widget_client_secret_masked",
        "hook_token",
        "expires_at",
        "connected_at",
        "connected_by",
        "last_error",
        "pipelines",
        "pipelines_synced_at",
    ]
    fieldsets = (
        (None, {"fields": ("company", "host", "host_link", ("account_id", "subdomain"), "status", "last_error")}),
        (
            "Integrations in amoCRM",
            {
                "fields": (
                    ("client_id", "client_secret_masked"),
                    ("widget_client_id", "widget_client_secret_masked"),
                    "hook_token",
                    ("expires_at", "connected_at", "connected_by"),
                )
            },
        ),
        (
            "What this amoCRM uses",
            {"fields": ("payment_accounts", "sms_account", ("sms_enabled", "bills_enabled"), "bills_catalog_id")},
        ),
        (
            "Pipelines and fields",
            {
                "classes": ("collapse",),
                "fields": (
                    "paid_stages",
                    "link_stages",
                    "add_notes",
                    ("link_field_id", "status_field_id", "sms_field_id"),
                    "pipelines",
                    "pipelines_synced_at",
                ),
            },
        ),
    )
    raw_id_fields = ["sms_account"]
    actions = ["refresh_tokens", "refresh_pipelines"]

    @admin.display(description="Status", ordering="status")
    def status_col(self, obj):
        return badge(obj.get_status_display(), STATUS_TONE.get(obj.status, "muted"))

    @admin.display(description="Widget", boolean=True)
    def widget(self, obj):
        return bool(obj.widget_client_id or obj.client_id)

    @admin.display(description="Open")
    def host_link(self, obj):
        return link(f"https://{obj.host}", f"{obj.host} ↗") if obj.host else "—"

    @admin.display(description="Client secret")
    def client_secret_masked(self, obj):
        return masked(obj.client_secret)

    @admin.display(description="Widget secret")
    def widget_client_secret_masked(self, obj):
        return masked(obj.widget_client_secret)

    @admin.action(description="Refresh API tokens now")
    def refresh_tokens(self, request, queryset):
        from . import oauth

        ok = failed = 0
        for conn in queryset.exclude(status=AmoConnection.Status.DISCONNECTED):
            try:
                oauth.refresh(conn.pk, force=True)
                ok += 1
            except Exception as e:  # noqa: BLE001 - reported to the operator
                failed += 1
                self.message_user(request, f"{conn.host}: {e}", messages.ERROR)
        self.message_user(
            request, f"Refreshed {ok}, failed {failed}.", messages.SUCCESS if not failed else messages.WARNING
        )

    @admin.action(description="Reload pipelines from amoCRM")
    def refresh_pipelines(self, request, queryset):
        from . import services

        for conn in queryset.filter(status=AmoConnection.Status.ACTIVE):
            try:
                services.sync_pipelines(conn)
            except Exception as e:  # noqa: BLE001
                self.message_user(request, f"{conn.host}: {e}", messages.ERROR)
        self.message_user(request, "Pipelines reloaded.", messages.SUCCESS)


RESULT_TONE = {"error": "bad", "skipped": "muted"}


@admin.register(AmoAutomationJob)
class AmoAutomationJobAdmin(ReadOnlyAdmin):
    """Digital Pipeline actions: what fired, when it ran and what happened."""

    list_display = ["created_at", "conn", "lead", "action", "delay_minutes", "run_at", "state", "result"]
    list_filter = ["action", "conn__company", "done_at"]
    search_fields = ["lead_id", "conn__host", "result"]
    date_hierarchy = "created_at"
    list_select_related = ["conn"]

    @admin.display(description="Lead")
    def lead(self, obj):
        return link(f"https://{obj.conn.host}/leads/detail/{obj.lead_id}", f"#{obj.lead_id}")

    @admin.display(description="State")
    def state(self, obj):
        if obj.done_at is None:
            return badge("waiting", "warn")
        first = (obj.result or "").split(":")[0]
        return badge("done" if first not in RESULT_TONE else first, RESULT_TONE.get(first, "ok"))


@admin.register(AmoInstall)
class AmoInstallAdmin(ReadOnlyAdmin):
    """Connect-button attempts in flight (amoCRM sends the new integration's keys here)."""

    list_display = ["company", "user", "client_id", "created_at"]
    search_fields = ["company__slug", "client_id"]
    exclude = ["client_secret", "nonce"]
