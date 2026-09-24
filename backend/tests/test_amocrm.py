import hashlib
import hmac
import json
import time
from datetime import timedelta

import httpx
import jwt
import pytest
import respx
from django.utils import timezone

from amocrm import oauth
from amocrm.models import AmoConnection
from payments.models import Invoice

HOST = "acmecrm.amocrm.ru"
TOKENS = {"token_type": "Bearer", "expires_in": 86400, "access_token": "AT1", "refresh_token": "RT1"}
PIPELINES = {
    "_embedded": {
        "pipelines": [
            {
                "id": 7001,
                "name": "Sotuv",
                "is_main": True,
                "_embedded": {
                    "statuses": [
                        {"id": 55, "name": "Yangi"},
                        {"id": 66, "name": "Toʻlandi"},
                        {"id": 142, "name": "Won"},
                    ]
                },
            }
        ]
    }
}


def mock_amo():
    respx.post(f"https://{HOST}/oauth2/access_token").mock(return_value=httpx.Response(200, json=TOKENS))
    respx.get(f"https://{HOST}/api/v4/account").mock(
        return_value=httpx.Response(200, json={"id": 31337, "subdomain": "acmecrm"})
    )
    respx.get(f"https://{HOST}/api/v4/leads/pipelines").mock(return_value=httpx.Response(200, json=PIPELINES))


SECRET = "client-secret-0123456789abcdef-0123456789"


@pytest.fixture
def conn(company):
    return AmoConnection.objects.create(
        company=company,
        account_id=31337,
        subdomain="acmecrm",
        host=HOST,
        client_id="client-id",
        client_secret=SECRET,
        access_token="AT1",
        refresh_token="RT1",
        expires_at=timezone.now() + timedelta(hours=20),
        pipelines=[{"id": 7001, "name": "Sotuv", "statuses": [{"id": 55}, {"id": 60}, {"id": 66}, {"id": 142}]}],
        paid_stages={"7001": 66},
        bills_enabled=False,  # covered in test_amocrm_automation
    )


def widget_token(account_id=31337, secret=SECRET, aud="https://app.uzbridge.test", exp_in=600):
    now = int(time.time())
    return jwt.encode(
        {
            "iss": f"https://{HOST}",
            "aud": aud,
            "jti": "x",
            "iat": now,
            "nbf": now,
            "exp": now + exp_in,
            "account_id": account_id,
            "user_id": 42,
            "subdomain": "acmecrm",
        },
        secret,
        algorithm="HS256",
    )


def button(client, owner):
    client.force_login(owner)
    csrf = client.get("/api/auth/csrf", HTTP_HOST="acme.uzbridge.test").cookies["csrftoken"].value
    r = client.post("/api/amocrm/connect-button", HTTP_HOST="acme.uzbridge.test", HTTP_X_CSRFTOKEN=csrf)
    assert r.status_code == 200, r.content
    return r.json()


def send_secrets(client, state, client_id="auto-client", client_secret="auto-secret"):
    return client.post(
        "/oauth/amocrm/secrets",
        {"client_id": client_id, "client_secret": client_secret, "state": state, "name": "uzbridge"},
        HTTP_HOST="app.uzbridge.test",
    )


@pytest.mark.django_db
class TestOAuth:
    @respx.mock
    def test_button_creates_integration_and_connects(self, client, company, owner):
        mock_amo()
        hook = respx.post(f"https://{HOST}/api/v4/webhooks").mock(return_value=httpx.Response(200, json={}))
        params = button(client, owner)
        assert params["redirect_uri"] == "https://app.uzbridge.test/oauth/amocrm/callback"
        assert params["secrets_uri"] == "https://app.uzbridge.test/oauth/amocrm/secrets"
        # amoCRM sends the new integration's keys first, then redirects with a code.
        assert send_secrets(client, params["state"]).status_code == 200
        r = client.get(
            "/oauth/amocrm/callback",
            {"code": "CODE", "state": params["state"], "referer": HOST, "client_id": "auto-client"},
            HTTP_HOST="app.uzbridge.test",
        )
        assert r.status_code == 200, r.content
        conn = AmoConnection.objects.get(company=company)
        assert (conn.account_id, conn.client_id, conn.client_secret, conn.access_token) == (
            31337,
            "auto-client",
            "auto-secret",
            "AT1",
        )
        sent = json.loads(respx.calls[0].request.content)
        assert (sent["client_id"], sent["client_secret"], sent["grant_type"]) == (
            "auto-client",
            "auto-secret",
            "authorization_code",
        )
        assert json.loads(hook.calls.last.request.content)["destination"].endswith(
            f"/oauth/amocrm/hook/{conn.hook_token}/"
        )
        # Keys and tokens are stored encrypted.
        from django.db import connection

        with connection.cursor() as cur:
            cur.execute("select access_token, client_secret from amocrm_amoconnection")
            stored = cur.fetchone()
            assert "AT1" not in stored and "auto-secret" not in stored

    def test_callback_without_keys(self, client, company, owner):
        params = button(client, owner)
        r = client.get(
            "/oauth/amocrm/callback",
            {"code": "C", "state": params["state"], "referer": HOST},
            HTTP_HOST="app.uzbridge.test",
        )
        assert r.status_code == 400 and not AmoConnection.objects.exists()

    @respx.mock
    def test_foreign_host_is_refused(self, client, company, owner):
        """A client secret must never be posted to a non-amoCRM host."""
        params = button(client, owner)
        send_secrets(client, params["state"])
        r = client.get(
            "/oauth/amocrm/callback",
            {"code": "C", "state": params["state"], "referer": "evil.example.com"},
            HTTP_HOST="app.uzbridge.test",
        )
        assert r.status_code == 400
        assert not respx.calls

    def test_tampered_state(self, client, company):
        assert send_secrets(client, "forged").status_code == 400
        r = client.get(
            "/oauth/amocrm/callback", {"code": "C", "state": "forged", "referer": HOST}, HTTP_HOST="app.uzbridge.test"
        )
        assert r.status_code == 400
        assert not AmoConnection.objects.exists()

    def test_member_cannot_connect(self, client, company):
        from accounts.models import Membership, User

        u = User.objects.create_user(email="m@acme.uz", password="x" * 10)
        Membership.objects.create(company=company, user=u, role="member")
        client.force_login(u)
        csrf = client.get("/api/auth/csrf", HTTP_HOST="acme.uzbridge.test").cookies["csrftoken"].value
        r = client.post("/api/amocrm/connect-button", HTTP_HOST="acme.uzbridge.test", HTTP_X_CSRFTOKEN=csrf)
        assert r.status_code == 403

    @respx.mock
    def test_refresh_stores_new_pair(self, conn):
        route = respx.post(f"https://{HOST}/oauth2/access_token").mock(
            return_value=httpx.Response(200, json={**TOKENS, "access_token": "AT2", "refresh_token": "RT2"})
        )
        AmoConnection.objects.filter(pk=conn.pk).update(expires_at=timezone.now() + timedelta(minutes=10))
        fresh = oauth.refresh(conn.pk)
        assert (fresh.access_token, fresh.refresh_token) == ("AT2", "RT2")
        assert json.loads(route.calls.last.request.content)["refresh_token"] == "RT1"
        # Not near expiry any more: a second call doesn't burn the new refresh token.
        oauth.refresh(conn.pk)
        assert route.call_count == 1

    @respx.mock
    def test_failed_refresh_marks_error(self, conn):
        respx.post(f"https://{HOST}/oauth2/access_token").mock(return_value=httpx.Response(401, json={}))
        with pytest.raises(oauth.OAuthError):
            oauth.refresh(conn.pk, force=True)
        conn.refresh_from_db()
        assert conn.status == AmoConnection.Status.ERROR

    def test_uninstall_hook(self, client, conn):
        sig = hmac.new(SECRET.encode(), b"client-id|31337", hashlib.sha256).hexdigest()
        assert (
            client.get(
                "/oauth/amocrm/uninstall", {"account_id": "31337", "signature": "bad"}, HTTP_HOST="app.uzbridge.test"
            ).status_code
            == 400
        )
        assert (
            client.get(
                "/oauth/amocrm/uninstall", {"account_id": "31337", "signature": sig}, HTTP_HOST="app.uzbridge.test"
            ).status_code
            == 200
        )
        conn.refresh_from_db()
        assert conn.status == AmoConnection.Status.DISCONNECTED


@pytest.mark.django_db
class TestWidget:
    def call(self, client, method, path, token, body=None):
        kw = {"HTTP_X_AUTH_TOKEN": token, "HTTP_HOST": "api.uzbridge.test"}
        if body is not None:
            return getattr(client, method)(path, data=json.dumps(body), content_type="application/json", **kw)
        return getattr(client, method)(path, **kw)

    def test_rejects_bad_tokens(self, client, conn):
        for token in [
            widget_token(secret="wrong-secret-0123456789abcdef-012345"),
            widget_token(aud="https://evil.test"),
            widget_token(exp_in=-120),
            widget_token(account_id=1),
            "",
        ]:
            assert self.call(client, "get", "/api/widget/context?lead_id=1", token).status_code == 401

    @respx.mock
    def test_create_link_and_note(self, client, conn, payme_account):
        notes = respx.post(f"https://{HOST}/api/v4/leads/9001/notes").mock(return_value=httpx.Response(200, json={}))
        r = self.call(
            client,
            "post",
            "/api/widget/invoices",
            widget_token(),
            {"lead_id": 9001, "amount": "1 500 000", "lead_name": "Deal #9001", "user_name": "Aziz"},
        )
        assert r.status_code == 200, r.content
        data = r.json()
        assert data["amount"] == "1 500 000" and data["url"].startswith("https://acme.uzbridge.test/p/")
        inv = Invoice.objects.get()
        assert (inv.source, inv.external_id, inv.amount_tiyin) == ("amocrm", "9001", 150_000_000)
        note = json.loads(notes.calls.last.request.content)[0]
        assert note["note_type"] == "service_message" and data["url"] in note["params"]["text"]

        ctx = self.call(client, "get", "/api/widget/context?lead_id=9001", widget_token()).json()
        assert ctx["providers"] == ["payme"] and ctx["invoices"][0]["number"] == inv.display_number

    def test_needs_a_provider(self, client, conn):
        r = self.call(client, "post", "/api/widget/invoices", widget_token(), {"lead_id": 1, "amount": "100"})
        assert r.status_code == 409

    def test_bad_amounts(self, client, conn, payme_account):
        for amount in ["0", "-5", "abc", "10.001"]:
            r = self.call(client, "post", "/api/widget/invoices", widget_token(), {"lead_id": 1, "amount": amount})
            assert r.status_code == 422, amount


@pytest.mark.django_db
@respx.mock
def test_paid_invoice_moves_lead(client, conn, payme_account, django_capture_on_commit_callbacks):
    from payments.services import create_invoice
    from tests.test_payme import AUTH

    inv = create_invoice(conn.company, amount_tiyin=5_000_00, source="amocrm", external_id="9001")
    respx.get(f"https://{HOST}/api/v4/leads/9001").mock(
        return_value=httpx.Response(200, json={"id": 9001, "pipeline_id": 7001})
    )
    patch = respx.patch(f"https://{HOST}/api/v4/leads/9001").mock(return_value=httpx.Response(200, json={}))
    notes = respx.post(f"https://{HOST}/api/v4/leads/9001/notes").mock(return_value=httpx.Response(200, json={}))

    def rpc(method, params):
        return client.post(
            f"/cb/payme/{payme_account.public_id}/",
            data=json.dumps({"method": method, "params": params, "id": 1}),
            content_type="application/json",
            HTTP_AUTHORIZATION=AUTH,
            HTTP_HOST="api.uzbridge.test",
        ).json()

    rpc("CreateTransaction", {"id": "t1", "time": 1, "amount": 5_000_00, "account": {"order_id": str(inv.number)}})
    with django_capture_on_commit_callbacks(execute=True):
        assert rpc("PerformTransaction", {"id": "t1"})["result"]["state"] == 2

    body = json.loads(patch.calls.last.request.content)
    assert body == {"updated_by": 0, "pipeline_id": 7001, "status_id": 66}
    assert "✅ Paid 5 000 UZS via Payme" in json.loads(notes.calls.last.request.content)[0]["params"]["text"]
    inv.refresh_from_db()
    assert inv.crm_synced_at is not None and inv.crm_sync_error == ""


@pytest.mark.django_db
@respx.mock
def test_dead_token_is_a_clean_error(client, conn, owner):
    respx.get(f"https://{HOST}/api/v4/leads/custom_fields").mock(return_value=httpx.Response(401, json={}))
    respx.post(f"https://{HOST}/oauth2/access_token").mock(return_value=httpx.Response(400, json={"hint": "bad"}))
    client.force_login(owner)
    r = client.get("/api/amocrm/custom-fields", HTTP_HOST="acme.uzbridge.test")
    assert r.status_code == 502 and "reconnect" in r.json()["detail"]
    conn.refresh_from_db()
    assert conn.status == AmoConnection.Status.ERROR


def hook_post(client, conn, lead_id=9001, status_id=60, pipeline_id=7001):
    return client.post(
        f"/oauth/amocrm/hook/{conn.hook_token}/",
        {
            "leads[status][0][id]": str(lead_id),
            "leads[status][0][status_id]": str(status_id),
            "leads[status][0][pipeline_id]": str(pipeline_id),
            "leads[status][0][old_status_id]": "55",
            "account[id]": "31337",
        },
        HTTP_HOST="app.uzbridge.test",
    )


@pytest.mark.django_db
class TestLinkStage:
    @respx.mock
    def test_entering_link_stage_creates_invoice(self, client, conn, payme_account):
        conn.link_stages = {"7001": 60}
        conn.save()
        respx.get(f"https://{HOST}/api/v4/leads/9001").mock(
            return_value=httpx.Response(
                200, json={"id": 9001, "name": "Kvartira A-12", "price": 1500000, "pipeline_id": 7001, "status_id": 60}
            )
        )
        notes = respx.post(f"https://{HOST}/api/v4/leads/9001/notes").mock(return_value=httpx.Response(200, json={}))
        assert hook_post(client, conn).status_code == 200
        inv = Invoice.objects.get()
        assert (inv.amount_tiyin, inv.external_id, inv.description) == (150_000_000, "9001", "Kvartira A-12")
        assert "/p/" in json.loads(notes.calls.last.request.content)[0]["params"]["text"]
        # Moving back into the stage doesn't create a second link while one is open.
        hook_post(client, conn)
        assert Invoice.objects.count() == 1

    @respx.mock
    def test_other_stage_or_bad_token_does_nothing(self, client, conn, payme_account):
        conn.link_stages = {"7001": 60}
        conn.save()
        assert hook_post(client, conn, status_id=55).status_code == 200
        assert client.post("/oauth/amocrm/hook/wrong-token/", {}, HTTP_HOST="app.uzbridge.test").status_code == 404
        assert not Invoice.objects.exists() and not respx.calls

    @respx.mock
    def test_empty_budget_leaves_a_note(self, client, conn, payme_account):
        conn.link_stages = {"7001": 60}
        conn.save()
        respx.get(f"https://{HOST}/api/v4/leads/9001").mock(
            return_value=httpx.Response(
                200, json={"id": 9001, "name": "X", "price": 0, "pipeline_id": 7001, "status_id": 60}
            )
        )
        notes = respx.post(f"https://{HOST}/api/v4/leads/9001/notes").mock(return_value=httpx.Response(200, json={}))
        hook_post(client, conn)
        assert not Invoice.objects.exists()
        assert "byudjeti" in json.loads(notes.calls.last.request.content)[0]["params"]["text"]

    @respx.mock
    def test_create_fields(self, client, conn, owner):
        respx.get(f"https://{HOST}/api/v4/leads/custom_fields").mock(
            return_value=httpx.Response(200, json={"_embedded": {"custom_fields": []}})
        )
        created = respx.post(f"https://{HOST}/api/v4/leads/custom_fields").mock(
            return_value=httpx.Response(
                200,
                json={
                    "_embedded": {
                        "custom_fields": [
                            {"id": 501, "name": "uzbridge: toʻlov havolasi"},
                            {"id": 502, "name": "uzbridge: toʻlov holati"},
                        ]
                    }
                },
            )
        )
        client.force_login(owner)
        csrf = client.get("/api/auth/csrf", HTTP_HOST="acme.uzbridge.test").cookies["csrftoken"].value
        r = client.post("/api/amocrm/fields/create", HTTP_HOST="acme.uzbridge.test", HTTP_X_CSRFTOKEN=csrf)
        assert r.status_code == 200 and (r.json()["link_field_id"], r.json()["status_field_id"]) == (501, 502)
        assert [f["type"] for f in json.loads(created.calls.last.request.content)] == ["url", "text"]


@pytest.mark.django_db
@respx.mock
def test_manual_integration_connect(client, company, owner):
    """A hand-made integration (the only kind that can carry our widget)."""
    mock_amo()
    respx.post(f"https://{HOST}/api/v4/webhooks").mock(return_value=httpx.Response(200, json={}))
    client.force_login(owner)
    csrf = client.get("/api/auth/csrf", HTTP_HOST="acme.uzbridge.test").cookies["csrftoken"].value
    r = client.post(
        "/api/amocrm/connect-manual",
        data=json.dumps(
            {
                "host": "https://acmecrm.amocrm.ru/leads",
                "client_id": "manual-id",
                "client_secret": "manual-secret",
                "code": "def502",
            }
        ),
        content_type="application/json",
        HTTP_HOST="acme.uzbridge.test",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert r.status_code == 200, r.content
    conn = AmoConnection.objects.get(company=company)
    assert (conn.client_id, conn.client_secret, conn.host) == ("manual-id", "manual-secret", HOST)
    sent = json.loads(respx.calls[0].request.content)
    assert (sent["code"], sent["client_id"], sent["grant_type"]) == ("def502", "manual-id", "authorization_code")
    bad = client.post(
        "/api/amocrm/connect-manual",
        data=json.dumps({"host": "evil.example.com", "client_id": "a", "client_secret": "b", "code": "c"}),
        content_type="application/json",
        HTTP_HOST="acme.uzbridge.test",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert bad.status_code == 422


@pytest.mark.django_db
def test_widget_keys_without_new_authorization(client, conn, owner):
    """Already connected: the widget's private integration needs only its ID and secret."""
    widget_secret = "widget-secret-0123456789abcdef-01234567"
    client.force_login(owner)
    csrf = client.get("/api/auth/csrf", HTTP_HOST="acme.uzbridge.test").cookies["csrftoken"].value

    def post(body):
        return client.post(
            "/api/amocrm/connect-manual",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_HOST="acme.uzbridge.test",
            HTTP_X_CSRFTOKEN=csrf,
        )

    wrong_host = post({"host": "other.amocrm.ru", "client_id": "w-id", "client_secret": widget_secret})
    assert wrong_host.status_code == 422
    r = post({"host": HOST, "client_id": "w-id", "client_secret": widget_secret})
    assert r.status_code == 200, r.content
    conn.refresh_from_db()
    # The API tokens and the original integration are untouched.
    assert (conn.client_secret, conn.access_token, conn.widget_client_id) == (SECRET, "AT1", "w-id")

    kw = {"HTTP_HOST": "api.uzbridge.test"}
    for secret in (widget_secret, SECRET):
        ok = client.get("/api/widget/context?lead_id=1", HTTP_X_AUTH_TOKEN=widget_token(secret=secret), **kw)
        assert ok.status_code == 200, ok.content


@pytest.mark.django_db
def test_widget_keys_need_a_connection_first(client, company, owner):
    client.force_login(owner)
    csrf = client.get("/api/auth/csrf", HTTP_HOST="acme.uzbridge.test").cookies["csrftoken"].value
    r = client.post(
        "/api/amocrm/connect-manual",
        data=json.dumps({"host": HOST, "client_id": "w-id", "client_secret": "s"}),
        content_type="application/json",
        HTTP_HOST="acme.uzbridge.test",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert r.status_code == 422


@pytest.mark.django_db
@respx.mock
def test_disconnect_keeps_settings_for_reconnect(client, conn, owner):
    """"Uzish" must not wipe stages, SMS field or widget keys: reconnecting the same account restores them."""
    AmoConnection.objects.filter(pk=conn.pk).update(sms_field_id=900, widget_client_id="w-id", link_stages={"7001": 55})
    respx.get(f"https://{HOST}/api/v4/webhooks").mock(return_value=httpx.Response(200, json={"_embedded": {"webhooks": []}}))
    respx.delete(f"https://{HOST}/api/v4/webhooks").mock(return_value=httpx.Response(204))
    client.force_login(owner)
    csrf = client.get("/api/auth/csrf", HTTP_HOST="acme.uzbridge.test").cookies["csrftoken"].value
    kw = {"HTTP_HOST": "acme.uzbridge.test", "HTTP_X_CSRFTOKEN": csrf}
    assert client.post("/api/amocrm/disconnect", **kw).json()["connected"] is False
    conn.refresh_from_db()
    assert conn.status == "disconnected" and conn.access_token == ""
    # The widget and hooks stop working while disconnected.
    widget = client.get("/api/widget/context?lead_id=1", HTTP_X_AUTH_TOKEN=widget_token(), HTTP_HOST="api.uzbridge.test")
    assert widget.status_code == 401

    mock_amo()
    respx.post(f"https://{HOST}/api/v4/webhooks").mock(return_value=httpx.Response(200, json={}))
    r = client.post(
        "/api/amocrm/connect-manual",
        data=json.dumps({"host": HOST, "client_id": "new-id", "client_secret": "new-secret", "code": "def502"}),
        content_type="application/json",
        **kw,
    )
    assert r.status_code == 200, r.content
    again = AmoConnection.objects.get()
    assert again.pk == conn.pk and again.status == "active"
    assert (again.sms_field_id, again.widget_client_id, again.link_stages, again.paid_stages) == (
        900,
        "w-id",
        {"7001": 55},
        {"7001": 66},
    )
