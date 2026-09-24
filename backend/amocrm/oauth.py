"""amoCRM OAuth2 for our external integration.

https://www.amocrm.ru/developers/content/oauth/step-by-step
Refresh tokens are single-use: whoever refreshes must store the new pair in
the same transaction, under a row lock, or the next refresh fails for good.
"""

import re
import secrets
from datetime import timedelta
from urllib.parse import urlencode

import httpx
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone

from .models import AmoConnection

STATE_SALT = "amocrm-oauth"
STATE_MAX_AGE = 20 * 60
# Only ever send our client_secret to a real amoCRM/Kommo account host.
HOST_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}\.(amocrm\.ru|amocrm\.com|kommo\.com)$")
REFRESH_MARGIN = timedelta(hours=2)


class OAuthError(Exception):
    pass


def authorize_url(company_id: int, user_id: int) -> str:
    state = signing.dumps({"c": company_id, "u": user_id, "n": secrets.token_hex(8)}, salt=STATE_SALT)
    q = {"client_id": settings.AMOCRM_CLIENT_ID, "state": state, "mode": "post_message"}
    return f"https://www.amocrm.ru/oauth?{urlencode(q)}"


def read_state(state: str) -> dict:
    try:
        return signing.loads(state, salt=STATE_SALT, max_age=STATE_MAX_AGE)
    except signing.BadSignature as exc:
        raise OAuthError("The connection link has expired. Start again from the dashboard.") from exc


def valid_host(host: str) -> bool:
    return bool(HOST_RE.match(host.lower()))


def _token_request(host: str, payload: dict) -> dict:
    if not valid_host(host):
        raise OAuthError(f"Not an amoCRM host: {host}")
    body = {
        "client_id": settings.AMOCRM_CLIENT_ID,
        "client_secret": settings.AMOCRM_CLIENT_SECRET,
        "redirect_uri": settings.AMOCRM_REDIRECT_URI,
        **payload,
    }
    resp = httpx.post(f"https://{host}/oauth2/access_token", json=body, timeout=20)
    if resp.status_code != 200:
        raise OAuthError(f"amoCRM token endpoint answered {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def exchange_code(host: str, code: str) -> dict:
    return _token_request(host, {"grant_type": "authorization_code", "code": code})


def apply_tokens(conn: AmoConnection, tokens: dict) -> None:
    conn.access_token = tokens["access_token"]
    conn.refresh_token = tokens["refresh_token"]
    conn.expires_at = timezone.now() + timedelta(seconds=int(tokens.get("expires_in", 86400)))


def refresh(conn_id: int, *, force: bool = False) -> AmoConnection:
    """Refresh the pair if it expires soon. Safe to call concurrently."""
    failure = None
    with transaction.atomic():
        conn = AmoConnection.objects.select_for_update().get(pk=conn_id)
        if not force and conn.expires_at - timezone.now() > REFRESH_MARGIN:
            return conn  # someone else refreshed while we waited for the lock
        try:
            tokens = _token_request(conn.host, {"grant_type": "refresh_token", "refresh_token": conn.refresh_token})
        except OAuthError as exc:
            failure = exc
        else:
            apply_tokens(conn, tokens)
            conn.status = AmoConnection.Status.ACTIVE
            conn.last_error = ""
            conn.save(update_fields=["access_token", "refresh_token", "expires_at", "status", "last_error"])
            return conn
    # Outside the atomic block so raising doesn't roll the error state back.
    AmoConnection.objects.filter(pk=conn_id).update(status=AmoConnection.Status.ERROR, last_error=str(failure))
    raise failure


def uninstall_signature_ok(account_id: str, signature: str) -> bool:
    import hashlib
    import hmac

    expected = hmac.new(
        settings.AMOCRM_CLIENT_SECRET.encode(),
        f"{settings.AMOCRM_CLIENT_ID}|{account_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return bool(signature) and hmac.compare_digest(expected, signature)
