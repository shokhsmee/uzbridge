"""Thin client for the uzbridge public API (/api/v1) and its webhook signature."""

import hashlib
import hmac
import logging
import time

import requests

from odoo import _
from odoo.exceptions import UserError

from ..const import DEFAULT_URL

_logger = logging.getLogger(__name__)
TIMEOUT = 20


class UzbridgeError(UserError):
    pass


class UzbridgeClient:
    def __init__(self, company):
        company = company.sudo()
        # People paste the API address from the dashboard; accept it with or without /api/v1.
        base = (company.uzbridge_url or DEFAULT_URL).strip().rstrip('/')
        for suffix in ('/api/v1', '/api'):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
        self.base = base
        self.key = company.uzbridge_api_key
        if not self.key:
            raise UzbridgeError(_("uzbridge isn't connected: set the API key in Settings → uzbridge."))

    def request(self, method, path, json=None):
        url = f"{self.base}/api/v1{path}"
        try:
            resp = requests.request(
                method, url, json=json, timeout=TIMEOUT,
                headers={'Authorization': f'Bearer {self.key}', 'Accept': 'application/json'},
            )
        except requests.exceptions.RequestException as e:
            _logger.warning("uzbridge request %s %s failed: %s", method, path, e)
            raise UzbridgeError(_("Could not reach uzbridge: %s", e)) from e
        if resp.status_code == 404 and not resp.content:
            raise UzbridgeError(_("No uzbridge API at %s. Check the uzbridge URL in Settings → uzbridge.", self.base))
        if resp.status_code == 401:
            raise UzbridgeError(_("uzbridge rejected the API key. Create a new one in the uzbridge dashboard."))
        if not resp.ok:
            try:
                detail = resp.json().get('detail')
            except ValueError:
                detail = resp.text[:300]
            raise UzbridgeError(_("uzbridge: %s", detail or resp.status_code))
        return resp.json()


def verify_signature(secret, body, header, tolerance=300):
    """Header: t=<unix>,v1=<hex hmac_sha256(secret, "<t>." + body)>."""
    if not (secret and header):
        return False
    try:
        parts = dict(p.split('=', 1) for p in header.split(','))
        ts = int(parts['t'])
    except (KeyError, ValueError):
        return False
    if abs(time.time() - ts) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts.get('v1', ''))
