from decimal import Decimal

from django import forms
from django.contrib import admin

from core.admin_utils import badge, soum

from . import services
from .models import CompanyTariff, LedgerEntry, TariffPrice

KIND_TONE = {"topup": "ok", "credit": "ok", "charge": "accent", "prorata": "accent", "adjust": "warn"}


class SoumPriceForm(forms.ModelForm):
    """Prices are typed in soʻm; they are stored in tiyin."""

    first_soum = forms.DecimalField(label="First account, soʻm / 30 days", min_value=0, decimal_places=2)
    extra_soum = forms.DecimalField(label="Each extra account, soʻm / 30 days", min_value=0, decimal_places=2)

    class Meta:
        fields = ["kind"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["first_soum"].initial = Decimal(self.instance.first_tiyin) / 100
            self.fields["extra_soum"].initial = Decimal(self.instance.extra_tiyin) / 100

    def save(self, commit=True):
        self.instance.first_tiyin = int(self.cleaned_data["first_soum"] * 100)
        self.instance.extra_tiyin = int(self.cleaned_data["extra_soum"] * 100)
        return super().save(commit)


class TariffPriceForm(SoumPriceForm):
    class Meta(SoumPriceForm.Meta):
        model = TariffPrice


class CompanyTariffForm(SoumPriceForm):
    class Meta(SoumPriceForm.Meta):
        model = CompanyTariff
        fields = ["company", "kind", "note"]


@admin.register(TariffPrice)
class TariffPriceAdmin(admin.ModelAdmin):
    """The price list every company pays unless it has a special price."""

    form = TariffPriceForm
    list_display = ["kind", "first", "extra", "example", "updated_at"]
    fields = ["kind", "first_soum", "extra_soum"]

    @admin.display(description="First")
    def first(self, obj):
        return soum(obj.first_tiyin)

    @admin.display(description="Each extra")
    def extra(self, obj):
        return soum(obj.extra_tiyin)

    @admin.display(description="3 accounts cost")
    def example(self, obj):
        return soum(obj.first_tiyin + 2 * obj.extra_tiyin)

    def has_delete_permission(self, request, obj=None):
        return False  # a missing row would fall back to the built-in defaults silently


class CompanyTariffInline(admin.TabularInline):
    model = CompanyTariff
    form = CompanyTariffForm
    extra = 0
    fields = ["kind", "first_soum", "extra_soum", "note"]
    verbose_name_plural = "special prices (instead of the price list)"


@admin.register(CompanyTariff)
class CompanyTariffAdmin(admin.ModelAdmin):
    form = CompanyTariffForm
    list_display = ["company", "kind", "first", "extra", "note", "updated_at"]
    list_filter = ["kind"]
    search_fields = ["company__slug", "company__name", "note"]
    autocomplete_fields = ["company"]
    fields = ["company", "kind", "first_soum", "extra_soum", "note"]

    @admin.display(description="First")
    def first(self, obj):
        return soum(obj.first_tiyin)

    @admin.display(description="Each extra")
    def extra(self, obj):
        return soum(obj.extra_tiyin)


class LedgerInline(admin.TabularInline):
    """The latest balance changes on the company page."""

    model = LedgerEntry
    extra = 0
    can_delete = False
    max_num = 0
    fields = ["created_at", "kind", "amount", "balance", "description"]
    readonly_fields = fields
    ordering = ["-created_at", "-id"]
    verbose_name_plural = "balance history (latest first)"

    @admin.display(description="Amount")
    def amount(self, obj):
        return soum(obj.amount_tiyin)

    @admin.display(description="Balance after")
    def balance(self, obj):
        return soum(obj.balance_after)


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    """Manual credits (bank transfer, cash) go through here; balance_after is computed."""

    list_display = ["created_at", "company", "kind_col", "amount", "balance", "description"]
    list_filter = ["kind", "company", "created_at"]
    date_hierarchy = "created_at"
    list_select_related = ["company"]
    search_fields = ["company__slug", "company__name", "description"]
    fields = ["company", "kind", "amount_tiyin", "description"]
    autocomplete_fields = ["company"]

    @admin.display(description="Kind", ordering="kind")
    def kind_col(self, obj):
        return badge(obj.get_kind_display(), KIND_TONE.get(obj.kind, "muted"))

    @admin.display(description="Amount", ordering="amount_tiyin")
    def amount(self, obj):
        return soum(obj.amount_tiyin)

    @admin.display(description="Balance after")
    def balance(self, obj):
        return soum(obj.balance_after)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "amount_tiyin" in form.base_fields:
            form.base_fields["amount_tiyin"].help_text = (
                "In tiyin: 1 soʻm = 100 tiyin (500 000 soʻm → 50000000). Negative to take off. "
                "Easier: Companies → select → “Top up balance”."
            )
        return form

    def get_readonly_fields(self, request, obj=None):
        return ["company", "kind", "amount_tiyin", "description"] if obj else []

    def save_model(self, request, obj, form, change):
        if change:
            return
        entry = services.credit(obj.company, obj.amount_tiyin, obj.kind, obj.description or f"by {request.user.email}")
        obj.pk = entry.pk

    def has_delete_permission(self, request, obj=None):
        return False
