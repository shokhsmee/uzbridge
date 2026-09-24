"""amoCRM OAuth2, with one integration per company.

The dashboard shows amoCRM's connect button without a client_id, so amoCRM
creates a private integration in the account the user picks, POSTs its keys
to our secrets_uri, then redirects back with a code
(https://www.amocrm.ru/developers/content/oauth/button). The keys live on the
company's AmoConnection.

Refresh tokens are single-use: whoever refreshes must store the new pair in
the same transaction, under a row lock, or the next refresh fails for good.
"""

import hashlib
import hmac
import re
import secrets
from datetime import timedelta

import httpx
from django.core import signing
from django.db import transaction
from django.utils import timezone

from core.tenancy import platform_url

from .models import AmoConnection, AmoInstall

STATE_SALT = "amocrm-oauth"
STATE_MAX_AGE = 20 * 60
# Only ever send a client_secret to a real amoCRM/Kommo account host.
HOST_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}\.(amocrm\.ru|amocrm\.com|kommo\.com)$")
REFRESH_MARGIN = timedelta(hours=2)


class OAuthError(Exception):
    pass


def redirect_uri() -> str:
    return platform_url("app", "/oauth/amocrm/callback")


def secrets_uri() -> str:
    return platform_url("app", "/oauth/amocrm/secrets")


def start_install(company, user) -> dict:
    """Everything the connect button needs; `state` ties the keys, the code and the company together."""
    nonce = secrets.token_hex(12)
    AmoInstall.objects.filter(company=company, created_at__lt=timezone.now() - timedelta(hours=1)).delete()
    AmoInstall.objects.create(nonce=nonce, company=company, user=user)
    return {
        "state": signing.dumps({"n": nonce}, salt=STATE_SALT),
        "redirect_uri": redirect_uri(),
        "secrets_uri": secrets_uri(),
        "logo": platform_url("app", "/amocrm-logo.png"),
        "name": "uzbridge",
        "description": (
            "Payme, Click va Uzum toʻlov havolalari bitimdan; toʻlovdan soʻng bitim “Toʻlandi” bosqichiga oʻtadi."
        ),
        "scopes": "crm,notifications",
    }


def install_for(state: str) -> AmoInstall:
    try:
        data = signing.loads(state, salt=STATE_SALT, max_age=STATE_MAX_AGE)
    except signing.BadSignature as exc:
        raise OAuthError("The connection link has expired. Start again from the dashboard.") from exc
    install = AmoInstall.objects.select_related("company", "user").filter(nonce=data.get("n")).first()
    if install is None:
        raise OAuthError("The connection link has expired. Start again from the dashboard.")
    return install


def valid_host(host: str) -> bool:
    return bool(HOST_RE.match(host.lower()))


def _token_request(host: str, client_id: str, client_secret: str, payload: dict) -> dict:
    if not valid_host(host):
        raise OAuthError(f"Not an amoCRM host: {host}")
    body = {"client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect_uri(), **payload}
    resp = httpx.post(f"https://{host}/oauth2/access_token", json=body, timeout=20)
    if resp.status_code != 200:
        raise OAuthError(f"amoCRM token endpoint answered {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def exchange_code(host: str, client_id: str, client_secret: str, code: str) -> dict:
    return _token_request(host, client_id, client_secret, {"grant_type": "authorization_code", "code": code})


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
            tokens = _token_request(
                conn.host,
                conn.client_id,
                conn.client_secret,
                {"grant_type": "refresh_token", "refresh_token": conn.refresh_token},
            )
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


def uninstall_signature_ok(conn: AmoConnection, signature: str) -> bool:
    expected = hmac.new(
        conn.client_secret.encode(), f"{conn.client_id}|{conn.account_id}".encode(), hashlib.sha256
    ).hexdigest()
    return bool(signature) and hmac.compare_digest(expected, signature)
