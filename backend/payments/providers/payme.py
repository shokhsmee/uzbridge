"""Payme Merchant API: Payme calls us over JSON-RPC 2.0.

Spec: https://developer.help.paycom.uz/metody-merchant-api/
Amounts are tiyin, times are ms. Every reply is HTTP 200; errors go in the
body. Create/Perform/Cancel can arrive twice and must answer the same way.
"""

import base64
import binascii
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from ..models import Invoice, Provider, ProviderAccount, ProviderTransaction
from ..services import mark_paid, mark_refunded, may_take, now_ms, receipt_items, to_ms

TIMEOUT = timedelta(milliseconds=43_200_000)  # 12 h
DEFAULT_ACCOUNT_FIELD = "order_id"

# Our account error codes inside Payme's -31050..-31099 range.
ORDER_NOT_FOUND = -31050
ORDER_NOT_PAYABLE = -31051
ORDER_BUSY = -31052


class RpcError(Exception):
    def __init__(self, code: int, message: str, data=None):
        self.code, self.message, self.data = code, message, data


MESSAGES = {
    -32504: ("Недостаточно привилегий", "Ruxsat yetarli emas", "Insufficient privileges"),
    -32300: ("Метод запроса не POST", "So'rov POST emas", "Request method is not POST"),
    -32700: ("Ошибка разбора JSON", "JSON xatosi", "JSON parse error"),
    -32600: ("Неверный запрос", "Noto'g'ri so'rov", "Invalid request"),
    -32601: ("Метод не найден", "Metod topilmadi", "Method not found"),
    -31001: ("Неверная сумма", "Noto'g'ri summa", "Incorrect amount"),
    -31003: ("Транзакция не найдена", "Tranzaksiya topilmadi", "Transaction not found"),
    -31007: ("Невозможно отменить транзакцию", "Tranzaksiyani bekor qilib bo'lmaydi", "Cannot cancel"),
    -31008: ("Невозможно выполнить операцию", "Amalni bajarib bo'lmaydi", "Unable to perform operation"),
    ORDER_NOT_FOUND: ("Заказ не найден", "Buyurtma topilmadi", "Order not found"),
    ORDER_NOT_PAYABLE: (
        "Заказ уже оплачен или отменён",
        "Buyurtma to'langan yoki bekor qilingan",
        "Order is not payable",
    ),
    ORDER_BUSY: ("Заказ ожидает оплаты", "Buyurtma to'lov kutmoqda", "Order is awaiting another payment"),
}


def _error(code: int, data=None) -> RpcError:
    ru, uz, en = MESSAGES.get(code, ("Системная ошибка", "Tizim xatosi", "System error"))
    return RpcError(code, {"ru": ru, "uz": uz, "en": en}, data)


def field(account: ProviderAccount) -> str:
    """The account field name set on the merchant's Payme cash desk (e.g. order_id)."""
    return account.account_field or DEFAULT_ACCOUNT_FIELD


# ---------------------------------------------------------------- link


def checkout_url(account: ProviderAccount, invoice: Invoice, *, return_url: str = "", lang: str = "uz") -> str:
    parts = [f"m={account.merchant_id}", f"ac.{field(account)}={invoice.number}", f"a={invoice.amount_tiyin}"]
    if return_url:
        parts.append(f"c={return_url}")
    parts.append(f"l={lang}")
    encoded = base64.b64encode(";".join(parts).encode()).decode()
    base = settings.PAYME_TEST_CHECKOUT_URL if account.test_mode else settings.PAYME_CHECKOUT_URL
    return f"{base}/{encoded}"


# ---------------------------------------------------------------- endpoint


def check_auth(account: ProviderAccount, header: str) -> bool:
    if not header.startswith("Basic "):
        return False
    try:
        login, _, password = base64.b64decode(header[6:]).decode().partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return False
    expected = account.active_secret or ""
    return login == "Paycom" and bool(expected) and secrets.compare_digest(password, expected)


def handle(account: ProviderAccount, body: dict, auth_header: str) -> dict:
    rpc_id = body.get("id") if isinstance(body, dict) else None
    try:
        if not check_auth(account, auth_header):
            raise _error(-32504)
        method = body.get("method")
        params = body.get("params")
        if not isinstance(method, str) or not isinstance(params, dict):
            raise _error(-32600)
        fn = METHODS.get(method)
        if fn is None:
            raise _error(-32601)
        return {"jsonrpc": "2.0", "id": rpc_id, "result": fn(account, params)}
    except RpcError as e:
        err = {"code": e.code, "message": e.message}
        if e.data is not None:
            err["data"] = e.data
        return {"jsonrpc": "2.0", "id": rpc_id, "error": err}
    except (KeyError, TypeError, ValueError):
        return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32600, "message": _error(-32600).message}}


def rpc_error(code: int, rpc_id=None) -> dict:
    e = _error(code)
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": e.code, "message": e.message}}


# ---------------------------------------------------------------- methods


def _invoice_for(account: ProviderAccount, params: dict, *, lock: bool) -> Invoice:
    order_id = str((params.get("account") or {}).get(field(account), ""))
    qs = Invoice.objects.filter(company_id=account.company_id)
    if lock:
        qs = qs.select_for_update()
    invoice = qs.filter(number=int(order_id)).first() if order_id.isdigit() else None
    if invoice is not None and not may_take(account, invoice):
        invoice = None  # routed to another cash desk of the company
    if invoice is None:
        raise _error(ORDER_NOT_FOUND, field(account))
    return invoice


def _check_payable(invoice: Invoice, amount, account_field: str = DEFAULT_ACCOUNT_FIELD) -> None:
    if not isinstance(amount, int) or isinstance(amount, bool) or amount != invoice.amount_tiyin:
        raise _error(-31001)
    if invoice.status != Invoice.Status.PENDING:
        raise _error(ORDER_NOT_PAYABLE, account_field)


def _detail(invoice: Invoice) -> dict:
    items = []
    for it in receipt_items(invoice):
        row = {
            "title": it["title"],
            "price": it["price_tiyin"],
            "count": it["count"],
            "code": it["ikpu_code"],
            "package_code": it["package_code"],
            "vat_percent": it["vat_percent"],
        }
        if it.get("units"):
            row["units"] = it["units"]
        items.append(row)
    return {"receipt_type": 0, "items": items}


def check_perform(account, params):
    invoice = _invoice_for(account, params, lock=False)
    _check_payable(invoice, params.get("amount"), field(account))
    return {"allow": True, "detail": _detail(invoice)}


def _txn(account, params, *, lock=True) -> ProviderTransaction:
    qs = ProviderTransaction.objects.filter(account=account, provider=Provider.PAYME, provider_txn_id=str(params["id"]))
    if lock:
        qs = qs.select_for_update()
    txn = qs.select_related("invoice").first()
    if txn is None:
        raise _error(-31003)
    return txn


def _timed_out(txn: ProviderTransaction) -> bool:
    return timezone.now() - txn.created_at > TIMEOUT


def _expire(txn: ProviderTransaction) -> None:
    txn.state = ProviderTransaction.CANCELLED
    txn.reason = 4
    txn.cancelled_at = timezone.now()
    txn.save(update_fields=["state", "reason", "cancelled_at"])


def _create_result(txn):
    return {"create_time": to_ms(txn.created_at), "transaction": str(txn.pk), "state": txn.state}


def create_transaction(account, params):
    # A timed-out transaction must stay cancelled even though we answer with
    # an error, so the expiry is committed on its own before raising.
    expired = False
    with transaction.atomic():
        existing = (
            ProviderTransaction.objects.select_for_update()
            .filter(account=account, provider=Provider.PAYME, provider_txn_id=str(params["id"]))
            .first()
        )
        if existing is not None:
            if existing.state != ProviderTransaction.CREATED:
                raise _error(-31008)
            if _timed_out(existing):
                _expire(existing)
                expired = True
            else:
                return _create_result(existing)
    if expired:
        raise _error(-31008)

    with transaction.atomic():
        invoice = _invoice_for(account, params, lock=True)
        _check_payable(invoice, params.get("amount"), field(account))
        busy = invoice.transactions.filter(provider=Provider.PAYME, state=ProviderTransaction.CREATED)
        if busy.exists():
            # One-time account: a second Payme transaction must wait for the first.
            raise _error(-31008)
        txn = ProviderTransaction(
            invoice=invoice,
            account=account,
            provider=Provider.PAYME,
            provider_txn_id=str(params["id"]),
            amount_tiyin=invoice.amount_tiyin,
            provider_time=int(params["time"]),
        )
        txn.log("create", params)
        txn.save()
        return _create_result(txn)


def perform_transaction(account, params):
    expired = False
    with transaction.atomic():
        txn = _txn(account, params)
        invoice = Invoice.objects.select_for_update().get(pk=txn.invoice_id)
        if txn.state == ProviderTransaction.PERFORMED:
            return {"transaction": str(txn.pk), "perform_time": to_ms(txn.performed_at), "state": txn.state}
        if txn.state != ProviderTransaction.CREATED:
            raise _error(-31008)
        if _timed_out(txn):
            _expire(txn)
            expired = True
        elif invoice.status != Invoice.Status.PENDING:
            # Paid meanwhile through Click or Uzum; Payme will cancel this one.
            raise _error(-31008)
        else:
            txn.state = ProviderTransaction.PERFORMED
            txn.performed_at = timezone.now()
            txn.log("perform", params)
            txn.save(update_fields=["state", "performed_at", "raw"])
            mark_paid(invoice, txn)
            return {"transaction": str(txn.pk), "perform_time": to_ms(txn.performed_at), "state": txn.state}
    if expired:
        raise _error(-31008)


def cancel_transaction(account, params):
    with transaction.atomic():
        txn = _txn(account, params)
        invoice = Invoice.objects.select_for_update().get(pk=txn.invoice_id)
        if txn.state in (ProviderTransaction.CANCELLED, ProviderTransaction.CANCELLED_AFTER):
            return {"transaction": str(txn.pk), "cancel_time": to_ms(txn.cancelled_at), "state": txn.state}
        was_performed = txn.state == ProviderTransaction.PERFORMED
        txn.state = ProviderTransaction.CANCELLED_AFTER if was_performed else ProviderTransaction.CANCELLED
        txn.reason = int(params.get("reason") or 10)
        txn.cancelled_at = timezone.now()
        txn.log("cancel", params)
        txn.save(update_fields=["state", "reason", "cancelled_at", "raw"])
        if was_performed and invoice.status == Invoice.Status.PAID and invoice.paid_via == Provider.PAYME:
            mark_refunded(invoice)
        return {"transaction": str(txn.pk), "cancel_time": to_ms(txn.cancelled_at), "state": txn.state}


def check_transaction(account, params):
    txn = _txn(account, params, lock=False)
    return {
        "create_time": to_ms(txn.created_at),
        "perform_time": to_ms(txn.performed_at),
        "cancel_time": to_ms(txn.cancelled_at),
        "transaction": str(txn.pk),
        "state": txn.state,
        "reason": txn.reason,
    }


def get_statement(account, params):
    rows = (
        ProviderTransaction.objects.filter(
            account=account,
            provider=Provider.PAYME,
            provider_time__gte=int(params["from"]),
            provider_time__lte=int(params["to"]),
        )
        .select_related("invoice")
        .order_by("provider_time")
    )
    return {
        "transactions": [
            {
                "id": t.provider_txn_id,
                "time": t.provider_time,
                "amount": t.amount_tiyin,
                "account": {field(account): str(t.invoice.number)},
                "create_time": to_ms(t.created_at),
                "perform_time": to_ms(t.performed_at),
                "cancel_time": to_ms(t.cancelled_at),
                "transaction": str(t.pk),
                "state": t.state,
                "reason": t.reason,
            }
            for t in rows
        ]
    }


def set_fiscal_data(account, params):
    with transaction.atomic():
        txn = _txn(account, params)
        kind = str(params.get("type", "PERFORM")).lower()
        txn.fiscal = {**txn.fiscal, kind: params.get("fiscal_data") or {}}
        txn.save(update_fields=["fiscal"])
    return {"success": True}


METHODS = {
    "CheckPerformTransaction": check_perform,
    "CreateTransaction": create_transaction,
    "PerformTransaction": perform_transaction,
    "CancelTransaction": cancel_transaction,
    "CheckTransaction": check_transaction,
    "GetStatement": get_statement,
    "SetFiscalData": set_fiscal_data,
}

__all__ = ["checkout_url", "handle", "rpc_error", "now_ms"]
