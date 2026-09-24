import uuid

from django.db import models
from django.db.models import Max

from accounts.models import Company
from core.crypto import EncryptedTextField


class Provider(models.TextChoices):
    PAYME = "payme", "Payme"
    CLICK = "click", "Click"
    UZUM = "uzum", "Uzum Bank"


class ProviderAccount(models.Model):
    """One merchant account of a company (it may have several per provider).

    `public_id` goes into the callback URL we give the provider, so the
    callback finds its merchant without trusting anything in the payload;
    that URL is also what keeps two Payme cash desks of one company apart.
    """

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="provider_accounts")
    provider = models.CharField(max_length=10, choices=Provider.choices)
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    label = models.CharField(max_length=80, blank=True)  # e.g. "Chilonzor filiali"
    # Off until its keys are entered and it is switched on.
    is_enabled = models.BooleanField(default=False)
    test_mode = models.BooleanField(default=True)

    # Payme: merchant_id (cash desk id). Click: merchant_id. Uzum: terminal_id.
    merchant_id = models.CharField(max_length=64, blank=True)
    # Click: service_id and merchant_user_id (Merchant API user).
    service_id = models.CharField(max_length=32, blank=True)
    merchant_user_id = models.CharField(max_length=32, blank=True)
    # Payme: prod key. Click: SECRET_KEY. Uzum: X-API-Key.
    secret = EncryptedTextField(blank=True)
    # Payme sandbox key (TEST_KEY).
    test_secret = EncryptedTextField(blank=True)
    # Payme: account field name configured on the cash desk ("order_id" by default).
    account_field = models.CharField(max_length=32, blank=True, default="order_id")
    # Uzum: the terminal has auto-fiscalization switched on.
    auto_fiscal = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "payment account"
        verbose_name_plural = "payment accounts"
        ordering = ["provider", "created_at", "pk"]

    def __str__(self):
        return f"{self.company.slug}:{self.provider}" + (f":{self.label}" if self.label else "")

    @property
    def display_name(self) -> str:
        return f"{self.get_provider_display()} · {self.label}" if self.label else self.get_provider_display()

    @property
    def active_secret(self) -> str:
        if self.provider == Provider.PAYME and self.test_mode:
            return self.test_secret
        return self.secret

    @property
    def is_configured(self) -> bool:
        required = {
            Provider.PAYME: [self.merchant_id, self.active_secret],
            Provider.CLICK: [self.merchant_id, self.service_id, self.secret],
            Provider.UZUM: [self.merchant_id, self.secret],
        }[self.provider]
        return all(required)


class FiscalDefaults(models.Model):
    """Receipt line defaults for invoices that come without product lines."""

    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name="fiscal_defaults")
    ikpu_code = models.CharField("MXIK / IKPU", max_length=17, blank=True)
    package_code = models.CharField(max_length=20, blank=True)
    vat_percent = models.PositiveSmallIntegerField(default=12)
    units = models.CharField(max_length=20, blank=True)

    class Meta:
        verbose_name = "fiscal defaults"
        verbose_name_plural = "fiscal defaults"


class Invoice(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        CANCELLED = "cancelled", "Cancelled"
        REFUNDED = "refunded", "Refunded"

    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        AMOCRM = "amocrm", "amoCRM"
        ODOO = "odoo", "Odoo"
        API = "api", "API"
        TOPUP = "topup", "Balance top-up"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="invoices")
    number = models.PositiveIntegerField()
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    external_id = models.CharField(max_length=64, blank=True, db_index=True)
    external_name = models.CharField(max_length=255, blank=True)
    amount_tiyin = models.PositiveBigIntegerField()
    currency = models.PositiveSmallIntegerField(default=860)
    description = models.CharField(max_length=255, blank=True)
    # Customer's mobile (998XXXXXXXXX) for SMS; from amoCRM's contact or typed in.
    customer_phone = models.CharField(max_length=12, blank=True)
    # Where the pay page sends the customer back to (e.g. the Odoo payment status page).
    return_url = models.URLField(max_length=500, blank=True)
    # [{title, price_tiyin, count, ikpu_code, package_code, vat_percent, units}]
    items = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    paid_via = models.CharField(max_length=10, choices=Provider.choices, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    crm_synced_at = models.DateTimeField(null=True, blank=True)
    crm_sync_error = models.TextField(blank=True)
    # The matching invoice in amoCRM's "Счета/покупки" catalog, if we made one.
    amo_bill_id = models.BigIntegerField(null=True, blank=True)
    # Where it came from, which decides the merchant accounts that may take it.
    amo_connection = models.ForeignKey(
        "amocrm.AmoConnection", null=True, blank=True, on_delete=models.SET_NULL, related_name="invoices"
    )
    api_key = models.ForeignKey("developer.ApiKey", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_by_label = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["company", "number"], name="uniq_invoice_number")]

    def __str__(self):
        return f"{self.company.slug} #{self.display_number}"

    @property
    def display_number(self) -> str:
        return f"INV-{self.number:05d}"

    @property
    def amount_soum(self) -> str:
        return f"{self.amount_tiyin // 100}.{self.amount_tiyin % 100:02d}"

    @classmethod
    def next_number(cls, company: Company) -> int:
        # Callers hold a lock on the company row, see payments.services.create_invoice.
        return (cls.objects.filter(company=company).aggregate(m=Max("number"))["m"] or 0) + 1


class ProviderTransaction(models.Model):
    """One provider-side transaction attempt for an invoice.

    `state` uses Payme's numbers for every provider so the dashboard reads
    one scale: 1 created, 2 performed, -1 cancelled before, -2 after.
    """

    CREATED, PERFORMED, CANCELLED, CANCELLED_AFTER = 1, 2, -1, -2

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="transactions")
    account = models.ForeignKey(ProviderAccount, on_delete=models.PROTECT, related_name="transactions")
    provider = models.CharField(max_length=10, choices=Provider.choices)
    provider_txn_id = models.CharField(max_length=64)
    amount_tiyin = models.PositiveBigIntegerField()
    state = models.SmallIntegerField(default=CREATED)
    reason = models.SmallIntegerField(null=True, blank=True)
    provider_time = models.BigIntegerField(null=True, blank=True)  # Payme "time", ms
    created_at = models.DateTimeField(auto_now_add=True)
    performed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    fiscal = models.JSONField(default=dict, blank=True)  # receipt ids / urls from the provider
    meta = models.JSONField(default=dict, blank=True)  # provider extras (Click paydoc id, Uzum redirect url)
    raw = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "provider transaction"
        verbose_name_plural = "provider transactions"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["provider", "account", "provider_txn_id"], name="uniq_provider_txn")
        ]

    def log(self, event: str, payload) -> None:
        self.raw = [*self.raw, {"event": event, "payload": payload}][-20:]
