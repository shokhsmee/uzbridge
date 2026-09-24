import logging

from django.db import transaction
from django.utils import timezone

from accounts.models import Company
from core.tenancy import pay_url, platform_url
from payments.models import Invoice

from . import oauth
from .client import AmoClient, AmoError
from .models import AmoConnection

log = logging.getLogger(__name__)


class AlreadyLinked(Exception):
    pass


def amo_accounts(conn: AmoConnection) -> list:
    """Merchant accounts this amoCRM account offers: its choice, one per provider."""
    from payments.services import route_accounts

    return route_accounts(conn.company, conn.payment_accounts)


def amo_sms_account(conn: AmoConnection):
    """The SMS account this amoCRM account sends through (None when SMS is off or missing)."""
    from sms.services import active_account

    return active_account(conn.company, conn.sms_account) if conn.sms_enabled else None


def amo_templates(conn: AmoConnection) -> list:
    """Approved SMS templates switched on for amoCRM; none while SMS is off there."""
    from sms.services import approved_templates

    if not conn.sms_enabled:
        return []
    return [t for t in approved_templates(conn.company, conn.sms_account) if t.use_in_amocrm]


def connect(company: Company, user, host: str, code: str, client_id: str, client_secret: str) -> AmoConnection:
    tokens = oauth.exchange_code(host, client_id, client_secret, code)
    probe = AmoConnection(
        company=company,
        host=host,
        account_id=0,
        subdomain="",
        client_id=client_id,
        client_secret=client_secret,
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_at=timezone.now(),
    )
    oauth.apply_tokens(probe, tokens)
    info = AmoClient(probe).account()

    with transaction.atomic():
        other = AmoConnection.objects.filter(account_id=info["id"]).exclude(company=company).first()
        if other is not None and other.status != AmoConnection.Status.DISCONNECTED:
            raise AlreadyLinked(f"This amoCRM account is already connected to {other.company.name}.")
        if other is not None:
            other.delete()
        # One row per amoCRM account; a company may connect several.
        conn, _ = AmoConnection.objects.update_or_create(
            account_id=info["id"],
            defaults={
                "company": company,
                "subdomain": info.get("subdomain", host.split(".")[0]),
                "host": host,
                "client_id": client_id,
                "client_secret": client_secret,
                "access_token": probe.access_token,
                "refresh_token": probe.refresh_token,
                "expires_at": probe.expires_at,
                "status": AmoConnection.Status.ACTIVE,
                "last_error": "",
                "connected_by": user,
            },
        )
    sync_pipelines(conn)
    try:
        subscribe_webhook(conn)
    except AmoError:
        # Links on stage change won't work until reconnect; everything else does.
        log.exception("amocrm webhook subscription failed for %s", conn.host)
    return conn


def hook_url(conn: AmoConnection) -> str:
    return platform_url("app", f"/oauth/amocrm/hook/{conn.hook_token}/")


def subscribe_webhook(conn: AmoConnection) -> None:
    # update_lead: the SMS template field; status_lead: link/paid stages.
    body = {"destination": hook_url(conn), "settings": ["status_lead", "update_lead"]}
    AmoClient(conn).request("POST", "/api/v4/webhooks", json=body)


def unsubscribe_webhook(conn: AmoConnection) -> None:
    AmoClient(conn).request("DELETE", "/api/v4/webhooks", json={"destination": hook_url(conn)})


SMS_FIELD_NAME = "uzbridge: SMS shablon"


def sync_sms_field(conn: AmoConnection) -> AmoConnection:
    """Make the lead's "uzbridge: SMS shablon" select list the approved templates.

    amoCRM matches enums by id; new texts get new ids, removed ones disappear.
    """
    from sms.models import SmsTemplate

    templates = amo_templates(conn)
    client = AmoClient(conn)
    enums, used = [], set()
    for i, t in enumerate(templates):
        value = t.title
        while value in used:  # enum values must be unique within the field
            value = f"{value} ·"
        used.add(value)
        enum = {"value": value, "sort": (i + 1) * 10}
        if t.amo_enum_id:
            enum["id"] = t.amo_enum_id
        enums.append(enum)
    if not enums:
        enums = [{"value": "— shablon yoʻq —", "sort": 10}]

    existing = {f["name"]: f["id"] for f in client.lead_custom_fields(all_types=True)}
    field_id = conn.sms_field_id if conn.sms_field_id in existing.values() else existing.get(SMS_FIELD_NAME)
    if field_id:
        data = client.request("PATCH", "/api/v4/leads/custom_fields", json=[{"id": field_id, "enums": enums}]) or {}
    else:
        data = (
            client.request(
                "POST", "/api/v4/leads/custom_fields", json=[{"name": SMS_FIELD_NAME, "type": "select", "enums": enums}]
            )
            or {}
        )
    field = (data.get("_embedded", {}).get("custom_fields") or [{}])[0]
    conn.sms_field_id = field.get("id", field_id)
    conn.save(update_fields=["sms_field_id"])

    by_value = {e["value"]: e["id"] for e in field.get("enums") or []}
    for t, e in zip(templates, enums, strict=False):
        SmsTemplate.objects.filter(pk=t.pk).update(amo_enum_id=by_value.get(e["value"]))
    subscribe_webhook(conn)
    return conn


LINK_FIELD_NAME = "uzbridge: toʻlov havolasi"
STATUS_FIELD_NAME = "uzbridge: toʻlov holati"


def create_lead_fields(conn: AmoConnection) -> AmoConnection:
    """Create (or find) the two lead fields we write the link and status into."""
    client = AmoClient(conn)
    existing = {f["name"]: f["id"] for f in client.lead_custom_fields()}
    wanted = [(LINK_FIELD_NAME, "url"), (STATUS_FIELD_NAME, "text")]
    missing = [{"name": n, "type": t} for n, t in wanted if n not in existing]
    if missing:
        data = client.request("POST", "/api/v4/leads/custom_fields", json=missing) or {}
        for f in data.get("_embedded", {}).get("custom_fields", []):
            existing[f["name"]] = f["id"]
    conn.link_field_id = existing.get(LINK_FIELD_NAME)
    conn.status_field_id = existing.get(STATUS_FIELD_NAME)
    conn.save(update_fields=["link_field_id", "status_field_id"])
    return conn


def sync_pipelines(conn: AmoConnection) -> AmoConnection:
    conn.pipelines = AmoClient(conn).pipelines()
    conn.pipelines_synced_at = timezone.now()
    conn.save(update_fields=["pipelines", "pipelines_synced_at"])
    return conn


def money(tiyin: int) -> str:
    whole, frac = divmod(tiyin, 100)
    s = f"{whole:,}".replace(",", " ")
    return f"{s}.{frac:02d}" if frac else s


def pay_link(invoice: Invoice) -> str:
    return pay_url(invoice)


def note_created(invoice: Invoice) -> str:
    who = f" · {invoice.created_by_label}" if invoice.created_by_label else ""
    return f"💳 Payment link {invoice.display_number}: {money(invoice.amount_tiyin)} UZS{who}\n{pay_link(invoice)}"


def note_paid(invoice: Invoice) -> str:
    return f"✅ Paid {money(invoice.amount_tiyin)} UZS via {invoice.get_paid_via_display()} · {invoice.display_number}"


def note_refunded(invoice: Invoice) -> str:
    return f"↩️ Refunded {money(invoice.amount_tiyin)} UZS · {invoice.display_number}"
