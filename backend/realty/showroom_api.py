"""No sign-in routes: the Google Sheet's sync, and the showroom (public or from an amoCRM deal).

The showroom URL carries one key:
  * a project's public key  → read-only for buyers (only when the project is public);
  * a signed deal key       → made by the amoCRM widget for one lead (4 h): can attach units.
"""

from django.core import signing
from django.core.cache import cache
from django.db.models import Q
from django.http import HttpResponse
from ninja import Router, Schema
from ninja.errors import HttpError

from . import services, sheet
from .models import Project, Unit, UnitStatus

router = Router(tags=["realty-public"])

DEAL_SALT = "realty-showroom-deal"
DEAL_MAX_AGE = 4 * 3600


def deal_key(conn, lead_id: int, user_name: str = "") -> str:
    return "d." + signing.dumps({"c": conn.pk, "l": int(lead_id), "u": user_name[:80]}, salt=DEAL_SALT, compress=True)


class Access:
    def __init__(self, projects, conn=None, lead_id=None, user=""):
        self.projects, self.conn, self.lead_id, self.user = projects, conn, lead_id, user

    @property
    def can_attach(self) -> bool:
        return self.conn is not None and self.lead_id is not None


def _access(key: str) -> Access:
    from amocrm.models import AmoConnection

    if key.startswith("d."):
        try:
            data = signing.loads(key[2:], salt=DEAL_SALT, max_age=DEAL_MAX_AGE)
        except signing.BadSignature:
            raise HttpError(401, "This showroom link has expired. Open it again from the deal.")
        conn = AmoConnection.objects.filter(
            pk=data["c"], status=AmoConnection.Status.ACTIVE, company__is_active=True
        ).first()
        if conn is None:
            raise HttpError(401, "amoCRM isn't connected.")
        projects = Project.objects.filter(company=conn.company, use_in_amocrm=True)
        return Access(list(projects), conn, data["l"], data.get("u", ""))
    project = Project.objects.filter(showroom_key=key, is_public=True, company__is_active=True).first()
    if project is None:
        raise HttpError(404, "Showroom not found.")
    return Access([project])


def _unit_out(u: Unit, access: Access, key: str) -> dict:
    hide_price = not access.can_attach and u.status == UnitStatus.SOLD and not u.project.show_sold_prices
    mine = access.can_attach and u.lead_id == access.lead_id and u.amo_connection_id == access.conn.pk
    return {
        "id": u.pk,
        "project": u.project_id,
        "ext_id": u.ext_id,
        "kind": u.kind,
        "block": u.block,
        "section": u.section,
        "floor": u.floor,
        "number": u.number,
        "rooms": u.rooms,
        "area": float(u.area or 0),
        "price": None if hide_price else float(u.price or 0),
        "price_m2": None if hide_price or u.price_m2 is None else float(u.price_m2),
        "old_price": None if hide_price or u.old_price is None else float(u.old_price),
        "layout": u.layout,
        "status": u.status,
        "description": u.description,
        "plan": (f"/api/realty/showroom/{key}/plan/{u.pk}?v={int(u.updated_at.timestamp())}" if u.plan else u.plan_url)
        or "",
        "extra": u.extra if access.can_attach else {},
        "mine": mine,
        # another deal holds it: the manager sees it's taken, not whose
        "taken": access.can_attach and bool(u.lead_id) and not mine,
        "reserved_until": u.reserved_until,
    }


@router.get("/showroom/{key}")
def showroom(request, key: str):
    access = _access(key)
    units = Unit.objects.filter(project__in=access.projects, archived=False).select_related("project")
    return {
        "mode": "deal" if access.can_attach else "public",
        "lead_id": access.lead_id,
        "projects": [
            {"id": p.id, "name": p.name, "currency": p.currency, "address": p.address, "stats": services.stats(p)}
            for p in access.projects
        ],
        "units": [_unit_out(u, access, key) for u in units],
    }


@router.get("/showroom/{key}/plan/{unit_id}")
def plan(request, key: str, unit_id: int):
    access = _access(key)
    unit = Unit.objects.filter(pk=unit_id, project__in=access.projects).exclude(plan=None).first()
    if unit is None:
        raise HttpError(404, "No plan.")
    resp = HttpResponse(bytes(unit.plan), content_type=unit.plan_type or "image/png")
    resp["Cache-Control"] = "public, max-age=86400"
    return services.plan_headers(resp)


class UnitIn(Schema):
    unit_id: int


@router.post("/showroom/{key}/attach")
def attach(request, key: str, data: UnitIn):
    access = _access(key)
    if not access.can_attach:
        raise HttpError(403, "Open the showroom from an amoCRM deal to attach units.")
    from amocrm.client import AmoError

    try:
        unit = services.attach(access.conn, data.unit_id, access.lead_id, user_label=access.user)
    except Unit.DoesNotExist:
        raise HttpError(404, "Unit not found.")
    except services.Taken as e:
        raise HttpError(409, str(e))
    except AmoError as e:
        raise HttpError(502, f"The unit is attached, but amoCRM refused the fields: {e}")
    return {"ok": True, "unit": _unit_out(unit, access, key)}


@router.post("/showroom/{key}/detach")
def detach(request, key: str, data: UnitIn):
    access = _access(key)
    if not access.can_attach:
        raise HttpError(403, "Open the showroom from an amoCRM deal.")
    try:
        unit = services.detach(access.conn, data.unit_id, access.lead_id)
    except Unit.DoesNotExist:
        raise HttpError(404, "Unit not found.")
    except services.Taken as e:
        raise HttpError(409, str(e))
    return {"ok": True, "unit": _unit_out(unit, access, key)}


# ------------------------------------------------------------------ Google Sheet


class SheetIn(Schema):
    headers: list
    rows: list[list]
    sheet_url: str = ""


@router.post("/sheet/sync")
def sheet_sync(request, data: SheetIn):
    """Called by the sheet's "uzbridge → Sinxronlash" (X-Uzbridge-Sheet-Key: the project's key)."""
    key = request.headers.get("X-Uzbridge-Sheet-Key", "")
    project = Project.objects.filter(sheet_key=key, company__is_active=True).first() if key else None
    if project is None:
        raise HttpError(401, "Unknown sheet key: copy the script again from uzbridge → Shaxmatka.")
    bucket = f"realty-sync:{project.pk}"
    cache.add(bucket, 0, 60)
    if cache.incr(bucket) > 20:
        raise HttpError(429, "Too many syncs in a minute; wait a moment.")
    if len(data.rows) > 20000:
        raise HttpError(422, "At most 20 000 rows per sheet.")
    if data.sheet_url.startswith("https://docs.google.com/") and data.sheet_url != project.sheet_url:
        project.sheet_url = data.sheet_url[:500]
        project.save(update_fields=["sheet_url"])
    try:
        return sheet.sync(project, data.headers, data.rows)
    except sheet.SheetError as e:
        raise HttpError(422, str(e))


def lead_units(conn, lead_id: int) -> list[Unit]:
    return list(
        Unit.objects.filter(Q(amo_connection=conn) & Q(lead_id=lead_id)).select_related("project").order_by("pk")
    )
