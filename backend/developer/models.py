import hashlib
import secrets

from django.db import models

from accounts.models import Company
from core.crypto import EncryptedTextField

KEY_PREFIX = "uzb_"


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class ApiKey(models.Model):
    """A company's key for the public API (/api/v1). Only the hash is stored."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="api_keys")
    name = models.CharField(max_length=100)
    # Which integration page owns the key: "odoo" or "api" (custom systems).
    integration = models.CharField(max_length=20, default="api", db_index=True)
    prefix = models.CharField(max_length=16)  # shown in the dashboard to tell keys apart
    key_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    # One key = one connected system (e.g. one Odoo). Which merchant accounts it
    # offers (ProviderAccount ids, one per provider; null = the first of each)
    # and which SMS account it sends through (null = the company default).
    payment_accounts = models.JSONField(null=True, blank=True)
    sms_account = models.ForeignKey(
        "sms.SmsAccount", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "API key"
        verbose_name_plural = "API keys"
        ordering = ["-created_at"]

    @classmethod
    def issue(cls, company: Company, name: str, integration: str = "api") -> tuple["ApiKey", str]:
        raw = KEY_PREFIX + secrets.token_urlsafe(32)
        key = cls.objects.create(
            company=company, name=name[:100], integration=integration, prefix=raw[:12], key_hash=hash_key(raw)
        )
        return key, raw


class WebhookEndpoint(models.Model):
    """Where we POST events for the company (its Odoo, website, 1C, n8n...)."""

    EVENTS = ["invoice.paid", "invoice.refunded", "invoice.cancelled", "sms.status"]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="webhooks")
    url = models.URLField(max_length=500)
    secret = EncryptedTextField()
    events = models.JSONField(default=list, blank=True)  # empty = all
    label = models.CharField(max_length=100, blank=True)  # e.g. "odoo"
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "webhook endpoint"
        verbose_name_plural = "webhook endpoints"
        constraints = [models.UniqueConstraint(fields=["company", "url"], name="uniq_webhook_url")]

    def wants(self, event: str) -> bool:
        return self.is_enabled and (not self.events or event in self.events)

    @staticmethod
    def new_secret() -> str:
        return "whsec_" + secrets.token_urlsafe(32)


class WebhookDelivery(models.Model):
    endpoint = models.ForeignKey(WebhookEndpoint, on_delete=models.CASCADE, related_name="deliveries")
    event = models.CharField(max_length=40)
    payload = models.JSONField()
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.TextField(blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "webhook delivery"
        verbose_name_plural = "webhook deliveries"
        ordering = ["-created_at"]
