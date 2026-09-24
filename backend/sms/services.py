from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from accounts.models import Company
from core.tenancy import pay_url, platform_url

from . import gateways
from .models import SmsAccount, SmsMessage, SmsProvider, SmsSettings, SmsTemplate


class _Blank(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def usable_accounts(company: Company) -> list[SmsAccount]:
    return [a for a in SmsAccount.objects.filter(company=company, is_enabled=True) if a.is_configured]


def active_account(company: Company, preferred: SmsAccount | None = None) -> SmsAccount | None:
    """The account to send through: the integration's pick, else the company default, else the first."""
    accounts = usable_accounts(company)
    by_pk = {a.pk: a for a in accounts}
    if preferred is not None and preferred.pk in by_pk:
        return by_pk[preferred.pk]
    settings = SmsSettings.objects.filter(company=company).first()
    if settings and settings.account_id in by_pk:
        return by_pk[settings.account_id]
    if settings and settings.provider:
        chosen = next((a for a in accounts if a.provider == settings.provider), None)
        if chosen:
            return chosen
    return accounts[0] if accounts else None


def approved_templates(company: Company, preferred: SmsAccount | None = None) -> list[SmsTemplate]:
    account = active_account(company, preferred)
    if account is None:
        return []
    return [t for t in account_templates(company, account) if t.is_approved]


def account_templates(company: Company, account: SmsAccount):
    """All of an account's templates; ones not linked to an account yet count for their gateway."""
    from django.db.models import Q

    return SmsTemplate.objects.filter(company=company).filter(
        Q(account=account) | Q(account=None, provider=account.provider)
    )


def dlr_url(account: SmsAccount) -> str:
    # Playmobile appends "/status" to the base URL it is given.
    return platform_url("api", f"/cb/sms/{account.provider}/{account.public_id}/")


def queue(
    company: Company,
    phone: str,
    text: str,
    *,
    event=SmsMessage.Event.MANUAL,
    invoice=None,
    template=None,
    lead_id=None,
    external_ref: str = "",
    account: SmsAccount | None = None,
) -> SmsMessage:
    from billing.services import is_paused

    if is_paused(company):
        raise gateways.SmsError("uzbridge obunasi toʻxtatilgan — Kabinet → Balans’ni toʻldiring.")
    # A template belongs to one gateway account: send through that one.
    account = active_account(
        company, (template.account if template is not None and template.account_id else None) or account
    )
    if account is None:
        raise gateways.SmsError("No SMS provider is set up.")
    msg = SmsMessage.objects.create(
        company=company,
        account=account,
        provider=account.provider,
        phone=gateways.normalize_phone(phone),
        text=text.strip(),
        event=event,
        invoice=invoice,
        template=template,
        lead_id=lead_id,
        external_ref=external_ref,
    )
    from .tasks import deliver

    transaction.on_commit(lambda: deliver.delay(msg.pk))
    return msg


def render(text: str, *, company: Company, invoice=None, name: str = "", extra: dict | None = None) -> str:
    """Fill {placeholders}: the built-ins plus the company's own keywords (`extra`)."""
    from amocrm.services import money

    values = _Blank(extra or {})
    values.update(company=company.name, name=name or values.get("name", ""))
    if invoice is not None:
        values.update(amount=money(invoice.amount_tiyin), number=invoice.display_number, link=pay_url(invoice))
    return text.format_map(values)


def variable_keys(company: Company, integration: str) -> list[str]:
    from .models import SmsVariable

    return list(SmsVariable.objects.filter(company=company, integration=integration).values_list("key", flat=True))


def sync_templates(company: Company, account: SmsAccount | None = None) -> list[SmsTemplate]:
    """Pull Eskiz's templates (all statuses; only approved ones are usable), per Eskiz account."""
    accounts = (
        [account]
        if account is not None
        else [a for a in SmsAccount.objects.filter(company=company, provider=SmsProvider.ESKIZ) if a.is_configured]
    )
    if not accounts or not all(a.provider == SmsProvider.ESKIZ and a.is_configured for a in accounts):
        raise gateways.SmsError("Set up Eskiz first.")
    for acc in accounts:
        remote = gateways.eskiz_templates(acc)
        seen = set()
        for r in remote:
            if not r["text"]:
                continue
            seen.add(r["id"])
            SmsTemplate.objects.update_or_create(
                company=company,
                account=acc,
                external_id=r["id"],
                defaults={"provider": SmsProvider.ESKIZ, "text": r["text"], "status": r["status"] or "moderation"},
            )
        SmsTemplate.objects.filter(account=acc).exclude(external_id__in=seen).delete()
    return list(SmsTemplate.objects.filter(company=company, account__in=accounts))


def _auto(invoice, attr: str, event: str) -> None:
    s = SmsSettings.objects.filter(company=invoice.company).select_related(attr).first()
    template = getattr(s, attr, None) if s else None
    if template is None or not template.is_approved or not invoice.customer_phone:
        return
    queue(
        invoice.company,
        invoice.customer_phone,
        render(template.text, company=invoice.company, invoice=invoice),
        event=event,
        invoice=invoice,
        template=template,
    )


def on_invoice_created(invoice) -> None:
    _auto(invoice, "link_template", SmsMessage.Event.LINK)


def on_invoice_paid(invoice) -> None:
    _auto(invoice, "paid_template", SmsMessage.Event.PAID)


def recently_sent(company: Company, lead_id: int, template: SmsTemplate, seconds: int = 120) -> bool:
    since = timezone.now() - timedelta(seconds=seconds)
    return SmsMessage.objects.filter(
        company=company, lead_id=lead_id, template=template, created_at__gte=since
    ).exists()


def save_variables(company: Company, integration: str, rows: list[dict], source_ok) -> list:
    """Replace the company's keywords for one integration. Raises ValueError on bad input."""
    import re

    from .models import BUILTIN_VARIABLES, VARIABLE_KEY_RE, SmsVariable

    clean, seen = [], set()
    for row in rows:
        key = str(row.get("key", "")).strip().strip("{}").lower()
        source = str(row.get("source", "")).strip()
        if not key and not source:
            continue
        if not re.match(VARIABLE_KEY_RE, key):
            raise ValueError(f"{{{key}}}: use latin letters, digits and _ (starting with a letter).")
        if key in BUILTIN_VARIABLES:
            raise ValueError(f"{{{key}}} is built in already.")
        if key in seen:
            raise ValueError(f"{{{key}}} is listed twice.")
        if not source_ok(source):
            raise ValueError(f"{{{key}}}: pick a field for it.")
        seen.add(key)
        clean.append(
            SmsVariable(
                company=company, integration=integration, key=key, source=source, label=str(row.get("label", ""))[:80]
            )
        )
    with transaction.atomic():
        SmsVariable.objects.filter(company=company, integration=integration).delete()
        SmsVariable.objects.bulk_create(clean)
    return clean
