import json
import logging

from django.contrib.auth import get_user_model
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from accounts.models import Company, Membership
from core.tenancy import company_url

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
            "origin": company_url(company, "").rstrip("/") if company else "",
            "payload": json.dumps({"source": "uzbridge-amocrm", "ok": ok, "message": message}),
        },
        status=200 if ok else 400,
    )


def oauth_callback(request):
    if request.GET.get("error"):
        return _finish(request, None, False, "Access was not granted in amoCRM.")
    try:
        state = oauth.read_state(request.GET.get("state", ""))
    except oauth.OAuthError as e:
        return _finish(request, None, False, str(e))

    company = Company.objects.filter(pk=state["c"], is_active=True).first()
    user = get_user_model().objects.filter(pk=state["u"]).first()
    membership = Membership.objects.filter(company=company, user=user).first() if company and user else None
    if membership is None or not membership.can_manage:
        return _finish(request, company, False, "Only company owners and admins can connect amoCRM.")

    host = request.GET.get("referer", "").lower()
    code = request.GET.get("code", "")
    if not code or not oauth.valid_host(host):
        return _finish(request, company, False, "amoCRM did not send a valid account address.")
    try:
        services.connect(company, user, host, code)
    except services.AlreadyLinked as e:
        return _finish(request, company, False, str(e))
    except Exception:
        log.exception("amocrm connect failed for company %s", company.pk)
        return _finish(request, company, False, "Could not finish connecting to amoCRM. Try again.")
    return _finish(request, company, True, "amoCRM connected.")


@csrf_exempt
def uninstall_hook(request):
    account_id = request.GET.get("account_id", "")
    if not oauth.uninstall_signature_ok(account_id, request.GET.get("signature", "")):
        return HttpResponseBadRequest("bad signature")
    AmoConnection.objects.filter(account_id=account_id).update(
        status=AmoConnection.Status.DISCONNECTED, last_error="The integration was disabled in amoCRM."
    )
    return HttpResponse("ok")
