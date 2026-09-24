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
) -> Invoice:
    if amount_tiyin <= 0:
        raise ValueError("amount must be positive")
    # Lock the company row so two invoices can't take the same number.
    Company.objects.select_for_update().get(pk=company.pk)
    return Invoice.objects.create(
        company=company,
        number=Invoice.next_number(company),
        amount_tiyin=amount_tiyin,
        description=description,
        source=source,
        external_id=str(external_id),
        external_name=external_name,
        items=items or [],
        created_by_label=created_by_label,
    )


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
    if Invoice.objects.filter(pk=invoice_id, source=Invoice.Source.AMOCRM).exists():
        sync_invoice_paid.delay(invoice_id)


def _after_refunded(invoice_id: int) -> None:
    from amocrm.tasks import sync_invoice_refunded

    if Invoice.objects.filter(pk=invoice_id, source=Invoice.Source.AMOCRM).exists():
        sync_invoice_refunded.delay(invoice_id)


def cancel_invoice(invoice: Invoice) -> Invoice:
    with transaction.atomic():
        invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
        if invoice.status != Invoice.Status.PENDING:
            raise ValueError("Only pending invoices can be cancelled.")
        invoice.status = Invoice.Status.CANCELLED
        invoice.save(update_fields=["status"])
    return invoice


def enabled_accounts(company: Company) -> list[ProviderAccount]:
    order = {Provider.PAYME: 0, Provider.CLICK: 1, Provider.UZUM: 2}
    accounts = [a for a in ProviderAccount.objects.filter(company=company, is_enabled=True) if a.is_configured]
    return sorted(accounts, key=lambda a: order[a.provider])
