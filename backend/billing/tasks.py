import logging

from celery import shared_task
from django.utils import timezone

from accounts.models import Company

from . import services

log = logging.getLogger(__name__)


@shared_task
def renew_due():
    for company in Company.objects.filter(is_platform=False, period_end__lte=timezone.now()):
        try:
            result = services.renew(company)
            if result != "noop":
                log.info("billing %s: %s", company.slug, result)
        except Exception:
            log.exception("billing renew failed for %s", company.slug)
