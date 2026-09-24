"""API for the amoCRM widget in the lead card.

The widget calls us with `self.$authorizedAjax`, which adds an
`X-Auth-Token` JWT signed HS256 with our integration's client secret
(https://www.amocrm.ru/developers/content/oauth/disposable-tokens).
"""

from urllib.parse import urlsplit

import jwt
from django.conf import settings
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.security import APIKeyHeader

from payments import services as pay
from payments.models import Invoice

from . import services
from .models import AmoConnection
from .tasks import post_link_note


class WidgetToken(APIKeyHeader):
    param_name = "X-Auth-Token"

    def authenticate(self, request, key):
        if not key or not settings.AMOCRM_CLIENT_SECRET:
            return None
        parts = urlsplit(settings.AMOCRM_REDIRECT_URI)
        try:
            claims = jwt.decode(
                key,
                settings.AMOCRM_CLIENT_SECRET,
                algorithms=["HS256"],
                audience=f"{parts.scheme}://{parts.netloc}",
                options={"require": ["exp", "account_id"]},
                leeway=30,
            )
        except jwt.PyJWTError:
            return None
        conn = (
            AmoConnection.objects.select_related("company")
            .filter(account_id=claims["account_id"], status=AmoConnection.Status.ACTIVE, company__is_active=True)
            .first()
        )
        if conn is None:
            return None
        request.amo = conn
        request.company = conn.company
        request.amo_user_id = claims.get("user_id")
        return conn


router = Router(tags=["widget"], auth=WidgetToken())


class InvoiceIn(Schema):
    lead_id: int
    amount: str  # soum, "1500000" or "1500000.50"
    description: str = ""
    lead_name: str = ""
    user_name: str = ""


def _to_tiyin(amount: str) -> int:
    from decimal import Decimal, InvalidOperation

    try:
        value = Decimal(amount.replace(" ", "").replace(",", "."))
    except InvalidOperation:
        raise HttpError(422, "Amount must be a number.")
    tiyin = value * 100
    if tiyin != tiyin.to_integral_value() or tiyin <= 0:
        raise HttpError(422, "Amount must be positive, with at most two decimals.")
    return int(tiyin)


def _invoice_out(inv: Invoice) -> dict:
    return {
        "id": str(inv.public_id),
        "number": inv.display_number,
        "amount": services.money(inv.amount_tiyin),
        "status": inv.status,
        "paid_via": inv.paid_via,
        "paid_at": inv.paid_at,
        "created_at": inv.created_at,
        "url": services.pay_link(inv),
    }


@router.get("/context")
def context(request, lead_id: int):
    providers = [a.provider for a in pay.enabled_accounts(request.company)]
    invoices = Invoice.objects.filter(
        company=request.company, source=Invoice.Source.AMOCRM, external_id=str(lead_id)
    ).select_related("company")[:20]
    return {
        "company": request.company.name,
        "providers": providers,
        "invoices": [_invoice_out(i) for i in invoices],
    }


@router.post("/invoices")
def create(request, data: InvoiceIn):
    if not pay.enabled_accounts(request.company):
        raise HttpError(409, "No payment methods are set up yet. Add Payme, Click or Uzum in the uzbridge dashboard.")
    invoice = pay.create_invoice(
        request.company,
        amount_tiyin=_to_tiyin(data.amount),
        description=data.description[:255] or data.lead_name[:255],
        source=Invoice.Source.AMOCRM,
        external_id=str(data.lead_id),
        external_name=data.lead_name[:255],
        created_by_label=data.user_name[:150],
    )
    post_link_note.delay(invoice.pk)
    return _invoice_out(invoice)


@router.post("/invoices/{public_id}/cancel")
def cancel(request, public_id: str):
    invoice = Invoice.objects.filter(company=request.company, public_id=public_id).first()
    if invoice is None:
        raise HttpError(404, "Invoice not found.")
    try:
        invoice = pay.cancel_invoice(invoice)
    except ValueError as e:
        raise HttpError(409, str(e))
    return _invoice_out(invoice)
