# ruff: noqa: F811  (pytest fixtures imported from test_realty)
"""Shaxmatka's own Google Sheet: connect, create, sync from the sheet's link."""

import json
from datetime import timedelta

import httpx
import jwt
import pytest
import respx
from django.core import signing
from django.utils import timezone

from realty import google
from realty.models import GoogleAccount, Unit, UnitStatus
from tests.test_realty import API, ROWS, project, push  # noqa: F401

SHEETS = google.SHEETS
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def client_keys(settings):
    settings.GOOGLE_CLIENT_ID = "gid.apps.googleusercontent.com"
    settings.GOOGLE_CLIENT_SECRET = "gsecret"


@pytest.fixture
def account(company):
    return GoogleAccount.objects.create(
        company=company,
        email="sales@acme.uz",
        refresh_token="RT",
        access_token="AT",
        expires_at=timezone.now() + timedelta(hours=1),
    )


def state_for(company, owner, project_id=None):
    return signing.dumps({"c": company.pk, "u": owner.pk, "p": project_id}, salt=google.STATE_SALT)


@respx.mock
def test_callback_connects_and_opens_the_new_sheet(client, company, owner, project):
    id_token = jwt.encode({"email": "sales@acme.uz"}, "x", algorithm="HS256")
    respx.post(google.TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "AT", "refresh_token": "RT", "expires_in": 3600, "id_token": id_token,
                  "scope": "openid email https://www.googleapis.com/auth/drive.file"},
        )
    )
    made = respx.post(SHEETS).mock(
        return_value=httpx.Response(200, json={"spreadsheetId": "S1", "sheets": [{"properties": {"sheetId": 7}}]})
    )
    values = respx.put(f"{SHEETS}/S1/values/Obyektlar!A1").mock(return_value=httpx.Response(200, json={}))
    fmt = respx.post(f"{SHEETS}/S1:batchUpdate").mock(return_value=httpx.Response(200, json={}))
    r = client.get(
        "/oauth/google/callback",
        {"code": "c0de", "state": state_for(company, owner, project.pk)},
        **API,
    )
    assert r.status_code == 302 and r["Location"] == "https://docs.google.com/spreadsheets/d/S1/edit"
    assert GoogleAccount.objects.get(company=company).email == "sales@acme.uz"
    project.refresh_from_db()
    assert (project.sheet_id, project.sheet_tab) == ("S1", 7)
    assert json.loads(made.calls.last.request.content)["sheets"][0]["properties"]["gridProperties"]["frozenRowCount"] == 2
    rows = json.loads(values.calls.last.request.content)["values"]
    assert "Sinxronlash" in rows[0][0] and project.pull_token in rows[0][0] and rows[1][0] == "ID"
    kinds = {next(iter(q)) for q in json.loads(fmt.calls.last.request.content)["requests"]}
    assert {"setDataValidation", "addConditionalFormatRule", "mergeCells"} <= kinds


def test_callback_rejects_a_forged_state(client):
    r = client.get("/oauth/google/callback", {"code": "x", "state": "forged"}, **API)
    assert r.status_code == 400 and not GoogleAccount.objects.exists()


@respx.mock
def test_the_sheet_link_syncs_and_writes_back(client, project, account):
    push(client, project, ROWS)  # units already known
    unit = Unit.objects.get(ext_id="A-1")
    unit.status = UnitStatus.RESERVED  # e.g. booked from amoCRM
    unit.save()
    project.sheet_id, project.sheet_tab = "S1", 7
    project.save()
    respx.get(f"{SHEETS}/S1").mock(
        return_value=httpx.Response(200, json={"sheets": [{"properties": {"sheetId": 7, "title": "Uylar"}}]})
    )
    headers = ["ID", "Blok", "Qavat", "Raqam", "Xonalar", "Maydon", "Narx", "Holat", "Planirovka turi", "Bitim", "Balkon"]
    read = respx.get(url__startswith=f"{SHEETS}/S1/values/").mock(
        return_value=httpx.Response(200, json={"values": [headers, *ROWS, ["A-9", "A", "3", "9", "2", "60", "700 000", "Band"]]})
    )
    wrote = respx.post(f"{SHEETS}/S1/values:batchUpdate").mock(return_value=httpx.Response(200, json={}))
    r = client.get(f"/g/{project.pull_token}/", **API)
    assert r.status_code == 200 and "Sinxronlandi" in r.content.decode()
    assert "'Uylar'!A2:ZZ" in str(read.calls.last.request.url).replace("%27", "'").replace("%21", "!")
    assert Unit.objects.get(ext_id="A-9").status == UnitStatus.RESERVED
    data = json.loads(wrote.calls.last.request.content)["data"]
    # A-1 is sheet row 3 (toolbar, headers); its status goes back as "Band"
    assert {"range": "'Uylar'!H3", "values": [["Band"]]} in data
    assert data[-1]["range"] == "'Uylar'!C1" and "oxirgi sinxron" in data[-1]["values"][0][0]


def test_unknown_sheet_link(client):
    assert client.get("/g/nope/", **API).status_code == 400


@respx.mock
def test_revoked_google_access_asks_to_reconnect(client, project, account):
    account.expires_at = timezone.now() - timedelta(minutes=1)
    account.save()
    project.sheet_id = "S1"
    project.save()
    respx.post(google.TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    r = client.get(f"/g/{project.pull_token}/", **API)
    assert r.status_code == 400 and "connect Google again" in r.content.decode()
    assert not GoogleAccount.objects.exists()


def test_connect_needs_the_server_keys(client, owner, project, settings):
    settings.GOOGLE_CLIENT_ID = ""
    client.force_login(owner)
    csrf = client.get("/api/auth/csrf", HTTP_HOST="acme.uzbridge.test").cookies["csrftoken"].value
    r = client.post(
        "/api/realty/google/connect",
        data=json.dumps({"project_id": project.pk}),
        content_type="application/json",
        HTTP_HOST="acme.uzbridge.test",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert r.status_code == 409


def test_connect_gives_googles_page(client, owner, project):
    client.force_login(owner)
    csrf = client.get("/api/auth/csrf", HTTP_HOST="acme.uzbridge.test").cookies["csrftoken"].value
    r = client.post(
        "/api/realty/google/connect",
        data=json.dumps({"project_id": project.pk}),
        content_type="application/json",
        HTTP_HOST="acme.uzbridge.test",
        HTTP_X_CSRFTOKEN=csrf,
    )
    url = r.json()["url"]
    assert url.startswith(google.AUTH_URL) and "drive.file" in url and "access_type=offline" in url
