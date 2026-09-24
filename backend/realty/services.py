"""Units and amoCRM deals: attach from the showroom, follow the deal's stage, write the lead."""

import logging
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import Project, Unit, UnitEvent, UnitStatus

log = logging.getLogger(__name__)

# key -> (name in amoCRM, type)
LEAD_FIELDS = [
    ("project", "Obyekt / Объект", "text"),
    ("block", "Blok / Корпус", "text"),
    ("section", "Podyezd / Подъезд", "text"),
    ("floor", "Qavat / Этаж", "numeric"),
    ("number", "Xonadon № / Квартира №", "text"),
    ("rooms", "Xonalar / Комнат", "numeric"),
    ("area", "Maydon m² / Площадь", "numeric"),
    ("price", "Narx / Цена", "numeric"),
    ("price_m2", "m² narxi / Цена за м²", "numeric"),
    ("status", "Holat / Статус", "text"),
]
DEFAULT_STAGE = {142: UnitStatus.SOLD, 143: UnitStatus.FREE}  # amoCRM's won / lost


class Taken(Exception):
    """Someone else's deal holds the unit."""


def _num(d: Decimal | None) -> str:
    if d is None:
        return ""
    return f"{int(d):,}".replace(",", " ") if d == int(d) else f"{d:,.2f}".replace(",", " ")


def money(unit: Unit) -> str:
    cur = unit.project.currency
    return f"{_num(unit.price)} {'soʻm' if cur == 'UZS' else '$'}"


def _event(unit: Unit, old: str, new: str, source: str, note: str = "") -> None:
    UnitEvent.objects.create(
        unit=unit, status_from=old, status_to=new, source=source, lead_id=unit.lead_id, note=note[:255]
    )


def set_status(unit: Unit, status: str, *, source: str, note: str = "") -> Unit:
    """Change a unit's status (the unit must be locked by the caller)."""
    if unit.status == status:
        return unit
    old = unit.status
    unit.status, unit.status_changed_at = status, timezone.now()
    if status in (UnitStatus.FREE, UnitStatus.CLOSED):
        unit.lead_id, unit.amo_connection, unit.reserved_until = None, None, None
    elif status == UnitStatus.RESERVED and unit.project.booking_hours:
        unit.reserved_until = timezone.now() + timedelta(hours=unit.project.booking_hours)
    elif status == UnitStatus.SOLD:
        unit.reserved_until = None
    unit.save()
    _event(unit, old, status, source, note)
    if unit.project.sheet_id:  # show it in the Google Sheet within seconds
        from .tasks import pull_sheet

        pid = unit.project_id
        transaction.on_commit(lambda: pull_sheet.apply_async((pid,), countdown=5))
    return unit


# ------------------------------------------------------------------ amoCRM lead fields


def ensure_lead_fields(conn, client) -> dict[str, int]:
    """The unit fields in the lead's "uzbridge" tab; ids kept on the connection."""
    from amocrm import fields

    have = dict(conn.realty_fields or {})
    ids = fields.ensure(conn, client, [(k, n, t, have.get(k)) for k, n, t in LEAD_FIELDS])
    if ids != conn.realty_fields:
        conn.realty_fields = ids
        conn.save(update_fields=["realty_fields"])
    return ids


def write_lead(conn, unit: Unit | None, lead_id: int) -> None:
    """Budget = the price; the Obyekt fields = the unit (or cleared when it's detached)."""
    from amocrm.client import AmoClient

    client = AmoClient(conn)
    ids = ensure_lead_fields(conn, client)
    if unit is None:
        values = [{"field_id": ids[k], "values": None} for k, _n, _t in LEAD_FIELDS if ids.get(k)]
        client.update_lead(lead_id, {"custom_fields_values": values})
        return
    raw = {
        "project": unit.project.name,
        "block": unit.block,
        "section": unit.section,
        "floor": unit.floor,
        "number": unit.number,
        "rooms": unit.rooms,
        "area": float(unit.area or 0),
        "price": float(unit.price or 0),
        "price_m2": float(unit.price_m2 or 0),
        "status": unit.get_status_display(),
    }
    values = [
        {"field_id": ids[k], "values": [{"value": raw[k]}]}
        for k, _n, _t in LEAD_FIELDS
        if ids.get(k) and raw[k] not in ("", None)
    ]
    fields = {"custom_fields_values": values}
    if unit.price:
        fields["price"] = int(unit.price)  # amoCRM budget is whole numbers
    client.update_lead(lead_id, fields)


def _follow_stages(conn) -> None:
    """The first unit in a deal: make sure amoCRM tells us when deals change stage."""
    from amocrm.services import subscribe_webhook

    try:
        subscribe_webhook(conn)
    except Exception:  # noqa: BLE001 - the unit is attached; the next attach tries again
        log.warning("could not subscribe the lead webhook for %s", conn.pk, exc_info=True)


def _note(conn, lead_id: int, text: str) -> None:
    from amocrm.client import AmoClient, AmoError

    try:
        AmoClient(conn).add_note(lead_id, text)
    except AmoError:
        log.warning("could not note lead %s", lead_id)


# ------------------------------------------------------------------ from the showroom


def attach(conn, unit_id: int, lead_id: int, *, user_label: str = "") -> Unit:
    """Put the unit into the deal: status Qiziqish (interest), budget and fields written."""
    with transaction.atomic():
        unit = Unit.objects.select_for_update().select_related("project").get(pk=unit_id, project__company=conn.company)
        if unit.lead_id and (unit.lead_id != lead_id or unit.amo_connection_id != conn.pk):
            raise Taken(f"№{unit.number} is already in another deal.")
        if unit.status in (UnitStatus.SOLD, UnitStatus.CLOSED) and unit.lead_id != lead_id:
            raise Taken(f"№{unit.number} is {unit.get_status_display().lower()}.")
        unit.lead_id, unit.amo_connection = lead_id, conn
        if unit.status == UnitStatus.FREE:
            set_status(unit, UnitStatus.INTEREST, source=UnitEvent.Source.AMOCRM, note=user_label)
        else:
            unit.save()
    write_lead(conn, unit, lead_id)
    if not Unit.objects.filter(amo_connection=conn).exclude(pk=unit.pk).exists():
        _follow_stages(conn)
    _note(
        conn,
        lead_id,
        f"🏠 {unit.project.name}, {unit.label} ({unit.rooms or 'studiya'}"
        f"{'-xona' if unit.rooms else ''}, {_num(unit.area)} m²) — {money(unit)} bitimga biriktirildi.",
    )
    return unit


def detach(conn, unit_id: int, lead_id: int) -> Unit:
    with transaction.atomic():
        unit = Unit.objects.select_for_update().select_related("project").get(pk=unit_id, project__company=conn.company)
        if unit.lead_id != lead_id or unit.amo_connection_id != conn.pk:
            raise Taken("This unit isn't in this deal.")
        if unit.status == UnitStatus.SOLD:
            raise Taken("A sold unit can't be taken off the deal.")
        set_status(unit, UnitStatus.FREE, source=UnitEvent.Source.AMOCRM, note="taken off the deal")
    write_lead(conn, None, lead_id)
    _note(conn, lead_id, f"🏠 {unit.project.name}, {unit.label} bitimdan olib tashlandi — endi boʻsh.")
    return unit


# ------------------------------------------------------------------ the deal moves


def stage_status(conn, pipeline_id: int, status_id: int) -> str | None:
    row = (conn.realty_stages or {}).get(str(pipeline_id), {})
    if str(status_id) in row:  # set in the widget; "" = this stage changes nothing
        return row[str(status_id)] if row[str(status_id)] in UnitStatus.values else None
    return DEFAULT_STAGE.get(int(status_id))


def on_stage(conn, lead_id: int, pipeline_id: int, status_id: int) -> list[Unit]:
    """The deal changed stage: its units follow (interest → reserved → sold, or free when lost)."""
    target = stage_status(conn, pipeline_id, status_id)
    if not target:
        return []
    moved = []
    with transaction.atomic():
        for unit in (
            Unit.objects.select_for_update().select_related("project").filter(amo_connection=conn, lead_id=lead_id)
        ):
            before = unit.status
            set_status(unit, target, source=UnitEvent.Source.AMOCRM, note=f"stage {status_id}")
            if unit.status != before:
                moved.append(unit)
    for unit in moved:
        text = (
            f"🏠 {unit.project.name}, №{unit.number} — {unit.get_status_display()}"
            if unit.status != UnitStatus.FREE
            else f"🏠 {unit.project.name}, №{unit.number} boʻshatildi."
        )
        _note(conn, lead_id, text)
    return moved


def expire_bookings() -> int:
    """Bookings past the project's time limit go back to free (and the deal is told)."""
    freed = 0
    due = Unit.objects.filter(status=UnitStatus.RESERVED, reserved_until__lte=timezone.now()).values_list(
        "pk", flat=True
    )
    for pk in list(due):
        with transaction.atomic():
            unit = Unit.objects.select_for_update(of=("self",)).select_related("project", "amo_connection").get(pk=pk)
            if unit.status != UnitStatus.RESERVED or not unit.reserved_until or unit.reserved_until > timezone.now():
                continue
            conn, lead_id = unit.amo_connection, unit.lead_id
            set_status(unit, UnitStatus.FREE, source=UnitEvent.Source.TIMER)
        freed += 1
        if conn and lead_id:
            _note(conn, lead_id, f"⏰ {unit.project.name}, №{unit.number} bron muddati tugadi — endi boʻsh.")
            try:
                write_lead(conn, None, lead_id)
            except Exception:  # noqa: BLE001
                log.warning("could not clear lead %s after booking expiry", lead_id)
    return freed


def stats(project: Project) -> dict:
    """For the site: how much is sold and what's left."""
    rows = project.units.filter(archived=False)
    out = {s: 0 for s in UnitStatus.values}
    sold_sum = left_sum = Decimal(0)
    for u in rows.only("status", "price"):
        out[u.status] += 1
        if u.status == UnitStatus.SOLD:
            sold_sum += u.price or 0
        elif u.status in (UnitStatus.FREE, UnitStatus.INTEREST, UnitStatus.RESERVED):
            left_sum += u.price or 0
    total = sum(out.values())
    return {
        "counts": out,
        "total": total,
        "sold_pct": round(100 * out[UnitStatus.SOLD] / total) if total else 0,
        "sold_sum": float(sold_sum),
        "left_sum": float(left_sum),
    }


def plan_headers(resp):
    """Uploaded plans may be SVG: never let one run script on our origin."""
    resp["Content-Security-Policy"] = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp
