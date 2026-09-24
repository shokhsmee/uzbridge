"""Mirror payment links as invoices in amoCRM's "Счета/покупки" catalog.

The account has at most one catalog of type "invoices"; its system fields are
found by field_code because an account may have deleted or renamed them
(codes from amoCRM's official PHP client, InvoicesCustomFieldsEnums).
"""

import logging

from django.utils import timezone

from core.tenancy import pay_url
from payments.models import Invoice

from .client import AmoClient, AmoError
from .models import AmoConnection

log = logging.getLogger(__name__)


def catalog_id(conn: AmoConnection, client: AmoClient) -> int | None:
    if conn.bills_catalog_id:
        return conn.bills_catalog_id
    page = 1
    while True:
        data = client.request("GET", "/api/v4/catalogs", params={"page": page, "limit": 250}) or {}
        catalogs = data.get("_embedded", {}).get("catalogs", [])
        found = next((c["id"] for c in catalogs if c.get("type") == "invoices"), None)
        if found or len(catalogs) < 250:
            break
        page += 1
    if found:
        AmoConnection.objects.filter(pk=conn.pk).update(bills_catalog_id=found)
        conn.bills_catalog_id = found
    return found


def _field_ids(client: AmoClient, cat_id: int) -> dict[str, int]:
    data = client.request("GET", f"/api/v4/catalogs/{cat_id}/custom_fields", params={"limit": 250}) or {}
    return {f["code"]: f["id"] for f in data.get("_embedded", {}).get("custom_fields", []) if f.get("code")}


def _value(field_id: int, value) -> dict:
    return {
        "field_id": field_id,
        "values": [value if isinstance(value, dict) and "enum_code" in value else {"value": value}],
    }


def create_bill(conn: AmoConnection, invoice: Invoice) -> int | None:
    """Create the amoCRM invoice for our payment link and link it to the lead."""
    if invoice.amo_bill_id:
        return invoice.amo_bill_id
    client = AmoClient(conn)
    cat_id = catalog_id(conn, client)
    if cat_id is None:
        log.info("amoCRM account %s has no invoices catalog", conn.account_id)
        return None
    ids = _field_ids(client, cat_id)
    soum = invoice.amount_tiyin / 100
    link = pay_url(invoice)
    fields = []
    if "BILL_STATUS" in ids:
        fields.append({"field_id": ids["BILL_STATUS"], "values": [{"enum_code": "created"}]})
    if "BILL_PRICE" in ids:
        fields.append(_value(ids["BILL_PRICE"], soum))
    if "BILL_COMMENT" in ids:
        fields.append(_value(ids["BILL_COMMENT"], f"uzbridge {invoice.display_number} · Toʻlov havolasi: {link}"))
    items = None
    if "ITEMS" in ids:
        items = {
            "field_id": ids["ITEMS"],
            "values": [
                {
                    "value": {
                        "description": (invoice.description or invoice.external_name or invoice.display_number)[:255],
                        "unit_price": soum,
                        "quantity": 1,
                        "unit_type": "шт",
                        "discount": {"type": "amount", "value": 0},
                        "vat_rate_id": 0,
                    }
                }
            ],
        }
    name = f"{invoice.display_number} · {invoice.external_name or invoice.description or 'uzbridge'}"[:255]

    def post(cf):
        return client.request(
            "POST", f"/api/v4/catalogs/{cat_id}/elements", json=[{"name": name, "custom_fields_values": cf}]
        )

    try:
        data = post(fields + ([items] if items else []))
    except AmoError as e:
        if items is None or e.status != 400:
            raise
        data = post(fields)  # the line-item format differs on some accounts; the total still shows
    element = ((data or {}).get("_embedded", {}).get("elements") or [{}])[0]
    bill_id = element.get("id")
    if not bill_id:
        return None
    Invoice.objects.filter(pk=invoice.pk).update(amo_bill_id=bill_id)
    invoice.amo_bill_id = bill_id
    if invoice.external_id.isdigit():
        client.request(
            "POST",
            f"/api/v4/leads/{int(invoice.external_id)}/link",
            json=[
                {
                    "to_entity_id": bill_id,
                    "to_entity_type": "catalog_elements",
                    "metadata": {"catalog_id": cat_id, "quantity": 1},
                }
            ],
        )
    return bill_id


def mark_bill_paid(conn: AmoConnection, invoice: Invoice) -> None:
    if not invoice.amo_bill_id:
        return
    client = AmoClient(conn)
    cat_id = catalog_id(conn, client)
    if cat_id is None:
        return
    ids = _field_ids(client, cat_id)
    fields = []
    if "BILL_STATUS" in ids:
        fields.append({"field_id": ids["BILL_STATUS"], "values": [{"enum_code": "paid"}]})
    if "BILL_PAYMENT_DATE" in ids:
        fields.append(_value(ids["BILL_PAYMENT_DATE"], int((invoice.paid_at or timezone.now()).timestamp())))
    if fields:
        client.request(
            "PATCH",
            f"/api/v4/catalogs/{cat_id}/elements",
            json=[{"id": invoice.amo_bill_id, "custom_fields_values": fields}],
        )
