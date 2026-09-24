"""Replays the Payme sandbox scenarios (https://developer.help.paycom.uz/pesochnitsa)."""

import base64
import json
from datetime import timedelta

import pytest
from django.utils import timezone

from payments.models import Invoice, ProviderTransaction
from payments.providers import payme

from .conftest import basic

AUTH = basic("Paycom", "TESTKEY")


def rpc(client, account, method, params, auth=AUTH, rpc_id=1):
    resp = client.post(
        f"/cb/payme/{account.public_id}/",
        data=json.dumps({"method": method, "params": params, "id": rpc_id}),
        content_type="application/json",
        HTTP_AUTHORIZATION=auth,
        HTTP_HOST="api.uzbridge.test",
    )
    assert resp.status_code == 200
    return resp.json()


def acc(invoice):
    return {"order_id": str(invoice.number)}


def create(client, account, invoice, txn_id="6385f0c5d9c5b7a8c3f1a001", amount=None, time_ms=1_700_000_000_000):
    return rpc(
        client,
        account,
        "CreateTransaction",
        {"id": txn_id, "time": time_ms, "amount": amount or invoice.amount_tiyin, "account": acc(invoice)},
    )


@pytest.mark.django_db
class TestScenario1:
    def test_bad_auth(self, client, payme_account, invoice):
        r = rpc(
            client,
            payme_account,
            "CheckPerformTransaction",
            {"amount": 1, "account": acc(invoice)},
            auth=basic("Paycom", "nope"),
        )
        assert r["error"]["code"] == -32504
        r = rpc(client, payme_account, "CheckPerformTransaction", {"amount": 1, "account": acc(invoice)}, auth="")
        assert r["error"]["code"] == -32504

    def test_prod_key_rejected_in_test_mode(self, client, payme_account, invoice):
        r = rpc(
            client,
            payme_account,
            "CheckPerformTransaction",
            {"amount": 1, "account": acc(invoice)},
            auth=basic("Paycom", "PRODKEY"),
        )
        assert r["error"]["code"] == -32504

    def test_wrong_amount(self, client, payme_account, invoice):
        r = rpc(client, payme_account, "CheckPerformTransaction", {"amount": 1, "account": acc(invoice)})
        assert r["error"]["code"] == -31001

    def test_missing_account(self, client, payme_account, invoice):
        r = rpc(
            client,
            payme_account,
            "CheckPerformTransaction",
            {"amount": invoice.amount_tiyin, "account": {"order_id": "999"}},
        )
        assert r["error"]["code"] == payme.ORDER_NOT_FOUND
        assert r["error"]["data"] == "order_id"
        assert set(r["error"]["message"]) == {"ru", "uz", "en"}

    def test_other_company_invoice_is_invisible(self, client, payme_account, other_company):
        from payments.services import create_invoice

        foreign = create_invoice(other_company, amount_tiyin=500)
        r = rpc(client, payme_account, "CheckPerformTransaction", {"amount": 500, "account": acc(foreign)})
        assert r["error"]["code"] == payme.ORDER_NOT_FOUND

    def test_check_perform_returns_fiscal_detail(self, client, payme_account, invoice):
        from payments.models import FiscalDefaults

        FiscalDefaults.objects.create(
            company=invoice.company, ikpu_code="10305008002000000", package_code="1500553", vat_percent=12
        )
        r = rpc(
            client, payme_account, "CheckPerformTransaction", {"amount": invoice.amount_tiyin, "account": acc(invoice)}
        )
        assert r["result"]["allow"] is True
        item = r["result"]["detail"]["items"][0]
        assert item == {
            "title": "Consulting",
            "price": invoice.amount_tiyin,
            "count": 1,
            "code": "10305008002000000",
            "package_code": "1500553",
            "vat_percent": 12,
        }

    def test_create_twice_is_idempotent_and_second_txn_rejected(self, client, payme_account, invoice):
        first = create(client, payme_account, invoice)
        assert first["result"]["state"] == 1
        again = create(client, payme_account, invoice)
        assert again["result"] == first["result"]
        other = create(client, payme_account, invoice, txn_id="6385f0c5d9c5b7a8c3f1a002")
        assert other["error"]["code"] == -31008

    def test_check_transaction(self, client, payme_account, invoice):
        created = create(client, payme_account, invoice)["result"]
        r = rpc(client, payme_account, "CheckTransaction", {"id": "6385f0c5d9c5b7a8c3f1a001"})["result"]
        assert r == {
            "create_time": created["create_time"],
            "perform_time": 0,
            "cancel_time": 0,
            "transaction": created["transaction"],
            "state": 1,
            "reason": None,
        }
        assert rpc(client, payme_account, "CheckTransaction", {"id": "nope"})["error"]["code"] == -31003

    def test_cancel_created(self, client, payme_account, invoice):
        create(client, payme_account, invoice)
        r = rpc(client, payme_account, "CancelTransaction", {"id": "6385f0c5d9c5b7a8c3f1a001", "reason": 3})["result"]
        assert r["state"] == -1
        again = rpc(client, payme_account, "CancelTransaction", {"id": "6385f0c5d9c5b7a8c3f1a001", "reason": 3})[
            "result"
        ]
        assert again == r
        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.PENDING
        # After a cancel the order can be paid with a new transaction.
        assert create(client, payme_account, invoice, txn_id="6385f0c5d9c5b7a8c3f1a003")["result"]["state"] == 1

    def test_timeout(self, client, payme_account, invoice):
        create(client, payme_account, invoice)
        ProviderTransaction.objects.update(created_at=timezone.now() - timedelta(hours=12, minutes=1))
        r = rpc(client, payme_account, "PerformTransaction", {"id": "6385f0c5d9c5b7a8c3f1a001"})
        assert r["error"]["code"] == -31008
        txn = ProviderTransaction.objects.get()
        assert (txn.state, txn.reason) == (-1, 4)


@pytest.mark.django_db
class TestScenario2:
    def test_perform_then_cancel_after(self, client, payme_account, invoice, django_capture_on_commit_callbacks):
        create(client, payme_account, invoice)
        with django_capture_on_commit_callbacks(execute=True):
            r = rpc(client, payme_account, "PerformTransaction", {"id": "6385f0c5d9c5b7a8c3f1a001"})["result"]
        assert r["state"] == 2 and r["perform_time"] > 0
        again = rpc(client, payme_account, "PerformTransaction", {"id": "6385f0c5d9c5b7a8c3f1a001"})["result"]
        assert again == r
        invoice.refresh_from_db()
        assert (invoice.status, invoice.paid_via) == ("paid", "payme")

        # Paid order: nothing more can be created against it.
        assert (
            create(client, payme_account, invoice, txn_id="6385f0c5d9c5b7a8c3f1a004")["error"]["code"]
            == payme.ORDER_NOT_PAYABLE
        )

        r = rpc(client, payme_account, "CancelTransaction", {"id": "6385f0c5d9c5b7a8c3f1a001", "reason": 5})["result"]
        assert r["state"] == -2
        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.REFUNDED

    def test_get_statement(self, client, payme_account, invoice):
        create(client, payme_account, invoice, time_ms=1_700_000_000_000)
        r = rpc(client, payme_account, "GetStatement", {"from": 1_699_999_999_000, "to": 1_700_000_001_000})["result"]
        assert len(r["transactions"]) == 1
        t = r["transactions"][0]
        assert t["id"] == "6385f0c5d9c5b7a8c3f1a001" and t["account"] == acc(invoice) and t["state"] == 1
        empty = rpc(client, payme_account, "GetStatement", {"from": 1, "to": 2})["result"]
        assert empty == {"transactions": []}


@pytest.mark.django_db
def test_protocol_errors(client, payme_account):
    url = f"/cb/payme/{payme_account.public_id}/"
    assert client.get(url, HTTP_HOST="api.uzbridge.test").json()["error"]["code"] == -32300
    r = client.post(url, data="{oops", content_type="application/json", HTTP_HOST="api.uzbridge.test")
    assert r.json()["error"]["code"] == -32700
    r = rpc(client, payme_account, "Nope", {})
    assert r["error"]["code"] == -32601


def test_checkout_url(payme_account, invoice):
    url = payme.checkout_url(payme_account, invoice, return_url="https://acme.uzbridge.test/p/x/", lang="ru")
    assert url.startswith("https://test.paycom.uz/")
    decoded = base64.b64decode(url.rsplit("/", 1)[1]).decode()
    assert decoded == (
        f"m=5e730e8e0b852a417aa49ceb;ac.order_id={invoice.number};a=15000000;c=https://acme.uzbridge.test/p/x/;l=ru"
    )
