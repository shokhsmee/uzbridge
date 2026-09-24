import re

from django.conf import settings
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,30}[a-z0-9])$")


def validate_company_slug(value: str) -> None:
    if not SLUG_RE.match(value):
        raise ValidationError("3–32 characters: lowercase letters, digits and hyphens, not at the ends.")
    if value in settings.RESERVED_SUBDOMAINS:
        raise ValidationError("This subdomain is reserved.")


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email, password, **extra):
        if not email:
            raise ValueError("email is required")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.update(is_staff=True, is_superuser=True)
        return self._create(email, password, **extra)


class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150, blank=True)
    language = models.CharField(max_length=2, choices=[("uz", "Oʻzbekcha"), ("ru", "Русский")], default="uz")

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []
    objects = UserManager()

    def __str__(self):
        return self.email


class Company(models.Model):
    name = models.CharField(max_length=150)
    slug = models.CharField(max_length=32, unique=True, validators=[validate_company_slug])
    tin = models.CharField("STIR / INN", max_length=14, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # ------------------------------------------------ legal profile (Kabinet)
    class EntityType(models.TextChoices):
        LEGAL = "legal", "Yuridik shaxs"
        SOLE = "sole", "YaTT (yakka tartibdagi tadbirkor)"
        PERSON = "person", "Jismoniy shaxs"

    entity_type = models.CharField(max_length=10, choices=EntityType.choices, blank=True)
    legal_name = models.CharField("Legal name / full name", max_length=255, blank=True)
    pinfl = models.CharField("JShShIR / PINFL", max_length=14, blank=True)
    legal_address = models.CharField(max_length=255, blank=True)
    director = models.CharField(max_length=150, blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    bank_name = models.CharField(max_length=150, blank=True)
    bank_mfo = models.CharField("MFO", max_length=5, blank=True)
    bank_account = models.CharField("Hisob raqam", max_length=20, blank=True)
    oked = models.CharField("OKED", max_length=10, blank=True)

    # ------------------------------------------------ security
    # One device at a time: a new sign-in to this company ends the user's other sessions.
    single_session = models.BooleanField(default=True)

    # ------------------------------------------------ billing
    # The platform's own company: its provider accounts take top-ups; it's never billed.
    is_platform = models.BooleanField(default=False)
    # Test / partner account set by the platform (Django admin): every provider
    # can be switched on without the tariff or the Kabinet profile.
    billing_exempt = models.BooleanField(default=False)
    # Why the platform blocked it (is_active off): shown to the operator in the admin.
    blocked_reason = models.CharField(max_length=255, blank=True)
    balance_tiyin = models.BigIntegerField(default=0)
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)
    # How many payment / SMS providers the current period is paid for.
    paid_payment_units = models.PositiveSmallIntegerField(default=0)
    paid_sms_units = models.PositiveSmallIntegerField(default=0)
    overdue_since = models.DateTimeField(null=True, blank=True)
    paused_at = models.DateTimeField(null=True, blank=True)

    REQUIRED_FIELDS_BY_TYPE = {
        "legal": [
            "legal_name",
            "tin",
            "legal_address",
            "director",
            "contact_phone",
            "bank_name",
            "bank_mfo",
            "bank_account",
        ],
        "sole": ["legal_name", "pinfl", "legal_address", "contact_phone", "bank_name", "bank_mfo", "bank_account"],
        "person": ["legal_name", "pinfl", "legal_address", "contact_phone"],
    }

    def missing_profile_fields(self) -> list[str]:
        if not self.entity_type:
            return ["entity_type"]
        return [f for f in self.REQUIRED_FIELDS_BY_TYPE[self.entity_type] if not getattr(self, f)]

    @property
    def profile_complete(self) -> bool:
        return not self.missing_profile_fields()

    class Meta:
        verbose_name_plural = "companies"

    def __str__(self):
        return f"{self.name} ({self.slug})"


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        MEMBER = "member", "Member"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "user"], name="uniq_membership")]

    @property
    def can_manage(self) -> bool:
        return self.role in (self.Role.OWNER, self.Role.ADMIN)


class HandoffToken(models.Model):
    token = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "handoff token"
        verbose_name_plural = "handoff tokens"


class UserSession(models.Model):
    """A signed-in browser/device, per company, so owners can see and end them."""

    session_key = models.CharField(max_length=40, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="device_sessions")
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="device_sessions")
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "signed-in device"
        verbose_name_plural = "signed-in devices"
        ordering = ["-last_seen"]
