from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import Company, Membership, User


class Command(BaseCommand):
    help = "Create (or mark) the platform company whose Payme/Click take balance top-ups."

    def add_arguments(self, parser):
        parser.add_argument("--owner", required=True, help="email of an existing user who manages it")

    def handle(self, *args, owner, **opts):
        user = User.objects.filter(email=owner.lower()).first()
        if user is None:
            raise CommandError(f"No user {owner}; sign up first.")
        company, created = Company.objects.get_or_create(
            slug=settings.PLATFORM_COMPANY_SLUG, defaults={"name": "uzbridge"}
        )
        company.is_platform = True
        company.save(update_fields=["is_platform"])
        Membership.objects.get_or_create(company=company, user=user, defaults={"role": Membership.Role.OWNER})
        self.stdout.write(f"{'created' if created else 'marked'} platform company {company.slug}; owner {user.email}")
