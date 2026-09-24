from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

from core.api import member_auth, require_manager
from core.crypto import mask
from core.tenancy import company_url, platform_url

from . import services
from .models import FiscalDefaults, Invoice, Provider, ProviderAccount

router = Router(tags=["payments"], auth=member_auth)

CALLBACK_PATH = {Provider.PAYME: "cb/payme", Provider.CLICK: "cb/click", Provider.UZUM: "cb/uzum"}


class ProviderIn(Schema):
    is_enabled: bool = True
    test_mode: bool = True
    merchant_id: str = ""
    service_id: str = ""
    merchant_user_id: str = ""
    # Secrets: omitted or null = keep the stored value, "" = clear it.
    secret: str | None = None
    test_secret: str | None = None
    auto_fiscal: bool = False


class FiscalIn(Schema):
    ikpu_code: str = ""
    package_code: str = ""
    vat_percent: int = 12
    units: str = ""


class InvoiceIn(Schema):
    amount: str
    description: str = ""


def _provider_out(provider: str, acc: ProviderAccount | None) -> dict:
    out = {
        "provider": provider,
        "label": Provider(provider).label,
        "exists": acc is not None,
        "is_enabled": acc.is_enabled if acc else False,
        "is_configured": acc.is_configured if acc else False,
        "test_mode": acc.test_mode if acc else True,
        "merchant_id": acc.merchant_id if acc else "",
        "service_id": acc.service_id if acc else "",
        "merchant_user_id": acc.merchant_user_id if acc else "",
        "secret_masked": mask(acc.secret) if acc else "",
        "test_secret_masked": mask(acc.test_secret) if acc else "",
        "auto_fiscal": acc.auto_fiscal if acc else False,
        "callback_url": platform_url("api", f"/{CALLBACK_PATH[provider]}/{acc.public_id}/") if acc else "",
    }
    return out


@router.get("/providers")
def list_providers(request):
    accounts = {a.provider: a for a in ProviderAccount.objects.filter(company=request.company)}
    return [_provider_out(p, accounts.get(p)) for p in Provider.values]


@router.put("/providers/{provider}")
def save_provider(request, provider: str, data: ProviderIn):
    require_manager(request)
    if provider not in Provider.values:
        raise HttpError(404, "Unknown provider.")
    acc, _ = ProviderAccount.objects.get_or_create(company=request.company, provider=provider)
    for f in ("is_enabled", "test_mode", "auto_fiscal"):
        setattr(acc, f, getattr(data, f))
    for f in ("merchant_id", "service_id", "merchant_user_id"):
        setattr(acc, f, getattr(data, f).strip())
    if data.secret is not None:
        acc.secret = data.secret.strip()
    if data.test_secret is not None:
        acc.test_secret = data.test_secret.strip()
    acc.save()
    return _provider_out(provider, acc)


@router.get("/fiscal")
def get_fiscal(request):
    d, _ = FiscalDefaults.objects.get_or_create(company=request.company)
    return {"ikpu_code": d.ikpu_code, "package_code": d.package_code, "vat_percent": d.vat_percent, "units": d.units}


@router.put("/fiscal")
def save_fiscal(request, data: FiscalIn):
    require_manager(request)
    if data.ikpu_code and (not data.ikpu_code.isdigit() or len(data.ikpu_code) != 17):
        raise HttpError(422, "MXIK / IKPU code is 17 digits.")
    if not 0 <= data.vat_percent <= 100:
        raise HttpError(422, "VAT must be between 0 and 100.")
    FiscalDefaults.objects.update_or_create(company=request.company, defaults=data.dict())
    return get_fiscal(request)


def _invoice_out(inv: Invoice, with_txns=False) -> dict:
    out = {
        "id": str(inv.public_id),
        "number": inv.display_number,
        "amount_tiyin": inv.amount_tiyin,
        "description": inv.description,
        "source": inv.source,
        "external_id": inv.external_id,
        "external_name": inv.external_name,
        "status": inv.status,
        "paid_via": inv.paid_via,
        "paid_at": inv.paid_at,
        "created_at": inv.created_at,
        "created_by": inv.created_by_label,
        "crm_synced_at": inv.crm_synced_at,
        "crm_sync_error": inv.crm_sync_error,
        "url": company_url(inv.company, f"/p/{inv.public_id}/"),
    }
    if with_txns:
        out["transactions"] = [
            {
                "provider": t.provider,
                "provider_txn_id": t.provider_txn_id,
                "state": t.state,
                "reason": t.reason,
                "created_at": t.created_at,
                "performed_at": t.performed_at,
                "cancelled_at": t.cancelled_at,
            }
            for t in inv.transactions.all()
        ]
    return out


@router.get("/invoices")
def list_invoices(request, status: str = "", q: str = "", limit: int = 50, offset: int = 0):
    qs = Invoice.objects.filter(company=request.company).select_related("company")
    if status:
        qs = qs.filter(status=status)
    if q:
        num = q.upper().removeprefix("INV-").lstrip("0")
        cond = Q(description__icontains=q) | Q(external_name__icontains=q) | Q(external_id=q)
        if num.isdigit():
            cond |= Q(number=int(num))
        qs = qs.filter(cond)
    total = qs.count()
    limit = max(1, min(limit, 200))
    return {"total": total, "items": [_invoice_out(i) for i in qs[offset : offset + limit]]}


@router.get("/invoices/{public_id}")
def get_invoice(request, public_id: str):
    inv = Invoice.objects.filter(company=request.company, public_id=public_id).select_related("company").first()
    if inv is None:
        raise HttpError(404, "Invoice not found.")
    return _invoice_out(inv, with_txns=True)


@router.post("/invoices")
def create_invoice(request, data: InvoiceIn):
    from amocrm.widget_api import _to_tiyin

    inv = services.create_invoice(
        request.company,
        amount_tiyin=_to_tiyin(data.amount),
        description=data.description[:255],
        created_by_label=request.user.full_name or request.user.email,
    )
    return _invoice_out(inv)


@router.post("/invoices/{public_id}/cancel")
def cancel_invoice(request, public_id: str):
    inv = Invoice.objects.filter(company=request.company, public_id=public_id).first()
    if inv is None:
        raise HttpError(404, "Invoice not found.")
    try:
        inv = services.cancel_invoice(inv)
    except ValueError as e:
        raise HttpError(409, str(e))
    return _invoice_out(inv)


@router.get("/stats")
def stats(request, days: int = 30):
    since = timezone.now() - timedelta(days=max(1, min(days, 365)))
    qs = Invoice.objects.filter(company=request.company, created_at__gte=since)
    agg = qs.aggregate(
        created=Count("id"),
        paid=Count("id", filter=Q(status=Invoice.Status.PAID)),
        paid_tiyin=Sum("amount_tiyin", filter=Q(status=Invoice.Status.PAID)),
        pending_tiyin=Sum("amount_tiyin", filter=Q(status=Invoice.Status.PENDING)),
    )
    by_provider = {
        row["paid_via"]: {"count": row["n"], "tiyin": row["s"]}
        for row in qs.filter(status=Invoice.Status.PAID)
        .values("paid_via")
        .annotate(n=Count("id"), s=Sum("amount_tiyin"))
    }
    return {
        "days": days,
        "created": agg["created"],
        "paid": agg["paid"],
        "paid_tiyin": agg["paid_tiyin"] or 0,
        "pending_tiyin": agg["pending_tiyin"] or 0,
        "by_provider": by_provider,
    }
