"""API for the amoCRM widget in the lead card.

The widget calls us with `self.$authorizedAjax`, which adds an
`X-Auth-Token` JWT signed HS256 with our integration's client secret
(https://www.amocrm.ru/developers/content/oauth/disposable-tokens).
"""

from urllib.parse import urlsplit

import jwt
from django.db import transaction
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.security import APIKeyHeader

from documents.models import DocTemplate
from payments import services as pay
from payments.models import Invoice

from . import oauth, services
from .models import AmoConnection
from .tasks import post_link_note


class WidgetToken(APIKeyHeader):
    param_name = "X-Auth-Token"

    def authenticate(self, request, key):
        if not key:
            return None
        # Each company has its own integration, so find it first (unverified),
        # then check the signature with that integration's secret.
        try:
            account_id = int(jwt.decode(key, options={"verify_signature": False}).get("account_id", 0))
        except (jwt.PyJWTError, TypeError, ValueError):
            return None
        conn = (
            AmoConnection.objects.select_related("company")
            .filter(account_id=account_id, status=AmoConnection.Status.ACTIVE, company__is_active=True)
            .first()
        )
        if conn is None:
            return None
        parts = urlsplit(oauth.redirect_uri())
        claims = None
        for secret in filter(None, (conn.widget_client_secret, conn.client_secret)):
            try:
                claims = jwt.decode(
                    key,
                    secret,
                    algorithms=["HS256"],
                    audience=f"{parts.scheme}://{parts.netloc}",
                    options={"require": ["exp", "account_id"]},
                    leeway=30,
                )
                break
            except jwt.PyJWTError:
                continue
        if claims is None:
            return None
        request.amo = conn
        request.company = conn.company
        request.amo_user_id = claims.get("user_id")
        return conn


router = Router(tags=["widget"], auth=WidgetToken())


class InvoiceIn(Schema):
    lead_id: int
    amount: str  # soum, "1500000" or "1500000.50"
    description: str = ""
    lead_name: str = ""
    user_name: str = ""


def _to_tiyin(amount: str) -> int:
    from decimal import Decimal, InvalidOperation

    try:
        value = Decimal(amount.replace(" ", "").replace(",", "."))
    except InvalidOperation:
        raise HttpError(422, "Amount must be a number.")
    tiyin = value * 100
    if tiyin != tiyin.to_integral_value() or tiyin <= 0:
        raise HttpError(422, "Amount must be positive, with at most two decimals.")
    return int(tiyin)


def _invoice_out(inv: Invoice) -> dict:
    return {
        "id": str(inv.public_id),
        "number": inv.display_number,
        "amount": services.money(inv.amount_tiyin),
        "status": inv.status,
        "paid_via": inv.paid_via,
        "paid_at": inv.paid_at,
        "created_at": inv.created_at,
        "url": services.pay_link(inv),
    }


@router.get("/context")
def context(request, lead_id: int = 0):
    from django.db.models import Q

    conn = request.amo
    providers = [a.provider for a in services.amo_accounts(conn)]
    invoices = (
        Invoice.objects.filter(company=request.company, source=Invoice.Source.AMOCRM, external_id=str(lead_id))
        .filter(Q(amo_connection=conn) | Q(amo_connection=None))
        .select_related("company")[:20]
    )
    return {
        "company": request.company.name,
        "providers": providers,
        "invoices": [_invoice_out(i) for i in invoices],
        "sms_ready": services.amo_sms_account(conn) is not None,
        "sms_templates": [{"id": t.pk, "text": t.text} for t in services.amo_templates(conn)],
    }


# ------------------------------------------------ the widget's page in Настройки


def _require_admin(request) -> None:
    from .client import AmoClient, AmoError

    user_id = getattr(request, "amo_user_id", None)
    try:
        ok = bool(user_id) and AmoClient(request.amo).is_admin(user_id)
    except AmoError:
        ok = False
    if not ok:
        raise HttpError(403, "Only amoCRM administrators can change uzbridge settings.")


def _settings_out(conn: AmoConnection) -> dict:
    from payments.models import Provider, ProviderAccount
    from sms.models import SmsAccount
    from sms.services import account_templates, active_account

    active = {a.pk for a in pay.enabled_accounts(conn.company)}
    used = {a.pk for a in services.amo_accounts(conn)}
    all_accounts = list(ProviderAccount.objects.filter(company=conn.company))
    sms_accounts = list(SmsAccount.objects.filter(company=conn.company))
    sms = active_account(conn.company, conn.sms_account)
    templates = account_templates(conn.company, sms) if sms is not None else []
    return {
        "company": conn.company.name,
        "account": conn.host,
        "providers": [
            {
                "code": p.value,
                "name": p.label,
                "accounts": [
                    {
                        "id": a.pk,
                        "name": a.label or p.label,
                        # active: keys entered and switched on in the uzbridge dashboard
                        "active": a.pk in active,
                        "configured": a.is_configured,
                        "use": a.pk in used,
                    }
                    for a in all_accounts
                    if a.provider == p.value
                ],
            }
            for p in Provider
        ],
        "sms": {
            "ready": sms is not None,
            "provider": sms.display_name if sms is not None else "",
            "enabled": conn.sms_enabled,
            "account_id": sms.pk if sms is not None else None,
            "accounts": [
                {"id": a.pk, "name": a.display_name, "active": a.is_enabled and a.is_configured} for a in sms_accounts
            ],
        },
        "templates": [
            {"id": t.pk, "text": t.text, "status": t.status, "approved": t.is_approved, "use": t.use_in_amocrm}
            for t in templates
        ],
        "bills_enabled": conn.bills_enabled,
        "docs": {
            "enabled": conn.docs_enabled,
            "templates": [
                {"id": t.pk, "name": t.name, "format": t.default_format, "use": t.use_in_amocrm}
                for t in DocTemplate.objects.filter(company=conn.company)
            ],
        },
        "realty": _realty_settings(conn),
        # Stored in each Digital Pipeline trigger; amoCRM sends it back with the hook.
        "dp_key": conn.hook_token,
        "dashboard": pay_dashboard_url(conn),
    }


def _realty_settings(conn: AmoConnection) -> dict:
    from realty.models import Project
    from realty.services import DEFAULT_STAGE

    stages = conn.realty_stages or {}
    return {
        "projects": [
            {
                "id": p.pk,
                "name": p.name,
                "currency": p.currency,
                "use": p.use_in_amocrm,
                "units": p.units.filter(archived=False).count(),
            }
            for p in Project.objects.filter(company=conn.company)
        ],
        # per pipeline, per stage: what the deal's units become there ("" = nothing changes)
        "pipelines": [
            {
                "id": pl["id"],
                "name": pl.get("name", ""),
                "statuses": [
                    {
                        "id": st["id"],
                        "name": st.get("name", ""),
                        "color": st.get("color"),
                        "type": st.get("type"),
                        "unit_status": stages.get(str(pl["id"]), {}).get(
                            str(st["id"]), DEFAULT_STAGE.get(st["id"], "")
                        ),
                    }
                    for st in pl.get("statuses", [])
                ],
            }
            for pl in conn.pipelines or []
        ],
        "dashboard": pay_dashboard_url(conn).replace("/integrations/amocrm", "/shaxmatka"),
    }


def _charge_docs(conn: AmoConnection) -> None:
    """Documents is a tariff item (per amoCRM account): pay for it before it switches on."""
    from billing.services import InsufficientBalance, apply_change

    try:
        apply_change(conn.company, "docs")
    except InsufficientBalance as e:
        raise HttpError(
            402,
            f"uzbridge balance is too low for Documents: {e.needed // 100:,} soʻm needed, "
            f"{e.balance // 100:,} available. Top up in the uzbridge dashboard (Kabinet).".replace(",", " "),
        )


def pay_dashboard_url(conn: AmoConnection) -> str:
    from core.tenancy import company_url

    return company_url(conn.company, "/integrations/amocrm")


class SettingsIn(Schema):
    accounts: list[int]  # ProviderAccount ids, at most one per provider
    sms_enabled: bool
    sms_account_id: int | None = None
    bills_enabled: bool = True
    templates: dict[str, bool] = {}  # {"<template id>": use in amoCRM}
    docs_enabled: bool | None = None
    doc_templates: dict[str, bool] = {}  # {"<document template id>": use in amoCRM}
    realty_projects: dict[str, bool] = {}  # {"<project id>": in the deal's showroom}
    realty_stages: dict[str, dict[str, str]] | None = None  # {"<pipeline>": {"<status>": unit status or ""}}


def _save_realty(conn: AmoConnection, data: SettingsIn) -> None:
    from realty.models import Project, UnitStatus

    for pid, use in data.realty_projects.items():
        if str(pid).isdigit():
            Project.objects.filter(company=conn.company, pk=int(pid)).update(use_in_amocrm=bool(use))
    if data.realty_stages is None:
        return
    known = {str(pl["id"]): {str(st["id"]) for st in pl.get("statuses", [])} for pl in conn.pipelines or []}
    allowed = {UnitStatus.INTEREST, UnitStatus.RESERVED, UnitStatus.SOLD, UnitStatus.FREE}
    clean = {}
    for pid, row in data.realty_stages.items():
        for sid, status in (row or {}).items():
            if sid not in known.get(str(pid), set()):
                continue
            # "" is kept too: it overrides the won/lost default with "nothing changes"
            if status in allowed or status == "":
                clean.setdefault(str(pid), {})[sid] = status
    conn.realty_stages = clean
    conn.save(update_fields=["realty_stages"])


@router.get("/settings")
def get_settings(request):
    return _settings_out(request.amo)


@router.put("/settings")
def put_settings(request, data: SettingsIn):
    from payments.models import ProviderAccount
    from sms.models import SmsAccount, SmsTemplate

    from .client import AmoError

    _require_admin(request)
    conn = request.amo
    chosen, seen = [], set()
    for acc in ProviderAccount.objects.filter(company=conn.company, pk__in=data.accounts):
        if acc.provider not in seen:  # one cash desk per provider
            seen.add(acc.provider)
            chosen.append(acc.pk)
    conn.payment_accounts = chosen
    conn.sms_enabled = data.sms_enabled
    if data.sms_account_id is not None:
        conn.sms_account = SmsAccount.objects.filter(company=conn.company, pk=data.sms_account_id).first()
    conn.bills_enabled = data.bills_enabled
    switching_docs_on = data.docs_enabled is True and not conn.docs_enabled
    if data.docs_enabled is not None:
        conn.docs_enabled = data.docs_enabled
    with transaction.atomic():
        conn.save(update_fields=["payment_accounts", "sms_enabled", "sms_account", "bills_enabled", "docs_enabled"])
        if switching_docs_on:
            _charge_docs(conn)  # raising rolls the switch back
    _save_realty(conn, data)
    for tid, use in data.doc_templates.items():
        if str(tid).isdigit():
            DocTemplate.objects.filter(company=conn.company, pk=int(tid)).update(use_in_amocrm=bool(use))
    for tid, use in data.templates.items():
        if str(tid).isdigit():
            SmsTemplate.objects.filter(company=conn.company, pk=int(tid)).update(use_in_amocrm=bool(use))
    try:
        services.sync_sms_field(conn)  # the lead's template list follows the switches
    except AmoError:
        pass  # saved; the hourly template sync retries the field
    return _settings_out(conn)


class SmsIn(Schema):
    phone: str | int  # amoCRM passes it as a number
    message: str
    contact_id: int | None = None
    lead_id: int | None = None


class SmsTemplateIn(Schema):
    lead_id: int
    template_id: int


@router.post("/sms")
def send_sms(request, data: SmsIn):
    """amoCRM's SMS source (add_source "sms"): the manager typed a text in the feed."""
    from sms.gateways import SmsError
    from sms.models import SmsMessage
    from sms.services import queue

    from .tasks import note_sms

    if not request.amo.sms_enabled:
        raise HttpError(409, "SMS is switched off for amoCRM (Настройки → uzbridge).")
    try:
        msg = queue(
            request.company,
            str(data.phone),
            data.message,
            event=SmsMessage.Event.AMOCRM,
            lead_id=data.lead_id,
            account=request.amo.sms_account,
        )
    except SmsError as e:
        raise HttpError(422, str(e))
    note = f"📱 SMS → +{msg.phone} ({msg.get_provider_display()}):\n{msg.text}"
    if request.amo.add_notes and data.lead_id:
        note_sms.delay(request.amo.pk, "lead", data.lead_id, note)
    elif request.amo.add_notes and data.contact_id:
        note_sms.delay(request.amo.pk, "contact", data.contact_id, note)
    return {"id": msg.pk, "status": msg.status, "phone": msg.phone}


@router.post("/sms/template")
def send_sms_template(request, data: SmsTemplateIn):
    from sms.gateways import SmsError
    from sms.models import SmsTemplate

    from .client import AmoClient, AmoError
    from .tasks import send_template_to_lead

    template = SmsTemplate.objects.filter(company=request.company, pk=data.template_id).first()
    if template is None or template not in services.amo_templates(request.amo):
        raise HttpError(422, "This template isn't approved or is switched off for amoCRM.")
    try:
        msg = send_template_to_lead(request.amo, AmoClient(request.amo), data.lead_id, template)
    except SmsError as e:
        raise HttpError(422, str(e))
    except AmoError as e:
        raise HttpError(502, str(e))
    return {"id": msg.pk, "status": msg.status, "phone": msg.phone, "text": msg.text}


@router.post("/invoices")
def create(request, data: InvoiceIn):
    if not services.amo_accounts(request.amo):
        raise HttpError(409, "No payment methods are set up yet. Add Payme, Click or Uzum in the uzbridge dashboard.")
    invoice = pay.create_invoice(
        request.company,
        amount_tiyin=_to_tiyin(data.amount),
        description=data.description[:255] or data.lead_name[:255],
        source=Invoice.Source.AMOCRM,
        external_id=str(data.lead_id),
        external_name=data.lead_name[:255],
        created_by_label=data.user_name[:150],
        amo_connection=request.amo,
    )
    post_link_note.delay(invoice.pk)
    return _invoice_out(invoice)


@router.post("/invoices/{public_id}/cancel")
def cancel(request, public_id: str):
    invoice = Invoice.objects.filter(company=request.company, public_id=public_id).first()
    if invoice is None:
        raise HttpError(404, "Invoice not found.")
    try:
        invoice = pay.cancel_invoice(invoice)
    except ValueError as e:
        raise HttpError(409, str(e))
    return _invoice_out(invoice)


# ------------------------------------------------ SMS keywords filled from amoCRM fields


class VariableIn(Schema):
    key: str
    source: str
    label: str = ""


def _variables_out(conn: AmoConnection, with_sources: bool) -> dict:
    from sms.models import BUILTIN_VARIABLES, SmsVariable

    from .client import AmoClient, AmoError
    from .variables import sources

    out = {
        "builtins": list(BUILTIN_VARIABLES),
        "variables": [
            {"key": v.key, "source": v.source, "label": v.label}
            for v in SmsVariable.objects.filter(company=conn.company, integration=SmsVariable.Integration.AMOCRM)
        ],
    }
    if with_sources:
        try:
            out["sources"] = sources(AmoClient(conn))
        except AmoError:
            out["sources"] = []
    return out


@router.get("/variables")
def get_variables(request):
    return _variables_out(request.amo, with_sources=True)


@router.put("/variables")
def put_variables(request, data: list[VariableIn]):
    from sms.models import SmsVariable
    from sms.services import save_variables

    from .variables import SOURCE_RE

    _require_admin(request)
    try:
        save_variables(
            request.amo.company,
            SmsVariable.Integration.AMOCRM,
            [d.dict() for d in data],
            lambda s: bool(SOURCE_RE.match(s)),
        )
    except ValueError as e:
        raise HttpError(422, str(e))
    return _variables_out(request.amo, with_sources=True)


# ------------------------------------------------ documents from templates


class GenerateIn(Schema):
    lead_id: int
    template_id: int
    format: str = ""  # "docx" | "pdf"; empty = the template's default
    user_name: str = ""


def _docs_out(conn: AmoConnection, lead_id: int) -> dict:
    from documents.models import GeneratedDoc
    from documents.services import download_url

    templates = DocTemplate.objects.filter(company=conn.company, use_in_amocrm=True) if conn.docs_enabled else []
    made = GeneratedDoc.objects.filter(amo_connection=conn, lead_id=lead_id).select_related("template")
    return {
        "enabled": conn.docs_enabled,
        "templates": [
            {"id": t.pk, "name": t.name, "format": t.default_format, "next": t.format_number(t.next_number)}
            for t in templates
        ],
        "documents": [
            {
                "id": d.pk,
                "number": d.number,
                "template_id": d.template_id,
                "template": d.template.name,
                "format": d.format,
                "url": download_url(d),
                "updated_at": d.updated_at,
            }
            for d in made
        ],
    }


@router.get("/docs")
def lead_docs(request, lead_id: int):
    return _docs_out(request.amo, lead_id)


@router.post("/docs/generate")
def generate_doc(request, data: GenerateIn):
    from documents import render
    from documents import services as docs

    from .client import AmoError

    conn = request.amo
    if not conn.docs_enabled:
        raise HttpError(409, "Documents are switched off for this amoCRM (Настройки → uzbridge).")
    template = DocTemplate.objects.filter(company=conn.company, pk=data.template_id, use_in_amocrm=True).first()
    if template is None:
        raise HttpError(404, "This template isn't available in amoCRM.")
    try:
        doc = docs.generate(conn, template, data.lead_id, data.format, user_label=data.user_name or "amoCRM")
    except render.RenderError as e:
        raise HttpError(422, str(e))
    except AmoError as e:
        raise HttpError(502, str(e))
    out = _docs_out(conn, data.lead_id)
    out["made"] = {"number": doc.number, "url": docs.download_url(doc), "format": doc.format}
    return out


# ------------------------------------------------ shaxmatka (units in the deal)


class RealtySessionIn(Schema):
    lead_id: int
    user_name: str = ""


class RealtyUnitIn(Schema):
    lead_id: int
    unit_id: int


def _realty_out(conn: AmoConnection, lead_id: int) -> dict:
    from realty.models import Project
    from realty.services import money
    from realty.showroom_api import lead_units

    return {
        "projects": Project.objects.filter(company=conn.company, use_in_amocrm=True).count(),
        "units": [
            {
                "id": u.pk,
                "project": u.project.name,
                "label": u.label,
                "rooms": u.rooms,
                "area": float(u.area or 0),
                "floor": u.floor,
                "price": money(u),
                "status": u.status,
                "status_name": u.get_status_display(),
                "reserved_until": u.reserved_until,
            }
            for u in lead_units(conn, lead_id)
        ],
    }


@router.get("/realty")
def realty_units(request, lead_id: int):
    return _realty_out(request.amo, lead_id)


@router.post("/realty/session")
def realty_session(request, data: RealtySessionIn):
    """A 4-hour showroom link for this deal (it can attach units to it)."""
    from core.tenancy import company_origin
    from realty.showroom_api import deal_key

    conn = request.amo
    key = deal_key(conn, data.lead_id, data.user_name or "amoCRM")
    return {"url": f"{company_origin(conn.company)}/s/{key}"}


@router.post("/realty/detach")
def realty_detach(request, data: RealtyUnitIn):
    from realty import services as realty
    from realty.models import Unit

    try:
        realty.detach(request.amo, data.unit_id, data.lead_id)
    except Unit.DoesNotExist:
        raise HttpError(404, "Unit not found.")
    except realty.Taken as e:
        raise HttpError(409, str(e))
    return _realty_out(request.amo, data.lead_id)
