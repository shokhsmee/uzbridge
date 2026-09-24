"""Delivery reports from the SMS gateways (unsigned: we only ever move a
message we sent to a final status, and only by the id we know)."""

import json

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt

from .gateways import ESKIZ_FINAL, PLAYMOBILE_FINAL
from .models import SmsAccount, SmsMessage, SmsProvider


def _body(request) -> dict:
    if request.POST:
        return request.POST.dict()
    try:
        return json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _apply(account, provider_id: str, raw_status: str, table: dict) -> None:
    status = table.get(raw_status)
    updates = {"provider_status": raw_status[:32]}
    if status:
        updates["status"] = status
    rows = SmsMessage.objects.filter(account=account, provider_id=provider_id).exclude(status="queued")
    rows.update(**updates)
    if status:
        from developer.webhooks import emit

        for m in rows.exclude(external_ref=""):
            emit(m.company, "sms.status", {"id": m.pk, "ref": m.external_ref, "phone": m.phone, "status": m.status})


@csrf_exempt
def eskiz_dlr(request, public_id):
    account = get_object_or_404(SmsAccount, public_id=public_id, provider=SmsProvider.ESKIZ)
    data = _body(request)
    if data.get("request_id"):
        _apply(account, str(data["request_id"]), str(data.get("status", "")), ESKIZ_FINAL)
    return HttpResponse("ok")


@csrf_exempt
def playmobile_dlr(request, public_id):
    account = get_object_or_404(SmsAccount, public_id=public_id, provider=SmsProvider.PLAYMOBILE)
    for m in _body(request).get("messages", []) or []:
        if isinstance(m, dict) and m.get("message-id"):
            _apply(account, str(m["message-id"]), str(m.get("status", "")), PLAYMOBILE_FINAL)
    return HttpResponse("Request is received", content_type="text/plain")
