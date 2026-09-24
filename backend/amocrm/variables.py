"""Company SMS keywords filled from amoCRM lead / contact fields.

A keyword's source is one of:
  lead.name  lead.price  lead.id  lead.responsible  lead.cf.<field_id>
  contact.name  contact.cf.<field_id>
"""

import re
from datetime import UTC, datetime

from django.utils import timezone

from sms.models import SmsVariable

from .client import AmoClient
from .models import AmoConnection

SOURCE_RE = re.compile(r"^(lead\.(name|price|id|responsible|cf\.\d+)|contact\.(name|cf\.\d+))$")
DATE_TYPES = {"date", "date_time", "birthday"}

STATIC_SOURCES = [
    ("lead.name", "lead", "Название сделки"),
    ("lead.price", "lead", "Бюджет"),
    ("lead.id", "lead", "ID сделки"),
    ("lead.responsible", "lead", "Ответственный"),
    ("contact.name", "contact", "Имя контакта"),
]


def _fields(client: AmoClient, entity: str) -> list[dict]:
    data = client.request("GET", f"/api/v4/{entity}/custom_fields", params={"limit": 250}) or {}
    return data.get("_embedded", {}).get("custom_fields", [])


def sources(client: AmoClient) -> list[dict]:
    """Every field a keyword can take its value from, for the settings page."""
    out = [{"value": v, "group": g, "label": label} for v, g, label in STATIC_SOURCES]
    for entity, group in (("leads", "lead"), ("contacts", "contact")):
        for f in _fields(client, entity):
            if f.get("code") == "PHONE" or f.get("type") in ("tracking_data", "chained_list", "items"):
                continue
            out.append({"value": f"{group}.cf.{f['id']}", "group": group, "label": f["name"]})
    return out


def _cf_value(entity: dict, field_id: int) -> str:
    for f in entity.get("custom_fields_values") or []:
        if f.get("field_id") != field_id:
            continue
        parts = []
        for v in f.get("values") or []:
            value = v.get("value")
            if f.get("field_type") in DATE_TYPES and str(value).lstrip("-").isdigit():
                value = timezone.localtime(datetime.fromtimestamp(int(value), tz=UTC)).strftime("%d.%m.%Y")
            if value not in (None, ""):
                parts.append(str(value))
        return ", ".join(parts)
    return ""


def read_sources(client: AmoClient, lead_id: int, sources: list[str], lead: dict | None = None) -> dict[str, str]:
    """{source: value} for lead / contact field sources, reading only what is asked for."""
    sources = [s for s in dict.fromkeys(sources) if SOURCE_RE.match(s)]
    if not sources:
        return {}
    if lead is None or "_embedded" not in lead:
        lead = client.request("GET", f"/api/v4/leads/{int(lead_id)}", params={"with": "contacts"}) or {}
    contact = {}
    if any(src.startswith("contact.") for src in sources):
        contacts = lead.get("_embedded", {}).get("contacts", [])
        main = next((c for c in contacts if c.get("is_main")), contacts[0] if contacts else None)
        contact = (client.request("GET", f"/api/v4/contacts/{main['id']}") or {}) if main else {}
    responsible = ""
    if "lead.responsible" in sources and lead.get("responsible_user_id"):
        user = client.request("GET", f"/api/v4/users/{int(lead['responsible_user_id'])}") or {}
        responsible = user.get("name", "")

    out = {}
    for src in sources:
        entity, _, rest = src.partition(".")
        if entity == "lead":
            if rest.startswith("cf."):
                value = _cf_value(lead, int(rest[3:]))
            elif rest == "price":
                value = f"{int(lead.get('price') or 0):,}".replace(",", " ")
            elif rest == "responsible":
                value = responsible
            else:
                value = str(lead.get(rest) or "")
        else:
            value = _cf_value(contact, int(rest[3:])) if rest.startswith("cf.") else str(contact.get("name") or "")
        out[src] = value
    return out


def values_for_lead(conn: AmoConnection, client: AmoClient, lead_id: int, lead: dict | None = None) -> dict[str, str]:
    """{keyword: value} for the company's amoCRM keywords, read fresh from the lead."""
    variables = list(SmsVariable.objects.filter(company=conn.company, integration=SmsVariable.Integration.AMOCRM))
    if not variables:
        return {}
    read = read_sources(client, lead_id, [v.source for v in variables], lead)
    return {v.key: read.get(v.source, "") for v in variables}
