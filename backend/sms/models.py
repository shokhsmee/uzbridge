import uuid

from django.db import models

from accounts.models import Company
from core.crypto import EncryptedTextField


class SmsProvider(models.TextChoices):
    ESKIZ = "eskiz", "Eskiz"
    PLAYMOBILE = "playmobile", "Playmobile"


class SmsAccount(models.Model):
    """One SMS gateway account of a company (it may have several, even of one gateway).

    Eskiz: login = cabinet email, secret = password, sender = nick ("4546" by default).
    Playmobile: login/secret = broker API credentials, sender = originator.
    """

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="sms_accounts")
    provider = models.CharField(max_length=12, choices=SmsProvider.choices)
    # Delivery reports come to /cb/sms/<provider>/<public_id>/...
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    label = models.CharField(max_length=80, blank=True)
    # Off until its login is entered and it is switched on.
    is_enabled = models.BooleanField(default=False)
    login = models.CharField(max_length=150, blank=True)
    secret = EncryptedTextField(blank=True)
    sender = models.CharField(max_length=11, blank=True)
    # Eskiz bearer token, valid 30 days.
    token = EncryptedTextField(blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    balance = models.CharField(max_length=32, blank=True)
    checked_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        verbose_name = "SMS account"
        verbose_name_plural = "SMS accounts"
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.company.slug}:{self.provider}" + (f":{self.label}" if self.label else "")

    @property
    def display_name(self) -> str:
        return f"{self.get_provider_display()} · {self.label}" if self.label else self.get_provider_display()

    @property
    def is_configured(self) -> bool:
        return bool(self.login and self.secret and (self.sender or self.provider == SmsProvider.ESKIZ))


class SmsTemplate(models.Model):
    """A message text the company may send.

    Eskiz only delivers texts that match a template it has approved, so for
    Eskiz these rows are synced from the account and only approved ones are
    usable. Playmobile has no moderation list; its templates are ours.
    Placeholders {company} {amount} {number} {link} {name} are filled in.
    """

    APPROVED = ("service", "reklama", "local")

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="sms_templates")
    # Each gateway account has its own moderated texts.
    account = models.ForeignKey(SmsAccount, null=True, blank=True, on_delete=models.CASCADE, related_name="templates")
    provider = models.CharField(max_length=12, choices=SmsProvider.choices)
    external_id = models.CharField(max_length=32, blank=True)  # Eskiz template id
    text = models.TextField()
    # Eskiz: moderation | inproccess | service | reklama | rejected; ours: local.
    status = models.CharField(max_length=16, default="local")
    # Enum id of this template in the amoCRM "uzbridge: SMS" lead field.
    amo_enum_id = models.BigIntegerField(null=True, blank=True)
    # Off: kept out of amoCRM (the lead field and the widget's list).
    use_in_amocrm = models.BooleanField(default=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "SMS template"
        verbose_name_plural = "SMS templates"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["account", "external_id"],
                condition=~models.Q(external_id=""),
                name="uniq_sms_template_external",
            )
        ]

    @property
    def is_approved(self) -> bool:
        return self.status in self.APPROVED

    @property
    def title(self) -> str:
        return self.text if len(self.text) <= 60 else self.text[:57] + "…"


BUILTIN_VARIABLES = ("name", "company", "amount", "number", "link")
VARIABLE_KEY_RE = r"^[a-z][a-z0-9_]{0,29}$"


class SmsVariable(models.Model):
    """A company's own {keyword} for SMS texts, filled from a field of the integration.

    amoCRM sources: lead.name | lead.price | lead.id | lead.responsible |
    lead.cf.<field_id> | contact.name | contact.cf.<field_id>  (set in amoCRM,
    Настройки → uzbridge). Odoo sources: a field path on the record the SMS is
    written from, e.g. partner_id.name or invoice_date_due (set on the website).
    """

    class Integration(models.TextChoices):
        AMOCRM = "amocrm", "amoCRM"
        ODOO = "odoo", "Odoo"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="sms_variables")
    integration = models.CharField(max_length=10, choices=Integration.choices)
    key = models.CharField(max_length=30)
    source = models.CharField(max_length=120)
    label = models.CharField(max_length=80, blank=True)  # shown next to the source in lists

    class Meta:
        verbose_name = "SMS keyword"
        verbose_name_plural = "SMS keywords"
        ordering = ["key"]
        constraints = [models.UniqueConstraint(fields=["company", "integration", "key"], name="uniq_sms_variable_key")]


class SmsSettings(models.Model):
    """Which gateway to use and which automatic messages to send."""

    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name="sms_settings")
    provider = models.CharField(max_length=12, choices=SmsProvider.choices, blank=True)  # legacy, before `account`
    # The account used when an integration hasn't picked one.
    account = models.ForeignKey(SmsAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    link_template = models.ForeignKey(SmsTemplate, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    paid_template = models.ForeignKey(SmsTemplate, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = "SMS settings"
        verbose_name_plural = "SMS settings"


class SmsMessage(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENT = "sent", "Sent"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"

    class Event(models.TextChoices):
        MANUAL = "manual", "Manual"
        LINK = "link", "Payment link"
        AMOCRM = "amocrm", "From amoCRM"
        API = "api", "API / Odoo"
        PAID = "paid", "Payment received"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="sms_messages")
    account = models.ForeignKey(SmsAccount, on_delete=models.PROTECT, related_name="messages")
    provider = models.CharField(max_length=12, choices=SmsProvider.choices)
    phone = models.CharField(max_length=12)
    text = models.TextField()
    event = models.CharField(max_length=10, choices=Event.choices, default=Event.MANUAL)
    invoice = models.ForeignKey(
        "payments.Invoice", null=True, blank=True, on_delete=models.SET_NULL, related_name="sms"
    )
    template = models.ForeignKey(SmsTemplate, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    lead_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    # The caller's id for the message (Odoo sms uuid), echoed in sms.status webhooks.
    external_ref = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED, db_index=True)
    # Eskiz request UUID, or the message-id we generated for Playmobile.
    provider_id = models.CharField(max_length=64, blank=True, db_index=True)
    provider_status = models.CharField(max_length=32, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "SMS message"
        verbose_name_plural = "SMS messages"
        ordering = ["-created_at"]
