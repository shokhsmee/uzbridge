import json
from datetime import timedelta

import pytest
from django.utils import timezone
from freezegun import freeze_time

from accounts.models import Company
from billing import services
from billing.models import LedgerEntry
from payments.models import ProviderAccount
from sms.models import SmsAccount

HOST = {"HTTP_HOST": "acme.uzbridge.test"}
SOUM = 100


def put(client, path, body):
    csrf = client.get("/api/auth/csrf", **HOST).cookies["csrftoken"].value
    return client.put(path, data=json.dumps(body), content_type="application/json", HTTP_X_CSRFTOKEN=csrf, **HOST)


def post(client, path, body):
    csrf = client.get("/api/auth/csrf", **HOST).cookies["csrftoken"].value
    return client.post(path, data=json.dumps(body), content_type="application/json", HTTP_X_CSRFTOKEN=csrf, **HOST)


def enable_payme(client):
    body = {"provider": "payme", "is_enabled": True, "merchant_id": "m1", "test_secret": "k", "test_mode": True}
    return post(client, "/api/payments/providers", body)


@pytest.mark.django_db
def test_prices():
    assert services.price("payment", 1) == 500_000 * SOUM
    assert services.price("payment", 3) == (500_000 + 2 * 200_000) * SOUM
    assert services.price("sms", 2) == 400_000 * SOUM
    assert services.price("sms", 0) == 0


@pytest.mark.django_db
class TestGate:
    def test_first_provider_opens_a_paid_period(self, client, owner, company):
        client.force_login(owner)
        assert enable_payme(client).status_code == 200
        company.refresh_from_db()
        assert company.balance_tiyin == (10_000_000 - 500_000) * SOUM
        assert company.period_end - company.period_start == timedelta(days=30)
        assert LedgerEntry.objects.get().kind == "charge"
        # Saving the same account again inside the period costs nothing.
        acc = ProviderAccount.objects.get()
        body = {"is_enabled": True, "merchant_id": "m1", "test_mode": True, "label": "Filial 1"}
        assert put(client, f"/api/payments/providers/{acc.pk}", body).status_code == 200
        assert LedgerEntry.objects.count() == 1
        # A second Payme cash desk is one more unit: +200 000 for the rest of the period.
        assert enable_payme(client).status_code == 200
        extra = LedgerEntry.objects.exclude(kind="charge").get()
        assert extra.amount_tiyin == -200_000 * SOUM
        assert ProviderAccount.objects.filter(provider="payme").count() == 2

    def test_profile_required_for_payments(self, client, owner, company):
        Company.objects.filter(pk=company.pk).update(bank_account="")
        client.force_login(owner)
        r = enable_payme(client)
        assert r.status_code == 409 and "bank_account" in r.json()["detail"]
        assert not ProviderAccount.objects.exists()  # rolled back

    def test_not_enough_balance(self, client, owner, company):
        Company.objects.filter(pk=company.pk).update(balance_tiyin=100_000 * SOUM)
        client.force_login(owner)
        r = enable_payme(client)
        assert r.status_code == 402 and "500 000" in r.json()["detail"]
        assert not ProviderAccount.objects.exists()

    def test_extra_provider_mid_period_is_prorated(self, client, owner, company):
        client.force_login(owner)
        with freeze_time("2026-10-01 10:00"):
            enable_payme(client)
        with freeze_time("2026-10-16 10:00"):  # half the period left
            client.force_login(owner)  # the first session is past its 2-week life
            r = post(
                client,
                "/api/payments/providers",
                {
                    "provider": "click",
                    "is_enabled": True,
                    "merchant_id": "1",
                    "service_id": "2",
                    "secret": "s",
                    "test_mode": False,
                },
            )
        assert r.status_code == 200, r.content
        pro = LedgerEntry.objects.get(kind="prorata")
        assert pro.amount_tiyin == -100_000 * SOUM  # 200 000 x 15/30

    def test_sms_has_no_profile_requirement(self, client, owner, company):
        Company.objects.filter(pk=company.pk).update(entity_type="")
        client.force_login(owner)
        r = post(
            client,
            "/api/sms/accounts",
            {"provider": "eskiz", "is_enabled": True, "login": "a@b.uz", "secret": "x", "sender": "4546"},
        )
        assert r.status_code == 200
        assert LedgerEntry.objects.get().amount_tiyin == -300_000 * SOUM


@pytest.mark.django_db
class TestRenewal:
    def _active(self, company, balance_soum):
        ProviderAccount.objects.create(
            company=company, is_enabled=True, provider="payme", merchant_id="m", test_secret="k"
        )
        SmsAccount.objects.create(company=company, is_enabled=True, provider="eskiz", login="a", secret="b")
        now = timezone.now()
        Company.objects.filter(pk=company.pk).update(
            balance_tiyin=balance_soum * SOUM,
            period_start=now - timedelta(days=30),
            period_end=now,
            paid_payment_units=1,
            paid_sms_units=1,
        )

    def test_renews_on_the_anniversary(self, company):
        self._active(company, 1_000_000)
        assert services.renew(company) == "renewed"
        company.refresh_from_db()
        assert company.balance_tiyin == (1_000_000 - 800_000) * SOUM
        assert company.period_end > timezone.now() + timedelta(days=29)

    def test_grace_then_pause_then_topup_resumes(self, company, django_capture_on_commit_callbacks):
        self._active(company, 100_000)
        assert services.renew(company) == "grace"
        company.refresh_from_db()
        assert not services.is_paused(company)
        with freeze_time(timezone.now() + timedelta(days=3, minutes=1)):
            assert services.renew(company) == "paused"
        company.refresh_from_db()
        assert services.is_paused(company)
        from payments.services import enabled_accounts
        from sms.gateways import SmsError
        from sms.services import queue

        assert enabled_accounts(company) == []
        with pytest.raises(SmsError, match="toʻxtatilgan"):
            queue(company, "901234567", "hi")
        with django_capture_on_commit_callbacks(execute=True):
            services.credit(company, 1_000_000 * SOUM, LedgerEntry.Kind.CREDIT, "bank")
        company.refresh_from_db()
        assert not services.is_paused(company) and company.balance_tiyin == (100_000 + 1_000_000 - 800_000) * SOUM


@pytest.mark.django_db
def test_topup_through_platform_payme(client, owner, company, django_capture_on_commit_callbacks, settings):
    from payments.models import Invoice
    from tests.conftest import basic

    platform = Company.objects.create(name="uzbridge", slug="uzbridge", is_platform=True)
    acc = ProviderAccount.objects.create(
        company=platform, provider="payme", merchant_id="plat", test_secret="PK", is_enabled=True
    )
    client.force_login(owner)
    csrf = client.get("/api/auth/csrf", **HOST).cookies["csrftoken"].value
    r = client.post(
        "/api/billing/topup",
        data=json.dumps({"amount": 750_000}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        **HOST,
    )
    assert r.status_code == 200, r.content
    inv = Invoice.objects.get(company=platform)
    assert (inv.source, inv.external_id) == ("topup", str(company.pk))

    def rpc(method, params):
        return client.post(
            f"/cb/payme/{acc.public_id}/",
            data=json.dumps({"method": method, "params": params, "id": 1}),
            content_type="application/json",
            HTTP_AUTHORIZATION=basic("Paycom", "PK"),
            HTTP_HOST="api.uzbridge.test",
        ).json()

    rpc(
        "CreateTransaction",
        {"id": "t", "time": 1, "amount": inv.amount_tiyin, "account": {"order_id": str(inv.number)}},
    )
    before = Company.objects.get(pk=company.pk).balance_tiyin
    with django_capture_on_commit_callbacks(execute=True):
        rpc("PerformTransaction", {"id": "t"})
    assert Company.objects.get(pk=company.pk).balance_tiyin == before + 750_000 * SOUM
    assert LedgerEntry.objects.get(company=company).kind == "topup"


@pytest.mark.django_db
def test_exempt_test_account_turns_everything_on_for_free(client, owner, company):
    """A platform-flagged test company: no profile, no balance, no charges."""
    Company.objects.filter(pk=company.pk).update(billing_exempt=True, entity_type="", balance_tiyin=0)
    client.force_login(owner)
    for body in (
        {"provider": "payme", "is_enabled": True, "merchant_id": "m1", "test_secret": "k"},
        {"provider": "click", "is_enabled": True, "merchant_id": "1", "service_id": "2", "secret": "s"},
        {"provider": "uzum", "is_enabled": True, "merchant_id": "t", "secret": "a"},
    ):
        assert post(client, "/api/payments/providers", body).status_code == 200
    assert not LedgerEntry.objects.exists()
    assert services.summary(Company.objects.get(pk=company.pk))["state"] == "exempt"


@pytest.mark.django_db
def test_price_list_and_company_deal_come_from_the_admin(client, owner, company):
    from billing.models import CompanyTariff, TariffPrice

    TariffPrice.objects.filter(kind="payment").update(first_tiyin=400_000 * SOUM)
    assert services.price("payment", 1, company) == 400_000 * SOUM
    CompanyTariff.objects.create(company=company, kind="payment", first_tiyin=100_000 * SOUM, extra_tiyin=50_000 * SOUM)
    assert services.price("payment", 2, company) == 150_000 * SOUM
    client.force_login(owner)
    assert enable_payme(client).status_code == 200
    assert LedgerEntry.objects.get().amount_tiyin == -100_000 * SOUM  # the deal, not the list price
    assert services.summary(Company.objects.get(pk=company.pk))["lines"][0]["first_tiyin"] == 100_000 * SOUM


@pytest.mark.django_db
def test_blocked_company_takes_no_new_payments(company, payme_account):
    from payments.services import enabled_accounts

    assert enabled_accounts(company)
    Company.objects.filter(pk=company.pk).update(is_active=False)
    blocked = Company.objects.get(pk=company.pk)
    assert services.is_paused(blocked) and enabled_accounts(blocked) == []
    assert services.summary(blocked)["state"] == "blocked"
