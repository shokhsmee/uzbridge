from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Company
from billing.services import PERIOD, active_units


class Command(BaseCommand):
    help = "Give companies that already run paid providers their first 30-day period free (one-off, at launch)."

    def handle(self, *args, **opts):
        now = timezone.now()
        for c in Company.objects.filter(is_platform=False, period_end__isnull=True):
            units = active_units(c)
            if units["payment"] or units["sms"]:
                c.period_start, c.period_end = now, now + PERIOD
                c.paid_payment_units, c.paid_sms_units = units["payment"], units["sms"]
                c.save(update_fields=["period_start", "period_end", "paid_payment_units", "paid_sms_units"])
                self.stdout.write(f"{c.slug}: free period until {(now + PERIOD):%Y-%m-%d} for {units}")
        _ = timedelta
