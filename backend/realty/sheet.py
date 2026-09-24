# ruff: noqa: E501 - the Apps Script below is JavaScript
"""The Google Sheet side of a project: column names, parsing a pushed sheet, the Apps Script.

The sheet is the sales team's working copy. Its "uzbridge → Sinxronlash" menu
posts all rows here; we upsert the units and answer with the statuses (and
deal links) to write back, so a booking made in amoCRM shows in the sheet too.

Who wins on status: if the sheet's status differs from the one we last
exchanged with it, a person changed it in the sheet — that's applied. Otherwise
our status (e.g. set from amoCRM) is kept and written back to the sheet.
"""

import re
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from .models import Project, Unit, UnitEvent, UnitKind, UnitStatus

# field -> accepted headers (lower-case, uz / ru / en)
COLUMNS: dict[str, tuple[str, ...]] = {
    "ext_id": ("id", "kod", "код"),
    "kind": ("turi", "тип", "type", "kind"),
    "block": ("blok", "bino", "корпус", "блок", "дом", "building", "block"),
    "section": ("podyezd", "podezd", "seksiya", "подъезд", "секция", "section", "entrance"),
    "floor": ("qavat", "этаж", "floor"),
    "number": ("raqam", "xonadon", "№", "номер", "квартира", "number", "unit"),
    "rooms": ("xonalar", "xona", "комнаты", "комнат", "rooms"),
    "area": ("maydon", "maydon m2", "maydon m²", "площадь", "area", "m2", "m²"),
    "price": ("narx", "narxi", "цена", "стоимость", "price"),
    "price_m2": ("m2 narxi", "m² narxi", "narx m2", "цена за м2", "цена м2", "price per m2", "price m2"),
    "old_price": ("eski narx", "старая цена", "old price"),
    "layout": ("planirovka turi", "tip", "тип планировки", "layout", "layout type"),
    "status": ("holat", "holati", "статус", "status"),
    "plan_url": ("planirovka", "planirovka rasmi", "планировка", "plan", "plan url", "layout image"),
    "description": ("tavsif", "izoh", "описание", "description"),
    "lead": ("bitim", "сделка", "deal", "lead"),
}
ALIASES = {alias: field for field, names in COLUMNS.items() for alias in names}

# Status words people type, per language; the first of each is what we write back.
STATUS_WORDS: dict[str, tuple[str, ...]] = {
    UnitStatus.FREE: ("Boʻsh", "bo'sh", "bosh", "свободно", "свободна", "free", "available"),
    UnitStatus.INTEREST: ("Qiziqish", "интерес", "interest"),
    UnitStatus.RESERVED: ("Band", "бронь", "забронировано", "reserved", "booked"),
    UnitStatus.SOLD: ("Sotilgan", "sotildi", "продано", "продана", "sold"),
    UnitStatus.CLOSED: ("Sotuvda emas", "не продается", "не продаётся", "closed", "not for sale"),
}
_STATUS = {w.lower().replace("ʻ", "'").replace("‘", "'"): s for s, words in STATUS_WORDS.items() for w in words}
KIND_WORDS = {
    **{w: UnitKind.FLAT for w in ("xonadon", "kvartira", "квартира", "flat", "apartment", "")},
    **{w: UnitKind.COMMERCIAL for w in ("tijorat", "коммерция", "commercial", "магазин")},
    **{w: UnitKind.OFFICE for w in ("ofis", "офис", "office")},
    **{w: UnitKind.PARKING for w in ("parking", "паркинг", "машиноместо", "avtoturargoh")},
    **{w: UnitKind.STORAGE for w in ("omborxona", "кладовая", "storage")},
    **{w: UnitKind.TOWNHOUSE for w in ("taunxaus", "таунхаус", "townhouse", "kottej", "коттедж")},
}
# The header row a new sheet starts with (the template on the site).
TEMPLATE_HEADERS = [
    "ID",
    "Turi",
    "Blok",
    "Podyezd",
    "Qavat",
    "Raqam",
    "Xonalar",
    "Maydon",
    "Narx",
    "m2 narxi",
    "Holat",
    "Planirovka turi",
    "Planirovka",
    "Tavsif",
    "Bitim",
]


def status_word(status: str) -> str:
    return STATUS_WORDS[status][0]


def parse_status(value) -> str | None:
    key = str(value or "").strip().lower().replace("ʻ", "'").replace("‘", "'")
    return _STATUS.get(key) if key else UnitStatus.FREE


def _num(value) -> Decimal | None:
    """Sheet numbers: "545 000 000", "1,250,000", "1.250.000,50", "54,5", "$85 000"."""
    s = re.sub(r"[^\d.,\-]", "", str(value if value is not None else ""))
    if not s:
        return None
    if "," in s and "." in s:  # the later one is the decimal mark
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if dec == "," else ",", "").replace(",", ".")
    elif s.count(",") > 1 or s.count(".") > 1:  # repeated = thousands
        s = s.replace(",", "").replace(".", "")
    elif "," in s:
        head, tail = s.split(",")
        s = head + tail if len(tail) == 3 and head not in ("", "0", "-") else f"{head}.{tail}"
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _header_map(headers: list) -> tuple[dict[int, str], dict[int, str]]:
    known, other = {}, {}
    for i, h in enumerate(headers):
        name = str(h or "").strip()
        field = ALIASES.get(name.lower())
        if field and field not in known.values():
            known[i] = field
        elif name:
            other[i] = name
    return known, other


class SheetError(Exception):
    pass


def sync(project: Project, headers: list, rows: list[list], header_row: int = 1) -> dict:
    """Upsert the sheet's units; returns what to write back and a summary.

    header_row: the sheet row the headers are on (writes use real sheet row numbers).
    """
    known, other = _header_map(headers)
    if "ext_id" not in known.values():
        raise SheetError("The sheet needs an “ID” column (a unique code per unit).")
    col = {field: i for i, field in known.items()}
    errors, seen, writes = [], set(), []
    created = updated = 0
    now = timezone.now()
    with transaction.atomic():
        existing = {u.ext_id: u for u in project.units.select_for_update()}
        for r, row in enumerate(rows):
            cell = lambda f, row=row: row[col[f]] if f in col and col[f] < len(row) else ""  # noqa: E731
            ext_id = str(cell("ext_id")).strip()
            if not ext_id:
                continue
            if ext_id in seen:
                errors.append(f"Row {r + header_row + 1}: ID {ext_id} appears twice")
                continue
            seen.add(ext_id)
            sheet_status = parse_status(cell("status")) if "status" in col else None
            if "status" in col and sheet_status is None:
                errors.append(f"Row {r + 2}: unknown status “{cell('status')}”")
            unit = existing.get(ext_id) or Unit(project=project, ext_id=ext_id)
            is_new = unit.pk is None
            floor = _num(cell("floor"))
            fields = {
                "kind": KIND_WORDS.get(str(cell("kind")).strip().lower(), UnitKind.FLAT)
                if "kind" in col
                else unit.kind,
                "block": str(cell("block")).strip()[:60] if "block" in col else unit.block,
                "section": str(cell("section")).strip()[:60] if "section" in col else unit.section,
                "floor": int(floor) if floor is not None else unit.floor,
                "number": str(cell("number")).strip()[:20] if "number" in col else unit.number,
                # an empty cell keeps a layout typed on the site
                "layout": str(cell("layout")).strip()[:60] or unit.layout,
                "plan_url": str(cell("plan_url")).strip()[:500] if "plan_url" in col else unit.plan_url,
            }
            if "description" in col and str(cell("description")).strip():
                fields["description"] = str(cell("description")).strip()
            for name in ("rooms", "area", "price", "price_m2", "old_price"):
                if name in col:
                    v = _num(cell(name))
                    if name == "rooms":
                        fields[name] = int(v) if v is not None and v >= 0 else 0
                    elif name in ("price_m2", "old_price"):
                        fields[name] = v
                    else:
                        fields[name] = v if v is not None else Decimal(0)
            for k, v in fields.items():
                setattr(unit, k, v)
            if unit.price_m2 is None and unit.area and unit.price:
                unit.price_m2 = (unit.price / unit.area).quantize(Decimal("1"))
            unit.extra = {name: row[i] for i, name in other.items() if i < len(row) and row[i] not in ("", None)}
            unit.archived = False
            # Status: a change typed in the sheet wins; otherwise ours stays and goes back.
            if sheet_status and (is_new or sheet_status != unit.sheet_status) and sheet_status != unit.status:
                old = unit.status if not is_new else ""
                unit.status, unit.status_changed_at = sheet_status, now
                if sheet_status in (UnitStatus.FREE, UnitStatus.CLOSED):
                    unit.lead_id, unit.amo_connection, unit.reserved_until = None, None, None
                unit._event = (old, sheet_status)
            unit.sheet_status = unit.status
            unit.save()
            if getattr(unit, "_event", None) and not is_new:
                UnitEvent.objects.create(
                    unit=unit,
                    status_from=unit._event[0],
                    status_to=unit._event[1],
                    source=UnitEvent.Source.SHEET,
                    lead_id=unit.lead_id,
                )
            created += is_new
            updated += not is_new
            write = {"row": r + header_row + 1}
            if "status" in col and parse_status(cell("status")) != unit.status:
                write["status"] = status_word(unit.status)
            lead_text = lead_url(unit) if unit.lead_id else ""
            if "lead" in col and str(cell("lead")).strip() != lead_text:
                write["lead"] = lead_text
            if len(write) > 1:
                writes.append(write)
        gone = [u for ext, u in existing.items() if ext not in seen and not u.archived]
        for u in gone:
            u.archived = True
            u.save(update_fields=["archived", "updated_at"])
    summary = {
        "created": created,
        "updated": updated,
        "archived": len(gone),
        "errors": errors[:20],
        "total": len(seen),
        "at": now.isoformat(),
    }
    project.last_sync_at, project.last_sync_summary = now, summary
    project.save(update_fields=["last_sync_at", "last_sync_summary"])
    return {
        "summary": summary,
        "columns": {"status": col.get("status"), "lead": col.get("lead")},  # 0-based column indexes
        "writes": writes,
    }


def lead_url(unit: Unit) -> str:
    if unit.lead_id and unit.amo_connection_id:
        return f"https://{unit.amo_connection.host}/leads/detail/{unit.lead_id}"
    return str(unit.lead_id or "")


def apps_script(project: Project, api_base: str) -> str:
    """The code the team pastes into the sheet (Extensions → Apps Script)."""
    return APPS_SCRIPT.replace("__URL__", f"{api_base}/api/realty/sheet/sync").replace("__KEY__", project.sheet_key)


APPS_SCRIPT = r"""/**
 * uzbridge · Shaxmatka — sync this sheet with uzbridge and amoCRM.
 * Extensions → Apps Script → paste this → Save → reload the sheet.
 * A menu "uzbridge" appears: Sinxronlash (sync now), Avto-sinxron (every 10 min).
 */
var UZBRIDGE_URL = '__URL__';
var UZBRIDGE_KEY = '__KEY__';

function onOpen() {
  SpreadsheetApp.getUi().createMenu('uzbridge')
    .addItem('Sinxronlash / Синхронизировать', 'uzbridgeSync')
    .addItem('Avto-sinxron (10 daqiqa) / Автосинхронизация', 'uzbridgeAutoOn')
    .addItem('Avto-sinxronni oʻchirish / Выключить автосинхронизацию', 'uzbridgeAutoOff')
    .addToUi();
}

function uzbridgeSync() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  var values = sheet.getDataRange().getDisplayValues();
  if (values.length < 2) { toast_('Jadval boʻsh / Таблица пуста'); return; }
  var res = UrlFetchApp.fetch(UZBRIDGE_URL, {
    method: 'post', contentType: 'application/json', muteHttpExceptions: true,
    headers: { 'X-Uzbridge-Sheet-Key': UZBRIDGE_KEY },
    payload: JSON.stringify({ headers: values[0], rows: values.slice(1), sheet_url: SpreadsheetApp.getActiveSpreadsheet().getUrl() })
  });
  var body = JSON.parse(res.getContentText() || '{}');
  if (res.getResponseCode() !== 200) { toast_((body.detail || res.getResponseCode())); return; }
  (body.writes || []).forEach(function (w) {
    if (w.status !== undefined && body.columns.status !== null) sheet.getRange(w.row, body.columns.status + 1).setValue(w.status);
    if (w.lead !== undefined && body.columns.lead !== null) sheet.getRange(w.row, body.columns.lead + 1).setValue(w.lead);
  });
  var s = body.summary;
  toast_('✓ ' + s.total + ' ta · yangi ' + s.created + ' · yangilandi ' + s.updated + (s.errors.length ? ' · xato: ' + s.errors[0] : ''));
}

function uzbridgeAutoOn() {
  uzbridgeAutoOff();
  ScriptApp.newTrigger('uzbridgeSync').timeBased().everyMinutes(10).create();
  toast_('Avto-sinxron yoqildi / включена');
}

function uzbridgeAutoOff() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'uzbridgeSync') ScriptApp.deleteTrigger(t);
  });
}

function toast_(msg) { SpreadsheetApp.getActiveSpreadsheet().toast(msg, 'uzbridge', 8); }
"""
