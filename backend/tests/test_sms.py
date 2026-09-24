import base64
import json
from datetime import timedelta

import httpx
import pytest
import respx
from django.utils import timezone

from amocrm.models import AmoConnection
from sms import gateways
from sms.models import SmsAccount, SmsMessage, SmsSettings, SmsTemplate

ESKIZ = "https://notify.eskiz.uz/api"
AMO = "acmecrm.amocrm.ru"


@pytest.fixture
def eskiz(company):
    return SmsAccount.objects.create(
        company=company, is_enabled=True, provider="eskiz", login="acme@mail.uz", secret="eskiz-pass", sender="4546"
    )


@pytest.fixture
def playmobile(company):
    return SmsAccount.objects.create(
        company=company, is_enabled=True, provider="playmobile", login="pm", secret="pm-pass", sender="ACME"
    )


def eskiz_login():
    return respx.post(f"{ESKIZ}/auth/login").mock(
        return_value=httpx.Response(200, json={"message": "token_generated", "data": {"token": "TKN"}})
    )


def csrf(client):
    return client.get("/api/auth/csrf", HTTP_HOST="acme.uzbridge.test").cookies["csrftoken"].value


def api(client, method, path, body=None):
    kw = {"HTTP_HOST": "acme.uzbridge.test", "HTTP_X_CSRFTOKEN": csrf(client)}
    if body is not None:
        return getattr(client, method)(path, data=json.dumps(body), content_type="application/json", **kw)
    return getattr(client, method)(path, **kw)


@pytest.mark.parametrize(
    "raw,out",
    [("+998 (90) 123-45-67", "998901234567"), ("901234567", "998901234567"), ("998901234567", "998901234567")],
)
def test_normalize_phone(raw, out):
    assert gateways.normalize_phone(raw) == out


@pytest.mark.parametrize("raw", ["12345", "+7 912 345 67 89", ""])
def test_normalize_phone_rejects(raw):
    with pytest.raises(gateways.SmsError):
        gateways.normalize_phone(raw)


@pytest.mark.django_db
class TestEskiz:
    @respx.mock
    def test_send_logs_in_once_and_tracks_delivery(self, client, owner, eskiz, django_capture_on_commit_callbacks):
        login = eskiz_login()
        send = respx.post(f"{ESKIZ}/message/sms/send").mock(
            return_value=httpx.Response(
                200, json={"id": "uuid-1", "message": "Waiting for SMS provider", "status": "waiting"}
            )
        )
        client.force_login(owner)
        with django_capture_on_commit_callbacks(execute=True):
            r = api(client, "post", "/api/sms/test", {"phone": "90 123 45 67", "text": "Bu Eskiz dan test"})
        assert r.status_code == 200, r.content
        msg = SmsMessage.objects.get()
        assert (msg.status, msg.provider_id, msg.phone) == ("sent", "uuid-1", "998901234567")
        form = dict(x.split("=", 1) for x in send.calls.last.request.content.decode().split("&"))
        assert form["mobile_phone"] == "998901234567" and form["from"] == "4546"
        assert send.calls.last.request.headers["Authorization"] == "Bearer TKN"
        assert "cb%2Fsms%2Feskiz%2F" in form["callback_url"]
        # Delivery report.
        client.post(
            f"/cb/sms/eskiz/{eskiz.public_id}/",
            data=json.dumps({"request_id": "uuid-1", "status": "DELIVRD", "phone_number": "998901234567"}),
            content_type="application/json",
            HTTP_HOST="api.uzbridge.test",
        )
        msg.refresh_from_db()
        assert (msg.status, msg.provider_status) == ("delivered", "DELIVRD")
        assert login.call_count == 1

    @respx.mock
    def test_expired_token_relogs(self, eskiz):
        eskiz.token, eskiz.token_expires_at = "OLD", timezone.now() + timedelta(days=5)
        eskiz.save()
        eskiz_login()
        route = respx.get(f"{ESKIZ}/user/get-limit").mock(
            side_effect=[httpx.Response(401, json={}), httpx.Response(200, json={"data": {"balance": 12500}})]
        )
        assert gateways.eskiz_balance(eskiz) == "12500"
        assert route.calls[-1].request.headers["Authorization"] == "Bearer TKN"

    @respx.mock
    def test_rejected_text_fails_without_retry(self, client, owner, eskiz, django_capture_on_commit_callbacks):
        eskiz_login()
        respx.post(f"{ESKIZ}/message/sms/send").mock(
            return_value=httpx.Response(400, json={"message": "Text is not in approved templates"})
        )
        client.force_login(owner)
        with django_capture_on_commit_callbacks(execute=True):
            api(client, "post", "/api/sms/test", {"phone": "901234567", "text": "Random text"})
        msg = SmsMessage.objects.get()
        assert msg.status == "failed" and "approved" in msg.error

    @respx.mock
    def test_templates_sync_only_approved_are_usable(self, client, owner, eskiz):
        eskiz_login()
        respx.get(f"{ESKIZ}/user/templates").mock(
            return_value=httpx.Response(
                200,
                json={
                    "success": True,
                    "result": [
                        {"id": 1, "original_text": "{company}: toʻlov {link}", "status": "service"},
                        {"id": 2, "original_text": "Aksiya!", "status": "reklama"},
                        {"id": 3, "original_text": "Kutilmoqda", "status": "moderation"},
                        {"id": 4, "original_text": "Rad etilgan", "status": "rejected"},
                    ],
                },
            )
        )
        client.force_login(owner)
        rows = api(client, "post", "/api/sms/templates/sync").json()
        assert {r["text"]: r["approved"] for r in rows} == {
            "{company}: toʻlov {link}": True,
            "Aksiya!": True,
            "Kutilmoqda": False,
            "Rad etilgan": False,
        }
        # Unapproved ones can't be used for automatic messages.
        pending = SmsTemplate.objects.get(external_id="3")
        assert api(client, "put", "/api/sms/settings", {"paid_template_id": pending.pk}).status_code == 422
        good = SmsTemplate.objects.get(external_id="1")
        assert api(client, "put", "/api/sms/settings", {"link_template_id": good.pk}).status_code == 200


@pytest.mark.django_db
@respx.mock
def test_playmobile_send_and_dlr(client, owner, playmobile, django_capture_on_commit_callbacks):
    route = respx.post("https://send.smsxabar.uz/broker-api/send").mock(
        return_value=httpx.Response(200, text="Request is received")
    )
    client.force_login(owner)
    with django_capture_on_commit_callbacks(execute=True):
        api(client, "post", "/api/sms/test", {"phone": "998901234567", "text": "Salom"})
    msg = SmsMessage.objects.get()
    body = json.loads(route.calls.last.request.content)["messages"][0]
    assert (
        body["recipient"] == "998901234567"
        and body["sms"]["originator"] == "ACME"
        and body["message-id"] == msg.provider_id
    )
    assert route.calls.last.request.headers["Authorization"] == "Basic " + base64.b64encode(b"pm:pm-pass").decode()
    r = client.post(
        f"/cb/sms/playmobile/{playmobile.public_id}/status",
        data=json.dumps({"messages": [{"message-id": msg.provider_id, "status": "Delivered"}]}),
        content_type="application/json",
        HTTP_HOST="api.uzbridge.test",
    )
    assert r.content == b"Request is received"
    msg.refresh_from_db()
    assert msg.status == "delivered"


@pytest.mark.django_db
@respx.mock
def test_payment_link_sms_is_sent_with_the_link(company, eskiz, django_capture_on_commit_callbacks):
    from payments.services import create_invoice

    t = SmsTemplate.objects.create(
        company=company, provider="eskiz", external_id="1", text="{company}: {link}", status="service"
    )
    SmsSettings.objects.create(company=company, link_template=t)
    eskiz_login()
    send = respx.post(f"{ESKIZ}/message/sms/send").mock(return_value=httpx.Response(200, json={"id": "u-9"}))
    with django_capture_on_commit_callbacks(execute=True):
        inv = create_invoice(company, amount_tiyin=5_000_00, customer_phone="+998 90 123 45 67")
    msg = SmsMessage.objects.get()
    assert msg.invoice == inv and msg.status == "sent"
    assert f"/p/{inv.public_id}/" in send.calls.last.request.content.decode().replace("%2F", "/")


@pytest.fixture
def amo(company):
    return AmoConnection.objects.create(
        company=company,
        account_id=31337,
        subdomain="acmecrm",
        host=AMO,
        client_id="cid",
        client_secret="csecret",
        access_token="AT",
        refresh_token="RT",
        expires_at=timezone.now() + timedelta(hours=20),
        add_notes=True,
    )


@pytest.mark.django_db
class TestSmsFromAmocrm:
    @respx.mock
    def test_field_gets_approved_templates_only(self, client, owner, eskiz, amo):
        SmsTemplate.objects.create(
            company=amo.company, provider="eskiz", external_id="1", text="Salom {name}", status="service"
        )
        SmsTemplate.objects.create(
            company=amo.company, provider="eskiz", external_id="2", text="Hali emas", status="moderation"
        )
        respx.get(f"https://{AMO}/api/v4/leads/custom_fields").mock(
            return_value=httpx.Response(200, json={"_embedded": {"custom_fields": []}})
        )
        create = respx.post(f"https://{AMO}/api/v4/leads/custom_fields").mock(
            return_value=httpx.Response(
                200,
                json={
                    "_embedded": {
                        "custom_fields": [
                            {
                                "id": 777,
                                "name": "SMS shablon",
                                "enums": [{"id": 9001, "value": "Salom {name}"}],
                            }
                        ]
                    }
                },
            )
        )
        hook = respx.post(f"https://{AMO}/api/v4/webhooks").mock(return_value=httpx.Response(200, json={}))
        client.force_login(owner)
        r = api(client, "post", "/api/sms/amocrm/sync")
        assert r.status_code == 200, r.content
        sent = json.loads(create.calls.last.request.content)[0]
        assert sent["type"] == "select" and [e["value"] for e in sent["enums"]] == ["Salom {name}"]
        assert SmsTemplate.objects.get(external_id="1").amo_enum_id == 9001
        assert "update_lead" in json.loads(hook.calls.last.request.content)["settings"]
        amo.refresh_from_db()
        assert amo.sms_field_id == 777

    @respx.mock
    def test_picking_a_template_sends_it(self, client, eskiz, amo, django_capture_on_commit_callbacks):
        amo.sms_field_id = 777
        amo.save()
        SmsTemplate.objects.create(
            company=amo.company,
            provider="eskiz",
            external_id="1",
            text="Salom {name}!",
            status="service",
            amo_enum_id=9001,
        )
        lead = {
            "id": 55,
            "pipeline_id": 1,
            "status_id": 2,
            "custom_fields_values": [{"field_id": 777, "values": [{"enum_id": 9001}]}],
        }
        respx.get(f"https://{AMO}/api/v4/leads/55").mock(
            side_effect=lambda req: httpx.Response(
                200, json={**lead, "_embedded": {"contacts": [{"id": 3, "is_main": True}]}}
            )
        )
        respx.get(f"https://{AMO}/api/v4/contacts/3").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 3,
                    "name": "Aziz",
                    "custom_fields_values": [{"field_code": "PHONE", "values": [{"value": "+998 90 111 22 33"}]}],
                },
            )
        )
        reset = respx.patch(f"https://{AMO}/api/v4/leads/55").mock(return_value=httpx.Response(200, json={}))
        notes = respx.post(f"https://{AMO}/api/v4/leads/55/notes").mock(return_value=httpx.Response(200, json={}))
        eskiz_login()
        send = respx.post(f"{ESKIZ}/message/sms/send").mock(return_value=httpx.Response(200, json={"id": "u-1"}))
        with django_capture_on_commit_callbacks(execute=True):
            r = client.post(
                f"/oauth/amocrm/hook/{amo.hook_token}/", {"leads[update][0][id]": "55"}, HTTP_HOST="app.uzbridge.test"
            )
        assert r.status_code == 200
        msg = SmsMessage.objects.get()
        assert (msg.phone, msg.text, msg.lead_id, msg.status) == ("998901112233", "Salom Aziz!", 55, "sent")
        assert json.loads(reset.calls.last.request.content)["custom_fields_values"] == [
            {"field_id": 777, "values": None}
        ]
        assert "SMS" in json.loads(notes.calls.last.request.content)[0]["params"]["text"]
        assert send.called

    @respx.mock
    def test_empty_field_does_nothing(self, client, eskiz, amo):
        amo.sms_field_id = 777
        amo.save()
        respx.get(f"https://{AMO}/api/v4/leads/55").mock(
            return_value=httpx.Response(200, json={"id": 55, "custom_fields_values": []})
        )
        client.post(
            f"/oauth/amocrm/hook/{amo.hook_token}/", {"leads[update][0][id]": "55"}, HTTP_HOST="app.uzbridge.test"
        )
        assert not SmsMessage.objects.exists()


def widget_token(conn):
    import time

    import jwt

    now = int(time.time())
    claims = {
        "aud": "https://app.uzbridge.test",
        "iat": now,
        "nbf": now,
        "exp": now + 600,
        "account_id": conn.account_id,
    }
    return jwt.encode(claims, conn.client_secret, algorithm="HS256")


@pytest.mark.django_db
class TestWidgetSms:
    @respx.mock
    def test_feed_sms_source_sends_and_notes(self, client, eskiz, amo, django_capture_on_commit_callbacks):
        amo.client_secret = "csecret-0123456789abcdef-0123456789"
        amo.save()
        eskiz_login()
        respx.post(f"{ESKIZ}/message/sms/send").mock(return_value=httpx.Response(200, json={"id": "u-5"}))
        notes = respx.post(f"https://{AMO}/api/v4/leads/55/notes").mock(return_value=httpx.Response(200, json={}))
        with django_capture_on_commit_callbacks(execute=True):
            r = client.post(
                "/api/widget/sms",
                data=json.dumps({"phone": 998903554341, "message": "Salom", "contact_id": 3, "lead_id": 55}),
                content_type="application/json",
                HTTP_X_AUTH_TOKEN=widget_token(amo),
                HTTP_HOST="api.uzbridge.test",
            )
        assert r.status_code == 200, r.content
        msg = SmsMessage.objects.get()
        assert (msg.phone, msg.status, msg.lead_id) == ("998903554341", "sent", 55)
        assert "Salom" in json.loads(notes.calls.last.request.content)[0]["params"]["text"]

    def test_context_lists_approved_templates(self, client, eskiz, amo):
        amo.client_secret = "csecret-0123456789abcdef-0123456789"
        amo.save()
        SmsTemplate.objects.create(company=amo.company, provider="eskiz", external_id="1", text="OK", status="service")
        SmsTemplate.objects.create(
            company=amo.company, provider="eskiz", external_id="2", text="Wait", status="moderation"
        )
        r = client.get(
            "/api/widget/context?lead_id=55", HTTP_X_AUTH_TOKEN=widget_token(amo), HTTP_HOST="api.uzbridge.test"
        )
        assert r.json()["sms_ready"] is True and [t["text"] for t in r.json()["sms_templates"]] == ["OK"]
