"""Eskiz and Playmobile HTTP clients.

Eskiz: https://documenter.getpostman.com/view/663428/TVK5eMco
  Bearer token from /auth/login (30 days); texts must match a template the
  account has had approved, and a test account can only send its test texts.
Playmobile (SMSXabar broker): https://playmobile.uz/instruction/
  Basic auth; "200 Request is received" is the only success signal, so our
  own message-id is the key for delivery reports.
"""

import base64
import re
import secrets
from datetime import timedelta

import httpx
from django.utils import timezone

from .models import SmsAccount, SmsProvider

ESKIZ_API = "https://notify.eskiz.uz/api"
ESKIZ_DEFAULT_SENDER = "4546"
PLAYMOBILE_API = "https://send.smsxabar.uz/broker-api/send"


class SmsError(Exception):
    pass


def normalize_phone(raw: str) -> str:
    """'+998 (90) 123-45-67' / '901234567' -> '998901234567'; anything else is an error."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 9:
        digits = "998" + digits
    if not re.fullmatch(r"998\d{9}", digits):
        raise SmsError(f"Not an Uzbek mobile number: {raw!r}")
    return digits


# ---------------------------------------------------------------- Eskiz


def _eskiz_login(account: SmsAccount) -> str:
    resp = httpx.post(f"{ESKIZ_API}/auth/login", data={"email": account.login, "password": account.secret}, timeout=20)
    if resp.status_code != 200:
        raise SmsError(f"Eskiz login failed ({resp.status_code}): {resp.text[:200]}")
    token = (resp.json().get("data") or {}).get("token")
    if not token:
        raise SmsError("Eskiz login returned no token.")
    account.token = token
    account.token_expires_at = timezone.now() + timedelta(days=29)
    account.save(update_fields=["token", "token_expires_at"])
    return token


def _eskiz_token(account: SmsAccount) -> str:
    if account.token and account.token_expires_at and account.token_expires_at > timezone.now():
        return account.token
    return _eskiz_login(account)


def _eskiz(account: SmsAccount, method: str, path: str, **kw) -> dict:
    for attempt in range(2):
        resp = httpx.request(
            method, f"{ESKIZ_API}{path}", headers={"Authorization": f"Bearer {_eskiz_token(account)}"}, timeout=20, **kw
        )
        if resp.status_code == 401 and attempt == 0:
            account.token = ""
            continue
        if resp.status_code >= 400:
            raise SmsError(f"Eskiz {resp.status_code}: {resp.text[:300]}")
        return resp.json()
    raise SmsError("Eskiz rejected the credentials.")


def eskiz_send(account: SmsAccount, phone: str, text: str, callback_url: str) -> str:
    data = _eskiz(
        account,
        "POST",
        "/message/sms/send",
        data={
            "mobile_phone": phone,
            "message": text,
            "from": account.sender or ESKIZ_DEFAULT_SENDER,
            "callback_url": callback_url,
        },
    )
    if not data.get("id"):
        raise SmsError(f"Eskiz didn't accept the message: {data}")
    return str(data["id"])


def eskiz_templates(account: SmsAccount) -> list[dict]:
    """[{id, text, status}] from the Eskiz account (status 'service'/'reklama' = approved)."""
    data = _eskiz(account, "GET", "/user/templates")
    rows = data.get("result") or data.get("data") or []
    return [
        {
            "id": str(r.get("id")),
            "text": (r.get("original_text") or r.get("template") or "").strip(),
            "status": r.get("status", ""),
        }
        for r in rows
        if isinstance(r, dict) and r.get("id") is not None
    ]


def eskiz_submit_template(account: SmsAccount, text: str) -> None:
    _eskiz(account, "POST", "/user/template", data={"template": text})


def eskiz_balance(account: SmsAccount) -> str:
    data = _eskiz(account, "GET", "/user/get-limit")
    return str((data.get("data") or {}).get("balance", ""))


# ---------------------------------------------------------------- Playmobile


def playmobile_send(account: SmsAccount, phone: str, text: str) -> str:
    message_id = "uzb" + secrets.token_hex(12)  # unique per send, <= 40 chars
    auth = base64.b64encode(f"{account.login}:{account.secret}".encode()).decode()
    resp = httpx.post(
        PLAYMOBILE_API,
        json={
            "messages": [
                {
                    "recipient": phone,
                    "message-id": message_id,
                    "sms": {"originator": account.sender, "content": {"text": text}},
                }
            ]
        },
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json; charset=UTF-8"},
        timeout=20,
    )
    if resp.status_code != 200:
        try:
            err = resp.json()
            detail = f"{err.get('error_code')}: {err.get('error_description')}"
        except ValueError:
            detail = resp.text[:200]
        raise SmsError(f"Playmobile {resp.status_code} {detail}")
    return message_id


# ---------------------------------------------------------------- statuses

ESKIZ_FINAL = {
    "DELIVRD": "delivered",
    "DELIVERED": "delivered",
    "UNDELIV": "failed",
    "UNDELIVERABLE": "failed",
    "EXPIRED": "failed",
    "REJECTD": "failed",
    "REJECTED": "failed",
    "DELETED": "failed",
}
PLAYMOBILE_FINAL = {
    "Delivered": "delivered",
    "NotDelivered": "failed",
    "Rejected": "failed",
    "Failed": "failed",
    "Expired": "failed",
}


def send(account: SmsAccount, phone: str, text: str, callback_url: str) -> str:
    if account.provider == SmsProvider.ESKIZ:
        return eskiz_send(account, phone, text, callback_url)
    return playmobile_send(account, phone, text)
