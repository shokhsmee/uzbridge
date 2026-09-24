# ruff: noqa: F811  (pytest fixture imported from test_amocrm)
"""Company {keywords} in SMS texts: amoCRM fields (set in amoCRM) and Odoo field paths (set on the site)."""

import json

import httpx
import pytest
import respx

from amocrm.client import AmoClient
from amocrm.variables import values_for_lead
from sms.models import SmsVariable
from sms.services import render
from tests.test_amocrm import HOST, conn, widget_token  # noqa: F401

KW = {"HTTP_HOST": "api.uzbridge.test"}


@pytest.mark.django_db
@respx.mock
def test_amocrm_keywords_come_from_lead_and_contact(conn, company):
    for key, source in (
        ("muddat", "lead.cf.501"),
        ("summa", "lead.price"),
        ("manzil", "contact.cf.702"),
        ("menejer", "lead.responsible"),
    ):
        SmsVariable.objects.create(company=company, integration="amocrm", key=key, source=source)
    respx.get(f"https://{HOST}/api/v4/leads/9001").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 9001,
                "price": 1500000,
                "responsible_user_id": 7,
                "custom_fields_values": [{"field_id": 501, "field_type": "date", "values": [{"value": 1790276400}]}],
                "_embedded": {"contacts": [{"id": 5, "is_main": True}]},
            },
        )
    )
    respx.get(f"https://{HOST}/api/v4/contacts/5").mock(
        return_value=httpx.Response(
            200, json={"name": "Ali", "custom_fields_values": [{"field_id": 702, "values": [{"value": "Toshkent"}]}]}
        )
    )
    respx.get(f"https://{HOST}/api/v4/users/7").mock(return_value=httpx.Response(200, json={"name": "Dilnoza"}))
    values = values_for_lead(conn, AmoClient(conn), 9001)
    assert values == {"muddat": "25.09.2026", "summa": "1 500 000", "manzil": "Toshkent", "menejer": "Dilnoza"}
    text = render("{name}, {summa} soʻm {muddat} gacha. {yoq}", company=company, name="Ali", extra=values)
    assert text == "Ali, 1 500 000 soʻm 25.09.2026 gacha. {yoq}"


@pytest.mark.django_db
@respx.mock
def test_amocrm_keywords_saved_from_amocrm_by_admins_only(client, conn, company):
    respx.get(f"https://{HOST}/api/v4/users/42").mock(
        return_value=httpx.Response(200, json={"rights": {"is_admin": True}})
    )
    respx.get(f"https://{HOST}/api/v4/leads/custom_fields").mock(
        return_value=httpx.Response(
            200, json={"_embedded": {"custom_fields": [{"id": 501, "name": "Muddat", "type": "date"}]}}
        )
    )
    respx.get(f"https://{HOST}/api/v4/contacts/custom_fields").mock(
        return_value=httpx.Response(
            200,
            json={"_embedded": {"custom_fields": [{"id": 1, "name": "Телефон", "type": "multitext", "code": "PHONE"}]}},
        )
    )
    kw = {"HTTP_X_AUTH_TOKEN": widget_token(), **KW}

    def put(rows):
        return client.put("/api/widget/variables", data=json.dumps(rows), content_type="application/json", **kw)

    assert put([{"key": "name", "source": "lead.name"}]).status_code == 422  # built-in
    assert put([{"key": "x", "source": "lead.cf.abc"}]).status_code == 422
    assert put([{"key": "a", "source": "lead.id"}, {"key": "a", "source": "lead.name"}]).status_code == 422
    r = put([{"key": "{Muddat}", "source": "lead.cf.501"}])
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["variables"] == [{"key": "muddat", "source": "lead.cf.501", "label": ""}]
    labels = {s["value"]: s["label"] for s in body["sources"]}
    assert labels["lead.cf.501"] == "Muddat" and "contact.cf.1" not in labels  # phone isn't offered

    respx.get(f"https://{HOST}/api/v4/users/42").mock(
        return_value=httpx.Response(200, json={"rights": {"is_admin": False}})
    )
    assert put([]).status_code == 403


@pytest.mark.django_db
def test_odoo_keywords_set_on_site_and_served_to_the_addon(client, company, owner):
    from developer.models import ApiKey

    client.force_login(owner)
    csrf = client.get("/api/auth/csrf", HTTP_HOST="acme.uzbridge.test").cookies["csrftoken"].value
    kw = {"HTTP_HOST": "acme.uzbridge.test", "HTTP_X_CSRFTOKEN": csrf}
    bad = client.put(
        "/api/sms/variables/odoo",
        data=json.dumps([{"key": "m", "source": "partner_id.__class__"}]),
        content_type="application/json",
        **kw,
    )
    assert bad.status_code == 422
    ok = client.put(
        "/api/sms/variables/odoo",
        data=json.dumps([{"key": "muddat", "source": "invoice_date_due", "label": "Srok"}]),
        content_type="application/json",
        **kw,
    )
    assert ok.status_code == 200, ok.content
    assert client.get("/api/sms/variables/amocrm", **kw).json()["variables"] == []

    key, raw = ApiKey.issue(company, name="Odoo", integration="odoo")
    r = client.get("/api/v1/sms/variables", HTTP_AUTHORIZATION=f"Bearer {raw}", HTTP_HOST="api.uzbridge.test")
    assert r.status_code == 200, r.content
    assert r.json() == [{"key": "muddat", "path": "invoice_date_due"}]
