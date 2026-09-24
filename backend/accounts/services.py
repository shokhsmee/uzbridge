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
    if settings.TENANCY == "path" or not settings.HOSTS_READY_FILE:
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


# ---------------------------------------------------------------- sessions

SESSION_COMPANIES = "uzb_companies"


def client_ip(request) -> str:
    fwd = request.META.get("HTTP_X_FORWARDED_FOR")
    return (fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR", "")) or None


def grant_company(request, company: Company) -> None:
    """Record that this browser signed in to `company` with a password or a handoff.

    One domain means one Django session for every company (path tenancy), so being
    a member isn't enough: each company has to be signed in to separately.
    """
    from django.contrib.sessions.models import Session

    from .models import UserSession

    ids = [i for i in request.session.get(SESSION_COMPANIES, []) if i != company.pk]
    request.session[SESSION_COMPANIES] = [*ids, company.pk]
    request.session.save()
    key = request.session.session_key
    if company.single_session:
        others = UserSession.objects.filter(user=request.user, company=company).exclude(session_key=key)
        Session.objects.filter(session_key__in=list(others.values_list("session_key", flat=True))).delete()
        others.delete()
    UserSession.objects.update_or_create(
        session_key=key,
        defaults={
            "user": request.user,
            "company": company,
            "ip": client_ip(request),
            "user_agent": request.META.get("HTTP_USER_AGENT", "")[:300],
        },
    )


def has_company(request, company: Company) -> bool:
    return company.pk in request.session.get(SESSION_COMPANIES, [])


def end_session(session_key: str) -> None:
    from django.contrib.sessions.models import Session

    from .models import UserSession

    Session.objects.filter(session_key=session_key).delete()
    UserSession.objects.filter(session_key=session_key).delete()
