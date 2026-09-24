import secrets

from django.conf import settings
from django.db import models

from accounts.models import Company
from core.crypto import EncryptedTextField


class AmoConnection(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ERROR = "error", "Needs attention"
        DISCONNECTED = "disconnected", "Disconnected"

    # A company may connect several amoCRM accounts; each is one row here.
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="amocrm_connections")
    account_id = models.BigIntegerField(unique=True)
    subdomain = models.CharField(max_length=100)
    host = models.CharField(max_length=150)  # e.g. acme.amocrm.ru, where API calls go
    # Each company's own integration, created in its amoCRM account by the
    # connect button (https://www.amocrm.ru/developers/content/oauth/button).
    client_id = models.CharField(max_length=64, blank=True)
    client_secret = EncryptedTextField(blank=True)
    # A private integration made by hand in the same account, only to carry our
    # widget archive. amoCRM signs the widget's X-Auth-Token with its secret; the
    # API tokens above keep working, so it needs no second authorization.
    widget_client_id = models.CharField(max_length=64, blank=True)
    widget_client_secret = EncryptedTextField(blank=True)
    # Secret part of the webhook URL amoCRM calls on lead stage changes
    # (amoCRM webhooks aren't signed).
    hook_token = models.CharField(max_length=64, unique=True, default=secrets.token_urlsafe)
    access_token = EncryptedTextField()
    refresh_token = EncryptedTextField()
    expires_at = models.DateTimeField()
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.ACTIVE)
    last_error = models.TextField(blank=True)
    connected_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    connected_at = models.DateTimeField(auto_now_add=True)

    # [{id, name, is_main, statuses: [{id, name, color, type}]}]
    pipelines = models.JSONField(default=list, blank=True)
    pipelines_synced_at = models.DateTimeField(null=True, blank=True)

    # Settings: {"<pipeline_id>": <status_id>}; missing pipeline -> 142 (won).
    paid_stages = models.JSONField(default=dict, blank=True)
    # {"<pipeline_id>": <status_id>}: entering this stage creates a payment link.
    link_stages = models.JSONField(default=dict, blank=True)
    add_notes = models.BooleanField(default=True)
    # Optional lead custom fields (url and text types) we keep up to date.
    link_field_id = models.BigIntegerField(null=True, blank=True)
    status_field_id = models.BigIntegerField(null=True, blank=True)
    # Select field on the lead card: picking a template there sends that SMS.
    sms_field_id = models.BigIntegerField(null=True, blank=True)
    # Chosen on the widget's page in amoCRM (Настройки → uzbridge).
    # ProviderAccount ids this amoCRM account offers (one per provider);
    # null = not chosen yet, which takes the company's first working account of each.
    payment_accounts = models.JSONField(null=True, blank=True)
    # The SMS gateway account it sends through; null = the company's default one.
    sms_account = models.ForeignKey(
        "sms.SmsAccount", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    sms_enabled = models.BooleanField(default=True)
    # Documents from templates in the lead card (Настройки → uzbridge → Documents).
    docs_enabled = models.BooleanField(default=False)
    # Shaxmatka: {"<pipeline_id>": {"<status_id>": "interest|reserved|sold|free"}}; missing =
    # the default (won 142 → sold, lost 143 → free). realty_fields: ids of the unit fields.
    realty_stages = models.JSONField(default=dict, blank=True)
    realty_fields = models.JSONField(default=dict, blank=True)
    # The lead card's "uzbridge" tab (amoCRM field group) that holds all our fields.
    field_group = models.CharField(max_length=64, blank=True)
    # Mirror each payment link as an invoice in amoCRM's "Счета/покупки" catalog.
    bills_enabled = models.BooleanField(default=True)
    bills_catalog_id = models.BigIntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.company.slug} → {self.host}"

    @property
    def base_url(self) -> str:
        return f"https://{self.host}"

    def paid_stage_for(self, pipeline_id: int) -> int:
        return int(self.paid_stages.get(str(pipeline_id), 142))

    class Meta:
        verbose_name = "amoCRM connection"
        verbose_name_plural = "amoCRM connections"


class AmoAutomationJob(models.Model):
    """One uzbridge action fired by amoCRM's Digital Pipeline (Воронка → automation).

    Kept in the table rather than as a Celery countdown so a delay of hours or
    days survives restarts and is never run twice.
    """

    class Action(models.TextChoices):
        LINK = "link", "Create payment link"
        SMS = "sms", "Send SMS template"
        LINK_SMS = "link_sms", "Create payment link, then send SMS"

    conn = models.ForeignKey(AmoConnection, on_delete=models.CASCADE, related_name="automation_jobs")
    lead_id = models.BigIntegerField()
    action = models.CharField(max_length=10, choices=Action.choices)
    template_id = models.BigIntegerField(null=True, blank=True)
    # The stage the lead was in when the trigger fired; a delayed job is
    # skipped if the lead has moved on by then.
    status_id = models.BigIntegerField(null=True, blank=True)
    delay_minutes = models.PositiveIntegerField(default=0)
    run_at = models.DateTimeField(db_index=True)
    done_at = models.DateTimeField(null=True, blank=True)
    result = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "automation job"
        verbose_name_plural = "automation jobs"
        ordering = ["-created_at"]


class AmoInstall(models.Model):
    """One press of the connect button, until amoCRM has sent the keys and the code."""

    nonce = models.CharField(max_length=32, unique=True)
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    client_id = models.CharField(max_length=64, blank=True)
    client_secret = EncryptedTextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "connect attempt"
        verbose_name_plural = "connect attempts"
