from django.contrib import admin

from core.admin_utils import ReadOnlyAdmin, ReadOnlyInline, badge, link, masked, soum
from core.tenancy import pay_url, platform_url

from .models import FiscalDefaults, Invoice, ProviderAccount, ProviderTransaction

STATUS_TONE = {"pending": "warn", "paid": "ok", "cancelled": "muted", "refunded": "bad"}
CALLBACK = {"payme": "cb/payme", "click": "cb/click", "uzum": "cb/uzum"}


class TransactionInline(ReadOnlyInline):
    model = ProviderTransaction
    fields = [
        "provider",
        "account",
        "provider_txn_id",
        "amount",
        "state",
        "reason",
        "created_at",
        "performed_at",
        "cancelled_at",
    ]
    readonly_fields = fields

    @admin.display(description="Amount")
    def amount(self, obj):
        return soum(obj.amount_tiyin)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = [
        "number_col",
        "company",
        "amount",
        "status_col",
        "paid_via",
        "source",
        "origin",
        "external_name",
        "created_at",
    ]
    list_filter = ["status", "paid_via", "source", "company", "created_at"]
    search_fields = ["company__slug", "external_id", "external_name", "description", "public_id", "customer_phone"]
    date_hierarchy = "created_at"
    list_select_related = ["company", "amo_connection", "api_key"]
    readonly_fields = [
        "public_id",
        "number",
        "pay_page",
        "amount",
        "status",
        "paid_via",
        "paid_at",
        "crm_synced_at",
        "crm_sync_error",
        "amo_bill_id",
        "created_at",
    ]
    fieldsets = (
        (
            None,
            {"fields": ("company", ("number", "public_id"), "pay_page", ("amount", "status"), ("paid_via", "paid_at"))},
        ),
        (
            "Where it came from",
            {
                "fields": (
                    "source",
                    "external_id",
                    "external_name",
                    "amo_connection",
                    "api_key",
                    "created_by_label",
                    "created_at",
                )
            },
        ),
        ("Customer and receipt", {"fields": ("description", "customer_phone", "return_url", "items")}),
        ("CRM sync", {"fields": ("crm_synced_at", "crm_sync_error", "amo_bill_id")}),
    )
    raw_id_fields = ["amo_connection", "api_key"]
    inlines = [TransactionInline]

    def has_add_permission(self, request):
        return False  # invoices are created from the dashboard, amoCRM, Odoo or the API

    @admin.display(description="Invoice", ordering="number")
    def number_col(self, obj):
        return obj.display_number

    @admin.display(description="Amount", ordering="amount_tiyin")
    def amount(self, obj):
        return soum(obj.amount_tiyin)

    @admin.display(description="Status", ordering="status")
    def status_col(self, obj):
        return badge(obj.get_status_display(), STATUS_TONE.get(obj.status, "muted"))

    @admin.display(description="Connection")
    def origin(self, obj):
        if obj.amo_connection_id:
            return obj.amo_connection.host
        if obj.api_key_id:
            return obj.api_key.name
        return "—"

    @admin.display(description="Pay page")
    def pay_page(self, obj):
        return link(pay_url(obj)) if obj.pk else "—"


@admin.register(ProviderAccount)
class ProviderAccountAdmin(admin.ModelAdmin):
    list_display = [
        "company",
        "provider",
        "label",
        "merchant_id",
        "enabled_col",
        "test_mode",
        "configured",
        "created_at",
    ]
    list_filter = ["provider", "is_enabled", "test_mode", "company"]
    search_fields = ["company__slug", "label", "merchant_id", "service_id", "public_id"]
    list_select_related = ["company"]
    # Secrets are never shown or edited here; merchants manage them in the dashboard.
    exclude = ["secret", "test_secret"]
    readonly_fields = ["public_id", "callback_url", "secret_masked", "test_secret_masked", "created_at", "updated_at"]
    fieldsets = (
        (None, {"fields": ("company", "provider", "label", ("is_enabled", "test_mode"), "callback_url", "public_id")}),
        ("Merchant", {"fields": (("merchant_id", "service_id"), ("merchant_user_id", "account_field"), "auto_fiscal")}),
        ("Keys (masked)", {"fields": (("secret_masked", "test_secret_masked"),)}),
        ("Dates", {"fields": (("created_at", "updated_at"),)}),
    )

    @admin.display(description="On", boolean=True, ordering="is_enabled")
    def enabled_col(self, obj):
        return obj.is_enabled

    @admin.display(description="Keys", boolean=True)
    def configured(self, obj):
        return obj.is_configured

    @admin.display(description="Callback URL")
    def callback_url(self, obj):
        return platform_url("api", f"/{CALLBACK[obj.provider]}/{obj.public_id}/") if obj.pk else "—"

    @admin.display(description="Key / Secret")
    def secret_masked(self, obj):
        return masked(obj.secret)

    @admin.display(description="TEST_KEY")
    def test_secret_masked(self, obj):
        return masked(obj.test_secret)


@admin.register(ProviderTransaction)
class ProviderTransactionAdmin(ReadOnlyAdmin):
    list_display = [
        "invoice",
        "provider",
        "account",
        "provider_txn_id",
        "amount",
        "state",
        "reason",
        "created_at",
        "performed_at",
    ]
    list_filter = ["provider", "state"]
    search_fields = ["provider_txn_id", "invoice__company__slug"]
    date_hierarchy = "created_at"
    list_select_related = ["invoice__company", "account__company"]

    @admin.display(description="Amount", ordering="amount_tiyin")
    def amount(self, obj):
        return soum(obj.amount_tiyin)


@admin.register(FiscalDefaults)
class FiscalDefaultsAdmin(admin.ModelAdmin):
    list_display = ["company", "ikpu_code", "package_code", "vat_percent", "units"]
    search_fields = ["company__slug", "ikpu_code"]
