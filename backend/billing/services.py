"""Tariffs and the balance.

A company pays per 30-day period, counted from the day its first paid provider
went live (started on the 15th -> renews on the 15th of the next period):

  payment providers: 500 000 so'm for the first, +200 000 for each extra
  SMS gateways:      300 000 so'm for the first, +100 000 for each extra
  amoCRM, Odoo, API/webhooks: free

A provider added mid-period is charged for the days left. If a renewal can't be
paid there are 3 days of grace, then new payment links and SMS pause until the
balance is topped up. Payments already in progress always complete.
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from accounts.models import Company

from .models import LedgerEntry

PERIOD = timedelta(days=30)
GRACE = timedelta(days=3)
SOUM = 100  # tiyin

# Defaults; the live price list is TariffPrice (edited in the admin), and a
# company may have its own CompanyTariff on top.
PRICES = {
    "payment": {"first": 500_000 * SOUM, "extra": 200_000 * SOUM},
    "sms": {"first": 300_000 * SOUM, "extra": 100_000 * SOUM},
    "docs": {"first": 200_000 * SOUM, "extra": 100_000 * SOUM},
}
KINDS = ("payment", "sms", "docs")
PAID_FIELD = {"payment": "paid_payment_units", "sms": "paid_sms_units", "docs": "paid_docs_units"}


def prices_for(company: Company | None = None) -> dict[str, dict[str, int]]:
    from .models import CompanyTariff, TariffPrice

    out = {k: dict(v) for k, v in PRICES.items()}
    for t in TariffPrice.objects.all():
        out[t.kind] = {"first": t.first_tiyin, "extra": t.extra_tiyin}
    if company is not None and company.pk:
        for t in CompanyTariff.objects.filter(company=company):
            out[t.kind] = {"first": t.first_tiyin, "extra": t.extra_tiyin}
    return out


class InsufficientBalance(Exception):
    def __init__(self, needed: int, balance: int):
        super().__init__(f"Not enough balance: {needed // SOUM:,} so'm needed, {balance // SOUM:,} available.")
        self.needed, self.balance = needed, balance


def price(kind: str, units: int, company: Company | None = None, prices: dict | None = None) -> int:
    if units <= 0:
        return 0
    p = (prices or prices_for(company))[kind]
    return p["first"] + p["extra"] * (units - 1)


def active_units(company: Company) -> dict[str, int]:
    from amocrm.models import AmoConnection
    from payments.models import ProviderAccount
    from sms.models import SmsAccount

    pay = sum(1 for a in ProviderAccount.objects.filter(company=company, is_enabled=True) if a.is_configured)
    sms = sum(1 for a in SmsAccount.objects.filter(company=company, is_enabled=True) if a.is_configured)
    docs = AmoConnection.objects.filter(
        company=company, docs_enabled=True, status=AmoConnection.Status.ACTIVE
    ).count()
    return {"payment": pay, "sms": sms, "docs": docs}


def monthly_fee(units: dict[str, int], company: Company | None = None) -> int:
    p = prices_for(company)
    return sum(price(k, units.get(k, 0), prices=p) for k in KINDS)


def is_billable(company: Company) -> bool:
    return not (company.is_platform or company.billing_exempt)


def is_paused(company: Company) -> bool:
    """No new payment links or SMS: blocked by the platform, or unpaid past the grace days."""
    if not company.is_active:
        return True
    return is_billable(company) and company.paused_at is not None


def _entry(company: Company, kind: str, amount: int, description: str, invoice=None) -> LedgerEntry:
    company.balance_tiyin += amount
    company.save(update_fields=["balance_tiyin"])
    return LedgerEntry.objects.create(
        company=company,
        kind=kind,
        amount_tiyin=amount,
        balance_after=company.balance_tiyin,
        description=description[:255],
        invoice=invoice,
    )


def _locked(company: Company) -> Company:
    return Company.objects.select_for_update().get(pk=company.pk)


def upgrade_cost(company: Company, new_units: dict[str, int]) -> int:
    """What turning on `new_units` costs now (0 if already paid for this period)."""
    if not is_billable(company):
        return 0
    if company.period_end is None or company.period_end <= timezone.now():
        return monthly_fee(new_units, company)  # opens a new period
    p = prices_for(company)
    extra = sum(
        price(k, new_units.get(k, 0), prices=p) - price(k, getattr(company, PAID_FIELD[k]), prices=p) for k in KINDS
    )
    if extra <= 0:
        return 0
    left = (company.period_end - timezone.now()).total_seconds() / PERIOD.total_seconds()
    return round(extra * min(1.0, max(0.0, left)))


@transaction.atomic
def ensure_paid(company: Company, new_units: dict[str, int]) -> int:
    """Charge for switching to `new_units`, before it takes effect. Raises InsufficientBalance."""
    company = _locked(company)
    if not is_billable(company):
        return 0
    cost = upgrade_cost(company, new_units)
    opening = company.period_end is None or company.period_end <= timezone.now()
    if cost > company.balance_tiyin:
        raise InsufficientBalance(cost, company.balance_tiyin)
    now = timezone.now()
    if opening:
        if cost:
            _entry(company, LedgerEntry.Kind.CHARGE, -cost, _describe(new_units, "30 kun"))
        company.period_start, company.period_end = now, now + PERIOD
    elif cost:
        _entry(company, LedgerEntry.Kind.PRORATA, -cost, _describe(new_units, "qolgan kunlar"))
    for k in KINDS:
        field = PAID_FIELD[k]
        setattr(company, field, max(getattr(company, field) if not opening else 0, new_units.get(k, 0)))
    company.overdue_since = company.paused_at = None
    company.save(update_fields=["period_start", "period_end", *PAID_FIELD.values(), "overdue_since", "paused_at"])
    return cost


def _describe(units: dict[str, int], span: str) -> str:
    parts = []
    if units.get("payment"):
        parts.append(f"{units['payment']} ta toʻlov tizimi")
    if units.get("sms"):
        parts.append(f"{units['sms']} ta SMS")
    if units.get("docs"):
        parts.append(f"hujjatlar ({units['docs']} ta amoCRM)")
    return f"Tarif: {', '.join(parts) or 'yoʻq'} · {span}"


@transaction.atomic
def renew(company: Company) -> str:
    """Start the next period if the current one ended. Returns what happened."""
    company = _locked(company)
    now = timezone.now()
    if not is_billable(company) or company.period_end is None or company.period_end > now:
        return "noop"
    units = active_units(company)
    fee = monthly_fee(units, company)
    if fee == 0:
        # Nothing paid is switched on: the period simply lapses.
        company.period_start = company.period_end = None
        company.paid_payment_units = company.paid_sms_units = company.paid_docs_units = 0
        company.overdue_since = company.paused_at = None
        company.save()
        return "lapsed"
    if company.balance_tiyin >= fee:
        _entry(company, LedgerEntry.Kind.CHARGE, -fee, _describe(units, "30 kun"))
        # Anniversary billing: the new period starts where the old one ended.
        start = company.period_end if not company.paused_at else now
        company.period_start, company.period_end = start, start + PERIOD
        for k in KINDS:
            setattr(company, PAID_FIELD[k], units[k])
        company.overdue_since = company.paused_at = None
        company.save()
        return "renewed"
    if company.overdue_since is None:
        company.overdue_since = now
    if not company.paused_at and now - company.overdue_since >= GRACE:
        company.paused_at = now
    company.save(update_fields=["overdue_since", "paused_at"])
    return "paused" if company.paused_at else "grace"


@transaction.atomic
def credit(company: Company, amount_tiyin: int, kind: str, description: str, invoice=None) -> LedgerEntry:
    company = _locked(company)
    entry = _entry(company, kind, amount_tiyin, description, invoice)
    transaction.on_commit(lambda: renew(company))  # a top-up clears grace / pause at once
    return entry


def apply_change(company: Company, kind: str) -> int:
    """Call inside the transaction that switched a provider on/changed it, after saving.

    Checks the Kabinet profile for payment providers and charges what the new
    set of providers costs; raising rolls the change back.
    """
    units = active_units(company)
    if kind == "payment" and units["payment"] and is_billable(company):
        fresh = Company.objects.get(pk=company.pk)
        if not fresh.profile_complete:
            raise ProfileIncomplete(fresh.missing_profile_fields())
    return ensure_paid(company, units)


class ProfileIncomplete(Exception):
    def __init__(self, missing: list[str]):
        super().__init__("Fill in the company details in Kabinet first: " + ", ".join(missing))
        self.missing = missing


def summary(company: Company) -> dict:
    units = active_units(company)
    prices = prices_for(company)
    now = timezone.now()
    state = "inactive"
    if company.is_platform:
        state = "platform"
    elif not company.is_active:
        state = "blocked"
    elif company.billing_exempt:
        state = "exempt"
    elif company.paused_at:
        state = "paused"
    elif company.overdue_since:
        state = "grace"
    elif company.period_end and company.period_end > now:
        state = "active"
    return {
        "state": state,
        "balance_tiyin": company.balance_tiyin,
        "period_start": company.period_start,
        "period_end": company.period_end,
        "grace_until": company.overdue_since + GRACE if company.overdue_since else None,
        "units": units,
        "paid_units": {k: getattr(company, PAID_FIELD[k]) for k in KINDS},
        "monthly_fee_tiyin": 0 if not is_billable(company) else monthly_fee(units, company),
        "lines": [
            {
                "kind": k,
                "units": units[k],
                "first_tiyin": prices[k]["first"],
                "extra_tiyin": prices[k]["extra"],
                "total_tiyin": price(k, units[k], prices=prices),
            }
            for k in KINDS
            if k != "docs" or units[k] or getattr(company, PAID_FIELD[k])
        ],
        "prices": prices,
    }
