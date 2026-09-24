import json

import pytest

from accounts.models import Company, Membership
from payments.models import ProviderAccount


def post(client, host, path, body):
    return client.post(path, data=json.dumps(body), content_type="application/json", HTTP_HOST=host)


@pytest.mark.django_db
class TestSignup:
    def test_signup_then_handoff_logs_in_on_subdomain(self, client):
        r = post(
            client,
            "app.uzbridge.test",
            "/api/auth/signup",
            {"company_name": "Nur Savdo", "slug": "nur", "email": "Boss@Nur.uz", "password": "long-enough-1"},
        )
        assert r.status_code == 200, r.content
        redirect = r.json()["redirect"]
        assert redirect.startswith("https://nur.uzbridge.test/auth/handoff?token=")
        token = redirect.split("token=")[1]
        company = Company.objects.get(slug="nur")
        assert Membership.objects.get(company=company).role == "owner"

        r = client.post(f"/api/auth/handoff?token={token}", HTTP_HOST="nur.uzbridge.test")
        assert r.status_code == 200
        me = client.get("/api/auth/me", HTTP_HOST="nur.uzbridge.test").json()
        assert me["email"] == "boss@nur.uz" and me["company"]["slug"] == "nur"
        # Tokens are single use.
        assert client.post(f"/api/auth/handoff?token={token}", HTTP_HOST="nur.uzbridge.test").status_code == 401

    @pytest.mark.parametrize("slug", ["api", "ab", "-bad", "Has Space", "x" * 40])
    def test_bad_slugs(self, client, slug):
        r = post(
            client,
            "app.uzbridge.test",
            "/api/auth/signup",
            {"company_name": "X", "slug": slug, "email": "a@b.uz", "password": "long-enough-1"},
        )
        assert r.status_code == 422

    def test_taken_slug(self, client, company):
        r = post(
            client,
            "app.uzbridge.test",
            "/api/auth/signup",
            {"company_name": "X", "slug": "acme", "email": "a@b.uz", "password": "long-enough-1"},
        )
        assert r.status_code == 422


@pytest.mark.django_db
class TestTenancy:
    def test_unknown_subdomain_404(self, client):
        assert client.get("/api/auth/csrf", HTTP_HOST="ghost.uzbridge.test").status_code == 404

    def test_login_only_into_own_company(self, client, owner, other_company):
        ok = post(
            client, "acme.uzbridge.test", "/api/auth/login", {"email": "owner@acme.uz", "password": "s3cret-pass!"}
        )
        assert ok.status_code == 200
        client.logout()
        denied = post(
            client, "other.uzbridge.test", "/api/auth/login", {"email": "owner@acme.uz", "password": "s3cret-pass!"}
        )
        assert denied.status_code == 401

    def test_session_does_not_cross_companies(self, client, owner, other_company):
        client.force_login(owner)
        assert client.get("/api/auth/me", HTTP_HOST="acme.uzbridge.test").status_code == 200
        assert client.get("/api/payments/providers", HTTP_HOST="other.uzbridge.test").status_code == 401

    def test_main_site_login_lists_companies(self, client, owner):
        r = post(client, "app.uzbridge.test", "/api/auth/login", {"email": "owner@acme.uz", "password": "s3cret-pass!"})
        companies = r.json()["companies"]
        assert [c["slug"] for c in companies] == ["acme"] and "/auth/handoff?token=" in companies[0]["enter"]


@pytest.mark.django_db
class TestProviderSettings:
    def test_secrets_are_masked_and_kept(self, client, owner):
        client.force_login(owner)
        csrf = client.get("/api/auth/csrf", HTTP_HOST="acme.uzbridge.test").cookies["csrftoken"].value
        body = {"merchant_id": "abc", "secret": "PRODKEY-123456", "test_secret": "TESTKEY-654321", "test_mode": True}
        r = client.put(
            "/api/payments/providers/payme",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_HOST="acme.uzbridge.test",
            HTTP_X_CSRFTOKEN=csrf,
        )
        assert r.status_code == 200, r.content
        out = r.json()
        assert "PRODKEY" not in json.dumps(out) and out["secret_masked"].endswith("3456")
        assert out["callback_url"].startswith("https://api.uzbridge.test/cb/payme/")
        # Leaving secrets out keeps them.
        r = client.put(
            "/api/payments/providers/payme",
            data=json.dumps({"merchant_id": "abc2", "test_mode": False}),
            content_type="application/json",
            HTTP_HOST="acme.uzbridge.test",
            HTTP_X_CSRFTOKEN=csrf,
        )
        acc = ProviderAccount.objects.get()
        assert (acc.merchant_id, acc.secret, acc.test_secret) == ("abc2", "PRODKEY-123456", "TESTKEY-654321")

    def test_csrf_required(self, client, owner):
        client.force_login(owner)
        c = type(client)(enforce_csrf_checks=True)
        c.force_login(owner)
        r = c.put(
            "/api/payments/providers/payme", data="{}", content_type="application/json", HTTP_HOST="acme.uzbridge.test"
        )
        assert r.status_code == 403

    def test_member_cannot_edit(self, client, company):
        from accounts.models import User

        u = User.objects.create_user(email="m@acme.uz", password="x" * 10)
        Membership.objects.create(company=company, user=u, role="member")
        client.force_login(u)
        r = client.put(
            "/api/payments/providers/payme", data="{}", content_type="application/json", HTTP_HOST="acme.uzbridge.test"
        )
        assert r.status_code == 403
