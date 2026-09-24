import json

import httpx
import pytest
import respx

from developer import webhooks
from developer.models import ApiKey, WebhookDelivery, WebhookEndpoint
from payments.models import Invoice

from .conftest import basic

HOST = {"HTTP_HOST": "api.uzbridge.test"}


@pytest.fixture
def key(company):
    _, raw = ApiKey.issue(company, "Odoo")
    return raw


def call(client, method, path, key, body=None):
    kw = {**HOST, "HTTP_AUTHORIZATION": f"Bearer {key}"}
    if body is not None:
        return getattr(client, method)(path, data=json.dumps(body), content_type="application/json", **kw)
    return getattr(client, method)(path, **kw)


@pytest.mark.django_db
class TestPublicApi:
    def test_auth(self, client, key, company):
        assert call(client, "get", "/api/v1/ping", "uzb_wrong").status_code == 401
        assert call(client, "get", "/api/v1/ping", key).json()["slug"] == "acme"
        k = ApiKey.objects.get()
        k.revoked_at = k.created_at
        k.save()
        assert call(client, "get", "/api/v1/ping", key).status_code == 401

    def test_invoice_with_items_is_idempotent(self, client, key):
        body = {
            "amount_tiyin": 300_000,
            "reference": "S00042-1",
            "source": "odoo",
            "description": "S00042",
            "return_url": "https://shop.example.uz/payment/status",
            "items": [
                {
                    "title": "Chair",
                    "price_tiyin": 100_000,
                    "count": 2,
                    "ikpu_code": "10305008002000000",
                    "vat_percent": 12,
                },
                {"title": "Delivery", "price_tiyin": 100_000, "count": 1},
            ],
        }
        a = call(client, "post", "/api/v1/invoices", key, body).json()
        b = call(client, "post", "/api/v1/invoices", key, body).json()
        assert a["id"] == b["id"] and a["status"] == "pending" and "/p/" in a["url"]
        inv = Invoice.objects.get()
        assert (inv.source, inv.external_id, len(inv.items)) == ("odoo", "S00042-1", 2)
        assert call(client, "post", "/api/v1/invoices", key, {**body, "amount_tiyin": 1}).status_code == 422
        assert (
            call(client, "post", "/api/v1/invoices", key, {**body, "items": [], "amount_tiyin": 5}).status_code == 409
        )

    def test_other_companys_invoice_is_404(self, client, key, other_company):
        from payments.services import create_invoice

        foreign = create_invoice(other_company, amount_tiyin=100)
        assert call(client, "get", f"/api/v1/invoices/{foreign.public_id}", key).status_code == 404


@pytest.mark.django_db
@respx.mock
def test_paid_event_is_signed_and_delivered(client, key, company, payme_account, django_capture_on_commit_callbacks):
    reg = call(
        client, "post", "/api/v1/webhooks", key, {"url": "https://shop.example.uz/uzbridge/webhook", "label": "odoo"}
    ).json()
    secret = reg["secret"]
    hook = respx.post("https://shop.example.uz/uzbridge/webhook").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    inv = call(
        client, "post", "/api/v1/invoices", key, {"amount_tiyin": 5000, "reference": "TX-1", "source": "odoo"}
    ).json()
    number = Invoice.objects.get().number

    def rpc(method, params):
        return client.post(
            f"/cb/payme/{payme_account.public_id}/",
            data=json.dumps({"method": method, "params": params, "id": 1}),
            content_type="application/json",
            HTTP_AUTHORIZATION=basic("Paycom", "TESTKEY"),
            **HOST,
        ).json()

    rpc("CreateTransaction", {"id": "p1", "time": 1, "amount": 5000, "account": {"order_id": str(number)}})
    with django_capture_on_commit_callbacks(execute=True):
        rpc("PerformTransaction", {"id": "p1"})
    req = hook.calls.last.request
    assert webhooks.verify(secret, req.content, req.headers["X-Uzbridge-Signature"])
    assert not webhooks.verify("whsec_wrong", req.content, req.headers["X-Uzbridge-Signature"])
    event = json.loads(req.content)
    assert event["type"] == "invoice.paid" and event["data"]["id"] == inv["id"] and event["data"]["reference"] == "TX-1"
    assert event["data"]["paid_via"] == "payme" and event["data"]["provider_txn_id"] == "p1"
    assert WebhookDelivery.objects.get().delivered_at is not None


@pytest.mark.django_db
@respx.mock
def test_sms_batch_and_status_event(client, key, company, django_capture_on_commit_callbacks):
    from sms.models import SmsAccount

    SmsAccount.objects.create(
        company=company, is_enabled=True, provider="playmobile", login="pm", secret="x", sender="ACME"
    )
    WebhookEndpoint.objects.create(
        company=company, url="https://shop.example.uz/uzbridge/webhook", secret="whsec_t", events=["sms.status"]
    )
    respx.post("https://send.smsxabar.uz/broker-api/send").mock(
        return_value=httpx.Response(200, text="Request is received")
    )
    hook = respx.post("https://shop.example.uz/uzbridge/webhook").mock(return_value=httpx.Response(200))
    with django_capture_on_commit_callbacks(execute=True):
        r = call(
            client,
            "post",
            "/api/v1/sms",
            key,
            {
                "messages": [
                    {"phone": "901234567", "text": "Salom", "ref": "odoo-uuid-1"},
                    {"phone": "12", "text": "x", "ref": "bad"},
                ]
            },
        )
    out = r.json()["messages"]
    assert out[0]["status"] == "queued" and out[1]["status"] == "failed"
    event = json.loads(hook.calls.last.request.content)
    assert event["type"] == "sms.status" and event["data"]["ref"] == "odoo-uuid-1" and event["data"]["status"] == "sent"


def test_signature_rejects_old_timestamps():
    body = b'{"a":1}'
    header = webhooks.sign("s", body, ts=1_000_000)
    assert not webhooks.verify("s", body, header)


@pytest.mark.django_db
def test_logs_split_by_integration_and_kind(client, owner, company):
    odoo = WebhookEndpoint.objects.create(
        company=company, url="https://erp.example.uz/uzbridge/webhook", secret="s", label="odoo"
    )
    site = WebhookEndpoint.objects.create(company=company, url="https://site.example.uz/hook", secret="s", label="api")
    WebhookDelivery.objects.create(
        endpoint=odoo,
        event="invoice.paid",
        payload={"data": {"number": "INV-00001", "amount": "5 000", "status": "paid", "paid_via": "payme"}},
    )
    WebhookDelivery.objects.create(
        endpoint=odoo, event="sms.status", payload={"data": {"phone": "998901234567", "status": "delivered"}}
    )
    WebhookDelivery.objects.create(endpoint=site, event="invoice.paid", payload={"data": {}})
    client.force_login(owner)

    def get(q):
        return client.get(f"/api/developer/deliveries?{q}", HTTP_HOST="acme.uzbridge.test").json()

    assert [d["event"] for d in get("integration=odoo&kind=payment")] == ["invoice.paid"]
    assert get("integration=odoo&kind=payment")[0]["summary"] == "INV-00001 · 5 000 UZS · paid · payme"
    assert [d["event"] for d in get("integration=odoo&kind=sms")] == ["sms.status"]
    assert len(get("integration=api")) == 1
    csrf = client.get("/api/auth/csrf", HTTP_HOST="acme.uzbridge.test").cookies["csrftoken"].value
    client.post(
        "/api/developer/keys",
        data=json.dumps({"name": "ERP", "integration": "odoo"}),
        content_type="application/json",
        HTTP_HOST="acme.uzbridge.test",
        HTTP_X_CSRFTOKEN=csrf,
    )
    keys = client.get("/api/developer/keys?integration=odoo", HTTP_HOST="acme.uzbridge.test").json()
    assert [k["name"] for k in keys] == ["ERP"]
