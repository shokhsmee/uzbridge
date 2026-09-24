import json
import logging
import re

from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from accounts.models import Company, Membership
from core.tenancy import company_origin, company_url

from . import oauth, services
from .models import AmoConnection

log = logging.getLogger(__name__)


def _finish(request, company: Company | None, ok: bool, message: str):
    """Tell the dashboard popup opener how it went, then close the popup."""
    target = company_url(company, "/integrations/amocrm") if company else ""
    return render(
        request,
        "amocrm/oauth_done.html",
        {
            "ok": ok,
            "message": message,
            "target": target,
            "origin": company_origin(company) if company else "",
            "payload": json.dumps({"source": "uzbridge-amocrm", "ok": ok, "message": message}),
        },
        status=200 if ok else 400,
    )


@csrf_exempt
def install_secrets(request):
    """amoCRM POSTs the keys of the integration it just created, before redirecting the user."""
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")
    data = request.POST.dict()
    if not data and request.body:
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = {}
    try:
        install = oauth.install_for(str(data.get("state", "")))
    except oauth.OAuthError:
        return HttpResponseBadRequest("bad state")
    client_id, client_secret = str(data.get("client_id", "")), str(data.get("client_secret", ""))
    if not client_id or not client_secret:
        return HttpResponseBadRequest("missing keys")
    install.client_id, install.client_secret = client_id, client_secret
    install.save(update_fields=["client_id", "client_secret"])
    return HttpResponse("ok")


def oauth_callback(request):
    if request.GET.get("error"):
        return _finish(request, None, False, "Access was not granted in amoCRM.")
    try:
        install = oauth.install_for(request.GET.get("state", ""))
    except oauth.OAuthError as e:
        return _finish(request, None, False, str(e))

    company, user = install.company, install.user
    membership = Membership.objects.filter(company=company, user=user).first()
    if not company.is_active or membership is None or not membership.can_manage:
        return _finish(request, company, False, "Only company owners and admins can connect amoCRM.")
    if not install.client_secret:
        return _finish(request, company, False, "amoCRM didn't send the integration keys. Try connecting again.")
    if request.GET.get("client_id") and request.GET["client_id"] != install.client_id:
        return _finish(request, company, False, "amoCRM sent keys for a different integration. Try again.")

    host = request.GET.get("referer", "").lower()
    code = request.GET.get("code", "")
    if not code or not oauth.valid_host(host):
        return _finish(request, company, False, "amoCRM did not send a valid account address.")
    try:
        services.connect(company, user, host, code, install.client_id, install.client_secret)
    except services.AlreadyLinked as e:
        return _finish(request, company, False, str(e))
    except Exception:
        log.exception("amocrm connect failed for company %s", company.pk)
        return _finish(request, company, False, "Could not finish connecting to amoCRM. Try again.")
    install.delete()
    return _finish(request, company, True, "amoCRM connected.")


@csrf_exempt
def uninstall_hook(request):
    account_id = request.GET.get("account_id", "")
    conn = AmoConnection.objects.filter(account_id=account_id).first() if account_id.isdigit() else None
    if conn is None or not oauth.uninstall_signature_ok(conn, request.GET.get("signature", "")):
        return HttpResponseBadRequest("bad signature")
    conn.status = AmoConnection.Status.DISCONNECTED
    conn.last_error = "The integration was disabled in amoCRM."
    conn.save(update_fields=["status", "last_error"])
    return HttpResponse("ok")


LEAD_STATUS_KEY = re.compile(r"^leads\[status\]\[(\d+)\]\[(id|status_id|pipeline_id)\]$")
LEAD_UPDATE_KEY = re.compile(r"^leads\[update\]\[(\d+)\]\[id\]$")


@csrf_exempt
def lead_hook(request, token):
    """amoCRM webhook (status_lead). Unsigned, so the token in the URL is the
    only proof, and lead data is re-read from the API before acting."""
    conn = AmoConnection.objects.filter(hook_token=token, status=AmoConnection.Status.ACTIVE).first()
    if conn is None or request.method != "POST":
        return HttpResponse(status=404)
    leads: dict[str, dict] = {}
    for key, value in request.POST.items():
        m = LEAD_STATUS_KEY.match(key)
        if m:
            leads.setdefault(m.group(1), {})[m.group(2)] = value
    for lead in leads.values():
        pipeline, status = str(lead.get("pipeline_id", "")), lead.get("status_id", "")
        if lead.get("id", "").isdigit() and str(conn.link_stages.get(pipeline, "")) == status:
            from .tasks import create_link_for_lead

            create_link_for_lead.delay(conn.pk, int(lead["id"]))
    if conn.sms_field_id:
        from .tasks import send_sms_from_lead

        for key, value in request.POST.items():
            if LEAD_UPDATE_KEY.match(key) and value.isdigit():
                send_sms_from_lead.delay(conn.pk, int(value))
    return HttpResponse("ok")


def _nested(form) -> dict:
    """Form keys like event[data][id] -> {"event": {"data": {"id": ...}}}."""
    out: dict = {}
    for key, value in form.items():
        parts = re.findall(r"[^\[\]]+", key)
        node = out
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                break
        else:
            if parts:
                node[parts[-1]] = value
    return out


DP_DELAYS = {0, 5, 15, 30, 60, 180, 360, 720, 1440, 2880, 4320, 10080}  # minutes, as offered in the widget


@csrf_exempt
def dp_hook(request):
    """amoCRM Digital Pipeline: a lead reached a trigger with an uzbridge action.

    Unsigned, so the per-account key the widget stores in the trigger's
    settings is the proof, and the lead is re-read from the API when the job runs.
    """
    from datetime import timedelta

    from django.utils import timezone

    from .models import AmoAutomationJob as Job
    from .tasks import run_automation_job

    if request.method != "POST":
        return HttpResponse(status=405)
    try:
        body = json.loads(request.body) if request.content_type == "application/json" else _nested(request.POST)
    except ValueError:
        return HttpResponseBadRequest("bad body")
    event = body.get("event") or {}
    data = event.get("data") or {}
    opts = ((body.get("action") or {}).get("settings") or {}).get("widget", {}).get("settings") or {}
    if not isinstance(opts, dict):
        opts = {}
    account_id = str(body.get("account_id") or "")
    conn = (
        AmoConnection.objects.filter(account_id=int(account_id), status=AmoConnection.Status.ACTIVE).first()
        if account_id.isdigit()
        else None
    )
    if conn is None or not opts.get("uzb_key") or opts.get("uzb_key") != conn.hook_token:
        return HttpResponse(status=403)
    if str(data.get("element_type", "2")) != "2" or not str(data.get("id", "")).isdigit():
        return HttpResponse("ignored")  # customers (12) aren't invoiced
    action = opts.get("uzb_action") or ""
    if action not in Job.Action.values:
        return HttpResponse("ignored")
    delay = int(opts["uzb_delay"]) if str(opts.get("uzb_delay", "")).isdigit() else 0
    delay = delay if delay in DP_DELAYS else 0
    template = str(opts.get("uzb_template", ""))
    status = str(data.get("status_id", ""))
    now = timezone.now()
    job = Job.objects.create(
        conn=conn,
        lead_id=int(data["id"]),
        action=action,
        template_id=int(template) if template.isdigit() else None,
        status_id=int(status) if status.isdigit() else None,
        delay_minutes=delay,
        run_at=now + timedelta(minutes=delay),
    )
    if not delay:
        run_automation_job.delay(job.pk)
    return HttpResponse("ok")
