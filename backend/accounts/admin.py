from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.sessions.models import Session
from django.db.models import Count, Q
from django.template.response import TemplateResponse
from django.utils import timezone

from core.admin_utils import ReadOnlyAdmin, ReadOnlyInline, badge, link, soum

from .models import Company, HandoffToken, Membership, User, UserSession


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ["user"]
    fields = ["user", "role", "created_at"]
    readonly_fields = ["created_at"]


class CompanyMembershipInline(MembershipInline):
    pass


class UserMembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ["company"]
    fields = ["company", "role", "created_at"]
    readonly_fields = ["created_at"]


class SessionInline(ReadOnlyInline):
    model = UserSession
    fields = ["company", "ip", "user_agent", "created_at", "last_seen"]
    readonly_fields = fields
    verbose_name_plural = "signed-in devices"


class PaymentStatusFilter(admin.SimpleListFilter):
    """How the company stands with its tariff right now."""

    title = "payment status"
    parameter_name = "pay"

    def lookups(self, request, model_admin):
        return [
            ("active", "Paid, period running"),
            ("grace", "Unpaid, in grace days"),
            ("paused", "Paused (unpaid)"),
            ("blocked", "Blocked by us"),
            ("exempt", "Test / tariff-free"),
            ("none", "Nothing switched on"),
        ]

    def queryset(self, request, qs):
        now = timezone.now()
        v = self.value()
        if v == "blocked":
            return qs.filter(is_active=False)
        live = qs.filter(is_active=True, is_platform=False)
        if v == "exempt":
            return live.filter(billing_exempt=True)
        live = live.filter(billing_exempt=False)
        if v == "paused":
            return live.exclude(paused_at=None)
        if v == "grace":
            return live.filter(paused_at=None).exclude(overdue_since=None)
        if v == "active":
            return live.filter(paused_at=None, overdue_since=None, period_end__gt=now)
        if v == "none":
            return live.filter(paused_at=None, overdue_since=None).filter(Q(period_end=None) | Q(period_end__lte=now))
        return qs


class TopUpForm(forms.Form):
    amount = forms.DecimalField(
        label="Amount, soʻm",
        decimal_places=2,
        help_text="Negative to take money off.",
        widget=forms.NumberInput(attrs={"class": "form-control", "placeholder": "500000", "step": "0.01"}),
    )
    note = forms.CharField(
        label="Note",
        max_length=200,
        required=False,
        help_text="e.g. bank transfer #123, 24.09",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )


class BlockForm(forms.Form):
    reason = forms.CharField(
        label="Reason",
        max_length=255,
        help_text="Kept on the company; the team sees it here.",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )


STATE_TONE = {
    "active": "ok",
    "grace": "warn",
    "paused": "bad",
    "inactive": "muted",
    "platform": "accent",
    "exempt": "accent",
    "blocked": "bad",
}


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "slug",
        "entity_type",
        "balance",
        "tariff",
        "paid_until",
        "monthly_fee",
        "billing_exempt",
        "members",
        "is_active",
        "created_at",
    ]
    list_display_links = ["name", "slug"]
    search_fields = ["name", "slug", "tin", "legal_name", "pinfl", "contact_phone"]
    list_filter = [PaymentStatusFilter, "is_active", "billing_exempt", "is_platform", "entity_type", "single_session"]
    list_editable = ["billing_exempt", "is_active"]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]
    inlines = [CompanyMembershipInline]
    readonly_fields = [
        "created_at",
        "dashboard",
        "balance",
        "tariff",
        "period_start",
        "period_end",
        "paid_payment_units",
        "paid_sms_units",
        "overdue_since",
        "paused_at",
        "profile_status",
        "paid_until",
        "monthly_fee",
    ]
    fieldsets = (
        (None, {"fields": ("name", "slug", "dashboard", "created_at")}),
        (
            "Legal profile (Kabinet)",
            {
                "fields": (
                    "profile_status",
                    "entity_type",
                    "legal_name",
                    ("tin", "pinfl"),
                    "legal_address",
                    ("director", "contact_phone"),
                    ("bank_name", "bank_mfo"),
                    ("bank_account", "oked"),
                )
            },
        ),
        (
            "Tariff and balance",
            {
                "fields": (
                    ("balance", "tariff"),
                    ("monthly_fee", "paid_until"),
                    ("billing_exempt", "is_platform"),
                    ("period_start", "period_end"),
                    ("paid_payment_units", "paid_sms_units"),
                    ("overdue_since", "paused_at"),
                ),
                "description": "Top up: select the company in the list → “Top up balance”. "
                "Special prices are below the form.",
            },
        ),
        ("Access", {"fields": (("is_active", "blocked_reason"), "single_session")}),
    )
    actions = ["top_up", "block", "unblock", "make_exempt", "make_billable", "resume"]

    def get_inlines(self, request, obj):
        from billing.admin import CompanyTariffInline, LedgerInline

        return [CompanyMembershipInline, CompanyTariffInline, LedgerInline] if obj else [CompanyMembershipInline]

    @admin.display(description="Paid until", ordering="period_end")
    def paid_until(self, obj):
        if obj.is_platform or obj.billing_exempt:
            return "—"
        if not obj.period_end:
            return badge("never", "muted")
        tone = "ok" if obj.period_end > timezone.now() else "bad"
        return badge(timezone.localtime(obj.period_end).strftime("%d.%m.%Y"), tone)

    @admin.display(description="Monthly fee")
    def monthly_fee(self, obj):
        from billing.services import active_units, is_billable
        from billing.services import monthly_fee as fee

        return soum(fee(active_units(obj), obj)) if is_billable(obj) else "—"

    def _action_form(self, request, queryset, form, *, action, title, button, intro="", button_class="primary"):
        companies = list(queryset)
        for c in companies:
            c.balance_label = soum(c.balance_tiyin)
        return TemplateResponse(
            request,
            "admin/uzbridge_action_form.html",
            {
                **self.admin_site.each_context(request),
                "title": title,
                "intro": intro,
                "form": form,
                "queryset": queryset,
                "companies": companies,
                "action": action,
                "button": button,
                "button_class": button_class,
                "opts": self.model._meta,
            },
        )

    @admin.action(description="Top up balance (bank transfer, cash, bonus)")
    def top_up(self, request, queryset):
        from billing import services
        from billing.models import LedgerEntry

        form = TopUpForm(request.POST if "apply" in request.POST else None)
        if "apply" in request.POST and form.is_valid():
            amount = int(Decimal(form.cleaned_data["amount"]) * 100)
            note = form.cleaned_data["note"] or f"by {request.user.email}"
            kind = LedgerEntry.Kind.CREDIT if amount >= 0 else LedgerEntry.Kind.ADJUST
            for c in queryset:
                services.credit(c, amount, kind, note)
            self.message_user(request, f"{soum(amount)} added to {queryset.count()} company(ies).", messages.SUCCESS)
            return None
        return self._action_form(
            request,
            queryset,
            form,
            action="top_up",
            title="Top up balance",
            button="Add to balance",
            intro="Each selected company gets this amount; a paused one resumes at once if it now covers its tariff.",
        )

    @admin.action(description="Block (dashboard, links and SMS stop)")
    def block(self, request, queryset):
        form = BlockForm(request.POST if "apply" in request.POST else None)
        if "apply" in request.POST and form.is_valid():
            n = queryset.exclude(is_platform=True).update(is_active=False, blocked_reason=form.cleaned_data["reason"])
            from .models import UserSession

            rows = UserSession.objects.filter(company__in=queryset)
            Session.objects.filter(session_key__in=rows.values_list("session_key", flat=True)).delete()
            rows.delete()
            self.message_user(request, f"Blocked {n} company(ies); their users were signed out.", messages.WARNING)
            return None
        return self._action_form(
            request,
            queryset,
            form,
            action="block",
            title="Block companies",
            button="Block",
            button_class="danger",
            intro="The dashboard closes, new payment links and SMS stop, the amoCRM widget and API keys stop working. "
            "Payments already in progress still complete.",
        )

    @admin.action(description="Unblock")
    def unblock(self, request, queryset):
        n = queryset.update(is_active=True, blocked_reason="")
        self.message_user(request, f"Unblocked {n} company(ies).", messages.SUCCESS)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(member_count=Count("memberships", distinct=True))

    @admin.display(description="Balance", ordering="balance_tiyin")
    def balance(self, obj):
        return soum(obj.balance_tiyin)

    @admin.display(description="Tariff")
    def tariff(self, obj):
        from billing.services import summary

        state = summary(obj)["state"]
        return badge(state, STATE_TONE.get(state, "muted"))

    @admin.display(description="Members", ordering="member_count")
    def members(self, obj):
        return obj.member_count

    @admin.display(description="Dashboard")
    def dashboard(self, obj):
        from core.tenancy import company_url

        return link(company_url(obj, "/"), "open ↗") if obj.pk else "—"

    @admin.display(description="Profile")
    def profile_status(self, obj):
        missing = obj.missing_profile_fields()
        return badge("complete", "ok") if not missing else badge("missing: " + ", ".join(missing), "warn")

    @admin.action(description="Mark as test account (tariff-free)")
    def make_exempt(self, request, queryset):
        n = queryset.update(billing_exempt=True)
        self.message_user(request, f"{n} company(ies) are tariff-free now.", messages.SUCCESS)

    @admin.action(description="Back to the normal tariff")
    def make_billable(self, request, queryset):
        n = queryset.update(billing_exempt=False)
        self.message_user(request, f"{n} company(ies) are billed again.", messages.SUCCESS)

    @admin.action(description="Resume a paused subscription (clear pause and grace)")
    def resume(self, request, queryset):
        n = queryset.update(paused_at=None, overdue_since=None)
        self.message_user(request, f"{n} company(ies) resumed.", messages.SUCCESS)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["email"]
    list_display = ["email", "full_name", "companies", "language", "is_staff", "is_active", "last_login", "date_joined"]
    list_filter = ["is_staff", "is_superuser", "is_active", "language"]
    search_fields = ["email", "full_name", "memberships__company__slug"]
    inlines = [UserMembershipInline, SessionInline]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("full_name", "language")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    readonly_fields = ["last_login", "date_joined"]
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)
    actions = ["end_sessions"]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("memberships__company")

    @admin.display(description="Companies")
    def companies(self, obj):
        return ", ".join(f"{m.company.slug} ({m.role})" for m in obj.memberships.all()) or "—"

    @admin.action(description="Sign out everywhere (end all sessions)")
    def end_sessions(self, request, queryset):
        rows = UserSession.objects.filter(user__in=queryset)
        Session.objects.filter(session_key__in=rows.values_list("session_key", flat=True)).delete()
        n = rows.count()
        rows.delete()
        self.message_user(request, f"Ended {n} session(s).", messages.SUCCESS)


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ["user", "company", "role", "created_at"]
    list_filter = ["role"]
    search_fields = ["user__email", "company__slug", "company__name"]
    autocomplete_fields = ["user", "company"]
    list_editable = ["role"]


@admin.register(UserSession)
class UserSessionAdmin(ReadOnlyAdmin):
    """Signed-in devices; deleting a row signs that device out."""

    list_display = ["user", "company", "ip", "device", "created_at", "last_seen"]
    list_filter = ["company"]
    search_fields = ["user__email", "company__slug", "ip"]
    date_hierarchy = "last_seen"
    actions = ["sign_out"]

    @admin.display(description="Device")
    def device(self, obj):
        return (obj.user_agent or "")[:60]

    @admin.action(description="Sign these devices out")
    def sign_out(self, request, queryset):
        Session.objects.filter(session_key__in=queryset.values_list("session_key", flat=True)).delete()
        n = queryset.count()
        queryset.delete()
        self.message_user(request, f"Signed out {n} device(s).", messages.SUCCESS)

    def delete_model(self, request, obj):
        Session.objects.filter(session_key=obj.session_key).delete()
        super().delete_model(request, obj)


@admin.register(HandoffToken)
class HandoffTokenAdmin(ReadOnlyAdmin):
    list_display = ["user", "company", "expires_at", "used_at"]
    search_fields = ["user__email", "company__slug"]
    exclude = ["token"]
