"""Make a numbered document for an amoCRM lead."""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from core.tenancy import platform_url

from . import render
from .models import DocFormat, DocTemplate, GeneratedDoc

log = logging.getLogger(__name__)

# Built-in keywords every template can use, next to the company's own ones.
BUILTINS = [
    ("number", "Hujjat raqami / номер документа"),
    ("date", "Bugungi sana / сегодня (dd.mm.yyyy)"),
    ("company", "Kompaniya nomi / название"),
    ("company_legal_name", "Yuridik nomi / юр. название"),
    ("company_tin", "STIR / ИНН"),
    ("company_address", "Yuridik manzil / юр. адрес"),
    ("company_director", "Direktor"),
    ("company_phone", "Telefon"),
    ("company_bank", "Bank"),
    ("company_mfo", "MFO"),
    ("company_account", "Hisob raqam / р/с"),
    ("lead_name", "Bitim nomi / название сделки"),
    ("lead_id", "Bitim ID"),
    ("amount", "Bitim summasi / бюджет (1 500 000)"),
    ("amount_words", "Summa soʻz bilan / прописью"),
    ("name", "Mijoz ismi / имя контакта"),
    ("phone", "Mijoz telefoni / телефон контакта"),
    ("link", "Toʻlov havolasi / ссылка на оплату"),
]
BUILTIN_KEYS = {k for k, _ in BUILTINS}

BINDING_TYPES = ("amo", "number", "date", "builtin", "text")
DATE_STYLES = ("short", "long", "ru")
_UZ_MONTHS = [
    "yanvar",
    "fevral",
    "mart",
    "aprel",
    "may",
    "iyun",
    "iyul",
    "avgust",
    "sentyabr",
    "oktyabr",
    "noyabr",
    "dekabr",
]
_RU_MONTHS = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]


def format_date(day, style: str = "short") -> str:
    if style == "long":
        return f"{day.day}-{_UZ_MONTHS[day.month - 1]} {day.year}-yil"
    if style == "ru":
        return f"{day.day} {_RU_MONTHS[day.month - 1]} {day.year} г."
    return day.strftime("%d.%m.%Y")


def clean_bindings(raw: dict) -> dict:
    """Keep only well-formed bindings; raises ValueError on a bad one."""
    from amocrm.variables import SOURCE_RE

    out = {}
    for key, b in (raw or {}).items():
        if not isinstance(b, dict) or not render.KEY_RE.fullmatch("{" + str(key) + "}"):
            raise ValueError(f"{{{key}}}: not a valid keyword.")
        kind = b.get("type")
        if kind not in BINDING_TYPES:
            raise ValueError(f"{{{key}}}: pick where its value comes from.")
        if kind == "amo":
            if not SOURCE_RE.match(str(b.get("source", ""))):
                raise ValueError(f"{{{key}}}: pick an amoCRM field.")
            out[key] = {"type": "amo", "source": b["source"]}
        elif kind == "date":
            offset = int(b.get("offset_days") or 0)
            if not -3650 <= offset <= 3650:
                raise ValueError(f"{{{key}}}: days must be within ±3650.")
            style = b.get("style") if b.get("style") in DATE_STYLES else "short"
            out[key] = {"type": "date", "offset_days": offset, "style": style}
        elif kind == "builtin":
            if b.get("key") not in BUILTIN_KEYS:
                raise ValueError(f"{{{key}}}: pick a value.")
            out[key] = {"type": "builtin", "key": b["key"]}
        elif kind == "text":
            out[key] = {"type": "text", "value": str(b.get("value", ""))[:500]}
        else:
            out[key] = {"type": "number"}
    return out


_ONES = ["", "bir", "ikki", "uch", "toʻrt", "besh", "olti", "yetti", "sakkiz", "toʻqqiz"]
_TENS = ["", "oʻn", "yigirma", "oʻttiz", "qirq", "ellik", "oltmish", "yetmish", "sakson", "toʻqson"]


def _below_thousand(n: int) -> list[str]:
    words = []
    if n >= 100:
        words += [_ONES[n // 100], "yuz"]
        n %= 100
    if n >= 10:
        words.append(_TENS[n // 10])
        n %= 10
    if n:
        words.append(_ONES[n])
    return words


def amount_in_words(n: int) -> str:
    """1 500 000 -> "bir million besh yuz ming" (Uzbek, as contracts write sums)."""
    if n == 0:
        return "nol"
    words = []
    for value, name in ((10**9, "milliard"), (10**6, "million"), (10**3, "ming")):
        if n >= value:
            words += _below_thousand(n // value) + [name]
            n %= value
    words += _below_thousand(n)
    return " ".join(w for w in words if w)


def lead_values(conn, lead_id: int, *, number: str, template: DocTemplate | None = None) -> dict[str, str]:
    from amocrm.client import AmoClient
    from amocrm.services import pay_link
    from amocrm.tasks import open_invoice_for
    from amocrm.variables import read_sources, values_for_lead

    client = AmoClient(conn)
    lead = client.request("GET", f"/api/v4/leads/{int(lead_id)}", params={"with": "contacts"}) or {}
    name, phone = client.lead_contact(lead_id)
    company = conn.company
    price = int(lead.get("price") or 0)
    invoice = open_invoice_for(conn, lead_id)
    values = {
        "number": number,
        "date": timezone.localdate().strftime("%d.%m.%Y"),
        "company": company.name,
        "company_legal_name": company.legal_name or company.name,
        "company_tin": company.tin or company.pinfl,
        "company_address": company.legal_address,
        "company_director": company.director,
        "company_phone": company.contact_phone,
        "company_bank": company.bank_name,
        "company_mfo": company.bank_mfo,
        "company_account": company.bank_account,
        "lead_name": lead.get("name") or "",
        "lead_id": str(lead_id),
        "amount": f"{price:,}".replace(",", " "),
        "amount_words": amount_in_words(price),
        "name": name,
        "phone": phone,
        "link": pay_link(invoice) if invoice else "",
    }
    # The company's own keywords (lead / contact fields) — the built-ins win on a clash.
    for key, value in values_for_lead(conn, client, lead_id, lead).items():
        values.setdefault(key, value)
    # This template's own bindings win over everything: they were set for this document.
    bindings = (template.bindings if template else {}) or {}
    amo = read_sources(client, lead_id, [b["source"] for b in bindings.values() if b.get("type") == "amo"], lead)
    base = dict(values)
    today = timezone.localdate()
    for key, b in bindings.items():
        kind = b.get("type")
        if kind == "amo":
            values[key] = amo.get(b.get("source", ""), "")
        elif kind == "number":
            values[key] = number
        elif kind == "date":
            values[key] = format_date(today + timedelta(days=int(b.get("offset_days") or 0)), b.get("style", "short"))
        elif kind == "builtin":
            values[key] = base.get(b.get("key", ""), "")
        elif kind == "text":
            values[key] = b.get("value", "")
    return values


def _filename(template: DocTemplate, number: str, fmt: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in f"{template.name} {number}").strip()
    return f"{safe or 'document'}.{fmt}"


def download_url(doc: GeneratedDoc) -> str:
    return platform_url("api", f"/d/{doc.token}/")


def preview(conn, template: DocTemplate, lead_id: int, fmt: str) -> tuple[bytes, str]:
    """A sample for the site: the next number shown, nothing saved or counted."""
    number = template.format_number(template.next_number)
    values = lead_values(conn, lead_id, number=number, template=template)
    return render.render(template, fmt, values), _filename(template, f"{number} namuna", fmt)


def generate(conn, template: DocTemplate, lead_id: int, fmt: str, *, user_label: str = "") -> GeneratedDoc:
    """Make (or re-make) the lead's document. The first time takes the template's next number."""
    if fmt not in DocFormat.values:
        fmt = template.default_format
    existing = GeneratedDoc.objects.filter(template=template, amo_connection=conn, lead_id=lead_id).first()
    number = existing.number if existing else template.format_number(template.next_number)
    values = lead_values(conn, lead_id, number=number, template=template)  # outside the lock: it calls amoCRM
    content = render.render(template, fmt, values)
    with transaction.atomic():
        if existing is None:
            locked = DocTemplate.objects.select_for_update().get(pk=template.pk)
            seq = locked.next_number
            number = locked.format_number(seq)
            if number != values["number"]:  # someone took it meanwhile: fill the real one
                values = {k: (number if v == values["number"] else v) for k, v in values.items()}
                content = render.render(locked, fmt, values)
            locked.next_number = seq + 1
            locked.save(update_fields=["next_number", "updated_at"])
            doc = GeneratedDoc.objects.create(
                company=template.company,
                template=template,
                amo_connection=conn,
                lead_id=lead_id,
                seq=seq,
                number=number,
                format=fmt,
                content=content,
                filename=_filename(template, number, fmt),
                values=values,
                created_by_label=user_label[:150],
            )
        else:
            doc = existing
            doc.format, doc.content, doc.values = fmt, content, values
            doc.filename = _filename(template, doc.number, fmt)
            doc.save(update_fields=["format", "content", "values", "filename", "updated_at"])
    _note(conn, doc, remade=existing is not None)
    return doc


def _note(conn, doc: GeneratedDoc, *, remade: bool) -> None:
    """Put the file into the lead's "Файлы" tab (a new version when re-made) and note it."""
    from amocrm.client import AmoClient, AmoError
    from amocrm.files import NoFileAccess, attach_to_lead, upload

    client = AmoClient(conn)
    in_files = False
    try:
        # Same format as before: a new version of the same file; otherwise a new file.
        same = doc.amo_file_uuid if doc.amo_file_format == doc.format else ""
        uuid = upload(client, doc.filename, bytes(doc.content), doc.content_type, file_uuid=same)
        if uuid != doc.amo_file_uuid:
            attach_to_lead(client, doc.lead_id, uuid)
        GeneratedDoc.objects.filter(pk=doc.pk).update(amo_file_uuid=uuid, amo_file_format=doc.format)
        doc.amo_file_uuid, doc.amo_file_format = uuid, doc.format
        in_files = True
    except NoFileAccess:
        log.info("amoCRM account %s gives no file access; document %s only linked", conn.account_id, doc.number)
    except Exception:  # noqa: BLE001 - the file tab is a bonus; the link in the note always works
        log.warning("could not put document %s into lead %s files", doc.number, doc.lead_id, exc_info=True)

    verb = "qayta yaratildi" if remade else "yaratildi"
    where = " — “Файлы” boʻlimida" if in_files else ""
    text = (
        f"📄 {doc.template.name} № {doc.number} {verb} ({doc.get_format_display()}){where}: "
        f"{download_url(doc)}"
    )
    try:
        client.add_note(doc.lead_id, text)
    except AmoError:
        log.warning("could not note document %s on lead %s", doc.number, doc.lead_id)
