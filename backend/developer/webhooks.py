"""Signed outbound events.

Header:  X-Uzbridge-Signature: t=<unix>,v1=<hex hmac_sha256(secret, "<t>.<raw body>")>
Receivers recompute the HMAC over the raw body and reject old timestamps.
"""

import hashlib
import hmac
import json
import time
import uuid

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from .models import WebhookDelivery, WebhookEndpoint


def sign(secret: str, body: bytes, ts: int | None = None) -> str:
    ts = ts or int(time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def verify(secret: str, body: bytes, header: str, tolerance: int = 300) -> bool:
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        ts = int(parts["t"])
    except (KeyError, ValueError):
        return False
    if abs(time.time() - ts) > tolerance:
        return False
    return hmac.compare_digest(sign(secret, body, ts), header)


def emit(company, event: str, data: dict) -> None:
    """Queue `event` for every endpoint of the company that wants it (after commit)."""
    endpoints = [e for e in WebhookEndpoint.objects.filter(company=company, is_enabled=True) if e.wants(event)]
    if not endpoints:
        return
    data = json.loads(json.dumps(data, cls=DjangoJSONEncoder))  # datetimes -> ISO strings
    payload = {"id": f"evt_{uuid.uuid4().hex}", "type": event, "created": int(time.time()), "data": data}
    rows = [WebhookDelivery.objects.create(endpoint=e, event=event, payload=payload) for e in endpoints]

    from .tasks import deliver_webhook

    transaction.on_commit(lambda: [deliver_webhook.delay(r.pk) for r in rows])


def body_of(delivery: WebhookDelivery) -> bytes:
    return json.dumps(delivery.payload, ensure_ascii=False, separators=(",", ":")).encode()


def mark(delivery: WebhookDelivery, status: int | None, error: str = "") -> None:
    delivery.attempts += 1
    delivery.status_code = status
    delivery.error = error[:1000]
    if status and 200 <= status < 300:
        delivery.delivered_at = timezone.now()
    delivery.save(update_fields=["attempts", "status_code", "error", "delivered_at"])
