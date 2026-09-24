# ruff: noqa: F811  (pytest fixtures imported from test_amocrm)
"""Shaxmatka: the Google Sheet sync, the showroom, units in amoCRM deals."""

import json
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
import respx
from django.utils import timezone

from realty import services
from realty.models import Project, Unit, UnitEvent, UnitStatus
from tests.test_amocrm import HOST, conn, widget_token  # noqa: F401

HEADERS = ["ID", "Blok", "Qavat", "Raqam", "Xonalar", "Maydon", "Narx", "Holat", "Planirovka turi", "Bitim", "Balkon"]
API = {"HTTP_HOST": "api.uzbridge.test"}


@pytest.fixture
def project(company):
    return Project.objects.create(company=company, name="Olmazor", currency="USD", is_public=True)


@pytest.fixture
def quiet(monkeypatch):
    """No amoCRM calls: record what would be written instead."""
    calls = {"lead": [], "note": []}
    monkeypatch.setattr(services, "write_lead", lambda conn, unit, lead_id: calls["lead"].append((unit, lead_id)))
    monkeypatch.setattr(services, "_note", lambda conn, lead_id, text: calls["note"].append(text))
    monkeypatch.setattr(services, "_follow_stages", lambda conn: None)
    return calls


def push(client, project, rows, headers=HEADERS):
    return client.post(
        "/api/realty/sheet/sync",
        data=json.dumps({"headers": headers, "rows": rows, "sheet_url": "https://docs.google.com/spreadsheets/d/x"}),
        content_type="application/json",
        HTTP_X_UZBRIDGE_SHEET_KEY=project.sheet_key,
        **API,
    )


ROWS = [
    ["A-1", "A", "1", "1", "2", "54,5", "85 000", "Boʻsh", "2A", "", "ha"],
    ["A-2", "A", "1", "2", "1", "38", "1,250,000", "Sotilgan", "1B", "", ""],
    ["A-3", "A", "2", "3", "0", "30", "60000", "", "S", "", ""],
]


# ------------------------------------------------------------------ the sheet


def test_sheet_sync_creates_units(client, project):
    r = push(client, project, ROWS)
    assert r.status_code == 200, r.content
    assert r.json()["summary"]["created"] == 3
    a1 = Unit.objects.get(ext_id="A-1")
    assert (a1.area, a1.price, a1.price_m2, a1.rooms) == (Decimal("54.5"), 85000, Decimal("1560"), 2)
    assert a1.extra == {"Balkon": "ha"}
    assert Unit.objects.get(ext_id="A-2").status == UnitStatus.SOLD
    assert Unit.objects.get(ext_id="A-3").status == UnitStatus.FREE  # empty cell = free
    project.refresh_from_db()
    assert project.sheet_url.startswith("https://docs.google.com/") and project.last_sync_at


def test_sheet_sync_needs_the_key(client, project):
    r = client.post(
        "/api/realty/sheet/sync",
        data=json.dumps({"headers": HEADERS, "rows": ROWS}),
        content_type="application/json",
        HTTP_X_UZBRIDGE_SHEET_KEY="wrong",
        **API,
    )
    assert r.status_code == 401 and not Unit.objects.exists()


def test_sheet_needs_an_id_column(client, project):
    assert push(client, project, [["A", "1"]], headers=["Blok", "Qavat"]).status_code == 422


def test_status_changed_here_is_written_back_to_the_sheet(client, project):
    push(client, project, ROWS)
    unit = Unit.objects.get(ext_id="A-1")
    services.set_status(unit, UnitStatus.RESERVED, source=UnitEvent.Source.SITE)
    body = push(client, project, ROWS).json()  # the sheet still says Boʻsh
    unit.refresh_from_db()
    assert unit.status == UnitStatus.RESERVED  # the sheet didn't change it, so ours stands
    write = next(w for w in body["writes"] if w["row"] == 2)  # sheet row (1 = headers)
    assert write["status"].startswith("Band") and body["columns"]["status"] == HEADERS.index("Holat")


def test_status_changed_in_the_sheet_wins(client, project):
    push(client, project, ROWS)
    rows = [list(r) for r in ROWS]
    rows[0][7] = "Band"
    push(client, project, rows)
    assert Unit.objects.get(ext_id="A-1").status == UnitStatus.RESERVED


def test_units_gone_from_the_sheet_are_archived(client, project):
    push(client, project, ROWS)
    push(client, project, ROWS[:2])
    assert Unit.objects.get(ext_id="A-3").archived
    push(client, project, ROWS)
    assert not Unit.objects.get(ext_id="A-3").archived


# ------------------------------------------------------------------ deals


@pytest.fixture
def units(client, project):
    push(client, project, ROWS)
    return {u.ext_id: u for u in Unit.objects.all()}


def test_attach_makes_it_interest(conn, units, quiet):
    unit = services.attach(conn, units["A-1"].pk, 9001)
    assert (unit.status, unit.lead_id, unit.amo_connection_id) == (UnitStatus.INTEREST, 9001, conn.pk)
    assert quiet["lead"] == [(unit, 9001)] and "85 000 $" in quiet["note"][0]
    assert not quiet["note"][0].startswith("🏠 uzbridge")


def test_attach_refuses_a_unit_in_another_deal_or_sold(conn, units, quiet):
    services.attach(conn, units["A-1"].pk, 9001)
    with pytest.raises(services.Taken):
        services.attach(conn, units["A-1"].pk, 9002)
    with pytest.raises(services.Taken):
        services.attach(conn, units["A-2"].pk, 9002)  # sold in the sheet


def test_detach_frees_it_and_clears_the_lead(conn, units, quiet):
    services.attach(conn, units["A-1"].pk, 9001)
    unit = services.detach(conn, units["A-1"].pk, 9001)
    assert (unit.status, unit.lead_id) == (UnitStatus.FREE, None)
    assert quiet["lead"][-1] == (None, 9001)


def test_deal_stages_move_the_units(conn, units, quiet):
    services.attach(conn, units["A-1"].pk, 9001)
    conn.realty_stages = {"7001": {"60": "reserved"}}
    conn.save()
    services.on_stage(conn, 9001, 7001, 60)
    assert Unit.objects.get(pk=units["A-1"].pk).status == UnitStatus.RESERVED
    services.on_stage(conn, 9001, 7001, 55)  # not mapped: nothing changes
    assert Unit.objects.get(pk=units["A-1"].pk).status == UnitStatus.RESERVED
    services.on_stage(conn, 9001, 7001, 142)  # won, by default
    assert Unit.objects.get(pk=units["A-1"].pk).status == UnitStatus.SOLD


def test_lost_deal_frees_the_unit(conn, units, quiet):
    services.attach(conn, units["A-1"].pk, 9001)
    services.on_stage(conn, 9001, 7001, 143)
    unit = Unit.objects.get(pk=units["A-1"].pk)
    assert (unit.status, unit.lead_id) == (UnitStatus.FREE, None)


def test_booking_runs_out(conn, units, quiet, project):
    project.booking_hours = 24
    project.save()
    unit = services.attach(conn, units["A-1"].pk, 9001)
    services.set_status(unit, UnitStatus.RESERVED, source=UnitEvent.Source.AMOCRM)
    assert unit.reserved_until
    assert services.expire_bookings() == 0
    Unit.objects.filter(pk=unit.pk).update(reserved_until=timezone.now() - timedelta(minutes=1))
    assert services.expire_bookings() == 1
    assert Unit.objects.get(pk=unit.pk).status == UnitStatus.FREE


@respx.mock
def test_write_lead_sets_budget_and_fields_in_the_uzbridge_tab(conn, units):
    groups = f"https://{HOST}/api/v4/leads/custom_fields/groups"
    respx.get(groups).mock(return_value=httpx.Response(200, json={"_embedded": {"custom_field_groups": []}}))
    respx.post(groups).mock(
        return_value=httpx.Response(200, json={"_embedded": {"custom_field_groups": [{"id": "g1", "name": "uzbridge"}]}})
    )
    respx.get(f"https://{HOST}/api/v4/leads/custom_fields").mock(
        return_value=httpx.Response(200, json={"_embedded": {"custom_fields": []}})
    )
    made = respx.post(f"https://{HOST}/api/v4/leads/custom_fields").mock(
        return_value=httpx.Response(
            200,
            json={
                "_embedded": {
                    "custom_fields": [{"id": 900 + i, "name": n} for i, (_k, n, _t) in enumerate(services.LEAD_FIELDS)]
                }
            },
        )
    )
    lead = respx.patch(f"https://{HOST}/api/v4/leads/9001").mock(return_value=httpx.Response(200, json={}))
    services.write_lead(conn, units["A-1"], 9001)
    assert {f["group_id"] for f in json.loads(made.calls.last.request.content)} == {"g1"}
    sent = json.loads(lead.calls.last.request.content)
    assert sent["price"] == 85000
    values = {v["field_id"]: v["values"][0]["value"] for v in sent["custom_fields_values"]}
    assert values[900] == "Olmazor" and values[906] == 54.5


# ------------------------------------------------------------------ showroom


def test_public_showroom_hides_sold_prices_and_deals(client, project, units, conn, quiet):
    services.attach(conn, units["A-1"].pk, 9001)
    r = client.get(f"/api/realty/showroom/{project.showroom_key}", **API)
    assert r.status_code == 200
    body = r.json()
    by = {u["ext_id"]: u for u in body["units"]}
    assert body["mode"] == "public" and by["A-2"]["price"] is None and by["A-1"]["price"] == 85000
    assert "lead_id" not in by["A-1"] and by["A-1"]["extra"] == {}
    assert client.post(
        f"/api/realty/showroom/{project.showroom_key}/attach",
        data=json.dumps({"unit_id": units["A-3"].pk}),
        content_type="application/json",
        **API,
    ).status_code == 403


def test_private_project_has_no_public_showroom(client, project):
    project.is_public = False
    project.save()
    assert client.get(f"/api/realty/showroom/{project.showroom_key}", **API).status_code == 404


def test_deal_showroom_attaches(client, conn, units, quiet):
    r = client.post(
        "/api/widget/realty/session",
        data=json.dumps({"lead_id": 9001, "user_name": "Ali"}),
        content_type="application/json",
        HTTP_X_AUTH_TOKEN=widget_token(),
        **API,
    )
    assert r.status_code == 200, r.content
    key = r.json()["url"].rsplit("/s/", 1)[1]
    data = client.get(f"/api/realty/showroom/{key}", **API).json()
    assert data["mode"] == "deal" and data["lead_id"] == 9001
    r = client.post(
        f"/api/realty/showroom/{key}/attach",
        data=json.dumps({"unit_id": units["A-1"].pk}),
        content_type="application/json",
        **API,
    )
    assert r.status_code == 200 and r.json()["unit"]["mine"]
    listed = client.get("/api/widget/realty?lead_id=9001", HTTP_X_AUTH_TOKEN=widget_token(), **API).json()
    assert [u["label"] for u in listed["units"]] == [units["A-1"].label]
    assert client.get(f"/api/realty/showroom/{key}x", **API).status_code == 401


@respx.mock
def test_widget_saves_the_stage_map(client, conn):
    respx.get(f"https://{HOST}/api/v4/users/42").mock(
        return_value=httpx.Response(200, json={"id": 42, "rights": {"is_admin": True}})
    )
    respx.route(host=HOST).mock(return_value=httpx.Response(200, json={}))
    body = {
        "accounts": [],
        "sms_enabled": False,
        "realty_stages": {"7001": {"60": "reserved", "142": "", "999": "sold"}, "1": {"2": "sold"}},
    }
    r = client.put(
        "/api/widget/settings",
        data=json.dumps(body),
        content_type="application/json",
        HTTP_X_AUTH_TOKEN=widget_token(),
        **API,
    )
    assert r.status_code == 200, r.content
    conn.refresh_from_db()
    assert conn.realty_stages == {"7001": {"60": "reserved", "142": ""}}  # unknown stages dropped
    stages = {s["id"]: s["unit_status"] for s in r.json()["realty"]["pipelines"][0]["statuses"]}
    assert stages == {55: "", 60: "reserved", 66: "", 142: ""}
    assert services.stage_status(conn, 7001, 142) is None  # "" overrides the won default


def test_plan_upload_and_safe_serving(client, owner, project, units):
    from django.core.files.uploadedfile import SimpleUploadedFile

    client.force_login(owner)
    csrf = client.get("/api/auth/csrf", HTTP_HOST="acme.uzbridge.test").cookies["csrftoken"].value
    svg = SimpleUploadedFile("p.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", content_type="image/svg+xml")
    unit = units["A-1"]
    r = client.post(f"/api/realty/units/{unit.pk}/plan", {"file": svg}, HTTP_HOST="acme.uzbridge.test", HTTP_X_CSRFTOKEN=csrf)
    assert r.status_code == 200 and r.json()["has_plan"]
    served = client.get(f"/api/realty/showroom/{project.showroom_key}/plan/{unit.pk}", **API)
    assert served["Content-Type"] == "image/svg+xml" and "sandbox" in served["Content-Security-Policy"]
    exe = SimpleUploadedFile("p.html", b"<script>", content_type="text/html")
    r = client.post(f"/api/realty/units/{unit.pk}/plan", {"file": exe}, HTTP_HOST="acme.uzbridge.test", HTTP_X_CSRFTOKEN=csrf)
    assert r.status_code == 422
