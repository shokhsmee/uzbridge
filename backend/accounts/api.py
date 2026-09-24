from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from ninja import Router, Schema
from ninja.errors import HttpError

from core.api import member_auth
from core.tenancy import company_url

from . import services
from .models import Company

router = Router(tags=["auth"])


class SignUpIn(Schema):
    company_name: str
    slug: str
    email: str
    password: str
    full_name: str = ""


class LoginIn(Schema):
    email: str
    password: str


class CompanyOut(Schema):
    name: str
    slug: str
    url: str


class MeOut(Schema):
    email: str
    full_name: str
    language: str
    role: str
    company: CompanyOut


def _company_out(c: Company) -> dict:
    return {"name": c.name, "slug": c.slug, "url": company_url(c)}


@router.get("/csrf", auth=None)
def csrf(request):
    """Sets the csrftoken cookie for the SPA; returns the tenant context."""
    get_token(request)
    return {"company": _company_out(request.company) if request.company else None}


@router.get("/slug-available", auth=None)
def slug_available(request, slug: str):
    from django.core.exceptions import ValidationError

    from .models import validate_company_slug

    try:
        validate_company_slug(slug)
    except ValidationError as e:
        return {"available": False, "reason": e.messages[0]}
    taken = Company.objects.filter(slug=slug).exists()
    return {"available": not taken, "reason": "This subdomain is taken." if taken else ""}


@router.get("/host-ready", auth=None)
def host_ready(request, slug: str):
    return {"ready": services.host_ready(slug)}


@router.post("/signup", auth=None)
def signup(request, data: SignUpIn):
    if request.company is not None:
        raise HttpError(400, "Sign up on the main site.")
    company, user = services.sign_up(**data.dict())
    token = services.issue_handoff(user, company)
    return {"redirect": company_url(company, f"/auth/handoff?token={token}"), "slug": company.slug}


@router.post("/login", auth=None)
def login_view(request, data: LoginIn):
    user = authenticate(request, email=data.email.strip().lower(), password=data.password)
    if user is None:
        raise HttpError(401, "Wrong email or password.")
    if request.company is None:
        # Main site: list the user's companies; each one is entered via handoff.
        companies = [m.company for m in user.memberships.select_related("company") if m.company.is_active]
        return {
            "companies": [
                {**_company_out(c), "enter": company_url(c, f"/auth/handoff?token={services.issue_handoff(user, c)}")}
                for c in companies
            ]
        }
    if services.membership_for(user, request.company) is None:
        raise HttpError(401, "Wrong email or password.")
    login(request, user)
    return {"ok": True}


@router.post("/handoff", auth=None)
def handoff(request, token: str):
    if request.company is None:
        raise HttpError(400, "No company.")
    user = services.redeem_handoff(token, request.company)
    if user is None:
        raise HttpError(401, "This sign-in link has expired. Sign in again.")
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return {"ok": True}


@router.post("/logout", auth=member_auth)
def logout_view(request):
    logout(request)
    return {"ok": True}


@router.get("/me", auth=member_auth, response=MeOut)
def me(request):
    u = request.user
    return {
        "email": u.email,
        "full_name": u.full_name,
        "language": u.language,
        "role": request.membership.role,
        "company": _company_out(request.company),
    }
