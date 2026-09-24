"""Public API for a company's own systems (Odoo module, websites, 1C...).

Auth: `Authorization: Bearer uzb_...` (a key from the dashboard).
Amounts are integers in tiyin (1 so'm = 100 tiyin), like the providers use.
"""

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.security import HttpBearer

from amocrm.services import money
from core.tenancy import pay_url
from payments import services as pay
from payments.models import Invoice, ProviderTransaction

from .models import ApiKey, WebhookEndpoint, hash_key


class KeyAuth(HttpBearer):
    def authenticate(self, request, token):
        key = (
            ApiKey.objects.select_related("company")
            .filter(key_hash=hash_key(token), revoked_at__isnull=True, company__is_active=True)
            .first()
        )
        if key is None:
            return None
        ApiKey.objects.filter(pk=key.pk).update(last_used_at=timezone.now())
        request.company = key.company
        request.api_key = key
        return key


router = Router(tags=["public v1"], auth=KeyAuth())


class ItemIn(Schema):
    title: str
    price_tiyin: int  # per unit
    count: int = 1
    ikpu_code: str = ""
    package_code: str = ""
    vat_percent: int = 0
    units: str = ""


class InvoiceIn(Schema):
    amount_tiyin: int
    reference: str = ""  # your id (Odoo transaction reference); repeat calls return the same invoice
    description: str = ""
    customer_phone: str = ""
    return_url: str = ""
    source: str = "api"  # "odoo" or "api"
    items: list[ItemIn] = []


def invoice_out(inv: Invoice) -> dict:
    txn = inv.transactions.filter(state=ProviderTransaction.PERFORMED).last() if inv.paid_via else None
    return {
        "id": str(inv.public_id),
        "number": inv.display_number,
        "reference": inv.external_id,
        "status": inv.status,
        "amount_tiyin": inv.amount_tiyin,
        "amount": money(inv.amount_tiyin),
        "currency": "UZS",
        "paid_via": inv.paid_via,
        "paid_at": inv.paid_at,
        "provider_txn_id": txn.provider_txn_id if txn else "",
        "url": pay_url(inv),
        "created_at": inv.created_at,
    }


@router.get("/ping")
def ping(request):
    from sms.services import active_account

    return {
        "company": request.company.name,
        "slug": request.company.slug,
        "providers": [a.provider for a in pay.route_accounts(request.company, request.api_key.payment_accounts)],
        "sms": getattr(active_account(request.company, request.api_key.sms_account), "provider", None),
    }


@router.post("/invoices")
def create_invoice(request, data: InvoiceIn):
    from billing.services import is_paused

    if data.amount_tiyin <= 0:
        raise HttpError(422, "amount_tiyin must be positive.")
    if is_paused(request.company):
        raise HttpError(402, "uzbridge subscription is paused: top up the balance in the dashboard (Kabinet).")
    source = Invoice.Source.ODOO if data.source == "odoo" else Invoice.Source.API
    items = [i.dict() for i in data.items]
    if items and sum(i["price_tiyin"] * i["count"] for i in items) != data.amount_tiyin:
        raise HttpError(422, "items don't add up to amount_tiyin.")
    if data.reference:
        existing = (
            Invoice.objects.filter(company=request.company, source=source, external_id=data.reference[:64])
            # Two Odoo databases of one company can both have INV/2026/00001.
            .filter(Q(api_key=request.api_key) | Q(api_key=None))
            .exclude(status=Invoice.Status.CANCELLED)
            .first()
        )
        if existing:
            if existing.amount_tiyin != data.amount_tiyin:
                raise HttpError(409, "An invoice with this reference exists with a different amount.")
            return invoice_out(existing)
    inv = pay.create_invoice(
        request.company,
        amount_tiyin=data.amount_tiyin,
        description=data.description[:255],
        source=source,
        external_id=data.reference[:64],
        external_name=data.description[:255],
        items=items,
        customer_phone=data.customer_phone,
        return_url=data.return_url[:500],
        created_by_label=request.api_key.name,
        api_key=request.api_key,
    )
    return invoice_out(inv)


def _get(request, public_id) -> Invoice:
    inv = Invoice.objects.filter(company=request.company, public_id=public_id).select_related("company").first()
    if inv is None:
        raise HttpError(404, "Invoice not found.")
    return inv


@router.get("/invoices/{public_id}")
def get_invoice(request, public_id: str):
    return invoice_out(_get(request, public_id))


@router.post("/invoices/{public_id}/cancel")
def cancel_invoice(request, public_id: str):
    try:
        return invoice_out(pay.cancel_invoice(_get(request, public_id)))
    except ValueError as e:
        raise HttpError(409, str(e))


@router.post("/invoices/{public_id}/refund")
def refund_invoice(request, public_id: str):
    try:
        return invoice_out(pay.refund_invoice(_get(request, public_id)))
    except pay.RefundError as e:
        raise HttpError(409, str(e))


class SmsItem(Schema):
    phone: str
    text: str
    ref: str = ""  # your id (Odoo sms uuid); echoed back in sms.status events


class SmsIn(Schema):
    messages: list[SmsItem]


@router.post("/sms")
def send_sms(request, data: SmsIn):
    from sms.gateways import SmsError
    from sms.models import SmsMessage
    from sms.services import queue

    if len(data.messages) > 500:
        raise HttpError(422, "At most 500 messages per call.")
    out = []
    for m in data.messages:
        try:
            msg = queue(
                request.company,
                m.phone,
                m.text,
                event=SmsMessage.Event.API,
                external_ref=m.ref[:64],
                account=request.api_key.sms_account,
            )
            out.append({"ref": m.ref, "id": msg.pk, "status": msg.status, "phone": msg.phone})
        except SmsError as e:
            out.append({"ref": m.ref, "id": None, "status": "failed", "error": str(e)})
    return {"messages": out}


@router.get("/sms/templates")
def sms_templates(request):
    from sms.services import approved_templates

    return [{"id": t.pk, "text": t.text} for t in approved_templates(request.company, request.api_key.sms_account)]


@router.get("/sms/variables")
def sms_variables(request):
    """The company's own {keywords} and the Odoo field path each one reads."""
    from sms.models import SmsVariable

    return [
        {"key": v.key, "path": v.source}
        for v in SmsVariable.objects.filter(company=request.company, integration=SmsVariable.Integration.ODOO)
    ]


class WebhookIn(Schema):
    url: str
    label: str = ""
    events: list[str] = []


@router.post("/webhooks")
def register_webhook(request, data: WebhookIn):
    """Register (or re-register) an endpoint; returns its signing secret."""
    local = data.url.startswith(("http://localhost", "http://127.0.0.1"))
    if not data.url.startswith("https://") and not (local and settings.DEBUG):
        raise HttpError(
            422,
            f"Webhook URL must be a public https address uzbridge can reach; got {data.url}. "
            "In Odoo set Settings → Technical → System Parameters → web.base.url to your https domain.",
        )
    bad = set(data.events) - set(WebhookEndpoint.EVENTS)
    if bad:
        raise HttpError(422, f"Unknown events: {', '.join(sorted(bad))}")
    # The endpoint belongs to the integration of the key that registers it.
    label = data.label[:100] or request.api_key.integration
    ep, created = WebhookEndpoint.objects.get_or_create(
        company=request.company,
        url=data.url[:500],
        defaults={"secret": WebhookEndpoint.new_secret(), "label": label, "events": data.events},
    )
    if not created:
        ep.secret, ep.label, ep.events, ep.is_enabled = WebhookEndpoint.new_secret(), label, data.events, True
        ep.save()
    return {"id": ep.pk, "url": ep.url, "secret": ep.secret, "events": ep.events or WebhookEndpoint.EVENTS}
