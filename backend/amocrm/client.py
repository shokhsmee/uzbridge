"""Thin amoCRM API v4 client for one connection.

Limits (https://www.amocrm.ru/developers/content/api/recommendations):
7 req/s per integration per account. 429 = slow down; repeated abuse gets
the whole account blocked with 403, so we throttle before sending.
"""

import logging
import threading
import time

import httpx
import redis
from django.conf import settings
from django.utils import timezone

from . import oauth
from .models import AmoConnection

log = logging.getLogger(__name__)


class AmoError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"amoCRM {status}: {message}")
        self.status = status


class _Throttle:
    """Fixed one-second windows shared through Redis, local fallback without it."""

    _local: dict[str, list[float]] = {}
    _lock = threading.Lock()

    def __init__(self):
        try:
            self.r = redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=0.5)
            self.r.ping()
        except redis.RedisError:
            self.r = None

    def wait(self, key: str, per_second: int) -> None:
        while True:
            now = time.time()
            if self.r is not None:
                window = f"amocrm:rl:{key}:{int(now)}"
                n = self.r.incr(window)
                if n == 1:
                    self.r.expire(window, 2)
                if n <= per_second:
                    return
            else:
                with self._lock:
                    hits = [t for t in self._local.get(key, []) if now - t < 1]
                    if len(hits) < per_second:
                        self._local[key] = [*hits, now]
                        return
                    self._local[key] = hits
            time.sleep(1 - (now % 1) + 0.01)


_throttle: _Throttle | None = None


def throttle() -> _Throttle:
    global _throttle
    if _throttle is None:
        _throttle = _Throttle()
    return _throttle


class AmoClient:
    def __init__(self, conn: AmoConnection, http: httpx.Client | None = None):
        self.conn = conn
        self.http = http or httpx.Client(timeout=20)

    def _refresh(self, force: bool) -> None:
        try:
            self.conn = oauth.refresh(self.conn.pk, force=force)
        except oauth.OAuthError as exc:
            # refresh() already marked the connection; callers see one error type.
            raise AmoError(401, f"amoCRM access has expired, reconnect the integration ({exc})") from exc

    def _ensure_token(self) -> None:
        if self.conn.expires_at - timezone.now() < oauth.REFRESH_MARGIN:
            self._refresh(force=False)

    def request(self, method: str, path: str, *, mark_errors: bool = True, **kw) -> dict | list | None:
        """Call amoCRM. `path` may also be a full https URL (the account's file service).

        mark_errors=False: a 402/403 doesn't flag the whole connection (e.g. the
        integration just lacks the "files" scope).
        """
        self._ensure_token()
        url = path if path.startswith("https://") else f"{self.conn.base_url}{path}"
        for attempt in range(4):
            throttle().wait(str(self.conn.account_id), settings.AMOCRM_RATE_PER_SECOND)
            resp = self.http.request(
                method,
                url,
                headers={"Authorization": f"Bearer {self.conn.access_token}", **kw.pop("headers", {})},
                **kw,
            )
            if resp.status_code == 401 and attempt == 0:
                self._refresh(force=True)
                continue
            if resp.status_code == 429:
                time.sleep(1 + attempt)
                continue
            if resp.status_code in (402, 403) and mark_errors:
                self._mark_error(resp)
            if resp.status_code == 204:
                return None
            if resp.status_code >= 400:
                raise AmoError(resp.status_code, resp.text[:500])
            return resp.json()
        raise AmoError(429, "rate limited")

    def _mark_error(self, resp: httpx.Response) -> None:
        msg = {402: "amoCRM subscription has expired.", 403: "amoCRM blocked access for this account."}
        AmoConnection.objects.filter(pk=self.conn.pk).update(
            status=AmoConnection.Status.ERROR, last_error=msg[resp.status_code]
        )

    # ------------------------------------------------------------ endpoints

    def account(self) -> dict:
        return self.request("GET", "/api/v4/account")

    def pipelines(self) -> list[dict]:
        data = self.request("GET", "/api/v4/leads/pipelines") or {}
        out = []
        for p in data.get("_embedded", {}).get("pipelines", []):
            out.append(
                {
                    "id": p["id"],
                    "name": p["name"],
                    "is_main": p.get("is_main", False),
                    "statuses": [
                        {"id": s["id"], "name": s["name"], "color": s.get("color"), "type": s.get("type")}
                        for s in p.get("_embedded", {}).get("statuses", [])
                    ],
                }
            )
        return out

    def lead_custom_fields(self, all_types: bool = True) -> list[dict]:
        data = self.request("GET", "/api/v4/leads/custom_fields", params={"limit": 250}) or {}
        return [
            {"id": f["id"], "name": f["name"], "type": f["type"]}
            for f in data.get("_embedded", {}).get("custom_fields", [])
        ]

    def is_admin(self, user_id: int) -> bool:
        user = self.request("GET", f"/api/v4/users/{int(user_id)}") or {}
        return bool((user.get("rights") or {}).get("is_admin"))

    def lead(self, lead_id: int) -> dict | None:
        return self.request("GET", f"/api/v4/leads/{lead_id}")

    def update_lead(self, lead_id: int, fields: dict) -> dict:
        return self.request("PATCH", f"/api/v4/leads/{lead_id}", json={"updated_by": 0, **fields})

    def lead_contact(self, lead_id: int) -> tuple[str, str]:
        """(name, phone) of the lead's main contact; empty strings if there is none."""
        lead = self.request("GET", f"/api/v4/leads/{lead_id}", params={"with": "contacts"}) or {}
        contacts = lead.get("_embedded", {}).get("contacts", [])
        main = next((c for c in contacts if c.get("is_main")), contacts[0] if contacts else None)
        if not main:
            return "", ""
        contact = self.request("GET", f"/api/v4/contacts/{main['id']}") or {}
        phone = ""
        for f in contact.get("custom_fields_values") or []:
            if f.get("field_code") == "PHONE" and f.get("values"):
                phone = str(f["values"][0].get("value", ""))
                break
        return contact.get("name", ""), phone

    def add_note(self, lead_id: int, text: str) -> dict:
        return self.request(
            "POST",
            f"/api/v4/leads/{lead_id}/notes",
            json=[{"note_type": "service_message", "params": {"service": "uzbridge", "text": text}}],
        )
