"""Every admin page opens: lists (with search) and change forms, for every registered model."""

from datetime import timedelta

import pytest
from django.contrib import admin
from django.urls import reverse
from django.utils import timezone

from amocrm.models import AmoAutomationJob, AmoConnection
from payments.services import create_invoice
from sms.models import SmsAccount, SmsMessage, SmsTemplate

HOST = "app.uzbridge.test"


@pytest.fixture
def data(company, payme_account):
    conn = AmoConnection.objects.create(
        company=company,
        account_id=1,
        subdomain="a",
        host="a.amocrm.ru",
        access_token="x",
        refresh_token="x",
        expires_at=timezone.now() + timedelta(hours=1),
    )
    AmoAutomationJob.objects.create(conn=conn, lead_id=5, action="sms", run_at=timezone.now())
    acc = SmsAccount.objects.create(company=company, provider="eskiz", login="a@b.uz", secret="s", is_enabled=True)
    tpl = SmsTemplate.objects.create(
        company=company, account=acc, provider="eskiz", text="Salom {name}", status="service"
    )
    SmsMessage.objects.create(
        company=company, account=acc, provider="eskiz", phone="998901234567", text="Salom", template=tpl
    )
    create_invoice(company, amount_tiyin=150_000, amo_connection=conn)


@pytest.mark.django_db
def test_every_admin_page_opens(client, data):
    from accounts.models import User

    root = User.objects.create_superuser(email="root@uzbridge.uz", password="x" * 12)
    client.force_login(root)
    for model, model_admin in admin.site._registry.items():
        info = (model._meta.app_label, model._meta.model_name)
        changelist = reverse("admin:{}_{}_changelist".format(*info))
        r = client.get(changelist, {"q": "a"}, HTTP_HOST=HOST)
        assert r.status_code == 200, f"{changelist}: {r.status_code}"
        obj = model.objects.first()
        if obj is not None:
            change = reverse("admin:{}_{}_change".format(*info), args=[obj.pk])
            assert client.get(change, HTTP_HOST=HOST).status_code == 200, change
        if model_admin.has_add_permission(r.wsgi_request):
            add = reverse("admin:{}_{}_add".format(*info))
            assert client.get(add, HTTP_HOST=HOST).status_code == 200, add
    # secrets never reach the page
    page = client.get(
        reverse("admin:payments_provideraccount_change", args=[data_account_pk()]), HTTP_HOST=HOST
    ).content.decode()
    assert "TESTKEY" not in page and "PRODKEY" not in page


def data_account_pk():
    from payments.models import ProviderAccount

    return ProviderAccount.objects.first().pk


@pytest.mark.django_db
def test_company_top_up_and_block_actions(client, company, owner):
    from accounts.models import Company, User
    from billing.models import LedgerEntry

    root = User.objects.create_superuser(email="root@uzbridge.uz", password="x" * 12)
    client.force_login(root)
    url = reverse("admin:accounts_company_changelist")
    # the action first shows its form, then applies
    form = client.post(url, {"action": "top_up", "_selected_action": [company.pk]}, HTTP_HOST=HOST)
    assert form.status_code == 200 and b"Add to balance" in form.content
    before = Company.objects.get(pk=company.pk).balance_tiyin
    client.post(
        url,
        {"action": "top_up", "_selected_action": [company.pk], "apply": "1", "amount": "250000", "note": "bank"},
        HTTP_HOST=HOST,
    )
    assert Company.objects.get(pk=company.pk).balance_tiyin == before + 25_000_000
    assert LedgerEntry.objects.get(company=company).description == "bank"

    client.post(
        url, {"action": "block", "_selected_action": [company.pk], "apply": "1", "reason": "unpaid"}, HTTP_HOST=HOST
    )
    c = Company.objects.get(pk=company.pk)
    assert (c.is_active, c.blocked_reason) == (False, "unpaid")
    client.force_login(owner)
    assert client.get("/api/auth/me", HTTP_HOST="acme.uzbridge.test").status_code in (401, 404)
    client.force_login(root)
    client.post(url, {"action": "unblock", "_selected_action": [company.pk]}, HTTP_HOST=HOST)
    assert Company.objects.get(pk=company.pk).is_active

    # the filter by payment status opens
    assert client.get(url, {"pay": "blocked"}, HTTP_HOST=HOST).status_code == 200
