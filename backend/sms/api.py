from django.db import transaction
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

from core.api import member_auth, require_manager
from core.crypto import mask

from . import gateways, services
from .models import SmsAccount, SmsMessage, SmsProvider, SmsSettings, SmsTemplate

router = Router(tags=["sms"], auth=member_auth)


class AccountIn(Schema):
    label: str = ""
    is_enabled: bool = False
    login: str = ""
    secret: str | None = None  # omitted = keep
    sender: str = ""


class NewAccountIn(AccountIn):
    provider: str


class SettingsIn(Schema):
    provider: str = ""  # legacy; `account_id` wins
    account_id: int | None = None
    link_template_id: int | None = None
    paid_template_id: int | None = None


class TemplateIn(Schema):
    text: str
    account_id: int | None = None  # default: the company's default SMS account


class TestIn(Schema):
    phone: str
    text: str
    account_id: int | None = None


def _account_out(a: SmsAccount) -> dict:
    return {
        "id": a.pk,
        "provider": a.provider,
        "provider_label": a.get_provider_display(),
        "label": a.label,
        "is_enabled": a.is_enabled,
        "is_configured": a.is_configured,
        "login": a.login,
        "secret_masked": mask(a.secret),
        "sender": a.sender,
        "balance": a.balance,
        "checked_at": a.checked_at,
        "last_error": a.last_error,
        # Delivery reports come back to this account's own URL.
        "dlr_url": services.dlr_url(a),
    }


@router.get("/accounts")
def accounts(request):
    return [_account_out(a) for a in SmsAccount.objects.filter(company=request.company)]


def _own(request, account_id: int) -> SmsAccount:
    a = SmsAccount.objects.filter(company=request.company, pk=account_id).first()
    if a is None:
        raise HttpError(404, "SMS account not found.")
    return a


def _apply(a: SmsAccount, data: AccountIn) -> None:
    sender = data.sender.strip()
    if len(sender) > 11:
        raise HttpError(422, "Sender name is at most 11 characters.")
    changed_login = a.login != data.login.strip() or data.secret is not None
    a.label, a.login, a.sender = data.label.strip()[:80], data.login.strip(), sender
    if data.secret is not None:
        a.secret = data.secret.strip()
    if changed_login:
        a.token, a.token_expires_at = "", None
    if data.is_enabled and not a.is_configured:
        raise HttpError(422, "Fill in the login and password before switching this account on.")
    a.is_enabled = data.is_enabled


@router.post("/accounts")
@transaction.atomic
def add_account(request, data: NewAccountIn):
    require_manager(request)
    if data.provider not in SmsProvider.values:
        raise HttpError(404, "Unknown SMS provider.")
    a = SmsAccount(company=request.company, provider=data.provider)
    _apply(a, data)
    a.save()
    from payments.api import _billing_gate

    _billing_gate(request, "sms")  # raising rolls the save back
    return _account_out(a)


@router.put("/accounts/{account_id}")
@transaction.atomic
def save_account(request, account_id: int, data: AccountIn):
    require_manager(request)
    a = _own(request, account_id)
    _apply(a, data)
    a.save()
    from payments.api import _billing_gate

    _billing_gate(request, "sms")
    return _account_out(a)


@router.delete("/accounts/{account_id}")
def delete_account(request, account_id: int):
    require_manager(request)
    a = _own(request, account_id)
    if a.messages.exists():
        raise HttpError(409, "This account has sent messages; switch it off instead of deleting it.")
    a.delete()
    return {"ok": True}


@router.post("/accounts/{account_id}/check")
def check_account(request, account_id: int):
    """Eskiz: log in and read the balance. Playmobile has no read-only call."""
    a = _own(request, account_id)
    if not a.is_configured:
        raise HttpError(409, "Fill in the login and password first.")
    if a.provider == SmsProvider.ESKIZ:
        try:
            a.balance = gateways.eskiz_balance(a)
            a.last_error = ""
        except gateways.SmsError as e:
            a.last_error = str(e)[:500]
        a.checked_at = timezone.now()
        a.save(update_fields=["balance", "last_error", "checked_at"])
    return _account_out(a)


def _settings(company) -> SmsSettings:
    s, _ = SmsSettings.objects.get_or_create(company=company)
    return s


def _settings_out(s: SmsSettings) -> dict:
    return {
        "provider": s.provider,
        "account_id": s.account_id,
        "link_template_id": s.link_template_id,
        "paid_template_id": s.paid_template_id,
    }


@router.get("/settings")
def get_settings(request):
    return _settings_out(_settings(request.company))


@router.put("/settings")
def save_settings(request, data: SettingsIn):
    require_manager(request)
    if data.provider and data.provider not in SmsProvider.values:
        raise HttpError(422, "Unknown SMS provider.")
    s = _settings(request.company)
    s.provider = data.provider
    if data.account_id is not None:
        s.account = SmsAccount.objects.filter(company=request.company, pk=data.account_id).first()
        s.provider = s.account.provider if s.account else ""
    for attr, tid in (("link_template", data.link_template_id), ("paid_template", data.paid_template_id)):
        t = SmsTemplate.objects.filter(company=request.company, pk=tid).first() if tid else None
        if tid and (t is None or not t.is_approved):
            raise HttpError(422, "Only approved templates can be used.")
        if attr == "link_template" and t is not None and "{link}" not in t.text:
            raise HttpError(422, "The payment-link template must contain {link}.")
        setattr(s, attr, t)
    s.save()
    return _settings_out(s)


def _template_out(t: SmsTemplate) -> dict:
    return {
        "id": t.pk,
        "provider": t.provider,
        "account_id": t.account_id,
        "text": t.text,
        "status": t.status,
        "approved": t.is_approved,
        "in_amocrm": bool(t.amo_enum_id),
    }


@router.get("/templates")
def templates(request):
    return [_template_out(t) for t in SmsTemplate.objects.filter(company=request.company)]


@router.post("/templates/sync")
def sync_templates(request):
    """Pull Eskiz templates; approved ones become usable."""
    require_manager(request)
    try:
        rows = services.sync_templates(request.company)
    except gateways.SmsError as e:
        raise HttpError(502, str(e))
    return [_template_out(t) for t in rows]


@router.post("/templates")
def add_template(request, data: TemplateIn):
    """Eskiz: submit for moderation. Playmobile: add straight away (no moderation there)."""
    require_manager(request)
    text = data.text.strip()
    if not text:
        raise HttpError(422, "Write the template text.")
    preferred = (
        SmsAccount.objects.filter(company=request.company, pk=data.account_id).first() if data.account_id else None
    )
    account = (
        preferred if preferred is not None and preferred.is_configured else services.active_account(request.company)
    )
    if account is None:
        raise HttpError(409, "Set up Eskiz or Playmobile first.")
    if account.provider == SmsProvider.ESKIZ:
        try:
            gateways.eskiz_submit_template(account, text)
            rows = services.sync_templates(request.company, account)
        except gateways.SmsError as e:
            raise HttpError(502, str(e))
        return [_template_out(t) for t in rows]
    SmsTemplate.objects.create(
        company=request.company, account=account, provider=account.provider, text=text, status="local"
    )
    return templates(request)


@router.delete("/templates/{template_id}")
def delete_template(request, template_id: int):
    require_manager(request)
    t = SmsTemplate.objects.filter(company=request.company, pk=template_id, status="local").first()
    if t is None:
        raise HttpError(404, "Only your own (Playmobile) templates can be deleted here.")
    t.delete()
    return templates(request)


@router.post("/amocrm/sync")
def sync_amocrm_field(request):
    """Put the approved templates into amoCRM's "SMS shablon" lead field (uzbridge tab)."""
    from amocrm.client import AmoError
    from amocrm.models import AmoConnection
    from amocrm.services import sync_sms_field

    require_manager(request)
    conns = list(AmoConnection.objects.filter(company=request.company, status=AmoConnection.Status.ACTIVE))
    if not conns:
        raise HttpError(409, "Connect amoCRM first.")
    try:
        for conn in conns:  # each amoCRM account gets its own SMS account's templates
            sync_sms_field(conn)
    except AmoError as e:
        raise HttpError(502, str(e))
    return {"field_id": conns[0].sms_field_id, "templates": templates(request)}


@router.get("/amocrm")
def amocrm_state(request):
    from amocrm.models import AmoConnection

    conn = AmoConnection.objects.filter(company=request.company).first()
    return {"connected": bool(conn and conn.status == "active"), "field_id": conn.sms_field_id if conn else None}


@router.post("/test")
def send_test(request, data: TestIn):
    require_manager(request)
    try:
        account = (
            SmsAccount.objects.filter(company=request.company, pk=data.account_id).first() if data.account_id else None
        )
        msg = services.queue(request.company, data.phone, data.text, account=account)
    except gateways.SmsError as e:
        raise HttpError(422, str(e))
    return {"id": msg.pk, "status": msg.status}


@router.get("/messages")
def messages(request, limit: int = 50):
    rows = SmsMessage.objects.filter(company=request.company).select_related("invoice", "account")[
        : max(1, min(limit, 200))
    ]
    return [
        {
            "id": m.pk,
            "provider": m.provider,
            "account": m.account.display_name if m.account_id else "",
            "phone": m.phone,
            "text": m.text,
            "event": m.event,
            "status": m.status,
            "provider_status": m.provider_status,
            "error": m.error,
            "invoice": m.invoice.display_number if m.invoice else "",
            "created_at": m.created_at,
        }
        for m in rows
    ]


# ------------------------------------------------ the company's own {keywords}

ODOO_PATH_RE = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){0,4}$"


class VariableIn(Schema):
    key: str
    source: str
    label: str = ""


def _variables(company, integration: str) -> dict:
    from .models import BUILTIN_VARIABLES, SmsVariable

    return {
        "builtins": list(BUILTIN_VARIABLES),
        "variables": [
            {"key": v.key, "source": v.source, "label": v.label}
            for v in SmsVariable.objects.filter(company=company, integration=integration)
        ],
    }


@router.get("/variables/{integration}")
def get_variables(request, integration: str):
    """amoCRM keywords are edited inside amoCRM (Настройки → uzbridge); shown here read-only."""
    from .models import SmsVariable

    if integration not in SmsVariable.Integration.values:
        raise HttpError(404, "Unknown integration.")
    return _variables(request.company, integration)


@router.put("/variables/{integration}")
def save_odoo_variables(request, integration: str, data: list[VariableIn]):
    import re

    from .models import SmsVariable

    require_manager(request)
    if integration != SmsVariable.Integration.ODOO:
        raise HttpError(405, "amoCRM keywords are set inside amoCRM: Настройки → uzbridge.")
    try:
        services.save_variables(
            request.company,
            SmsVariable.Integration.ODOO,
            [d.dict() for d in data],
            lambda s: bool(re.match(ODOO_PATH_RE, s)),
        )
    except ValueError as e:
        raise HttpError(422, str(e))
    return _variables(request.company, SmsVariable.Integration.ODOO)
