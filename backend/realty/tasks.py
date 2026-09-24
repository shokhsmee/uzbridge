import logging

from celery import shared_task

log = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def lead_moved(self, conn_id: int, lead_id: int):
    """A deal with units changed stage: re-read it (the webhook is unsigned) and move its units."""
    from amocrm.client import AmoClient, AmoError
    from amocrm.models import AmoConnection

    from . import services
    from .models import Unit

    conn = AmoConnection.objects.filter(pk=conn_id, status=AmoConnection.Status.ACTIVE).first()
    if conn is None or not Unit.objects.filter(amo_connection=conn, lead_id=lead_id).exists():
        return
    try:
        lead = AmoClient(conn).lead(lead_id) or {}
    except AmoError as e:
        raise self.retry(exc=e)
    if lead.get("status_id"):
        services.on_stage(conn, lead_id, int(lead["pipeline_id"]), int(lead["status_id"]))


@shared_task
def expire_bookings():
    from . import services

    return services.expire_bookings()


@shared_task
def pull_sheet(project_id: int):
    """Sync one project's uzbridge-made sheet (after a status change here, or on schedule)."""
    from django.core.cache import cache

    from . import google, sheet
    from .models import Project

    project = Project.objects.filter(pk=project_id, company__is_active=True).exclude(sheet_id="").first()
    if project is None or not cache.add(f"realty-pull:{project.pk}", 1, 60):
        return
    try:
        google.pull(project)
    except (google.GoogleError, sheet.SheetError) as e:
        log.warning("sheet sync for project %s failed: %s", project_id, e)
    finally:
        cache.delete(f"realty-pull:{project.pk}")


@shared_task
def pull_all_sheets():
    from .models import GoogleAccount, Project

    companies = GoogleAccount.objects.values_list("company_id", flat=True)
    for pk in Project.objects.filter(company_id__in=companies).exclude(sheet_id="").values_list("pk", flat=True):
        pull_sheet.delay(pk)
