from ninja import Router, Schema
from ninja.errors import HttpError

from core.api import member_auth, require_manager

from . import oauth, services
from .client import AmoClient, AmoError
from .models import AmoConnection

router = Router(tags=["amocrm"], auth=member_auth)


class ManualIn(Schema):
    host: str
    client_id: str
    client_secret: str
    code: str = ""


class SettingsIn(Schema):
    paid_stages: dict[str, int] = {}
    link_stages: dict[str, int] = {}
    add_notes: bool = True
    link_field_id: int | None = None
    status_field_id: int | None = None


def _conn(request) -> AmoConnection | None:
    """The connection the dashboard is looking at: ?conn=<id>, else the company's first."""
    qs = AmoConnection.objects.filter(company=request.company).order_by("connected_at", "pk")
    pick = request.GET.get("conn", "")
    if pick.isdigit():
        return qs.filter(pk=int(pick)).first()
    return qs.first()


@router.get("/connections")
def connections(request):
    return [
        {"id": c.pk, "host": c.host, "status": c.status, "connected_at": c.connected_at}
        for c in AmoConnection.objects.filter(company=request.company).order_by("connected_at", "pk")
    ]


def _out(conn: AmoConnection | None) -> dict:
    if conn is None:
        return {"connected": False}
    return {
        "id": conn.pk,
        "connected": conn.status != AmoConnection.Status.DISCONNECTED,
        "status": conn.status,
        "last_error": conn.last_error,
        "account_id": conn.account_id,
        "host": conn.host,
        "connected_at": conn.connected_at,
        "pipelines": conn.pipelines,
        "pipelines_synced_at": conn.pipelines_synced_at,
        "paid_stages": {str(p["id"]): conn.paid_stage_for(p["id"]) for p in conn.pipelines},
        "link_stages": conn.link_stages,
        "widget_client_id": conn.widget_client_id,
        "add_notes": conn.add_notes,
        "link_field_id": conn.link_field_id,
        "status_field_id": conn.status_field_id,
        "payment_accounts": conn.payment_accounts,
        "sms_account_id": conn.sms_account_id,
        "widget_urls": {
            "redirect": oauth.redirect_uri(),
            "uninstall": oauth.redirect_uri().replace("/callback", "/uninstall"),
        },
    }


@router.get("/status")
def status(request):
    return _out(_conn(request))


@router.post("/connect-button")
def connect_button(request):
    """Parameters for amoCRM's button; amoCRM creates the integration in the chosen account."""
    require_manager(request)
    return oauth.start_install(request.company, request.user)


@router.post("/connect-manual")
def connect_manual(request, data: ManualIn):
    """Connect through an integration the company created by hand in amoCRM.

    Only hand-made integrations can carry our widget archive (lead-card panel,
    SMS on phone click), so this is the route when the widget is wanted.
    The code comes from the integration's "Ключи и доступы" tab (valid 20 min).
    """
    import re

    require_manager(request)
    host = re.sub(r"^https?://", "", data.host.strip().lower()).split("/")[0]
    if "." not in host:
        host = f"{host}.amocrm.ru"
    if not oauth.valid_host(host):
        raise HttpError(422, "Enter your amoCRM address, e.g. mycompany.amocrm.ru")
    if not (data.client_id.strip() and data.client_secret.strip()):
        raise HttpError(422, "Integration ID and secret key are required.")
    if not data.code.strip():
        # Already connected to this account: the private integration only carries
        # the widget, so its keys are enough; the existing API tokens stay.
        conn = AmoConnection.objects.filter(company=request.company, host=host).first()
        if conn is None or conn.status == AmoConnection.Status.DISCONNECTED:
            raise HttpError(422, f"{host} isn't connected yet: the authorization code is required the first time.")
        conn.widget_client_id = data.client_id.strip()
        conn.widget_client_secret = data.client_secret.strip()
        conn.save(update_fields=["widget_client_id", "widget_client_secret"])
        return _out(conn)
    try:
        conn = services.connect(
            request.company, request.user, host, data.code.strip(), data.client_id.strip(), data.client_secret.strip()
        )
    except services.AlreadyLinked as e:
        raise HttpError(409, str(e))
    except oauth.OAuthError as e:
        if "revoked" in str(e).lower():
            # amoCRM issues a new code each time the integration is saved (e.g. after an
            # archive upload); the one on an already-open tab is dead even inside 20 minutes.
            raise HttpError(
                422,
                "amoCRM says this authorization code is no longer valid. Reload the integration page "
                "in amoCRM (F5), copy the fresh code from «Ключи и доступы» and paste it here straight away.",
            )
        raise HttpError(422, f"amoCRM refused the keys or the code (the code lives 20 minutes). {e}")
    except AmoError as e:
        raise HttpError(502, str(e))
    return _out(conn)


@router.post("/fields/create")
def create_fields(request):
    require_manager(request)
    conn = _conn(request)
    if conn is None:
        raise HttpError(404, "amoCRM isn't connected.")
    try:
        services.create_lead_fields(conn)
    except AmoError as e:
        raise HttpError(502, str(e))
    return _out(conn)


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
    for pid, sid in [*data.paid_stages.items(), *data.link_stages.items()]:
        if pid not in valid or sid not in valid[pid]:
            raise HttpError(422, f"Stage {sid} isn't in pipeline {pid}. Refresh pipelines and try again.")
    for pid, sid in data.link_stages.items():
        if data.paid_stages.get(pid, 142) == sid:
            raise HttpError(422, "The link stage and the paid stage must differ.")
    conn.paid_stages = data.paid_stages
    conn.link_stages = data.link_stages
    conn.add_notes = data.add_notes
    conn.link_field_id = data.link_field_id
    conn.status_field_id = data.status_field_id
    fields = ["paid_stages", "link_stages", "add_notes", "link_field_id", "status_field_id"]
    conn.save(update_fields=fields)
    return _out(conn)


class AccountsIn(Schema):
    payment_accounts: list[int] | None = None  # None = the first working account of each provider
    sms_account_id: int | None = None


@router.put("/accounts")
def save_accounts(request, data: AccountsIn):
    """Which merchant and SMS accounts this amoCRM account uses (?conn=<id>)."""
    from payments.models import ProviderAccount
    from sms.models import SmsAccount

    require_manager(request)
    conn = _conn(request)
    if conn is None:
        raise HttpError(404, "amoCRM isn't connected.")
    if data.payment_accounts is None:
        conn.payment_accounts = None
    else:
        chosen, seen = [], set()
        for acc in ProviderAccount.objects.filter(company=conn.company, pk__in=data.payment_accounts):
            if acc.provider not in seen:  # one cash desk per provider
                seen.add(acc.provider)
                chosen.append(acc.pk)
        conn.payment_accounts = chosen
    conn.sms_account = (
        SmsAccount.objects.filter(company=conn.company, pk=data.sms_account_id).first() if data.sms_account_id else None
    )
    conn.save(update_fields=["payment_accounts", "sms_account"])
    return _out(conn)


@router.post("/disconnect")
def disconnect(request):
    require_manager(request)
    conn = _conn(request)
    if conn is not None:
        try:
            services.unsubscribe_webhook(conn)
        except AmoError:
            pass  # token already dead; nothing left to clean up on their side
        # Keep the row: stages, SMS field, widget keys and account choices come
        # back when the same amoCRM account is connected again.
        conn.status = AmoConnection.Status.DISCONNECTED
        conn.access_token = conn.refresh_token = ""
        conn.last_error = ""
        conn.save(update_fields=["status", "access_token", "refresh_token", "last_error"])
    return _out(conn)


# ------------------------------------------------ SMS / document keywords from amoCRM fields


class VariableIn(Schema):
    key: str
    source: str
    label: str = ""


def _vars_out(conn: AmoConnection) -> dict:
    from sms.models import BUILTIN_VARIABLES, SmsVariable

    from .variables import sources

    try:
        src = sources(AmoClient(conn))
    except AmoError:
        src = []
    return {
        "builtins": list(BUILTIN_VARIABLES),
        "variables": [
            {"key": v.key, "source": v.source, "label": v.label}
            for v in SmsVariable.objects.filter(company=conn.company, integration=SmsVariable.Integration.AMOCRM)
        ],
        "sources": src,
    }


@router.get("/variables")
def get_variables(request):
    """The company's {keywords} and the amoCRM lead / contact fields they can read (?conn=<id>)."""
    conn = _conn(request)
    if conn is None or conn.status != AmoConnection.Status.ACTIVE:
        raise HttpError(409, "Connect amoCRM first.")
    return _vars_out(conn)


@router.put("/variables")
def save_variables(request, data: list[VariableIn]):
    from sms.models import SmsVariable
    from sms.services import save_variables as save

    from .variables import SOURCE_RE

    require_manager(request)
    conn = _conn(request)
    if conn is None or conn.status != AmoConnection.Status.ACTIVE:
        raise HttpError(409, "Connect amoCRM first.")
    try:
        save(conn.company, SmsVariable.Integration.AMOCRM, [d.dict() for d in data], lambda s: bool(SOURCE_RE.match(s)))
    except ValueError as e:
        raise HttpError(422, str(e))
    return _vars_out(conn)
