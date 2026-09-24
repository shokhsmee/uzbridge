from urllib.parse import quote

from django.http import Http404, HttpResponse
from django.views.decorators.http import require_GET

from .models import GeneratedDoc


@require_GET
def download(request, token):
    """The document behind a lead note's link. The unguessable token is the key."""
    doc = GeneratedDoc.objects.filter(token=token).only("content", "filename", "format").first()
    if doc is None:
        raise Http404
    resp = HttpResponse(bytes(doc.content), content_type=doc.content_type)
    disposition = "inline" if doc.format == "pdf" else "attachment"
    resp["Content-Disposition"] = f"{disposition}; filename*=UTF-8''{quote(doc.filename)}"
    resp["Cache-Control"] = "private, no-store"
    resp["X-Robots-Tag"] = "noindex"
    return resp
