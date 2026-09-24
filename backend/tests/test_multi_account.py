# ruff: noqa: F811  (pytest fixture imported from test_amocrm)
"""One company, several accounts per integration: two Payme cash desks, two amoCRM accounts."""

from datetime import timedelta

import pytest
from django.utils import timezone

from amocrm.models import AmoConnection
from payments.models import Invoice, ProviderAccount
from payments.services import accounts_for, create_invoice, route_accounts
from tests.test_amocrm import conn  # noqa: F401
from tests.test_payme import acc, rpc


@pytest.fixture
def two_paymes(company, payme_account):
    second = ProviderAccount.objects.create(
        company=company, provider="payme", label="Filial 2", merchant_id="second", test_secret="TESTKEY", is_enabled=True
    )
    return payme_account, second


@pytest.fixture
def second_conn(company):
    return AmoConnection.objects.create(
        company=company,
        account_id=777,
        subdomain="filial2",
        host="filial2.amocrm.ru",
        access_token="AT",
        refresh_token="RT",
        expires_at=timezone.now() + timedelta(hours=20),
    )


@pytest.mark.django_db
def test_each_amocrm_account_uses_its_own_cash_desk(client, company, conn, second_conn, two_paymes):
    first, second = two_paymes
    # Not chosen yet: the first working account of each provider.
    assert route_accounts(company, None) == [first]
    conn.payment_accounts = [first.pk]
    second_conn.payment_accounts = [second.pk]
    conn.save()
    second_conn.save()

    inv = create_invoice(company, amount_tiyin=100_000, source=Invoice.Source.AMOCRM, external_id="5", amo_connection=second_conn)
    assert accounts_for(inv) == [second]

    # Payme calls the first cash desk's URL for an invoice routed to the second: refused.
    wrong = rpc(client, first, "CheckPerformTransaction", {"amount": inv.amount_tiyin, "account": acc(inv)})
    assert wrong["error"]["code"] == -31050
    right = rpc(client, second, "CheckPerformTransaction", {"amount": inv.amount_tiyin, "account": acc(inv)})
    assert right["result"]["allow"] is True


@pytest.mark.django_db
def test_route_keeps_one_account_per_provider(company, two_paymes):
    first, second = two_paymes
    assert route_accounts(company, [second.pk, first.pk]) == [first]  # first by creation order wins
    assert route_accounts(company, []) == []
