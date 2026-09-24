"""Play a provider's side of a payment against the local server.

    uv run python scripts/simulate.py payme <company-slug> <invoice-number>
    uv run python scripts/simulate.py click <company-slug> <invoice-number>

Reads the company's provider credentials from the database and sends the
same callbacks Payme / Click would, so a full "link → paid → CRM" run can be
tried without a public URL.
"""

import base64
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime

import django
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from payments.models import Invoice, ProviderAccount  # noqa: E402

SERVER = os.environ.get("SERVER", "http://127.0.0.1:8010")
HOST = "api.localhost"


def show(label, data):
    print(f"→ {label}: {json.dumps(data, ensure_ascii=False)}")


def payme(account: ProviderAccount, invoice: Invoice):
    auth = "Basic " + base64.b64encode(f"Paycom:{account.active_secret}".encode()).decode()
    url = f"{SERVER}/cb/payme/{account.public_id}/"
    txn_id = uuid.uuid4().hex[:24]

    def rpc(method, params):
        r = httpx.post(
            url, json={"method": method, "params": params, "id": 1}, headers={"Authorization": auth, "Host": HOST}
        )
        body = r.json()
        show(method, body.get("result") or body.get("error"))
        return body

    account_param = {"order_id": str(invoice.number)}
    rpc("CheckPerformTransaction", {"amount": invoice.amount_tiyin, "account": account_param})
    rpc(
        "CreateTransaction",
        {"id": txn_id, "time": int(time.time() * 1000), "amount": invoice.amount_tiyin, "account": account_param},
    )
    rpc("PerformTransaction", {"id": txn_id})
    rpc("CheckTransaction", {"id": txn_id})


def click(account: ProviderAccount, invoice: Invoice):
    url = f"{SERVER}/cb/click/{account.public_id}/"
    trans_id = str(int(time.time()))
    sign_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    amount = invoice.amount_soum

    def sign(action, prepare_id=""):
        parts = [trans_id, account.service_id, account.secret, str(invoice.number)]
        if action == "1":
            parts.append(prepare_id)
        parts += [amount, action, sign_time]
        return hashlib.md5("".join(parts).encode()).hexdigest()

    base = {
        "click_trans_id": trans_id,
        "service_id": account.service_id,
        "click_paydoc_id": str(int(trans_id) + 1),
        "merchant_trans_id": str(invoice.number),
        "amount": amount,
        "error": "0",
        "error_note": "Success",
        "sign_time": sign_time,
    }
    r = httpx.post(url, data={**base, "action": "0", "sign_string": sign("0")}, headers={"Host": HOST}).json()
    show("Prepare", r)
    prepare_id = str(r.get("merchant_prepare_id", ""))
    r = httpx.post(
        url,
        data={**base, "action": "1", "merchant_prepare_id": prepare_id, "sign_string": sign("1", prepare_id)},
        headers={"Host": HOST},
    ).json()
    show("Complete", r)


def main():
    if len(sys.argv) != 4 or sys.argv[1] not in ("payme", "click"):
        sys.exit(__doc__)
    provider, slug, number = sys.argv[1], sys.argv[2], int(sys.argv[3].upper().removeprefix("INV-"))
    invoice = Invoice.objects.get(company__slug=slug, number=number)
    account = ProviderAccount.objects.get(company__slug=slug, provider=provider)
    {"payme": payme, "click": click}[provider](account, invoice)
    invoice.refresh_from_db()
    print(f"\n{invoice.display_number}: {invoice.status} {invoice.paid_via or ''}".rstrip())


if __name__ == "__main__":
    main()
