from django.contrib import admin

from .models import FiscalDefaults, Invoice, ProviderAccount, ProviderTransaction


class TransactionInline(admin.TabularInline):
    model = ProviderTransaction
    extra = 0
    can_delete = False
    fields = [
        "provider",
        "provider_txn_id",
        "amount_tiyin",
        "state",
        "reason",
        "created_at",
        "performed_at",
        "cancelled_at",
    ]
    readonly_fields = fields


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ["__str__", "amount_tiyin", "status", "paid_via", "source", "external_id", "created_at"]
    list_filter = ["status", "paid_via", "source"]
    search_fields = ["company__slug", "external_id", "description", "public_id"]
    readonly_fields = ["public_id", "paid_at", "crm_synced_at"]
    inlines = [TransactionInline]


@admin.register(ProviderAccount)
class ProviderAccountAdmin(admin.ModelAdmin):
    list_display = ["company", "provider", "is_enabled", "test_mode", "public_id"]
    list_filter = ["provider", "is_enabled", "test_mode"]
    # Secrets are never shown here; merchants manage them in the dashboard.
    exclude = ["secret", "test_secret"]
    readonly_fields = ["public_id"]


@admin.register(ProviderTransaction)
class ProviderTransactionAdmin(admin.ModelAdmin):
    list_display = ["invoice", "provider", "provider_txn_id", "state", "reason", "created_at"]
    list_filter = ["provider", "state"]
    search_fields = ["provider_txn_id"]


admin.site.register(FiscalDefaults)
