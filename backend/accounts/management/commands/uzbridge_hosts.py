from django.conf import settings
from django.core.management.base import BaseCommand

from accounts.models import Company


class Command(BaseCommand):
    help = "Print every hostname that needs a TLS certificate, one per line."

    def handle(self, *args, **options):
        base = settings.BASE_DOMAIN
        self.stdout.write(base)
        for sub in [
            "app",
            "api",
            *Company.objects.filter(is_active=True).order_by("id").values_list("slug", flat=True),
        ]:
            self.stdout.write(f"{sub}.{base}")
