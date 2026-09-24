import secrets
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Company, HandoffToken, Membership, validate_company_slug

User = get_user_model()

# Long enough to wait for a new subdomain's TLS certificate after signup.
HANDOFF_TTL = 300


@transaction.atomic
def sign_up(*, company_name: str, slug: str, email: str, password: str, full_name: str = "") -> tuple[Company, User]:
    slug = slug.strip().lower()
    validate_company_slug(slug)
    if Company.objects.filter(slug=slug).exists():
        raise ValidationError({"slug": "This subdomain is taken."})
    email = email.strip().lower()
    user = User.objects.filter(email=email).first()
    if user is None:
        user = User.objects.create_user(email=email, password=password, full_name=full_name)
    elif not user.check_password(password):
        # An existing account adding a second company must prove it owns it.
        raise ValidationError({"email": "An account with this email exists; use its password."})
    company = Company.objects.create(name=company_name.strip(), slug=slug)
    Membership.objects.create(company=company, user=user, role=Membership.Role.OWNER)
    transaction.on_commit(request_certificate)
    return company, user


def request_certificate() -> None:
    if settings.CERT_REQUEST_FILE:
        Path(settings.CERT_REQUEST_FILE).touch()


def host_ready(slug: str) -> bool:
    if not settings.HOSTS_READY_FILE:
        return True
    try:
        hosts = Path(settings.HOSTS_READY_FILE).read_text().split()
    except OSError:
        return False
    return f"{slug}.{settings.BASE_DOMAIN}" in hosts


def issue_handoff(user, company: Company) -> str:
    """One-time token that logs `user` in on the company's subdomain.

    Sessions are per host, so after signing in on app.* the browser has no
    session on acme.*; the token carries it over once, within a few minutes.
    """
    token = secrets.token_urlsafe(32)
    HandoffToken.objects.create(
        token=token, user=user, company=company, expires_at=timezone.now() + timedelta(seconds=HANDOFF_TTL)
    )
    return token


@transaction.atomic
def redeem_handoff(token: str, company: Company):
    row = (
        HandoffToken.objects.select_for_update()
        .filter(token=token, company=company, used_at__isnull=True, expires_at__gt=timezone.now())
        .select_related("user")
        .first()
    )
    if row is None:
        return None
    row.used_at = timezone.now()
    row.save(update_fields=["used_at"])
    return row.user


def membership_for(user, company: Company | None) -> Membership | None:
    if company is None or not user.is_authenticated:
        return None
    return Membership.objects.filter(user=user, company=company).first()
