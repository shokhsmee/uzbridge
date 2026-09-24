from django.conf import settings
from ninja import Router, Schema
from ninja.errors import HttpError

from core.api import member_auth, require_manager

from . import oauth, services
from .client import AmoClient, AmoError
from .models import AmoConnection

router = Router(tags=["amocrm"], auth=member_auth)


class SettingsIn(Schema):
    paid_stages: dict[str, int] = {}
    add_notes: bool = True
    link_field_id: int | None = None
    status_field_id: int | None = None


def _conn(request) -> AmoConnection | None:
    return AmoConnection.objects.filter(company=request.company).first()


def _out(conn: AmoConnection | None) -> dict:
    if conn is None:
        return {"connected": False, "configured": bool(settings.AMOCRM_CLIENT_ID)}
    return {
        "connected": conn.status != AmoConnection.Status.DISCONNECTED,
        "configured": True,
        "status": conn.status,
        "last_error": conn.last_error,
        "account_id": conn.account_id,
        "host": conn.host,
        "connected_at": conn.connected_at,
        "pipelines": conn.pipelines,
        "pipelines_synced_at": conn.pipelines_synced_at,
        "paid_stages": {str(p["id"]): conn.paid_stage_for(p["id"]) for p in conn.pipelines},
        "add_notes": conn.add_notes,
        "link_field_id": conn.link_field_id,
        "status_field_id": conn.status_field_id,
    }


@router.get("/status")
def status(request):
    return _out(_conn(request))


@router.get("/connect-url")
def connect_url(request):
    require_manager(request)
    if not settings.AMOCRM_CLIENT_ID:
        raise HttpError(503, "The amoCRM integration isn't configured on this server yet.")
    return {"url": oauth.authorize_url(request.company.pk, request.user.pk)}


@router.post("/pipelines/refresh")
def refresh_pipelines(request):
    require_manager(request)
    conn = _conn(request)
    if conn is None:
        raise HttpError(404, "amoCRM isn't connected.")
    try:
        services.sync_pipelines(conn)
    except AmoError as e:
        raise HttpError(502, str(e))
    return _out(conn)


@router.get("/custom-fields")
def custom_fields(request):
    conn = _conn(request)
    if conn is None:
        raise HttpError(404, "amoCRM isn't connected.")
    try:
        fields = AmoClient(conn).lead_custom_fields()
    except AmoError as e:
        raise HttpError(502, str(e))
    return [f for f in fields if f["type"] in ("url", "text", "textarea")]


@router.put("/settings")
def save_settings(request, data: SettingsIn):
    require_manager(request)
    conn = _conn(request)
    if conn is None:
        raise HttpError(404, "amoCRM isn't connected.")
    valid = {str(p["id"]): {s["id"] for s in p["statuses"]} for p in conn.pipelines}
    for pid, sid in data.paid_stages.items():
        if pid not in valid or sid not in valid[pid]:
            raise HttpError(422, f"Stage {sid} isn't in pipeline {pid}. Refresh pipelines and try again.")
    conn.paid_stages = data.paid_stages
    conn.add_notes = data.add_notes
    conn.link_field_id = data.link_field_id
    conn.status_field_id = data.status_field_id
    conn.save(update_fields=["paid_stages", "add_notes", "link_field_id", "status_field_id"])
    return _out(conn)


@router.post("/disconnect")
def disconnect(request):
    require_manager(request)
    conn = _conn(request)
    if conn is not None:
        conn.delete()
    return _out(None)
