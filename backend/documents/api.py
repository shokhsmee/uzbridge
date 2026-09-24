"""Dashboard: document templates (Word upload or built on the site) and the documents made."""

import re

from django.http import HttpResponse
from ninja import File, Router, Schema, UploadedFile
from ninja.errors import HttpError

from core.api import member_auth, require_manager

from . import render, services
from .models import DocFormat, DocTemplate, GeneratedDoc

router = Router(tags=["documents"], auth=member_auth)

MAX_DOCX = 5 * 1024 * 1024
PREFIX_RE = re.compile(r"^[A-Za-z0-9А-Яа-яЁёʻʼ'./_-]{0,20}$")


class TemplateIn(Schema):
    name: str
    kind: str = DocTemplate.Kind.HTML
    html: str = ""
    default_format: str = DocFormat.PDF
    prefix: str = ""
    padding: int = 4
    next_number: int | None = None  # set the counter (e.g. continue an old numbering)
    use_in_amocrm: bool = True
    bindings: dict[str, dict] | None = None  # None = keep; see DocTemplate.bindings


class PreviewIn(Schema):
    lead_id: int
    format: str = DocFormat.PDF
    conn: int | None = None  # which amoCRM account; default the company's first


def _keywords(t: DocTemplate) -> list[str]:
    try:
        return render.docx_keywords(bytes(t.docx)) if t.kind == "docx" and t.docx else render.html_keywords(t.html)
    except Exception:  # noqa: BLE001 - a broken file just shows no keywords
        return []


def _known_keys(company) -> set[str]:
    from sms.models import SmsVariable

    own = SmsVariable.objects.filter(company=company, integration=SmsVariable.Integration.AMOCRM)
    return services.BUILTIN_KEYS | set(own.values_list("key", flat=True))


def _out(t: DocTemplate) -> dict:
    used = _keywords(t)
    known = _known_keys(t.company)
    return {
        "id": t.id,
        "name": t.name,
        "kind": t.kind,
        "html": t.html if t.kind == "html" else "",
        "docx_name": t.docx_name,
        "has_file": bool(t.docx),
        "default_format": t.default_format,
        "prefix": t.prefix,
        "padding": t.padding,
        "next_number": t.next_number,
        "next_label": t.format_number(t.next_number),
        "use_in_amocrm": t.use_in_amocrm,
        "keywords": used,
        "bindings": t.bindings or {},
        # used in the template but not defined: shown on the site so nothing prints as "{typo}"
        "unknown_keywords": [k for k in used if k not in known and k not in (t.bindings or {})],
        "can_edit_word": t.kind == "html" and bool(t.docx),  # converted from Word: can go back
        "documents": t.documents.count(),
        "updated_at": t.updated_at,
    }


def _own(request, template_id: int) -> DocTemplate:
    t = DocTemplate.objects.filter(company=request.company, pk=template_id).first()
    if t is None:
        raise HttpError(404, "Template not found.")
    return t


def _apply(t: DocTemplate, data: TemplateIn) -> None:
    name = data.name.strip()
    if not name:
        raise HttpError(422, "Name the template (e.g. Shartnoma).")
    if data.kind not in DocTemplate.Kind.values:
        raise HttpError(422, "Unknown template kind.")
    if data.default_format not in DocFormat.values:
        raise HttpError(422, "Format is Word or PDF.")
    prefix = data.prefix.strip()
    if not PREFIX_RE.match(prefix):
        raise HttpError(422, "Number prefix: up to 20 letters, digits and - / . _ (e.g. DOG-).")
    if not 1 <= data.padding <= 8:
        raise HttpError(422, "Number length is 1–8 digits.")
    if data.next_number is not None:
        taken = t.pk and t.documents.filter(seq__gte=data.next_number).exists()
        if data.next_number < 1 or taken:
            raise HttpError(422, "The next number must be higher than the numbers already used.")
        t.next_number = data.next_number
    t.name, t.kind, t.default_format, t.prefix, t.padding = (
        name[:120],
        data.kind,
        data.default_format,
        prefix,
        data.padding,
    )
    t.use_in_amocrm = data.use_in_amocrm
    if data.kind == DocTemplate.Kind.HTML:
        t.html = data.html
    if data.bindings is not None:
        try:
            t.bindings = services.clean_bindings(data.bindings)
        except ValueError as e:
            raise HttpError(422, str(e))


@router.get("/keywords")
def keywords(request):
    """Everything a template can use: built-ins and the company's amoCRM field keywords."""
    from sms.models import SmsVariable

    own = SmsVariable.objects.filter(company=request.company, integration=SmsVariable.Integration.AMOCRM)
    return {
        "builtins": [{"key": k, "label": label} for k, label in services.BUILTINS],
        "own": [{"key": v.key, "label": v.label or v.source, "source": v.source} for v in own],
    }


@router.get("/templates")
def list_templates(request):
    return [_out(t) for t in DocTemplate.objects.filter(company=request.company)]


@router.post("/templates")
def create_template(request, data: TemplateIn):
    require_manager(request)
    t = DocTemplate(company=request.company)
    _apply(t, data)
    t.save()
    return _out(t)


@router.put("/templates/{template_id}")
def save_template(request, template_id: int, data: TemplateIn):
    require_manager(request)
    t = _own(request, template_id)
    _apply(t, data)
    t.save()
    return _out(t)


@router.post("/templates/{template_id}/upload")
def upload_docx(request, template_id: int, file: UploadedFile = File(...)):  # noqa: B008 - Ninja's upload syntax
    """The Word file of an upload-kind template (replaces the previous one)."""
    require_manager(request)
    t = _own(request, template_id)
    data = file.read(MAX_DOCX + 1)
    if len(data) > MAX_DOCX:
        raise HttpError(422, "The Word file is over 5 MB.")
    if not data.startswith(b"PK"):
        raise HttpError(422, "Upload a .docx file (Word 2007 or newer). Save .doc files as .docx first.")
    try:
        render.fill_docx(data, {})  # opens it: a broken file fails here, not at the lead
    except render.RenderError as e:
        raise HttpError(422, str(e))
    t.kind, t.docx, t.docx_name = DocTemplate.Kind.DOCX, data, (file.name or "template.docx")[:200]
    t.save(update_fields=["kind", "docx", "docx_name", "updated_at"])
    return _out(t)


@router.post("/templates/{template_id}/edit-on-site")
def edit_on_site(request, template_id: int):
    """Open an uploaded Word template in the site's editor (the Word file is kept to go back to)."""
    require_manager(request)
    t = _own(request, template_id)
    if not t.docx:
        raise HttpError(409, "Upload the Word file first.")
    try:
        html = render.docx_to_html(bytes(t.docx))
    except render.RenderError as e:
        raise HttpError(422, str(e))
    t.kind, t.html = DocTemplate.Kind.HTML, html
    t.save(update_fields=["kind", "html", "updated_at"])
    return _out(t)


@router.post("/templates/{template_id}/use-word")
def use_word(request, template_id: int):
    """Back to the uploaded Word file (drops the on-site edits)."""
    require_manager(request)
    t = _own(request, template_id)
    if not t.docx:
        raise HttpError(409, "No Word file to go back to.")
    t.kind = DocTemplate.Kind.DOCX
    t.save(update_fields=["kind", "updated_at"])
    return _out(t)


@router.get("/templates/{template_id}/file")
def download_template(request, template_id: int):
    t = _own(request, template_id)
    if not t.docx:
        raise HttpError(404, "No Word file uploaded.")
    resp = HttpResponse(
        bytes(t.docx), content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    resp["Content-Disposition"] = f'attachment; filename="{t.docx_name or "template.docx"}"'
    return resp


@router.delete("/templates/{template_id}")
def delete_template(request, template_id: int):
    require_manager(request)
    t = _own(request, template_id)
    if t.documents.exists():
        raise HttpError(409, "Documents were made from this template; switch it off for amoCRM instead of deleting.")
    t.delete()
    return {"ok": True}


@router.post("/templates/{template_id}/preview")
def preview(request, template_id: int, data: PreviewIn):
    """A sample on a real lead, with the next number; nothing is saved or counted."""
    from amocrm.client import AmoError
    from amocrm.models import AmoConnection

    t = _own(request, template_id)
    conns = AmoConnection.objects.filter(company=request.company, status=AmoConnection.Status.ACTIVE)
    conn = conns.filter(pk=data.conn).first() if data.conn else conns.first()
    if conn is None:
        raise HttpError(409, "Connect amoCRM first: the sample is filled from a real lead.")
    fmt = data.format if data.format in DocFormat.values else t.default_format
    try:
        content, filename = services.preview(conn, t, data.lead_id, fmt)
    except render.RenderError as e:
        raise HttpError(422, str(e))
    except AmoError as e:
        raise HttpError(502, f"amoCRM: {e}")
    resp = HttpResponse(content, content_type=GeneratedDoc(format=fmt).content_type)
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


@router.get("/documents")
def history(request, limit: int = 100):
    rows = GeneratedDoc.objects.filter(company=request.company).select_related("template", "amo_connection")
    return [
        {
            "id": d.id,
            "number": d.number,
            "template": d.template.name,
            "format": d.format,
            "lead_id": d.lead_id,
            "lead_url": f"https://{d.amo_connection.host}/leads/detail/{d.lead_id}" if d.amo_connection else "",
            "url": services.download_url(d),
            "created_by": d.created_by_label,
            "created_at": d.created_at,
            "updated_at": d.updated_at,
        }
        for d in rows[: max(1, min(limit, 500))]
    ]
