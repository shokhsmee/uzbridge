# ruff: noqa: F811  (pytest fixture imported from test_amocrm)
"""The widget's page in amoCRM (Настройки → uzbridge): providers, SMS, templates."""

import json

import httpx
import pytest
import respx

from sms.models import SmsAccount, SmsTemplate
from tests.test_amocrm import HOST, conn, widget_token  # noqa: F401  (fixture)

KW = {"HTTP_HOST": "api.uzbridge.test"}


def call(client, method, path, body=None):
    kw = {"HTTP_X_AUTH_TOKEN": widget_token(), **KW}
    if body is not None:
        return getattr(client, method)(path, data=json.dumps(body), content_type="application/json", **kw)
    return getattr(client, method)(path, **kw)


@pytest.fixture
def playmobile(company):
    return SmsAccount.objects.create(
        company=company, is_enabled=True, provider="playmobile", login="pm", secret="pm-pass", sender="ACME"
    )


@pytest.fixture
def templates(company, playmobile):
    return [
        SmsTemplate.objects.create(company=company, provider="playmobile", text="Toʻlov: {link}"),
        SmsTemplate.objects.create(company=company, provider="playmobile", text="Rahmat, {name}!"),
    ]


def admin(is_admin=True):
    respx.get(f"https://{HOST}/api/v4/users/42").mock(
        return_value=httpx.Response(200, json={"id": 42, "rights": {"is_admin": is_admin}})
    )


@pytest.mark.django_db
def test_settings_lists_providers_sms_and_templates(client, conn, payme_account, templates, playmobile):
    r = call(client, "get", "/api/widget/settings")
    assert r.status_code == 200, r.content
    body = r.json()
    by_code = {p["code"]: p for p in body["providers"]}
    [payme] = by_code["payme"]["accounts"]
    assert payme["id"] == payme_account.pk and payme["active"] and payme["use"]
    assert by_code["click"]["accounts"] == []  # none connected
    sms = body["sms"]
    assert (sms["ready"], sms["provider"], sms["enabled"], sms["account_id"]) == (
        True,
        "Playmobile",
        True,
        playmobile.pk,
    )
    assert [t["use"] for t in body["templates"]] == [True, True]


@pytest.mark.django_db
@respx.mock
def test_switches_narrow_what_amocrm_sees(client, conn, payme_account, templates):
    admin()
    respx.get(f"https://{HOST}/api/v4/leads/custom_fields").mock(
        return_value=httpx.Response(200, json={"_embedded": {"custom_fields": []}})
    )
    field = respx.post(f"https://{HOST}/api/v4/leads/custom_fields").mock(
        return_value=httpx.Response(200, json={"_embedded": {"custom_fields": [{"id": 900, "enums": []}]}})
    )
    respx.get(f"https://{HOST}/api/v4/webhooks").mock(return_value=httpx.Response(200, json={}))
    respx.post(f"https://{HOST}/api/v4/webhooks").mock(return_value=httpx.Response(200, json={}))
    off = templates[1]
    r = call(
        client, "put", "/api/widget/settings", {"accounts": [], "sms_enabled": True, "templates": {str(off.pk): False}}
    )
    assert r.status_code == 200, r.content
    # The lead's select field now carries only the template left on.
    sent = json.loads(field.calls[0].request.content)[0]["enums"]
    assert [e["value"] for e in sent] == [templates[0].title]

    ctx = call(client, "get", "/api/widget/context?lead_id=9001").json()
    assert ctx["providers"] == []  # no provider chosen for amoCRM
    assert [t["id"] for t in ctx["sms_templates"]] == [templates[0].pk]
    assert call(client, "post", "/api/widget/invoices", {"lead_id": 9001, "amount": "1000"}).status_code == 409
    blocked = call(client, "post", "/api/widget/sms/template", {"lead_id": 9001, "template_id": off.pk})
    assert blocked.status_code == 422


@pytest.mark.django_db
@respx.mock
def test_sms_off_hides_it_everywhere(client, conn, templates):
    admin()
    respx.get(f"https://{HOST}/api/v4/leads/custom_fields").mock(
        return_value=httpx.Response(200, json={"_embedded": {"custom_fields": []}})
    )
    respx.post(f"https://{HOST}/api/v4/leads/custom_fields").mock(
        return_value=httpx.Response(200, json={"_embedded": {"custom_fields": [{"id": 900, "enums": []}]}})
    )
    respx.get(f"https://{HOST}/api/v4/webhooks").mock(return_value=httpx.Response(200, json={}))
    respx.post(f"https://{HOST}/api/v4/webhooks").mock(return_value=httpx.Response(200, json={}))
    assert call(client, "put", "/api/widget/settings", {"accounts": [], "sms_enabled": False}).status_code == 200
    ctx = call(client, "get", "/api/widget/context?lead_id=9001").json()
    assert (ctx["sms_ready"], ctx["sms_templates"]) == (False, [])
    r = call(client, "post", "/api/widget/sms", {"phone": 998901234567, "message": "hi", "lead_id": 9001})
    assert r.status_code == 409


@pytest.mark.django_db
@respx.mock
def test_only_amocrm_admins_change_settings(client, conn, payme_account):
    admin(is_admin=False)
    r = call(client, "put", "/api/widget/settings", {"accounts": [], "sms_enabled": False})
    assert r.status_code == 403
    conn.refresh_from_db()
    assert (conn.payment_accounts, conn.sms_enabled) == (None, True)


@pytest.mark.django_db
def test_pay_page_follows_amocrm_choice(client, conn, payme_account, company):
    from payments.models import Invoice, ProviderAccount
    from payments.services import create_invoice

    click = ProviderAccount.objects.create(
        company=company,
        is_enabled=True,
        provider="click",
        merchant_id="1",
        service_id="2",
        merchant_user_id="3",
        secret="s",
    )
    conn.payment_accounts = [click.pk]
    conn.save()
    inv = create_invoice(
        company, amount_tiyin=100000, source=Invoice.Source.AMOCRM, external_id="1", amo_connection=conn
    )
    page = client.get(f"/p/{inv.public_id}/", HTTP_HOST="acme.uzbridge.test").content.decode()
    assert "go/click/" in page and "go/payme/" not in page
