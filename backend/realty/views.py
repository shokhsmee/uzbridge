# ruff: noqa: E501 - inline page CSS
"""Google's OAuth redirect and the "🔄 Sinxronlash" link inside a project's sheet."""

import logging

from django.core.cache import cache
from django.http import HttpResponse, HttpResponseRedirect
from django.utils.html import escape

from accounts.models import Company
from core.tenancy import company_url

from . import google, sheet
from .models import Project

log = logging.getLogger(__name__)


def _page(title: str, body: str, ok: bool, back: str = "") -> HttpResponse:
    color = "#1d7a3a" if ok else "#a33b2b"
    link = f'<p><a href="{escape(back)}">← Jadvalga qaytish / Вернуться к таблице</a></p>' if back else ""
    html = (
        '<!doctype html><html lang="uz"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        f"<title>{escape(title)}</title><style>body{{font:15px/1.5 system-ui,sans-serif;background:#f3f5f5;color:#14201f;"
        "display:grid;place-items:center;min-height:100vh;margin:0}main{background:#fff;border:1px solid #dde3e2;"
        "border-radius:14px;padding:28px 32px;max-width:440px;text-align:center}h1{font-size:20px;margin:0 0 6px;"
        f"color:{color}}}p{{margin:6px 0;color:#5b6765}}a{{color:#0d6660;font-weight:600}}</style></head>"
        f"<body><main><h1>{escape(title)}</h1><p>{body}</p>{link}</main></body></html>"
    )
    return HttpResponse(html, status=200 if ok else 400)


def oauth_callback(request):
    """Google sends the user back here; then we make the sheet and go straight to it."""
    try:
        state = google.read_state(request.GET.get("state", ""))
    except google.GoogleError as e:
        return _page("Google", escape(str(e)), ok=False)
    company = Company.objects.filter(pk=state["c"], is_active=True).first()
    if company is None:
        return _page("Google", "Company not found.", ok=False)
    back = company_url(company, "/shaxmatka")
    if request.GET.get("error"):
        return HttpResponseRedirect(f"{back}?google=cancelled")
    try:
        from accounts.models import User

        user = User.objects.filter(pk=state.get("u")).first()
        google.finish(request.GET.get("code", ""), company, user.email if user else "")
        project = Project.objects.filter(company=company, pk=state.get("p")).first() if state.get("p") else None
        if project is not None:
            url = project.sheet_url if project.sheet_id else google.create_sheet(project)
            return HttpResponseRedirect(url)
    except google.GoogleError as e:
        return _page("Google", escape(str(e)), ok=False, back=back)
    return HttpResponseRedirect(f"{back}?google=connected")


def pull(request, token: str):
    """The link in the sheet's toolbar: sync now and say how it went."""
    project = Project.objects.filter(pull_token=token, company__is_active=True).exclude(sheet_id="").first()
    if project is None:
        return _page("uzbridge", "Bu havola eskirgan. / Ссылка устарела.", ok=False)
    if not cache.add(f"realty-pull:{project.pk}", 1, 10):
        return _page(
            "⏳", "Sinxronlash ketmoqda, bir necha soniyadan soʻng qayta bosing.", ok=True, back=project.sheet_url
        )
    try:
        s = google.pull(project)
    except (google.GoogleError, sheet.SheetError) as e:
        return _page("Sinxronlanmadi / Ошибка", escape(str(e)), ok=False, back=project.sheet_url)
    finally:
        cache.delete(f"realty-pull:{project.pk}")
    body = (
        f"<b>{s['total']}</b> ta obyekt: {s['created']} yangi, {s['updated']} yangilandi"
        + (f", {s['archived']} arxivga" if s.get("archived") else "")
        + ("<br>" + "<br>".join(escape(e) for e in s["errors"][:5]) if s.get("errors") else "")
    )
    return _page("✅ Sinxronlandi", body, ok=True, back=project.sheet_url)
