"""Uzum Checkout (acquiring): we register an order and redirect the customer.

Spec: https://developer.uzumbank.uz/en/checkout
Callbacks carry no signature, so a callback only tells us *which* order to
look at; the payment is confirmed by asking Uzum (getOrderStatus).
"""

import logging
from datetime import timedelta

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from ..models import Invoice, Provider, ProviderAccount, ProviderTransaction
from ..services import mark_paid, mark_refunded, receipt_items

log = logging.getLogger(__name__)

SESSION_SECS = 1800
LANG = {"uz": "uz-UZ", "ru": "ru-RU", "en": "en-EN"}


class UzumError(Exception):
    pass


def _base(account: ProviderAccount) -> str:
    return settings.UZUM_TEST_CHECKOUT_URL if account.test_mode else settings.UZUM_CHECKOUT_URL


def _post(account: ProviderAccount, path: str, body: dict, lang: str = "ru") -> dict:
    resp = httpx.post(
        f"{_base(account)}{path}",
        json=body,
        headers={
            "X-Terminal-Id": account.merchant_id,
            "X-API-Key": account.secret,
            "Content-Language": LANG.get(lang, "ru-RU"),
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errorCode") not in (0, None):
        raise UzumError(f"{data.get('errorCode')}: {data.get('message')}")
    return data.get("result") or {}


def _cart(invoice: Invoice) -> dict:
    items = []
    for i, it in enumerate(receipt_items(invoice), start=1):
        total = it["price_tiyin"] * it["count"]
        params = {"spic": it["ikpu_code"], "packageCode": it["package_code"], "vatPercent": it["vat_percent"]}
        if invoice.company.tin:
            params["TIN"] = invoice.company.tin
        items.append(
            {
                "title": it["title"],
                "productId": f"{invoice.number}-{i}",
                "quantity": it["count"],
                "unitPrice": it["price_tiyin"],
                "total": total,
                "receiptParams": params,
            }
        )
    return {"cartId": str(invoice.public_id), "receiptType": "PURCHASE", "items": items, "total": invoice.amount_tiyin}


def redirect_url(account: ProviderAccount, invoice: Invoice, *, success_url: str, failure_url: str, lang="uz") -> str:
    """Registers (or reuses) an Uzum order for the invoice and returns the payment page URL."""
    fresh = timezone.now() - timedelta(seconds=SESSION_SECS - 120)
    reuse = invoice.transactions.filter(
        provider=Provider.UZUM, account=account, state=ProviderTransaction.CREATED, created_at__gt=fresh
    ).first()
    if reuse and reuse.meta.get("redirect_url"):
        return reuse.meta["redirect_url"]

    attempt = invoice.transactions.filter(provider=Provider.UZUM).count() + 1
    body = {
        "amount": invoice.amount_tiyin,
        "clientId": str(invoice.public_id),
        "currency": 860,
        "orderNumber": f"{invoice.number}-{attempt}",
        "viewType": "REDIRECT",
        "paymentParams": {"payType": "ONE_STEP", "operationType": "PAYMENT"},
        "sessionTimeoutSecs": SESSION_SECS,
        "successUrl": success_url,
        "failureUrl": failure_url,
        "paymentDetails": (invoice.description or invoice.display_number)[:255],
    }
    if account.auto_fiscal:
        body["merchantParams"] = {"cart": _cart(invoice)}
    result = _post(account, "/api/v1/payment/register", body, lang)
    ProviderTransaction.objects.create(
        invoice=invoice,
        account=account,
        provider=Provider.UZUM,
        provider_txn_id=result["orderId"],
        amount_tiyin=invoice.amount_tiyin,
        meta={"redirect_url": result["paymentRedirectUrl"], "order_number": body["orderNumber"]},
    )
    return result["paymentRedirectUrl"]


def handle_callback(account: ProviderAccount, payload: dict) -> int | None:
    """Returns the txn id to verify, or None if the callback isn't ours."""
    order_id = str(payload.get("orderId", ""))
    txn = ProviderTransaction.objects.filter(account=account, provider=Provider.UZUM, provider_txn_id=order_id).first()
    if txn is None:
        return None
    if payload.get("receiptUrl"):
        txn.fiscal = {**txn.fiscal, "receipt_url": payload["receiptUrl"], "receipt_type": payload.get("receiptType")}
        txn.save(update_fields=["fiscal"])
    return txn.pk


def verify(txn_id: int) -> str:
    """Ask Uzum for the order's real status and apply it. Returns that status."""
    txn = ProviderTransaction.objects.select_related("account").get(pk=txn_id)
    status = _post(txn.account, "/api/v1/payment/getOrderStatus", {"orderId": txn.provider_txn_id})
    state = status.get("status")
    with transaction.atomic():
        txn = ProviderTransaction.objects.select_for_update().get(pk=txn_id)
        invoice = Invoice.objects.select_for_update().get(pk=txn.invoice_id)
        txn.log("status", status)
        if state == "COMPLETED" and txn.state == ProviderTransaction.CREATED:
            completed = status.get("completedAmount") or status.get("amount")
            if completed != txn.amount_tiyin:
                log.error("uzum order %s completed %s, expected %s", txn.provider_txn_id, completed, txn.amount_tiyin)
            elif invoice.status == Invoice.Status.PENDING:
                txn.state = ProviderTransaction.PERFORMED
                txn.performed_at = timezone.now()
                mark_paid(invoice, txn)
            else:
                # Paid twice (another provider won the race): refund this one.
                log.warning("uzum order %s paid on a %s invoice; refunding", txn.provider_txn_id, invoice.status)
                transaction.on_commit(lambda: refund(txn_id))
                txn.state = ProviderTransaction.PERFORMED
                txn.performed_at = timezone.now()
        elif state in ("DECLINED", "REVERSED") and txn.state == ProviderTransaction.CREATED:
            txn.state = ProviderTransaction.CANCELLED
            txn.cancelled_at = timezone.now()
        elif state == "REFUNDED" and txn.state == ProviderTransaction.PERFORMED:
            txn.state = ProviderTransaction.CANCELLED_AFTER
            txn.cancelled_at = timezone.now()
            if invoice.status == Invoice.Status.PAID and invoice.paid_via == Provider.UZUM:
                mark_refunded(invoice)
        txn.save()
    return state


def refund(txn_id: int) -> None:
    txn = ProviderTransaction.objects.select_related("account", "invoice").get(pk=txn_id)
    body = {"orderId": txn.provider_txn_id, "amount": txn.amount_tiyin}
    if txn.account.auto_fiscal:
        body["cart"] = _cart(txn.invoice)
    _post(txn.account, "/api/v1/acquiring/refund", body)
