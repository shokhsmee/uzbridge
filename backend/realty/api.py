"""Dashboard: projects, their sheet setup, and editing units (layout plan, description, price, status)."""

import csv
import io
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.http import HttpResponse
from ninja import File, Router, Schema, UploadedFile
from ninja.errors import HttpError

from core.api import member_auth, require_manager
from core.tenancy import company_origin, platform_url

from . import services, sheet
from .models import Currency, Project, Unit, UnitEvent, UnitKind, UnitStatus

router = Router(tags=["realty"], auth=member_auth)

MAX_PLAN = 3 * 1024 * 1024
PLAN_TYPES = {"image/png", "image/jpeg", "image/webp", "image/svg+xml"}


class ProjectIn(Schema):
    name: str
    currency: str = Currency.UZS
    address: str = ""
    is_public: bool = False
    show_sold_prices: bool = False
    booking_hours: int = 0
    use_in_amocrm: bool = True


class UnitIn(Schema):
    description: str | None = None
    layout: str | None = None
    price: str | None = None
    old_price: str | None = None
    status: str | None = None
    rooms: int | None = None
    area: str | None = None
    kind: str | None = None


def _project_out(p: Project) -> dict:
    base = platform_url("api", "").rstrip("/")
    return {
        "id": p.id,
        "name": p.name,
        "currency": p.currency,
        "address": p.address,
        "is_public": p.is_public,
        "show_sold_prices": p.show_sold_prices,
        "booking_hours": p.booking_hours,
        "use_in_amocrm": p.use_in_amocrm,
        "sheet_url": p.sheet_url,
        "showroom_url": f"{company_origin(p.company)}/s/{p.showroom_key}",
        "last_sync_at": p.last_sync_at,
        "last_sync": p.last_sync_summary,
        "stats": services.stats(p),
        "apps_script": sheet.apps_script(p, base),
        "google_sheet": bool(p.sheet_id),
    }


def _unit_out(u: Unit) -> dict:
    return {
        "id": u.id,
        "ext_id": u.ext_id,
        "kind": u.kind,
        "block": u.block,
        "section": u.section,
        "floor": u.floor,
        "number": u.number,
        "rooms": u.rooms,
        "area": float(u.area or 0),
        "price": float(u.price or 0),
        "price_m2": float(u.price_m2) if u.price_m2 is not None else None,
        "old_price": float(u.old_price) if u.old_price is not None else None,
        "layout": u.layout,
        "status": u.status,
        "description": u.description,
        "has_plan": bool(u.plan),
        "plan": (f"/api/realty/units/{u.pk}/plan?v={int(u.updated_at.timestamp())}" if u.plan else u.plan_url) or "",
        "extra": u.extra,
        "lead_id": u.lead_id,
        "lead_url": sheet.lead_url(u) if u.lead_id else "",
        "reserved_until": u.reserved_until,
        "archived": u.archived,
    }


def _own(request, project_id: int) -> Project:
    p = Project.objects.filter(company=request.company, pk=project_id).first()
    if p is None:
        raise HttpError(404, "Project not found.")
    return p


def _own_unit(request, unit_id: int) -> Unit:
    u = Unit.objects.filter(project__company=request.company, pk=unit_id).select_related("project").first()
    if u is None:
        raise HttpError(404, "Unit not found.")
    return u


def _apply(p: Project, data: ProjectIn) -> None:
    if not data.name.strip():
        raise HttpError(422, "Name the project (e.g. “Olmazor Residence”).")
    if data.currency not in Currency.values:
        raise HttpError(422, "Currency is UZS or USD.")
    if not 0 <= data.booking_hours <= 24 * 90:
        raise HttpError(422, "Booking time: 0 (no limit) up to 90 days.")
    p.name, p.currency, p.address = data.name.strip()[:150], data.currency, data.address.strip()[:255]
    p.is_public, p.show_sold_prices = data.is_public, data.show_sold_prices
    p.booking_hours, p.use_in_amocrm = data.booking_hours, data.use_in_amocrm


@router.get("/projects")
def projects(request):
    return [_project_out(p) for p in Project.objects.filter(company=request.company)]


@router.post("/projects")
def create_project(request, data: ProjectIn):
    require_manager(request)
    p = Project(company=request.company)
    _apply(p, data)
    p.save()
    return _project_out(p)


@router.put("/projects/{project_id}")
def save_project(request, project_id: int, data: ProjectIn):
    require_manager(request)
    p = _own(request, project_id)
    _apply(p, data)
    p.save()
    return _project_out(p)


@router.delete("/projects/{project_id}")
def delete_project(request, project_id: int):
    require_manager(request)
    p = _own(request, project_id)
    if p.units.exclude(lead_id=None).exists():
        raise HttpError(409, "Units of this project are in deals; take them off the deals first.")
    p.delete()
    return {"ok": True}


@router.get("/projects/{project_id}/template.csv")
def template_csv(request, project_id: int):
    """The column headers to start the Google Sheet with (File → Import)."""
    _own(request, project_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(sheet.TEMPLATE_HEADERS)
    w.writerow(
        ["A-1-01", "Xonadon", "A", "1", "1", "1", "2", "54.5", "545000000", "", "Boʻsh", "2A", "", "Janubiy tomon", ""]
    )
    resp = HttpResponse("﻿" + buf.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="shaxmatka-shablon.csv"'
    return resp


@router.get("/projects/{project_id}/units")
def units(request, project_id: int, archived: bool = False):
    p = _own(request, project_id)
    qs = p.units.all() if archived else p.units.filter(archived=False)
    return [_unit_out(u) for u in qs]


def _dec(value: str, what: str) -> Decimal:
    try:
        d = Decimal(str(value).replace(" ", "").replace(",", "."))
    except InvalidOperation:
        raise HttpError(422, f"{what} must be a number.")
    if d < 0:
        raise HttpError(422, f"{what} can't be negative.")
    return d


@router.put("/units/{unit_id}")
def save_unit(request, unit_id: int, data: UnitIn):
    """Site edits: layout, description, price, status. Status set here is written to the sheet on its next sync."""
    require_manager(request)
    with transaction.atomic():
        u = Unit.objects.select_for_update().select_related("project").get(pk=_own_unit(request, unit_id).pk)
        if data.description is not None:
            u.description = data.description[:5000]
        if data.layout is not None:
            u.layout = data.layout.strip()[:60]
        if data.kind is not None:
            if data.kind not in UnitKind.values:
                raise HttpError(422, "Unknown unit type.")
            u.kind = data.kind
        if data.rooms is not None:
            u.rooms = max(0, min(20, data.rooms))
        if data.area is not None:
            u.area = _dec(data.area, "Area")
        if data.price is not None:
            u.price = _dec(data.price, "Price")
        if data.old_price is not None:
            u.old_price = _dec(data.old_price, "Old price") if data.old_price.strip() else None
        if u.area and u.price:
            u.price_m2 = (u.price / u.area).quantize(Decimal("1"))
        u.save()
        if data.status is not None and data.status != u.status:
            if data.status not in UnitStatus.values:
                raise HttpError(422, "Unknown status.")
            if data.status == UnitStatus.FREE and u.lead_id:
                raise HttpError(409, "This unit is in a deal; free it from the deal (or move the deal to lost).")
            services.set_status(u, data.status, source=UnitEvent.Source.SITE, note=request.user.email)
    return _unit_out(u)


@router.post("/units/{unit_id}/plan")
def upload_plan(request, unit_id: int, file: UploadedFile = File(...)):  # noqa: B008 - Ninja's upload syntax
    require_manager(request)
    u = _own_unit(request, unit_id)
    data = file.read(MAX_PLAN + 1)
    if len(data) > MAX_PLAN:
        raise HttpError(422, "The plan image is over 3 MB.")
    ctype = (file.content_type or "").split(";")[0]
    if ctype not in PLAN_TYPES:
        raise HttpError(422, "Upload a PNG, JPG, WEBP or SVG image.")
    u.plan, u.plan_type = data, ctype
    u.save(update_fields=["plan", "plan_type", "updated_at"])
    return _unit_out(u)


@router.post("/units/{unit_id}/plan/same-layout")
def plan_to_layout(request, unit_id: int):
    """Copy this unit's plan to every unit of the same layout type in the project."""
    require_manager(request)
    u = _own_unit(request, unit_id)
    if not u.plan or not u.layout:
        raise HttpError(409, "The unit needs a plan image and a layout type.")
    n = (
        Unit.objects.filter(project=u.project, layout=u.layout)
        .exclude(pk=u.pk)
        .update(plan=u.plan, plan_type=u.plan_type)
    )
    return {"copied": n}


@router.delete("/units/{unit_id}/plan")
def delete_plan(request, unit_id: int):
    require_manager(request)
    u = _own_unit(request, unit_id)
    u.plan, u.plan_type = None, ""
    u.save(update_fields=["plan", "plan_type", "updated_at"])
    return _unit_out(u)


@router.get("/units/{unit_id}/plan")
def get_plan(request, unit_id: int):
    u = _own_unit(request, unit_id)
    if not u.plan:
        raise HttpError(404, "No plan uploaded.")
    return services.plan_headers(HttpResponse(bytes(u.plan), content_type=u.plan_type or "image/png"))


@router.get("/units/{unit_id}/events")
def events(request, unit_id: int):
    u = _own_unit(request, unit_id)
    return [
        {
            "from": e.status_from,
            "to": e.status_to,
            "source": e.source,
            "lead_id": e.lead_id,
            "note": e.note,
            "at": e.created_at,
        }
        for e in u.events.all()[:50]
    ]


# ------------------------------------------------------------------ Google Sheets


class ConnectIn(Schema):
    project_id: int | None = None


@router.get("/google")
def google_status(request):
    from . import google
    from .models import GoogleAccount

    acc = GoogleAccount.objects.filter(company=request.company).first()
    return {"configured": google.configured(), "connected": acc is not None, "email": acc.email if acc else ""}


@router.post("/google/connect")
def google_connect(request, data: ConnectIn):
    """Google's sign-in page; afterwards the new sheet opens (when a project is given)."""
    from . import google

    require_manager(request)
    if data.project_id is not None:
        _own(request, data.project_id)
    try:
        return {"url": google.auth_url(request.company, request.user, data.project_id)}
    except google.GoogleError as e:
        raise HttpError(409, str(e))


@router.delete("/google")
def google_disconnect(request):
    from . import google
    from .models import GoogleAccount

    require_manager(request)
    acc = GoogleAccount.objects.filter(company=request.company).first()
    if acc:
        google.disconnect(acc)
    return {"ok": True}


@router.post("/projects/{project_id}/sheet")
def sheet_create(request, project_id: int):
    from . import google

    require_manager(request)
    p = _own(request, project_id)
    try:
        url = p.sheet_url if p.sheet_id else google.create_sheet(p)
    except google.GoogleError as e:
        raise HttpError(409, str(e))
    return {"url": url, "project": _project_out(p)}


@router.post("/projects/{project_id}/sheet/sync")
def sheet_pull(request, project_id: int):
    from . import google

    require_manager(request)
    p = _own(request, project_id)
    try:
        google.pull(p)
    except (google.GoogleError, sheet.SheetError) as e:
        raise HttpError(409, str(e))
    p.refresh_from_db()
    return _project_out(p)


@router.delete("/projects/{project_id}/sheet")
def sheet_unlink(request, project_id: int):
    """Stop syncing with the sheet (the sheet itself stays in Google Drive)."""
    require_manager(request)
    p = _own(request, project_id)
    p.sheet_id, p.sheet_tab, p.sheet_url = "", None, ""
    p.save(update_fields=["sheet_id", "sheet_tab", "sheet_url"])
    return _project_out(p)
