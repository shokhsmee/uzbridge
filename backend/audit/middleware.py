"""Guards and logs the public callback endpoints (provider callbacks, amoCRM hooks).

- IP allowlists per source (settings.CALLBACK_ALLOWED_IPS, empty = open;
  production-only accounts, sandbox/test mode accounts are never blocked).
- A per-IP rate limit so a flood can't exhaust workers.
- One CallbackLog row per call, with the business outcome parsed from the answer.
"""

import json
import logging
import re
import time

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse

from .models import CallbackLog

log = logging.getLogger(__name__)

ROUTES = [
    (re.compile(r"^/cb/(payme|click|uzum)/([0-9a-f-]{36})/"), "provider"),
    (re.compile(r"^/cb/sms/(eskiz|playmobile)/([0-9a-f-]{36})/"), "sms"),
    (re.compile(r"^/oauth/amocrm/(hook|secrets|uninstall|dp)"), "amocrm"),
]
RATE_PER_MINUTE = 120


def _ip(request) -> str:
    fwd = request.META.get("HTTP_X_FORWARDED_FOR")
    return (fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR", "")) or ""


def _match(path: str):
    for rx, kind in ROUTES:
        m = rx.match(path)
        if m:
            return kind, m
    return None, None


def _company_for(kind, m):
    try:
        if kind == "provider":
            from payments.models import ProviderAccount

            acc = ProviderAccount.objects.filter(public_id=m.group(2)).only("company_id", "test_mode").first()
            return (acc.company_id, acc.test_mode) if acc else (None, False)
        if kind == "sms":
            from sms.models import SmsAccount

            acc = SmsAccount.objects.filter(public_id=m.group(2)).only("company_id").first()
            return (acc.company_id if acc else None), False
    except Exception:  # never let logging break a payment
        log.exception("callback company lookup failed")
    return None, False


def _outcome(source: str, response) -> tuple[bool, str]:
    """(ok, note) from our answer: Payme/Click put errors in a 200 body."""
    if response.status_code >= 400:
        return False, f"HTTP {response.status_code}"
    try:
        body = json.loads(response.content or b"{}")
    except (ValueError, TypeError):
        return True, ""
    if source == "payme" and isinstance(body, dict) and body.get("error"):
        e = body["error"]
        msg = e.get("message")
        return False, f"{e.get('code')} {msg.get('en') if isinstance(msg, dict) else msg or ''}".strip()
    if source == "click" and isinstance(body, dict) and body.get("error", 0) not in (0, "0", None):
        return False, f"{body.get('error')} {body.get('error_note', '')}".strip()
    return True, ""


class CallbackGuard:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        kind, m = _match(request.path)
        if kind is None:
            return self.get_response(request)
        source = m.group(1) if kind != "amocrm" else "amocrm"
        ip = _ip(request)
        company_id, test_mode = _company_for(kind, m)

        allowed = settings.CALLBACK_ALLOWED_IPS.get(source) or []
        if allowed and not test_mode and ip not in allowed:
            return self._log(request, source, company_id, ip, self._deny(source), False, "IP not in allowlist", True)

        bucket = f"cbrl:{ip}:{int(time.time() // 60)}"
        try:
            hits = cache.get_or_set(bucket, 0, 70)
            hits = cache.incr(bucket)
        except Exception:
            hits = 0
        if hits > RATE_PER_MINUTE:
            return self._log(request, source, company_id, ip, HttpResponse(status=429), False, "rate limited", True)

        response = self.get_response(request)
        ok, note = _outcome(source, response)
        return self._log(request, source, company_id, ip, response, ok, note, False)

    def _deny(self, source):
        if source == "payme":
            return JsonResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32504, "message": "Forbidden"}})
        return HttpResponse(status=403)

    def _log(self, request, source, company_id, ip, response, ok, note, blocked):
        try:
            CallbackLog.objects.create(
                company_id=company_id,
                source=source,
                path=request.path[:200],
                ip=ip or None,
                status_code=response.status_code,
                ok=ok,
                note=note[:255],
                blocked=blocked,
            )
        except Exception:
            log.exception("callback log write failed")
        return response
