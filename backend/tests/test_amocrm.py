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


@pytest.fixture
def conn(company):
    return AmoConnection.objects.create(
        company=company,
        account_id=31337,
        subdomain="acmecrm",
        host=HOST,
        access_token="AT1",
        refresh_token="RT1",
        expires_at=timezone.now() + timedelta(hours=20),
        pipelines=[{"id": 7001, "name": "Sotuv", "statuses": [{"id": 55}, {"id": 66}, {"id": 142}]}],
        paid_stages={"7001": 66},
    )


def widget_token(
    account_id=31337, secret="client-secret-0123456789abcdef-0123456789", aud="https://app.uzbridge.test", exp_in=600
):
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


@pytest.mark.django_db
class TestOAuth:
    @respx.mock
    def test_connect_flow(self, client, company, owner):
        mock_amo()
        url = oauth.authorize_url(company.pk, owner.pk)
        from urllib.parse import parse_qs, urlsplit

        raw_state = parse_qs(urlsplit(url).query)["state"][0]
        r = client.get(
            "/oauth/amocrm/callback",
            {"code": "CODE", "state": raw_state, "referer": HOST, "platform": "1"},
            HTTP_HOST="app.uzbridge.test",
        )
        assert r.status_code == 200, r.content
        conn = AmoConnection.objects.get(company=company)
        assert (conn.account_id, conn.host, conn.access_token, conn.refresh_token) == (31337, HOST, "AT1", "RT1")
        assert conn.pipelines[0]["statuses"][1]["name"] == "Toʻlandi"
        sent = json.loads(respx.calls[0].request.content)
        assert sent["grant_type"] == "authorization_code" and sent["redirect_uri"].endswith("/oauth/amocrm/callback")
        # Tokens are stored encrypted.
        from django.db import connection

        with connection.cursor() as cur:
            cur.execute("select access_token from amocrm_amoconnection")
            assert cur.fetchone()[0] != "AT1"

    @respx.mock
    def test_foreign_host_is_refused(self, client, company, owner):
        """The client secret must never be posted to a non-amoCRM host."""
        from urllib.parse import parse_qs, urlsplit

        raw_state = parse_qs(urlsplit(oauth.authorize_url(company.pk, owner.pk)).query)["state"][0]
        r = client.get(
            "/oauth/amocrm/callback",
            {"code": "C", "state": raw_state, "referer": "evil.example.com"},
            HTTP_HOST="app.uzbridge.test",
        )
        assert r.status_code == 400
        assert not respx.calls

    def test_tampered_state(self, client, company):
        r = client.get(
            "/oauth/amocrm/callback", {"code": "C", "state": "forged", "referer": HOST}, HTTP_HOST="app.uzbridge.test"
        )
        assert r.status_code == 400
        assert not AmoConnection.objects.exists()

    def test_member_cannot_connect(self, client, company):
        from urllib.parse import parse_qs, urlsplit

        from accounts.models import Membership, User

        u = User.objects.create_user(email="m@acme.uz", password="x" * 10)
        Membership.objects.create(company=company, user=u, role="member")
        raw_state = parse_qs(urlsplit(oauth.authorize_url(company.pk, u.pk)).query)["state"][0]
        r = client.get(
            "/oauth/amocrm/callback", {"code": "C", "state": raw_state, "referer": HOST}, HTTP_HOST="app.uzbridge.test"
        )
        assert r.status_code == 400

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
        sig = hmac.new(b"client-secret-0123456789abcdef-0123456789", b"client-id|31337", hashlib.sha256).hexdigest()
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
            widget_token(secret="wrong"),
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
