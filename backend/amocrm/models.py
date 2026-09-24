from django.conf import settings
from django.db import models

from accounts.models import Company
from core.crypto import EncryptedTextField


class AmoConnection(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ERROR = "error", "Needs attention"
        DISCONNECTED = "disconnected", "Disconnected"

    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name="amocrm")
    account_id = models.BigIntegerField(unique=True)
    subdomain = models.CharField(max_length=100)
    host = models.CharField(max_length=150)  # e.g. acme.amocrm.ru, where API calls go
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
    add_notes = models.BooleanField(default=True)
    # Optional lead custom fields (url and text types) we keep up to date.
    link_field_id = models.BigIntegerField(null=True, blank=True)
    status_field_id = models.BigIntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.company.slug} → {self.host}"

    @property
    def base_url(self) -> str:
        return f"https://{self.host}"

    def paid_stage_for(self, pipeline_id: int) -> int:
        return int(self.paid_stages.get(str(pipeline_id), 142))
