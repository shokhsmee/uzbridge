import logging
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from accounts.models import Company

from .models import FiscalDefaults, Invoice, Provider, ProviderAccount, ProviderTransaction

log = logging.getLogger(__name__)


def to_ms(dt: datetime | None) -> int:
    return int(dt.timestamp() * 1000) if dt else 0


def now_ms() -> int:
    return to_ms(timezone.now())


@transaction.atomic
def create_invoice(
    company: Company,
    *,
    amount_tiyin: int,
    description: str = "",
    source: str = Invoice.Source.MANUAL,
    external_id: str = "",
    external_name: str = "",
    items: list | None = None,
    created_by_label: str = "",
    customer_phone: str = "",
    return_url: str = "",
    amo_connection=None,
    api_key=None,
) -> Invoice:
    if amount_tiyin <= 0:
        raise ValueError("amount must be positive")
    # Lock the company row so two invoices can't take the same number.
    Company.objects.select_for_update().get(pk=company.pk)
    phone = _clean_phone(customer_phone)
    invoice = Invoice.objects.create(
        company=company,
        number=Invoice.next_number(company),
        amount_tiyin=amount_tiyin,
        description=description,
        source=source,
        external_id=str(external_id),
        external_name=external_name,
        items=items or [],
        created_by_label=created_by_label,
        customer_phone=phone,
        return_url=return_url,
        amo_connection=amo_connection,
        api_key=api_key,
    )
    if phone:
        from sms.services import on_invoice_created

        transaction.on_commit(lambda: _safe(on_invoice_created, invoice))
    return invoice


def _clean_phone(raw: str) -> str:
    from sms.gateways import SmsError, normalize_phone

    if not raw:
        return ""
    try:
        return normalize_phone(raw)
    except SmsError:
        return ""  # a bad number must never block taking a payment


def _safe(fn, *args) -> None:
    try:
        fn(*args)
    except Exception:
        log.exception("%s failed", fn.__name__)


def receipt_items(invoice: Invoice) -> list[dict]:
    """Invoice lines for a fiscal receipt, falling back to one line for the whole amount."""
    if invoice.items:
        return invoice.items
    d = FiscalDefaults.objects.filter(company=invoice.company).first() or FiscalDefaults()
    return [
        {
            "title": (invoice.description or invoice.external_name or invoice.display_number)[:63],
            "price_tiyin": invoice.amount_tiyin,
            "count": 1,
            "ikpu_code": d.ikpu_code,
            "package_code": d.package_code,
            "vat_percent": d.vat_percent,
            "units": d.units,
        }
    ]


def vat_tiyin(total_tiyin: int, vat_percent: int) -> int:
    # Uzbek receipts carry VAT included in the price: vat = total * p / (100 + p).
    return round(total_tiyin * vat_percent / (100 + vat_percent)) if vat_percent else 0


def mark_paid(invoice: Invoice, txn: ProviderTransaction) -> None:
    """Call inside the transaction that performed `txn`, with `invoice` locked."""
    invoice.status = Invoice.Status.PAID
    invoice.paid_via = txn.provider
    invoice.paid_at = txn.performed_at or timezone.now()
    invoice.save(update_fields=["status", "paid_via", "paid_at"])
    transaction.on_commit(lambda: _after_paid(invoice.pk, txn.pk))


def mark_refunded(invoice: Invoice) -> None:
    invoice.status = Invoice.Status.REFUNDED
    invoice.save(update_fields=["status"])
    transaction.on_commit(lambda: _after_refunded(invoice.pk))


def _after_paid(invoice_id: int, txn_id: int) -> None:
    from amocrm.tasks import sync_invoice_paid
    from payments.tasks import submit_fiscal_receipt

    submit_fiscal_receipt.delay(txn_id)
    from sms.services import on_invoice_paid

    invoice = Invoice.objects.select_related("company").get(pk=invoice_id)
    if invoice.source == Invoice.Source.TOPUP:
        _safe(_credit_topup, invoice)
        return
    _safe(on_invoice_paid, invoice)
    _safe(_emit, invoice, "invoice.paid")
    if Invoice.objects.filter(pk=invoice_id, source=Invoice.Source.AMOCRM).exists():
        sync_invoice_paid.delay(invoice_id)


def _credit_topup(invoice: Invoice) -> None:
    """A payment to the platform's own cash desk tops up the company named in external_id."""
    from billing.models import LedgerEntry
    from billing.services import credit

    target = Company.objects.filter(pk=int(invoice.external_id or 0), is_platform=False).first()
    if target is None or LedgerEntry.objects.filter(invoice=invoice).exists():
        return
    credit(
        target,
        invoice.amount_tiyin,
        LedgerEntry.Kind.TOPUP,
        f"Balans toʻldirildi · {invoice.get_paid_via_display()}",
        invoice,
    )


def _emit(invoice: Invoice, event: str) -> None:
    from developer.api_v1 import invoice_out
    from developer.webhooks import emit

    emit(invoice.company, event, invoice_out(invoice))


def _after_refunded(invoice_id: int) -> None:
    from amocrm.tasks import sync_invoice_refunded

    _safe(_emit, Invoice.objects.select_related("company").get(pk=invoice_id), "invoice.refunded")

    if Invoice.objects.filter(pk=invoice_id, source=Invoice.Source.AMOCRM).exists():
        sync_invoice_refunded.delay(invoice_id)


def cancel_invoice(invoice: Invoice) -> Invoice:
    with transaction.atomic():
        invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
        if invoice.status != Invoice.Status.PENDING:
            raise ValueError("Only pending invoices can be cancelled.")
        invoice.status = Invoice.Status.CANCELLED
        invoice.save(update_fields=["status"])
        transaction.on_commit(lambda: _safe(_emit, invoice, "invoice.cancelled"))
    return invoice


class RefundError(Exception):
    pass


def refund_invoice(invoice: Invoice) -> Invoice:
    """Give the money back through the provider that took it."""
    from .providers import click, uzum

    if invoice.status != Invoice.Status.PAID:
        raise RefundError("Only paid invoices can be refunded.")
    txn = (
        invoice.transactions.select_related("account")
        .filter(provider=invoice.paid_via, state=ProviderTransaction.PERFORMED)
        .last()
    )
    if txn is None:
        raise RefundError("No completed payment found for this invoice.")
    if txn.provider == Provider.PAYME:
        # Payme refunds Merchant API payments only from its business cabinet;
        # it then calls CancelTransaction and the invoice turns "refunded" here.
        raise RefundError("Payme refunds are made in the Payme business cabinet; this page updates by itself.")
    if txn.provider == Provider.CLICK:
        try:
            click.reverse(txn.account, txn)
        except click.ClickApiError as e:
            raise RefundError(str(e)) from e
        with transaction.atomic():
            invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
            txn = ProviderTransaction.objects.select_for_update().get(pk=txn.pk)
            txn.state = ProviderTransaction.CANCELLED_AFTER
            txn.cancelled_at = timezone.now()
            txn.reason = 5
            txn.save(update_fields=["state", "cancelled_at", "reason"])
            mark_refunded(invoice)
        return invoice
    try:
        uzum.refund(txn.pk)
    except Exception as e:
        raise RefundError(f"Uzum refused the refund: {e}") from e
    uzum.verify(txn.pk)  # Uzum reports REFUNDED; verify applies it
    invoice.refresh_from_db()
    return invoice


PROVIDER_ORDER = {Provider.PAYME: 0, Provider.CLICK: 1, Provider.UZUM: 2}


def enabled_accounts(company: Company) -> list[ProviderAccount]:
    """Every merchant account that can take payments now (several per provider possible)."""
    from billing.services import is_paused

    if is_paused(company):
        return []  # subscription paused: no new payments until the balance is topped up
    accounts = [a for a in ProviderAccount.objects.filter(company=company, is_enabled=True) if a.is_configured]
    return sorted(accounts, key=lambda a: (PROVIDER_ORDER[a.provider], a.created_at, a.pk))


def route_accounts(company: Company, chosen: list[int] | None) -> list[ProviderAccount]:
    """The accounts a connection offers: its choice, at most one per provider.

    `chosen` is a list of ProviderAccount ids; None means "not chosen yet", which
    takes the first working account of each provider.
    """
    out, seen = [], set()
    for a in enabled_accounts(company):
        if a.provider in seen or (chosen is not None and a.pk not in chosen):
            continue
        seen.add(a.provider)
        out.append(a)
    return out


def _chosen_for(invoice: Invoice) -> list[int] | None:
    source = invoice.amo_connection or invoice.api_key
    return getattr(source, "payment_accounts", None) if source is not None else None


def accounts_for(invoice: Invoice) -> list[ProviderAccount]:
    """Accounts the customer may pay this invoice with."""
    return route_accounts(invoice.company, _chosen_for(invoice))


def may_take(account: ProviderAccount, invoice: Invoice) -> bool:
    """May a callback to this merchant account settle the invoice?

    An account the invoice's connection explicitly left out may not, so a
    payment never lands with the wrong cash desk.
    """
    if account.company_id != invoice.company_id:
        return False
    chosen = _chosen_for(invoice)
    return chosen is None or account.pk in chosen
