import re

from django.conf import settings
from ninja import Router, Schema
from ninja.errors import HttpError

from accounts.models import Company
from core.api import member_auth, require_manager
from core.tenancy import pay_url

from . import services
from .models import LedgerEntry

router = Router(tags=["billing"], auth=member_auth)

PROFILE_FIELDS = [
    "entity_type",
    "legal_name",
    "tin",
    "pinfl",
    "legal_address",
    "director",
    "contact_phone",
    "bank_name",
    "bank_mfo",
    "bank_account",
    "oked",
]


class ProfileIn(Schema):
    entity_type: str
    legal_name: str = ""
    tin: str = ""
    pinfl: str = ""
    legal_address: str = ""
    director: str = ""
    contact_phone: str = ""
    bank_name: str = ""
    bank_mfo: str = ""
    bank_account: str = ""
    oked: str = ""


class TopupIn(Schema):
    amount: int  # so'm


def _profile_out(c: Company) -> dict:
    return {
        **{f: getattr(c, f) for f in PROFILE_FIELDS},
        "complete": c.profile_complete,
        "missing": c.missing_profile_fields(),
        "required": Company.REQUIRED_FIELDS_BY_TYPE,
    }


DIGITS = {"tin": 9, "pinfl": 14, "bank_mfo": 5, "bank_account": 20}


@router.get("/profile")
def get_profile(request):
    return _profile_out(request.company)


@router.put("/profile")
def save_profile(request, data: ProfileIn):
    require_manager(request)
    if data.entity_type not in Company.EntityType.values:
        raise HttpError(422, "Choose: yuridik shaxs, YaTT or jismoniy shaxs.")
    values = {k: (v or "").strip() for k, v in data.dict().items()}
    for field, n in DIGITS.items():
        v = re.sub(r"\s", "", values[field])
        if v and not re.fullmatch(rf"\d{{{n}}}", v):
            raise HttpError(422, f"{field}: {n} digits.")
        values[field] = v
    c = request.company
    for k, v in values.items():
        setattr(c, k, v)
    c.save(update_fields=PROFILE_FIELDS)
    return _profile_out(c)


@router.get("/summary")
def summary(request):
    return services.summary(request.company)


@router.get("/ledger")
def ledger(request, limit: int = 100):
    return [
        {
            "id": e.pk,
            "kind": e.kind,
            "amount_tiyin": e.amount_tiyin,
            "balance_after": e.balance_after,
            "description": e.description,
            "created_at": e.created_at,
        }
        for e in LedgerEntry.objects.filter(company=request.company)[: max(1, min(limit, 500))]
    ]


@router.post("/topup")
def topup(request, data: TopupIn):
    """A payment link to uzbridge's own Payme/Click; paying it credits this company's balance."""
    from payments.models import Invoice
    from payments.services import create_invoice, enabled_accounts

    if data.amount < 10_000:
        raise HttpError(422, "Minimum top-up is 10 000 so'm.")
    platform = Company.objects.filter(slug=settings.PLATFORM_COMPANY_SLUG, is_platform=True).first()
    if platform is None or not enabled_accounts(platform):
        raise HttpError(503, "Online top-up isn't set up yet. Contact uzbridge support to top up by bank transfer.")
    inv = create_invoice(
        platform,
        amount_tiyin=data.amount * 100,
        description=f"uzbridge balansi: {request.company.name}",
        source=Invoice.Source.TOPUP,
        external_id=str(request.company.pk),
        external_name=request.company.name,
        created_by_label=request.user.email,
    )
    return {"url": pay_url(inv), "number": inv.display_number}
