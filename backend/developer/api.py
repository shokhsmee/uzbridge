"""Dashboard side: manage API keys and webhook endpoints."""

from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

from core.api import member_auth, require_manager

from .models import ApiKey, WebhookDelivery, WebhookEndpoint

router = Router(tags=["developer"], auth=member_auth)


class KeyIn(Schema):
    name: str
    integration: str = "api"


INTEGRATIONS = ("odoo", "api")
KINDS = {"payment": "invoice.", "sms": "sms."}


def _endpoints(request, integration: str):
    qs = WebhookEndpoint.objects.filter(company=request.company)
    if integration == "odoo":
        return qs.filter(label="odoo")
    if integration == "api":
        return qs.exclude(label="odoo")
    return qs


@router.get("/keys")
def keys(request, integration: str = ""):
    return [
        {
            "id": k.pk,
            "name": k.name,
            "prefix": k.prefix,
            "created_at": k.created_at,
            "last_used_at": k.last_used_at,
            "revoked": k.revoked_at is not None,
            "payment_accounts": k.payment_accounts,
            "sms_account_id": k.sms_account_id,
        }
        for k in ApiKey.objects.filter(company=request.company, **({"integration": integration} if integration else {}))
    ]


@router.post("/keys")
def create_key(request, data: KeyIn):
    require_manager(request)
    if not data.name.strip():
        raise HttpError(422, "Name the key (e.g. Odoo).")
    if data.integration not in INTEGRATIONS:
        raise HttpError(422, "Unknown integration.")
    key, raw = ApiKey.issue(request.company, data.name.strip(), data.integration)
    # The only time the full key is shown.
    return {"id": key.pk, "name": key.name, "key": raw}


class KeyAccountsIn(Schema):
    payment_accounts: list[int] | None = None  # None = the first working account of each provider
    sms_account_id: int | None = None


@router.put("/keys/{key_id}/accounts")
def key_accounts(request, key_id: int, data: KeyAccountsIn):
    """Which merchant and SMS accounts this connected system (one Odoo, one site) uses."""
    from payments.models import ProviderAccount
    from sms.models import SmsAccount

    require_manager(request)
    key = ApiKey.objects.filter(company=request.company, pk=key_id).first()
    if key is None:
        raise HttpError(404, "Key not found.")
    if data.payment_accounts is None:
        key.payment_accounts = None
    else:
        chosen, seen = [], set()
        for acc in ProviderAccount.objects.filter(company=request.company, pk__in=data.payment_accounts):
            if acc.provider not in seen:  # one cash desk per provider
                seen.add(acc.provider)
                chosen.append(acc.pk)
        key.payment_accounts = chosen
    key.sms_account = (
        SmsAccount.objects.filter(company=request.company, pk=data.sms_account_id).first()
        if data.sms_account_id
        else None
    )
    key.save(update_fields=["payment_accounts", "sms_account"])
    return {"id": key.pk, "payment_accounts": key.payment_accounts, "sms_account_id": key.sms_account_id}


@router.post("/keys/{key_id}/revoke")
def revoke_key(request, key_id: int):
    require_manager(request)
    n = ApiKey.objects.filter(company=request.company, pk=key_id, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
    if not n:
        raise HttpError(404, "Key not found.")
    return {"ok": True}


@router.get("/webhooks")
def webhooks(request, integration: str = ""):
    out = []
    for ep in _endpoints(request, integration):
        last = ep.deliveries.first()
        out.append(
            {
                "id": ep.pk,
                "url": ep.url,
                "label": ep.label,
                "events": ep.events or WebhookEndpoint.EVENTS,
                "is_enabled": ep.is_enabled,
                "last": {
                    "event": last.event,
                    "status_code": last.status_code,
                    "delivered": bool(last.delivered_at),
                    "at": last.created_at,
                    "error": last.error,
                }
                if last
                else None,
            }
        )
    return out


@router.post("/webhooks/{ep_id}/toggle")
def toggle_webhook(request, ep_id: int):
    require_manager(request)
    ep = WebhookEndpoint.objects.filter(company=request.company, pk=ep_id).first()
    if ep is None:
        raise HttpError(404, "Webhook not found.")
    ep.is_enabled = not ep.is_enabled
    ep.save(update_fields=["is_enabled"])
    return {"is_enabled": ep.is_enabled}


@router.get("/deliveries")
def deliveries(request, integration: str = "", kind: str = "", limit: int = 50):
    """Webhook log for one integration, split by payment (invoice.*) and SMS (sms.*) events."""
    rows = WebhookDelivery.objects.filter(endpoint__in=_endpoints(request, integration)).select_related("endpoint")
    if kind in KINDS:
        rows = rows.filter(event__startswith=KINDS[kind])
    return [
        {
            "id": d.pk,
            "event": d.event,
            "url": d.endpoint.url,
            "status_code": d.status_code,
            "attempts": d.attempts,
            "delivered": bool(d.delivered_at),
            "error": d.error,
            "created_at": d.created_at,
            "summary": _summary(d),
        }
        for d in rows[: max(1, min(limit, 200))]
    ]


def _summary(d: WebhookDelivery) -> str:
    """One readable line: "INV-00005 · 500 000 UZS · paid · payme" or "+998… · delivered"."""
    data = (d.payload or {}).get("data") or {}
    if d.event.startswith("invoice."):
        bits = [data.get("number") or "", f"{data.get('amount', '')} UZS", data.get("status") or ""]
        if data.get("paid_via"):
            bits.append(data["paid_via"])
        if data.get("reference"):
            bits.append(f"ref {data['reference']}")
        return " · ".join(b for b in bits if str(b).strip())
    if d.event.startswith("sms."):
        return " · ".join(
            b for b in [f"+{data.get('phone', '')}", data.get("status") or "", data.get("error") or ""] if b
        )
    return ""
