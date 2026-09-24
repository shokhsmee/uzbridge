"""Shaxmatka: a developer's projects and units (flats, parking, commercial…).

A project's data lives in its Google Sheet (the working copy the sales team
edits); the sheet's "uzbridge → Sinxronlash" menu pushes rows here and writes
statuses back. Layout images and descriptions can be edited on the site too.
"""

import secrets

from django.db import models

from accounts.models import Company
from core.crypto import EncryptedTextField


class Currency(models.TextChoices):
    UZS = "UZS", "soʻm"
    USD = "USD", "USD"


class UnitStatus(models.TextChoices):
    FREE = "free", "Boʻsh"
    INTEREST = "interest", "Qiziqish"
    RESERVED = "reserved", "Band"
    SOLD = "sold", "Sotilgan"
    CLOSED = "closed", "Sotuvda emas"


class UnitKind(models.TextChoices):
    FLAT = "flat", "Xonadon"
    COMMERCIAL = "commercial", "Tijorat"
    OFFICE = "office", "Ofis"
    PARKING = "parking", "Parking"
    STORAGE = "storage", "Omborxona"
    TOWNHOUSE = "townhouse", "Taunxaus"


class Project(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="realty_projects")
    name = models.CharField(max_length=150)
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.UZS)
    address = models.CharField(max_length=255, blank=True)
    # The Google Sheet's key: its Apps Script sends it with every sync.
    sheet_key = models.CharField(max_length=43, unique=True, default=secrets.token_urlsafe)
    sheet_url = models.URLField(max_length=500, blank=True)
    # Buyers' read-only showroom at /s/<showroom_key>/ (only when public).
    showroom_key = models.CharField(max_length=43, unique=True, default=secrets.token_urlsafe)
    is_public = models.BooleanField(default=False)
    show_sold_prices = models.BooleanField(default=False)
    # A booking ("Band") from amoCRM expires after this many hours; 0 = never.
    booking_hours = models.PositiveIntegerField(default=0)
    use_in_amocrm = models.BooleanField(default=True)
    # A sheet uzbridge made in the company's Google Drive (synced by us, no script needed).
    sheet_id = models.CharField(max_length=100, blank=True)
    sheet_tab = models.BigIntegerField(null=True, blank=True)
    # The "🔄 Sinxronlash" link inside that sheet: /g/<pull_token>
    pull_token = models.CharField(max_length=43, unique=True, default=secrets.token_urlsafe)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_summary = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "pk"]
        verbose_name = "project"
        verbose_name_plural = "projects"

    def __str__(self):
        return f"{self.company.slug}: {self.name}"


class Unit(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="units")
    ext_id = models.CharField("ID in the sheet", max_length=40)
    kind = models.CharField(max_length=12, choices=UnitKind.choices, default=UnitKind.FLAT)
    block = models.CharField(max_length=60, blank=True)  # building / blok
    section = models.CharField(max_length=60, blank=True)  # entrance / podyezd
    floor = models.IntegerField(default=1)
    number = models.CharField(max_length=20, blank=True)
    rooms = models.PositiveSmallIntegerField(default=0)  # 0 = studio
    area = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    price = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    price_m2 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    old_price = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)  # shown struck through
    layout = models.CharField(max_length=60, blank=True)  # layout type, e.g. "2A"
    status = models.CharField(max_length=10, choices=UnitStatus.choices, default=UnitStatus.FREE, db_index=True)
    # The status last exchanged with the sheet: tells a staff edit in the sheet from our own change.
    sheet_status = models.CharField(max_length=10, blank=True)
    description = models.TextField(blank=True)
    plan_url = models.URLField(max_length=500, blank=True)  # from the sheet
    plan = models.BinaryField(null=True, blank=True)  # uploaded on the site (wins over plan_url)
    plan_type = models.CharField(max_length=40, blank=True)
    extra = models.JSONField(default=dict, blank=True)  # the sheet's other columns
    archived = models.BooleanField(default=False)  # gone from the sheet
    # The amoCRM deal holding it.
    amo_connection = models.ForeignKey(
        "amocrm.AmoConnection", null=True, blank=True, on_delete=models.SET_NULL, related_name="units"
    )
    lead_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    reserved_until = models.DateTimeField(null=True, blank=True)
    status_changed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["block", "section", "-floor", "number", "pk"]
        verbose_name = "unit"
        verbose_name_plural = "units"
        constraints = [models.UniqueConstraint(fields=["project", "ext_id"], name="uniq_unit_ext_id")]

    def __str__(self):
        return f"{self.project.name} · {self.block} №{self.number}"

    @property
    def label(self) -> str:
        parts = [
            self.block and f"{self.block}-blok",
            self.section and f"{self.section}-podyezd",
            f"{self.floor}-qavat",
            self.number and f"№{self.number}",
        ]
        return ", ".join(p for p in parts if p)


class UnitEvent(models.Model):
    """Every status change of a unit and who made it."""

    class Source(models.TextChoices):
        SHEET = "sheet", "Google Sheet"
        AMOCRM = "amocrm", "amoCRM"
        SITE = "site", "uzbridge"
        TIMER = "timer", "Booking expired"

    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="events")
    status_from = models.CharField(max_length=10, blank=True)
    status_to = models.CharField(max_length=10)
    source = models.CharField(max_length=10, choices=Source.choices)
    lead_id = models.BigIntegerField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "status change"
        verbose_name_plural = "status changes"


class GoogleAccount(models.Model):
    """The company's Google account (scope drive.file: only sheets uzbridge made)."""

    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name="google")
    email = models.EmailField(blank=True)
    refresh_token = EncryptedTextField()
    access_token = EncryptedTextField(blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    connected_by = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Google account"

    def __str__(self):
        return f"{self.company.slug}: {self.email}"
