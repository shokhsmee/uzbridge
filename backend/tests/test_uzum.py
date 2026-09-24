import json

import httpx
import pytest
import respx

from payments.models import Invoice, ProviderTransaction
from payments.providers import uzum

BASE = "https://test-chk-api.uzumcheckout.uz"


def register_mock(order_id="ord-1"):
    return respx.post(f"{BASE}/api/v1/payment/register").mock(
        return_value=httpx.Response(
            200,
            json={
                "errorCode": 0,
                "result": {"orderId": order_id, "paymentRedirectUrl": f"https://pay.uzum/{order_id}"},
            },
        )
    )


def status_mock(status, amount):
    return respx.post(f"{BASE}/api/v1/payment/getOrderStatus").mock(
        return_value=httpx.Response(
            200, json={"errorCode": 0, "result": {"status": status, "amount": amount, "completedAmount": amount}}
        )
    )


@pytest.mark.django_db
class TestUzum:
    @respx.mock
    def test_register_and_reuse(self, uzum_account, invoice):
        route = register_mock()
        url = uzum.redirect_url(uzum_account, invoice, success_url="https://s", failure_url="https://f")
        assert url == "https://pay.uzum/ord-1"
        body = json.loads(route.calls.last.request.content)
        assert body["amount"] == invoice.amount_tiyin and body["currency"] == 860
        assert body["orderNumber"] == f"{invoice.number}-1" and "merchantParams" not in body
        headers = route.calls.last.request.headers
        assert headers["X-Terminal-Id"] == uzum_account.merchant_id and headers["X-API-Key"] == uzum_account.secret
        # A second click within the session reuses the order.
        assert uzum.redirect_url(uzum_account, invoice, success_url="https://s", failure_url="https://f") == url
        assert route.call_count == 1

    @respx.mock
    def test_auto_fiscal_sends_cart(self, uzum_account, invoice):
        uzum_account.auto_fiscal = True
        uzum_account.save()
        route = register_mock()
        uzum.redirect_url(uzum_account, invoice, success_url="https://s", failure_url="https://f")
        cart = json.loads(route.calls.last.request.content)["merchantParams"]["cart"]
        assert cart["total"] == invoice.amount_tiyin and cart["items"][0]["receiptParams"]["TIN"] == "123456789"

    @respx.mock
    def test_callback_is_verified_with_uzum(self, client, uzum_account, invoice, django_capture_on_commit_callbacks):
        register_mock()
        uzum.redirect_url(uzum_account, invoice, success_url="https://s", failure_url="https://f")
        status_mock("COMPLETED", invoice.amount_tiyin)
        with django_capture_on_commit_callbacks(execute=True):
            r = client.post(
                f"/cb/uzum/{uzum_account.public_id}/",
                data=json.dumps({"orderId": "ord-1", "operationState": "SUCCESS", "operationType": "COMPLETE"}),
                content_type="application/json",
                HTTP_HOST="api.uzbridge.test",
            )
        assert r.status_code == 200
        invoice.refresh_from_db()
        assert (invoice.status, invoice.paid_via) == ("paid", "uzum")

    @respx.mock
    def test_forged_callback_does_nothing(self, client, uzum_account, invoice):
        """Callbacks aren't signed; what Uzum's API says is what counts."""
        register_mock()
        uzum.redirect_url(uzum_account, invoice, success_url="https://s", failure_url="https://f")
        status_mock("DECLINED", invoice.amount_tiyin)
        client.post(
            f"/cb/uzum/{uzum_account.public_id}/",
            data=json.dumps({"orderId": "ord-1", "operationState": "SUCCESS", "operationType": "COMPLETE"}),
            content_type="application/json",
            HTTP_HOST="api.uzbridge.test",
        )
        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.PENDING
        assert ProviderTransaction.objects.get().state == ProviderTransaction.CANCELLED

    @respx.mock
    def test_amount_mismatch_is_not_paid(self, uzum_account, invoice):
        register_mock()
        uzum.redirect_url(uzum_account, invoice, success_url="https://s", failure_url="https://f")
        status_mock("COMPLETED", 100)
        uzum.verify(ProviderTransaction.objects.get().pk)
        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.PENDING

    @respx.mock
    def test_refund_after_paid(self, uzum_account, invoice, django_capture_on_commit_callbacks):
        register_mock()
        uzum.redirect_url(uzum_account, invoice, success_url="https://s", failure_url="https://f")
        txn = ProviderTransaction.objects.get()
        status_mock("COMPLETED", invoice.amount_tiyin)
        uzum.verify(txn.pk)
        status_mock("REFUNDED", invoice.amount_tiyin)
        with django_capture_on_commit_callbacks(execute=True):
            uzum.verify(txn.pk)
        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.REFUNDED

    @respx.mock
    def test_register_error(self, uzum_account, invoice):
        respx.post(f"{BASE}/api/v1/payment/register").mock(
            return_value=httpx.Response(200, json={"errorCode": 1001, "message": "bad terminal"})
        )
        with pytest.raises(uzum.UzumError):
            uzum.redirect_url(uzum_account, invoice, success_url="https://s", failure_url="https://f")
        assert not ProviderTransaction.objects.exists()
