from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone
from ninja import Router

from core.api import member_auth

from .models import CallbackLog

router = Router(tags=["audit"], auth=member_auth)


@router.get("/callbacks")
def callbacks(request, source: str = "", failed: bool = False, limit: int = 100):
    qs = CallbackLog.objects.filter(company=request.company)
    if source:
        qs = qs.filter(source=source)
    if failed:
        qs = qs.filter(Q(ok=False) | Q(blocked=True))
    since = timezone.now() - timedelta(days=1)
    stats = CallbackLog.objects.filter(company=request.company, created_at__gte=since).aggregate(
        total=Count("id"), failed=Count("id", filter=Q(ok=False)), blocked=Count("id", filter=Q(blocked=True))
    )
    return {
        "stats_24h": stats,
        "items": [
            {
                "id": c.pk,
                "source": c.source,
                "path": c.path,
                "ip": c.ip,
                "status_code": c.status_code,
                "ok": c.ok,
                "blocked": c.blocked,
                "note": c.note,
                "created_at": c.created_at,
            }
            for c in qs[: max(1, min(limit, 500))]
        ],
    }
