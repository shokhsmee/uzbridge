# ruff: noqa: F811  (pytest fixture imported from test_amocrm)
"""amoCRM invoices ("Счета/покупки") mirroring and Digital Pipeline actions."""

import json
from datetime import timedelta

import httpx
import pytest
import respx
from django.utils import timezone

from amocrm.models import AmoAutomationJob
from payments.models import Invoice
from sms.models import SmsAccount, SmsMessage, SmsTemplate
from tests.test_amocrm import HOST, conn  # noqa: F401  (fixture)

LEAD = {"id": 9001, "name": "Olma", "price": 150000, "pipeline_id": 7001, "status_id": 55}


def amo_lead(lead=LEAD):
    respx.get(f"https://{HOST}/api/v4/leads/9001").mock(
        side_effect=lambda req: httpx.Response(
            200, json={**lead, "_embedded": {"contacts": [{"id": 5, "is_main": True}]}}
        )
    )
    respx.get(f"https://{HOST}/api/v4/contacts/5").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "Ali",
                "custom_fields_values": [{"field_code": "PHONE", "values": [{"value": "+998901234567"}]}],
            },
        )
    )
    respx.post(f"https://{HOST}/api/v4/leads/9001/notes").mock(return_value=httpx.Response(200, json={}))


def amo_catalog():
    respx.get(f"https://{HOST}/api/v4/catalogs").mock(
        return_value=httpx.Response(
            200, json={"_embedded": {"catalogs": [{"id": 11, "type": "regular"}, {"id": 77, "type": "invoices"}]}}
        )
    )
    respx.get(f"https://{HOST}/api/v4/catalogs/77/custom_fields").mock(
        return_value=httpx.Response(
            200,
            json={
                "_embedded": {
                    "custom_fields": [
                        {"id": 1, "code": "BILL_STATUS"},
                        {"id": 2, "code": "BILL_PRICE"},
                        {"id": 3, "code": "BILL_COMMENT"},
                        {"id": 4, "code": "ITEMS"},
                        {"id": 5, "code": "BILL_PAYMENT_DATE"},
                    ]
                }
            },
        )
    )


def dp_post(client, conn, action="link", delay=0, template="", key=None):
    body = {
        "event": {
            "type": 14,
            "type_code": "lead_status_changed",
            "data": {"id": 9001, "element_type": 2, "status_id": 55, "pipeline_id": 7001},
        },
        "action": {
            "settings": {
                "widget": {
                    "settings": {
                        "uzb_action": action,
                        "uzb_delay": str(delay),
                        "uzb_template": str(template),
                        "uzb_key": key or conn.hook_token,
                    }
                }
            }
        },
        "subdomain": "acmecrm",
        "account_id": 31337,
    }
    return client.post(
        "/oauth/amocrm/dp/", data=json.dumps(body), content_type="application/json", HTTP_HOST="app.uzbridge.test"
    )


@pytest.mark.django_db
@respx.mock
def test_link_is_mirrored_as_amocrm_invoice_and_marked_paid(conn, payme_account, company):
    from amocrm.tasks import create_amo_bill, mark_amo_bill_paid
    from payments.services import create_invoice

    conn.bills_enabled = True
    conn.save()
    amo_catalog()
    element = respx.post(f"https://{HOST}/api/v4/catalogs/77/elements").mock(
        return_value=httpx.Response(200, json={"_embedded": {"elements": [{"id": 555}]}})
    )
    link = respx.post(f"https://{HOST}/api/v4/leads/9001/link").mock(return_value=httpx.Response(200, json={}))
    patch = respx.patch(f"https://{HOST}/api/v4/catalogs/77/elements").mock(return_value=httpx.Response(200, json={}))
    inv = create_invoice(
        company, amount_tiyin=15000000, source=Invoice.Source.AMOCRM, external_id="9001", external_name="Olma"
    )
    create_amo_bill(inv.pk)
    inv.refresh_from_db()
    assert inv.amo_bill_id == 555
    sent = json.loads(element.calls[0].request.content)[0]
    by_id = {f["field_id"]: f["values"][0] for f in sent["custom_fields_values"]}
    assert by_id[1] == {"enum_code": "created"} and by_id[2] == {"value": 150000.0}
    assert str(inv.public_id) in by_id[3]["value"]
    assert json.loads(link.calls[0].request.content)[0]["to_entity_id"] == 555

    Invoice.objects.filter(pk=inv.pk).update(status=Invoice.Status.PAID, paid_at=timezone.now())
    mark_amo_bill_paid(inv.pk)
    paid = json.loads(patch.calls[0].request.content)[0]
    assert paid["id"] == 555 and paid["custom_fields_values"][0]["values"] == [{"enum_code": "paid"}]


@pytest.mark.django_db
@respx.mock
def test_dp_hook_creates_link_now(client, conn, payme_account):
    amo_lead()
    r = dp_post(client, conn, action="link")
    assert r.status_code == 200
    job = AmoAutomationJob.objects.get()
    assert job.done_at and job.result.startswith("link")
    assert Invoice.objects.filter(external_id="9001", amount_tiyin=15000000).exists()


@pytest.mark.django_db
def test_dp_hook_needs_the_account_key(client, conn):
    assert dp_post(client, conn, key="guess").status_code == 403
    assert not AmoAutomationJob.objects.exists()


@pytest.mark.django_db
@respx.mock
def test_delayed_sms_waits_and_skips_if_lead_moved(client, conn, company):
    from amocrm.tasks import run_due_automations

    SmsAccount.objects.create(
        company=company, is_enabled=True, provider="playmobile", login="pm", secret="s", sender="ACME"
    )
    tpl = SmsTemplate.objects.create(company=company, provider="playmobile", text="Salom {name}")
    assert dp_post(client, conn, action="sms", delay=60, template=tpl.pk).status_code == 200
    job = AmoAutomationJob.objects.get()
    assert job.done_at is None and job.run_at > timezone.now() + timedelta(minutes=59)
    run_due_automations()  # not due yet
    assert AmoAutomationJob.objects.get().done_at is None

    AmoAutomationJob.objects.update(run_at=timezone.now() - timedelta(seconds=1))
    amo_lead({**LEAD, "status_id": 66})  # moved on meanwhile
    run_due_automations()
    job.refresh_from_db()
    assert job.done_at and "skipped" in job.result
    assert not SmsMessage.objects.exists()
