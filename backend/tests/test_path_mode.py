"""TENANCY=path: one host, the company comes from the X-Company header."""

import json

import pytest

from payments.services import create_invoice

HOST = "uzbridge.test"


@pytest.fixture(autouse=True)
def _path_mode(settings):
    settings.TENANCY = "path"


def post(client, path, body, **headers):
    return client.post(path, data=json.dumps(body), content_type="application/json", HTTP_HOST=HOST, **headers)


@pytest.mark.django_db
def test_signup_redirects_to_company_path(client):
    r = post(
        client,
        "/api/auth/signup",
        {"company_name": "Nur", "slug": "nur", "email": "a@nur.uz", "password": "long-enough-1"},
    )
    assert r.json()["redirect"].startswith("https://uzbridge.test/nur/auth/handoff?token=")
    assert client.get("/api/auth/host-ready?slug=nur", HTTP_HOST=HOST).json() == {"ready": True}


@pytest.mark.django_db
def test_company_from_header_and_isolation(client, owner, other_company):
    client.force_login(owner)
    assert (
        client.get("/api/auth/me", HTTP_HOST=HOST, HTTP_X_COMPANY="acme").json()["company"]["url"]
        == "https://uzbridge.test/acme/"
    )
    # Same session, other company's header: not a member.
    assert client.get("/api/payments/providers", HTTP_HOST=HOST, HTTP_X_COMPANY="other").status_code == 401
    assert client.get("/api/auth/me", HTTP_HOST=HOST, HTTP_X_COMPANY="ghost").status_code == 404
    assert client.get("/api/auth/me", HTTP_HOST=HOST).status_code == 401


@pytest.mark.django_db
def test_pay_page_by_uuid(client, company, payme_account):
    inv = create_invoice(company, amount_tiyin=10_000, description="Test")
    r = client.get(f"/p/{inv.public_id}/", HTTP_HOST=HOST)
    assert r.status_code == 200 and b"Payme" in r.content
    go = client.get(f"/p/{inv.public_id}/go/payme/", HTTP_HOST=HOST)
    assert go.status_code == 302 and go["Location"].startswith("https://test.paycom.uz/")


@pytest.mark.django_db
def test_callback_urls_on_one_host(client, owner, payme_account):
    client.force_login(owner)
    out = client.get("/api/payments/providers", HTTP_HOST=HOST, HTTP_X_COMPANY="acme").json()
    assert out[0]["callback_url"] == f"https://uzbridge.test/cb/payme/{payme_account.public_id}/"
