from django.db import models

from accounts.models import Company


class LedgerEntry(models.Model):
    """Every change of a company's balance. balance_after makes the history self-checking."""

    class Kind(models.TextChoices):
        TOPUP = "topup", "Top-up"
        CHARGE = "charge", "Subscription"
        PRORATA = "prorata", "Added mid-period"
        CREDIT = "credit", "Manual credit"
        ADJUST = "adjust", "Adjustment"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="ledger")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    amount_tiyin = models.BigIntegerField()  # + in, - out
    balance_after = models.BigIntegerField()
    description = models.CharField(max_length=255, blank=True)
    invoice = models.ForeignKey("payments.Invoice", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "ledger entry"
        verbose_name_plural = "ledger entries"
        ordering = ["-created_at", "-id"]


class TariffKind(models.TextChoices):
    PAYMENT = "payment", "Payment system account (Payme / Click / Uzum)"
    SMS = "sms", "SMS gateway account (Eskiz / Playmobile)"


class TariffPrice(models.Model):
    """The price list, per 30-day period: the first account, then each extra one."""

    kind = models.CharField(max_length=10, choices=TariffKind.choices, unique=True)
    first_tiyin = models.BigIntegerField(help_text="In tiyin: 1 soʻm = 100 tiyin.")
    extra_tiyin = models.BigIntegerField(help_text="Each account after the first, in tiyin.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "tariff price"
        verbose_name_plural = "tariff prices"
        ordering = ["kind"]

    def __str__(self):
        return self.get_kind_display()


class CompanyTariff(models.Model):
    """A special price for one company (a deal, a partner); overrides the price list."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="tariffs")
    kind = models.CharField(max_length=10, choices=TariffKind.choices)
    first_tiyin = models.BigIntegerField(help_text="In tiyin: 1 soʻm = 100 tiyin.")
    extra_tiyin = models.BigIntegerField(help_text="Each account after the first, in tiyin.")
    note = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "special price"
        verbose_name_plural = "special prices"
        constraints = [models.UniqueConstraint(fields=["company", "kind"], name="uniq_company_tariff")]

    def __str__(self):
        return f"{self.company.slug}: {self.get_kind_display()}"
