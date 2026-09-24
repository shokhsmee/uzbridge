from django.db import models

from accounts.models import Company


class CallbackLog(models.Model):
    """Every call into our public callback URLs: who called, what we answered, why."""

    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.CASCADE, related_name="callback_logs")
    source = models.CharField(max_length=20, db_index=True)  # payme / click / uzum / eskiz / playmobile / amocrm
    path = models.CharField(max_length=200)
    ip = models.GenericIPAddressField(null=True, blank=True)
    status_code = models.PositiveSmallIntegerField()
    # Business outcome, not HTTP: Payme answers errors with HTTP 200 and an error body.
    ok = models.BooleanField(default=True)
    note = models.CharField(max_length=255, blank=True)
    blocked = models.BooleanField(default=False)  # refused by allowlist / rate limit
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "callback log"
        verbose_name_plural = "callback logs"
        ordering = ["-created_at"]
