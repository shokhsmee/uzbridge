"""Click SHOP API: Click calls Prepare (action=0) then Complete (action=1).

Spec: https://docs.click.uz/en/shop-api/requests
Requests are form-encoded, amounts are soum ("1000.00"), and the MD5 sign
is built from the raw posted strings, never re-formatted numbers.
"""

import hashlib
import secrets
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from ..models import Invoice, Provider, ProviderAccount, ProviderTransaction
from ..services import mark_paid, may_take, receipt_items, vat_tiyin

SUCCESS = 0
SIGN_FAILED = -1
BAD_AMOUNT = -2
ACTION_NOT_FOUND = -3
ALREADY_PAID = -4
ORDER_NOT_FOUND = -5
TXN_NOT_FOUND = -6
UPDATE_FAILED = -7
BAD_REQUEST = -8
CANCELLED = -9

NOTES = {
    SUCCESS: "Success",
    SIGN_FAILED: "SIGN CHECK FAILED!",
    BAD_AMOUNT: "Incorrect parameter amount",
    ACTION_NOT_FOUND: "Action not found",
    ALREADY_PAID: "Already paid",
    ORDER_NOT_FOUND: "User does not exist",
    TXN_NOT_FOUND: "Transaction does not exist",
    UPDATE_FAILED: "Failed to update user",
    BAD_REQUEST: "Error in request from click",
    CANCELLED: "Transaction cancelled",
}

REQUIRED = ["click_trans_id", "service_id", "merchant_trans_id", "amount", "action", "sign_time", "sign_string"]


# ---------------------------------------------------------------- link


def pay_url(account: ProviderAccount, invoice: Invoice, *, return_url: str = "") -> str:
    q = {
        "service_id": account.service_id,
        "merchant_id": account.merchant_id,
        "amount": invoice.amount_soum,
        "transaction_param": str(invoice.number),
    }
    if return_url:
        q["return_url"] = return_url
    return f"{settings.CLICK_PAY_URL}?{urlencode(q)}"


# ---------------------------------------------------------------- endpoint


def expected_sign(account: ProviderAccount, p: dict) -> str:
    parts = [p["click_trans_id"], p["service_id"], account.secret, p["merchant_trans_id"]]
    if p["action"] == "1":
        parts.append(p.get("merchant_prepare_id", ""))
    parts += [p["amount"], p["action"], p["sign_time"]]
    return hashlib.md5("".join(parts).encode()).hexdigest()


def _reply(p: dict, error: int, **extra) -> dict:
    return {
        "click_trans_id": p.get("click_trans_id"),
        "merchant_trans_id": p.get("merchant_trans_id"),
        **extra,
        "error": error,
        "error_note": NOTES[error],
    }


def handle(account: ProviderAccount, post: dict) -> dict:
    p = {k: str(post.get(k, "")) for k in [*REQUIRED, "merchant_prepare_id", "error", "click_paydoc_id"]}
    if any(not p[k] for k in REQUIRED):
        return _reply(p, BAD_REQUEST)
    if p["action"] not in ("0", "1"):
        return _reply(p, ACTION_NOT_FOUND)
    if p["service_id"] != account.service_id or not secrets.compare_digest(
        p["sign_string"].lower(), expected_sign(account, p)
    ):
        return _reply(p, SIGN_FAILED)
    try:
        amount_tiyin = Decimal(p["amount"]) * 100
    except InvalidOperation:
        return _reply(p, BAD_AMOUNT)
    return prepare(account, p, amount_tiyin) if p["action"] == "0" else complete(account, p, amount_tiyin)


def _invoice(account, p, *, lock=True) -> Invoice | None:
    number = p["merchant_trans_id"]
    if not number.isdigit():
        return None
    qs = Invoice.objects.filter(company_id=account.company_id, number=int(number))
    invoice = (qs.select_for_update() if lock else qs).first()
    return invoice if invoice is not None and may_take(account, invoice) else None


@transaction.atomic
def prepare(account, p, amount_tiyin: Decimal) -> dict:
    invoice = _invoice(account, p)
    if invoice is None:
        return _reply(p, ORDER_NOT_FOUND)
    if amount_tiyin != invoice.amount_tiyin:
        return _reply(p, BAD_AMOUNT)
    if invoice.status == Invoice.Status.PAID:
        return _reply(p, ALREADY_PAID)
    if invoice.status != Invoice.Status.PENDING:
        return _reply(p, CANCELLED)
    txn, created = ProviderTransaction.objects.get_or_create(
        account=account,
        provider=Provider.CLICK,
        provider_txn_id=p["click_trans_id"],
        defaults={
            "invoice": invoice,
            "amount_tiyin": invoice.amount_tiyin,
            "meta": {"paydoc_id": p["click_paydoc_id"]},
        },
    )
    if txn.invoice_id != invoice.pk:
        return _reply(p, BAD_REQUEST)
    if txn.state == ProviderTransaction.CANCELLED:
        return _reply(p, CANCELLED)
    txn.log("prepare", p | {"sign_string": "…"})
    txn.save(update_fields=["raw"])
    return _reply(p, SUCCESS, merchant_prepare_id=txn.pk)


@transaction.atomic
def complete(account, p, amount_tiyin: Decimal) -> dict:
    prepare_id = p["merchant_prepare_id"]
    txn = (
        ProviderTransaction.objects.select_for_update()
        .filter(pk=int(prepare_id) if prepare_id.isdigit() else 0, account=account, provider=Provider.CLICK)
        .first()
    )
    if txn is None or txn.provider_txn_id != p["click_trans_id"]:
        return _reply(p, TXN_NOT_FOUND)
    invoice = Invoice.objects.select_for_update().get(pk=txn.invoice_id)
    if str(invoice.number) != p["merchant_trans_id"]:
        return _reply(p, ORDER_NOT_FOUND)
    if amount_tiyin != txn.amount_tiyin:
        return _reply(p, BAD_AMOUNT)
    if txn.state == ProviderTransaction.PERFORMED:
        return _reply(p, ALREADY_PAID, merchant_confirm_id=txn.pk)
    if txn.state == ProviderTransaction.CANCELLED:
        return _reply(p, CANCELLED)

    click_error = int(p["error"] or 0) if p["error"].lstrip("-").isdigit() else 0
    if click_error < 0:
        # Click failed to debit the customer.
        txn.state = ProviderTransaction.CANCELLED
        txn.cancelled_at = timezone.now()
        txn.reason = click_error
        txn.log("complete-failed", p | {"sign_string": "…"})
        txn.save(update_fields=["state", "cancelled_at", "reason", "raw"])
        return _reply(p, CANCELLED)

    if invoice.status == Invoice.Status.PAID:
        # Paid meanwhile elsewhere; -4 makes Click return the money.
        return _reply(p, ALREADY_PAID)
    if invoice.status != Invoice.Status.PENDING:
        return _reply(p, CANCELLED)

    txn.state = ProviderTransaction.PERFORMED
    txn.performed_at = timezone.now()
    txn.meta = {**txn.meta, "paydoc_id": p["click_paydoc_id"] or txn.meta.get("paydoc_id", "")}
    txn.log("complete", p | {"sign_string": "…"})
    txn.save(update_fields=["state", "performed_at", "meta", "raw"])
    mark_paid(invoice, txn)
    return _reply(p, SUCCESS, merchant_confirm_id=txn.pk)


# ---------------------------------------------------------------- Merchant API


def auth_header(account: ProviderAccount, ts: int | None = None) -> str:
    ts = ts or int(time.time())
    digest = hashlib.sha1(f"{ts}{account.secret}".encode()).hexdigest()
    return f"{account.merchant_user_id}:{digest}:{ts}"


def submit_fiscal_items(account: ProviderAccount, txn: ProviderTransaction) -> dict:
    """Send receipt lines to Click's OFD bridge after a completed payment."""
    items = []
    for it in receipt_items(txn.invoice):
        total = it["price_tiyin"] * it["count"]
        row = {
            "Name": it["title"][:63],
            "SPIC": it["ikpu_code"],
            "PackageCode": it["package_code"],
            "Price": total,
            "Amount": it["count"],
            "VAT": vat_tiyin(total, it["vat_percent"]),
            "VATPercent": it["vat_percent"],
            "CommissionInfo": {"TIN": txn.invoice.company.tin} if txn.invoice.company.tin else {},
        }
        if it.get("units"):
            row["Units"] = it["units"]
        items.append(row)
    body = {
        "service_id": int(account.service_id),
        "payment_id": int(txn.meta["paydoc_id"]),
        "items": items,
        "received_ecash": txn.amount_tiyin,
        "received_cash": 0,
        "received_card": 0,
    }
    resp = httpx.post(
        f"{settings.CLICK_API_URL}/payment/ofd_data/submit_items",
        json=body,
        headers={"Auth": auth_header(account), "Accept": "application/json"},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def reverse(account: ProviderAccount, txn: ProviderTransaction) -> dict:
    """Refund a completed payment (Merchant API "payment reversal").

    Click only reverses card payments from the current month (or the 1st of
    the next one); anything older has to go through Click support.
    """
    paydoc = txn.meta.get("paydoc_id")
    if not (account.merchant_user_id and paydoc):
        raise ClickApiError("Merchant User ID or Click payment id is missing; refund it in the Click cabinet.")
    resp = httpx.delete(
        f"{settings.CLICK_API_URL}/payment/reversal/{account.service_id}/{paydoc}",
        headers={"Auth": auth_header(account), "Accept": "application/json"},
        timeout=20,
    )
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400 or int(data.get("error_code", -1)) != 0:
        raise ClickApiError(data.get("error_note") or f"Click answered {resp.status_code}")
    return data


class ClickApiError(Exception):
    pass
