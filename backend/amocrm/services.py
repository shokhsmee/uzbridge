from django.db import transaction
from django.utils import timezone

from accounts.models import Company
from core.tenancy import company_url
from payments.models import Invoice

from . import oauth
from .client import AmoClient
from .models import AmoConnection


class AlreadyLinked(Exception):
    pass


def connect(company: Company, user, host: str, code: str) -> AmoConnection:
    tokens = oauth.exchange_code(host, code)
    probe = AmoConnection(
        company=company,
        host=host,
        account_id=0,
        subdomain="",
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
        conn, _ = AmoConnection.objects.update_or_create(
            company=company,
            defaults={
                "account_id": info["id"],
                "subdomain": info.get("subdomain", host.split(".")[0]),
                "host": host,
                "access_token": probe.access_token,
                "refresh_token": probe.refresh_token,
                "expires_at": probe.expires_at,
                "status": AmoConnection.Status.ACTIVE,
                "last_error": "",
                "connected_by": user,
            },
        )
    sync_pipelines(conn)
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
    return company_url(invoice.company, f"/p/{invoice.public_id}/")


def note_created(invoice: Invoice) -> str:
    who = f" · {invoice.created_by_label}" if invoice.created_by_label else ""
    return f"💳 Payment link {invoice.display_number}: {money(invoice.amount_tiyin)} UZS{who}\n{pay_link(invoice)}"


def note_paid(invoice: Invoice) -> str:
    return f"✅ Paid {money(invoice.amount_tiyin)} UZS via {invoice.get_paid_via_display()} · {invoice.display_number}"


def note_refunded(invoice: Invoice) -> str:
    return f"↩️ Refunded {money(invoice.amount_tiyin)} UZS · {invoice.display_number}"
