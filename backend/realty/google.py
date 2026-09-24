"""A project's Google Sheet, made and synced by uzbridge (no Apps Script to paste).

The company connects its Google account once with the `drive.file` scope, so we
only ever see the sheets we created. "Jadval yaratish" makes a formatted sheet
in their Drive (status drop-downs and colours, the units we already have) and the
browser goes straight to it. Row 1 is a toolbar whose "🔄 Sinxronlash" link runs
a sync; row 2 holds the headers. We also pull every few minutes and push a
status as soon as it changes in amoCRM or on the site.
"""

import logging
from datetime import timedelta

import httpx
import jwt
from django.conf import settings
from django.core import signing
from django.utils import timezone

from core.tenancy import company_origin, platform_url

from . import sheet
from .models import GoogleAccount, Project, UnitKind, UnitStatus

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
SCOPES = "openid email https://www.googleapis.com/auth/drive.file"
STATE_SALT = "realty-google"
STATE_MAX_AGE = 20 * 60
TAB = "Obyektlar"
HEADER_ROW = 2  # row 1 is the toolbar

STATUS_COLORS = {  # the sheet's status cell background
    UnitStatus.FREE: (0.84, 0.94, 0.87),
    UnitStatus.INTEREST: (0.86, 0.91, 0.98),
    UnitStatus.RESERVED: (0.98, 0.94, 0.82),
    UnitStatus.SOLD: (0.89, 0.91, 0.90),
    UnitStatus.CLOSED: (0.93, 0.93, 0.93),
}
WIDTHS = {"ID": 90, "Tavsif": 260, "Planirovka": 180, "Bitim": 230, "Narx": 130, "Holat": 120}


class GoogleError(Exception):
    pass


def configured() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def redirect_uri() -> str:
    return platform_url("app", "/oauth/google/callback")


def pull_url(project: Project) -> str:
    return platform_url("api", f"/g/{project.pull_token}/")


# ------------------------------------------------------------------ connecting


def auth_url(company, user, project_id: int | None) -> str:
    if not configured():
        raise GoogleError("Google isn't set up on this uzbridge server yet.")
    state = signing.dumps({"c": company.pk, "u": user.pk, "p": project_id}, salt=STATE_SALT)
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",  # always hand back a refresh token
        "include_granted_scopes": "true",
        "state": state,
    }
    return str(httpx.URL(AUTH_URL, params=params))


def read_state(state: str) -> dict:
    try:
        return signing.loads(state, salt=STATE_SALT, max_age=STATE_MAX_AGE)
    except signing.BadSignature as e:
        raise GoogleError("The Google sign-in took too long; start again from uzbridge.") from e


def finish(code: str, company, user_label: str = "") -> GoogleAccount:
    """Swap the code for tokens and keep them on the company."""
    resp = httpx.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    data = resp.json() if resp.content else {}
    if resp.status_code != 200 or "access_token" not in data:
        raise GoogleError(
            f"Google refused the sign-in: {data.get('error_description') or data.get('error') or resp.status_code}"
        )
    if "drive.file" not in data.get("scope", ""):
        raise GoogleError("Allow uzbridge to create Google Sheets (tick the Drive box on Google's screen).")
    email = ""
    if data.get("id_token"):  # straight from Google over TLS: the payload is enough here
        email = jwt.decode(data["id_token"], options={"verify_signature": False}).get("email", "")
    account = GoogleAccount.objects.filter(company=company).first() or GoogleAccount(company=company)
    if data.get("refresh_token"):
        account.refresh_token = data["refresh_token"]
    elif not account.refresh_token:
        raise GoogleError(
            "Google gave no offline access; remove uzbridge at myaccount.google.com/permissions and connect again."
        )
    account.access_token = data["access_token"]
    account.expires_at = timezone.now() + timedelta(seconds=int(data.get("expires_in", 3600)) - 60)
    account.email = email or account.email
    account.connected_by = user_label[:150]
    account.save()
    return account


def disconnect(account: GoogleAccount) -> None:
    try:
        httpx.post(REVOKE_URL, data={"token": account.refresh_token}, timeout=10)
    except httpx.HTTPError:
        pass  # forgetting it here is what matters
    account.delete()


# ------------------------------------------------------------------ the API


class Sheets:
    def __init__(self, account: GoogleAccount):
        self.account = account

    def _token(self) -> str:
        a = self.account
        if a.access_token and a.expires_at and a.expires_at > timezone.now():
            return a.access_token
        resp = httpx.post(
            TOKEN_URL,
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "refresh_token": a.refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=20,
        )
        data = resp.json() if resp.content else {}
        if data.get("error") == "invalid_grant":
            a.delete()
            raise GoogleError("Google access was removed; connect Google again in uzbridge → Shaxmatka.")
        if resp.status_code != 200:
            raise GoogleError(f"Google token refresh failed ({resp.status_code}).")
        a.access_token = data["access_token"]
        a.expires_at = timezone.now() + timedelta(seconds=int(data.get("expires_in", 3600)) - 60)
        a.save(update_fields=["access_token", "expires_at"])
        return a.access_token

    def request(self, method: str, url: str, **kw) -> dict:
        resp = httpx.request(method, url, headers={"Authorization": f"Bearer {self._token()}"}, timeout=30, **kw)
        if resp.status_code == 404:
            raise GoogleError("The Google Sheet is gone (deleted or moved to trash). Create a new one.")
        if resp.status_code == 403:
            raise GoogleError("Google denied access to this sheet; connect Google again.")
        if resp.status_code >= 400:
            try:
                msg = resp.json()["error"]["message"]
            except Exception:  # noqa: BLE001
                msg = resp.text[:200]
            raise GoogleError(f"Google Sheets: {msg}")
        return resp.json() if resp.content else {}


def _client(project: Project) -> Sheets:
    account = GoogleAccount.objects.filter(company=project.company).first()
    if account is None:
        raise GoogleError("Connect Google first (uzbridge → Shaxmatka → Google Sheets).")
    return Sheets(account)


def col_letter(i: int) -> str:
    """0 → A, 25 → Z, 26 → AA."""
    out = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(65 + r) + out
    return out


def _rgb(r, g, b) -> dict:
    return {"red": r, "green": g, "blue": b}


def _unit_row(u) -> list:
    return [
        u.ext_id,
        UnitKind(u.kind).label,
        u.block,
        u.section,
        u.floor,
        u.number,
        u.rooms,
        float(u.area or 0),
        float(u.price or 0),
        float(u.price_m2) if u.price_m2 is not None else "",
        sheet.status_word(u.status),
        u.layout,
        u.plan_url,
        u.description,
        sheet.lead_url(u) if u.lead_id else "",
    ]


def _toolbar(project: Project, note: str) -> list:
    showroom = (
        f'=HYPERLINK("{company_origin(project.company)}/s/{project.showroom_key}";"🏠 Showroom")'
        if project.is_public
        else ""
    )
    return [f'=HYPERLINK("{pull_url(project)}";"🔄 Sinxronlash")', "", note, "", "", "", "", "", showroom]


def _note(project: Project) -> str:
    s = project.last_sync_summary or {}
    if not project.last_sync_at:
        return f"uzbridge · {project.name} — maʼlumotni kiriting va “🔄 Sinxronlash”ni bosing"
    at = timezone.localtime(project.last_sync_at).strftime("%d.%m %H:%M")
    return f"uzbridge · {project.name} · oxirgi sinxron {at} · {s.get('total', 0)} ta obyekt"


def create_sheet(project: Project) -> str:
    """A new, formatted sheet in the company's Drive with the units we already have."""
    api = _client(project)
    headers = sheet.TEMPLATE_HEADERS
    made = api.request(
        "POST",
        SHEETS,
        json={
            "properties": {"title": f"{project.name} · Shaxmatka (uzbridge)", "locale": "ru_RU"},
            "sheets": [
                {"properties": {"title": TAB, "gridProperties": {"frozenRowCount": HEADER_ROW, "columnCount": 26}}}
            ],
        },
    )
    sid, tab = made["spreadsheetId"], made["sheets"][0]["properties"]["sheetId"]
    units = list(project.units.filter(archived=False).select_related("amo_connection"))
    rows = [_toolbar(project, _note(project)), headers, *[_unit_row(u) for u in units]]
    if not units:
        rows.append(["A-1-01", "Xonadon", "A", "1", 1, "101", 2, 54.5, 545000000, "", "Boʻsh", "2A", "", "", ""])
    api.request(
        "PUT",
        f"{SHEETS}/{sid}/values/{TAB}!A1",
        params={"valueInputOption": "USER_ENTERED"},
        json={"values": rows},
    )
    n = len(headers)
    col = {h: i for i, h in enumerate(headers)}
    data_rows = {"sheetId": tab, "startRowIndex": HEADER_ROW, "endRowIndex": 5000}

    def column(name):
        return {**data_rows, "startColumnIndex": col[name], "endColumnIndex": col[name] + 1}

    status_words = [sheet.status_word(s) for s in UnitStatus.values]
    requests = [
        {
            "mergeCells": {
                "range": {
                    "sheetId": tab,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": 2,
                },
                "mergeType": "MERGE_ALL",
            }
        },
        {
            "mergeCells": {
                "range": {
                    "sheetId": tab,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 2,
                    "endColumnIndex": 8,
                },
                "mergeType": "MERGE_ALL",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": tab,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": n,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": _rgb(0.07, 0.53, 0.5),
                        "verticalAlignment": "MIDDLE",
                        "textFormat": {"foregroundColor": _rgb(1, 1, 1), "bold": True, "fontSize": 11},
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,verticalAlignment,textFormat)",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": tab,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": 2,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": _rgb(0.05, 0.4, 0.38),
                        "horizontalAlignment": "CENTER",
                        "textFormat": {"foregroundColor": _rgb(1, 1, 1), "bold": True, "fontSize": 12},
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": tab,
                    "startRowIndex": 1,
                    "endRowIndex": 2,
                    "startColumnIndex": 0,
                    "endColumnIndex": n,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": _rgb(0.88, 0.95, 0.94),
                        "verticalAlignment": "MIDDLE",
                        "textFormat": {"bold": True},
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,verticalAlignment,textFormat)",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {"sheetId": tab, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 38},
                "fields": "pixelSize",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {"sheetId": tab, "dimension": "ROWS", "startIndex": 1, "endIndex": 2},
                "properties": {"pixelSize": 30},
                "fields": "pixelSize",
            }
        },
        *[
            {
                "updateDimensionProperties": {
                    "range": {"sheetId": tab, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
                    "properties": {"pixelSize": WIDTHS.get(h, 100)},
                    "fields": "pixelSize",
                }
            }
            for i, h in enumerate(headers)
        ],
        {
            "setDataValidation": {
                "range": column("Holat"),
                "rule": {
                    "condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": w} for w in status_words]},
                    "showCustomUi": True,
                    "strict": False,
                },
            }
        },
        {
            "setDataValidation": {
                "range": column("Turi"),
                "rule": {
                    "condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": k.label} for k in UnitKind]},
                    "showCustomUi": True,
                    "strict": False,
                },
            }
        },
        *[
            {
                "repeatCell": {
                    "range": column(name),
                    "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}}},
                    "fields": "userEnteredFormat.numberFormat",
                }
            }
            for name in ("Narx", "m2 narxi")
        ],
        *[
            {
                "addConditionalFormatRule": {
                    "index": 0,
                    "rule": {
                        "ranges": [column("Holat")],
                        "booleanRule": {
                            "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": sheet.status_word(s)}]},
                            "format": {"backgroundColor": _rgb(*rgb)},
                        },
                    },
                }
            }
            for s, rgb in STATUS_COLORS.items()
        ],
        {
            "addProtectedRange": {
                "protectedRange": {
                    "range": {"sheetId": tab, "startRowIndex": 0, "endRowIndex": 1},
                    "description": "uzbridge toolbar",
                    "warningOnly": True,
                }
            }
        },
    ]
    api.request("POST", f"{SHEETS}/{sid}:batchUpdate", json={"requests": requests})
    project.sheet_id, project.sheet_tab = sid, tab
    project.sheet_url = f"https://docs.google.com/spreadsheets/d/{sid}/edit"
    project.save(update_fields=["sheet_id", "sheet_tab", "sheet_url"])
    return project.sheet_url


def _tab_title(api: Sheets, project: Project) -> str:
    """The tab's current name (people rename tabs)."""
    meta = api.request("GET", f"{SHEETS}/{project.sheet_id}", params={"fields": "sheets.properties(sheetId,title)"})
    tabs = [s["properties"] for s in meta.get("sheets", [])]
    for t in tabs:
        if t["sheetId"] == project.sheet_tab:
            return t["title"]
    if not tabs:
        raise GoogleError("The Google Sheet has no tabs.")
    return tabs[0]["title"]


def pull(project: Project) -> dict:
    """Read the sheet, apply it, write statuses / deal links back, refresh the toolbar."""
    if not project.sheet_id:
        raise GoogleError("This project has no Google Sheet made by uzbridge.")
    api = _client(project)
    title = _tab_title(api, project)
    q = "'" + title.replace("'", "''") + "'"
    data = api.request(
        "GET",
        f"{SHEETS}/{project.sheet_id}/values/{q}!A{HEADER_ROW}:ZZ",
        params={"valueRenderOption": "FORMATTED_VALUE"},
    )
    values = data.get("values") or []
    if not values:
        raise sheet.SheetError(f"Row {HEADER_ROW} of the sheet must hold the column names (ID, Blok, Qavat…).")
    result = sheet.sync(project, values[0], values[1:], header_row=HEADER_ROW)
    cols = result["columns"]
    updates = []
    for w in result["writes"]:
        for key in ("status", "lead"):
            if key in w and cols.get(key) is not None:
                updates.append({"range": f"{q}!{col_letter(cols[key])}{w['row']}", "values": [[w[key]]]})
    project.refresh_from_db()
    updates.append({"range": f"{q}!C1", "values": [[_note(project)]]})
    api.request(
        "POST",
        f"{SHEETS}/{project.sheet_id}/values:batchUpdate",
        json={"valueInputOption": "RAW", "data": updates},
    )
    return result["summary"]
