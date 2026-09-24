import base64

import pytest

from config.celery import app as celery_app


@pytest.fixture(autouse=True)
def _eager_celery(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
    celery_app.conf.update(task_always_eager=True, task_eager_propagates=True)
    settings.BASE_DOMAIN = "uzbridge.test"
    settings.PUBLIC_SCHEME = "https"
    settings.PUBLIC_PORT = ""
    settings.ALLOWED_HOSTS = [".uzbridge.test"]
    settings.AMOCRM_CLIENT_ID = "client-id"
    settings.AMOCRM_CLIENT_SECRET = "client-secret-0123456789abcdef-0123456789"
    settings.AMOCRM_REDIRECT_URI = "https://app.uzbridge.test/oauth/amocrm/callback"
    yield


@pytest.fixture
def company(db):
    from accounts.models import Company

    return Company.objects.create(name="Acme", slug="acme", tin="123456789")


@pytest.fixture
def other_company(db):
    from accounts.models import Company

    return Company.objects.create(name="Other", slug="other")


@pytest.fixture
def owner(company):
    from accounts.models import Membership, User

    user = User.objects.create_user(email="owner@acme.uz", password="s3cret-pass!")
    Membership.objects.create(company=company, user=user, role=Membership.Role.OWNER)
    return user


@pytest.fixture
def payme_account(company):
    from payments.models import ProviderAccount

    return ProviderAccount.objects.create(
        company=company,
        provider="payme",
        merchant_id="5e730e8e0b852a417aa49ceb",
        test_secret="TESTKEY",
        secret="PRODKEY",
    )


@pytest.fixture
def click_account(company):
    from payments.models import ProviderAccount

    return ProviderAccount.objects.create(
        company=company,
        provider="click",
        merchant_id="11111",
        service_id="22222",
        merchant_user_id="33333",
        secret="CLICKSECRET",
        test_mode=False,
    )


@pytest.fixture
def uzum_account(company):
    from payments.models import ProviderAccount

    return ProviderAccount.objects.create(
        company=company,
        provider="uzum",
        merchant_id="7b3f1a52-0000-4000-8000-000000000001",
        secret="9c1e2b77-0000-4000-8000-000000000002",
        test_mode=True,
    )


@pytest.fixture
def invoice(company):
    from payments.services import create_invoice

    return create_invoice(company, amount_tiyin=150_000_00, description="Consulting")


def basic(login, password):
    return "Basic " + base64.b64encode(f"{login}:{password}".encode()).decode()
