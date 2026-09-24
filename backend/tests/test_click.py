import hashlib

import httpx
import pytest
import respx

from payments.models import Invoice, ProviderTransaction
from payments.providers import click

SIGN_TIME = "2026-09-24 12:00:00"


def signed(account, invoice, action, click_trans_id="900001", amount=None, prepare_id="", error="0", secret=None):
    amount = amount or invoice.amount_soum
    p = {
        "click_trans_id": click_trans_id,
        "service_id": account.service_id,
        "click_paydoc_id": "555001",
        "merchant_trans_id": str(invoice.number),
        "amount": amount,
        "action": str(action),
        "error": error,
        "error_note": "Success",
        "sign_time": SIGN_TIME,
    }
    if action == 1:
        p["merchant_prepare_id"] = str(prepare_id)
    parts = [p["click_trans_id"], p["service_id"], secret or account.secret, p["merchant_trans_id"]]
    if action == 1:
        parts.append(p["merchant_prepare_id"])
    parts += [p["amount"], p["action"], p["sign_time"]]
    p["sign_string"] = hashlib.md5("".join(parts).encode()).hexdigest()
    return p


def post(client, account, data):
    r = client.post(f"/cb/click/{account.public_id}/", data=data, HTTP_HOST="api.uzbridge.test")
    assert r.status_code == 200
    return r.json()


@pytest.mark.django_db
class TestClick:
    def test_prepare_complete(self, client, click_account, invoice, django_capture_on_commit_callbacks):
        r = post(client, click_account, signed(click_account, invoice, 0))
        assert r["error"] == 0 and r["merchant_prepare_id"]
        # Prepare repeated with the same click_trans_id gives the same id.
        assert (
            post(client, click_account, signed(click_account, invoice, 0))["merchant_prepare_id"]
            == r["merchant_prepare_id"]
        )

        with respx.mock:
            route = respx.post("https://api.click.uz/v2/merchant/payment/ofd_data/submit_items").mock(
                return_value=httpx.Response(200, json={"error_code": 0})
            )
            with django_capture_on_commit_callbacks(execute=True):
                c = post(client, click_account, signed(click_account, invoice, 1, prepare_id=r["merchant_prepare_id"]))
        assert c["error"] == 0 and c["merchant_confirm_id"] == r["merchant_prepare_id"]
        invoice.refresh_from_db()
        assert (invoice.status, invoice.paid_via) == ("paid", "click")

        # Fiscal receipt went to Click with the Merchant API auth header.
        sent = route.calls.last.request
        user_id, digest, ts = sent.headers["Auth"].split(":")
        assert user_id == "33333" and digest == hashlib.sha1(f"{ts}CLICKSECRET".encode()).hexdigest()
        txn = ProviderTransaction.objects.get()
        assert txn.fiscal["submitted"] is True

        again = post(client, click_account, signed(click_account, invoice, 1, prepare_id=r["merchant_prepare_id"]))
        assert again["error"] == click.ALREADY_PAID
        assert (
            post(client, click_account, signed(click_account, invoice, 0, click_trans_id="900002"))["error"]
            == click.ALREADY_PAID
        )

    def test_bad_sign(self, client, click_account, invoice):
        assert (
            post(client, click_account, signed(click_account, invoice, 0, secret="wrong"))["error"] == click.SIGN_FAILED
        )

    def test_amount_must_match_exactly(self, client, click_account, invoice):
        assert (
            post(client, click_account, signed(click_account, invoice, 0, amount="150000.01"))["error"]
            == click.BAD_AMOUNT
        )
        # Same value written differently is fine: the sign covers the raw string.
        assert post(client, click_account, signed(click_account, invoice, 0, amount="150000"))["error"] == 0

    def test_unknown_order_and_action(self, client, click_account, invoice):
        p = signed(click_account, invoice, 0)
        p["merchant_trans_id"] = "999"
        parts = [p["click_trans_id"], p["service_id"], click_account.secret, "999", p["amount"], "0", SIGN_TIME]
        p["sign_string"] = hashlib.md5("".join(parts).encode()).hexdigest()
        assert post(client, click_account, p)["error"] == click.ORDER_NOT_FOUND
        bad = signed(click_account, invoice, 0)
        bad["action"] = "7"
        assert post(client, click_account, bad)["error"] == click.ACTION_NOT_FOUND
        assert post(client, click_account, {"click_trans_id": "1"})["error"] == click.BAD_REQUEST

    def test_complete_with_click_error_cancels(self, client, click_account, invoice):
        r = post(client, click_account, signed(click_account, invoice, 0))
        c = post(
            client, click_account, signed(click_account, invoice, 1, prepare_id=r["merchant_prepare_id"], error="-5017")
        )
        assert c["error"] == click.CANCELLED
        assert ProviderTransaction.objects.get().state == ProviderTransaction.CANCELLED
        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.PENDING

    def test_complete_unknown_prepare(self, client, click_account, invoice):
        assert (
            post(client, click_account, signed(click_account, invoice, 1, prepare_id="424242"))["error"]
            == click.TXN_NOT_FOUND
        )

    def test_paid_elsewhere_between_prepare_and_complete(self, client, click_account, invoice):
        r = post(client, click_account, signed(click_account, invoice, 0))
        Invoice.objects.filter(pk=invoice.pk).update(status="paid", paid_via="payme")
        c = post(client, click_account, signed(click_account, invoice, 1, prepare_id=r["merchant_prepare_id"]))
        assert c["error"] == click.ALREADY_PAID

    def test_cancelled_invoice(self, client, click_account, invoice):
        Invoice.objects.filter(pk=invoice.pk).update(status="cancelled")
        assert post(client, click_account, signed(click_account, invoice, 0))["error"] == click.CANCELLED


def test_pay_url(click_account, invoice):
    url = click.pay_url(click_account, invoice, return_url="https://acme.uzbridge.test/p/x/?r=1")
    assert url.startswith("https://my.click.uz/services/pay?service_id=22222&merchant_id=11111&amount=150000.00")
    assert f"transaction_param={invoice.number}" in url


@pytest.mark.django_db
@respx.mock
def test_refund_from_dashboard(client, owner, click_account, invoice, django_capture_on_commit_callbacks):
    respx.post("https://api.click.uz/v2/merchant/payment/ofd_data/submit_items").mock(
        return_value=httpx.Response(200, json={})
    )
    r = post(client, click_account, signed(click_account, invoice, 0))
    post(client, click_account, signed(click_account, invoice, 1, prepare_id=r["merchant_prepare_id"]))
    reversal = respx.delete("https://api.click.uz/v2/merchant/payment/reversal/22222/555001").mock(
        return_value=httpx.Response(200, json={"error_code": 0, "error_note": "Success", "payment_id": 555001})
    )
    client.force_login(owner)
    csrf = client.get("/api/auth/csrf", HTTP_HOST="acme.uzbridge.test").cookies["csrftoken"].value
    resp = client.post(
        f"/api/payments/invoices/{invoice.public_id}/refund", HTTP_HOST="acme.uzbridge.test", HTTP_X_CSRFTOKEN=csrf
    )
    assert resp.status_code == 200, resp.content
    assert resp.json()["status"] == "refunded" and reversal.called
    assert ProviderTransaction.objects.get().state == ProviderTransaction.CANCELLED_AFTER


@pytest.mark.django_db
@respx.mock
def test_refund_error_is_reported(owner, click_account, invoice, client):
    from payments.services import RefundError, refund_invoice

    r = post(client, click_account, signed(click_account, invoice, 0))
    respx.post("https://api.click.uz/v2/merchant/payment/ofd_data/submit_items").mock(
        return_value=httpx.Response(200, json={})
    )
    post(client, click_account, signed(click_account, invoice, 1, prepare_id=r["merchant_prepare_id"]))
    respx.delete(url__startswith="https://api.click.uz/v2/merchant/payment/reversal/").mock(
        return_value=httpx.Response(400, json={"error_code": -5017, "error_note": "Payment is older than this month"})
    )
    invoice.refresh_from_db()
    with pytest.raises(RefundError, match="older"):
        refund_invoice(invoice)
    invoice.refresh_from_db()
    assert invoice.status == Invoice.Status.PAID
