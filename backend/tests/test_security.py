import json

import pytest

from accounts.models import Company, Membership, UserSession
from audit.models import CallbackLog

from .conftest import basic

HOST_A = {"HTTP_HOST": "acme.uzbridge.test"}


def login(client, host, email="owner@acme.uz", password="s3cret-pass!", **meta):
    return client.post(
        "/api/auth/login",
        data=json.dumps({"email": email, "password": password}),
        content_type="application/json",
        HTTP_HOST=host,
        **meta,
    )


@pytest.mark.django_db
class TestCompanyScoping:
    def test_member_of_two_companies_signs_in_to_each(self, client, owner, company, settings):
        """Path tenancy: one domain, one session; a second company still needs its own sign-in."""
        settings.TENANCY = "path"
        second = Company.objects.create(name="Second", slug="second")
        Membership.objects.create(company=second, user=owner, role="owner")
        host = {"HTTP_HOST": "uzbridge.test"}
        assert login(client, "uzbridge.test", HTTP_X_COMPANY="acme").status_code == 200
        assert client.get("/api/auth/me", HTTP_X_COMPANY="acme", **host).status_code == 200
        # Typing the other company's name in the URL is not enough.
        assert client.get("/api/auth/me", HTTP_X_COMPANY="second", **host).status_code == 401
        assert login(client, "uzbridge.test", HTTP_X_COMPANY="second").status_code == 200
        assert client.get("/api/auth/me", HTTP_X_COMPANY="second", **host).status_code == 200
        assert client.get("/api/auth/me", HTTP_X_COMPANY="acme", **host).status_code == 200

    def test_no_session_no_entry(self, client, company):
        assert client.get("/api/auth/me", **HOST_A).status_code == 401
        assert client.get("/api/payments/invoices", **HOST_A).status_code == 401


@pytest.mark.django_db
class TestSingleDevice:
    def test_new_sign_in_ends_the_other_device(self, owner, company):
        from django.test import Client

        laptop, phone = Client(), Client()
        login(laptop, "acme.uzbridge.test", HTTP_USER_AGENT="Laptop")
        assert laptop.get("/api/auth/me", **HOST_A).status_code == 200
        login(phone, "acme.uzbridge.test", HTTP_USER_AGENT="Phone")
        assert phone.get("/api/auth/me", **HOST_A).status_code == 200
        assert laptop.get("/api/auth/me", **HOST_A).status_code == 401  # kicked out
        assert list(UserSession.objects.values_list("user_agent", flat=True)) == ["Phone"]

    def test_can_allow_several_devices_and_end_one(self, owner, company):
        from django.test import Client

        Company.objects.filter(pk=company.pk).update(single_session=False)
        a, b = Client(), Client()
        login(a, "acme.uzbridge.test", HTTP_USER_AGENT="A")
        login(b, "acme.uzbridge.test", HTTP_USER_AGENT="B")
        assert a.get("/api/auth/me", **HOST_A).status_code == 200 and b.get("/api/auth/me", **HOST_A).status_code == 200
        sessions = a.get("/api/auth/sessions", **HOST_A).json()["sessions"]
        other = next(s for s in sessions if not s["current"])
        csrf = a.cookies["csrftoken"].value
        a.post(f"/api/auth/sessions/{other['id']}/end", HTTP_X_CSRFTOKEN=csrf, **HOST_A)
        assert b.get("/api/auth/me", **HOST_A).status_code == 401


@pytest.mark.django_db
class TestCallbackGuard:
    def _rpc(self, client, acc, auth, ip="10.0.0.1"):
        return client.post(
            f"/cb/payme/{acc.public_id}/",
            data=json.dumps(
                {"method": "CheckPerformTransaction", "params": {"amount": 1, "account": {"order_id": "1"}}, "id": 1}
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=auth,
            HTTP_HOST="api.uzbridge.test",
            HTTP_X_FORWARDED_FOR=ip,
        )

    def test_logs_outcome_including_payme_errors(self, client, payme_account):
        self._rpc(client, payme_account, basic("Paycom", "wrong"))
        row = CallbackLog.objects.get()
        assert (row.source, row.company_id, row.ok, row.status_code) == ("payme", payme_account.company_id, False, 200)
        assert row.note.startswith("-32504")

    def test_allowlist_blocks_production_only(self, client, settings, payme_account):
        settings.CALLBACK_ALLOWED_IPS = {"payme": ["185.234.113.1"]}
        self._rpc(client, payme_account, basic("Paycom", "TESTKEY"))  # test mode: not blocked
        assert not CallbackLog.objects.get().blocked
        payme_account.test_mode = False
        payme_account.save()
        r = self._rpc(client, payme_account, basic("Paycom", "PRODKEY"))
        assert r.json()["error"]["code"] == -32504
        assert CallbackLog.objects.filter(blocked=True, note="IP not in allowlist").exists()

    def test_rate_limit(self, client, payme_account, monkeypatch):
        import audit.middleware as mw

        monkeypatch.setattr(mw, "RATE_PER_MINUTE", 3)
        codes = [
            self._rpc(client, payme_account, basic("Paycom", "TESTKEY"), ip="10.9.9.9").status_code for _ in range(5)
        ]
        assert codes[-1] == 429 and CallbackLog.objects.filter(note="rate limited").count() == 2

    def test_dashboard_sees_only_own_company(self, client, owner, payme_account, other_company):
        CallbackLog.objects.create(company=other_company, source="click", path="/cb/click/x/", status_code=200)
        self._rpc(client, payme_account, basic("Paycom", "TESTKEY"))
        client.force_login(owner)
        items = client.get("/api/audit/callbacks", **HOST_A).json()["items"]
        assert [i["source"] for i in items] == ["payme"]
