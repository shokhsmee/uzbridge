from django.core.exceptions import ValidationError
from ninja import NinjaAPI
from ninja.errors import HttpError
from ninja.security import SessionAuth

from accounts.services import membership_for


class CompanyMember(SessionAuth):
    """Session auth (with CSRF) that also requires membership of request.company."""

    def authenticate(self, request, key):
        user = super().authenticate(request, key)
        if user is None:
            return None
        membership = membership_for(user, request.company)
        if membership is None:
            return None
        from accounts.services import has_company

        if not has_company(request, request.company):
            return None  # member, but this browser hasn't signed in to this company
        _touch_session(request)
        request.membership = membership
        return user


def _touch_session(request) -> None:
    from datetime import timedelta

    from django.utils import timezone

    from accounts.models import UserSession

    key = request.session.session_key
    stale = timezone.now() - timedelta(minutes=5)
    UserSession.objects.filter(session_key=key, last_seen__lt=stale).update(last_seen=timezone.now())


member_auth = CompanyMember()


def require_manager(request) -> None:
    if not request.membership.can_manage:
        raise HttpError(403, "Only owners and admins can change this.")


api = NinjaAPI(title="uzbridge", version="1", urls_namespace="api", docs_url="/docs")


@api.exception_handler(ValidationError)
def on_validation_error(request, exc: ValidationError):
    detail = exc.message_dict if hasattr(exc, "error_dict") else {"__all__": exc.messages}
    return api.create_response(request, {"detail": detail}, status=422)


def register_routers():
    from accounts.api import router as accounts_router
    from amocrm.api import router as amocrm_router
    from amocrm.widget_api import router as widget_router
    from audit.api import router as audit_router
    from billing.api import router as billing_router
    from developer.api import router as developer_router
    from developer.api_v1 import router as v1_router
    from documents.api import router as documents_router
    from integrations.api import router as integrations_router
    from payments.api import router as payments_router
    from realty.api import router as realty_router
    from realty.showroom_api import router as showroom_router
    from sms.api import router as sms_router

    api.add_router("/auth", accounts_router)
    api.add_router("/integrations", integrations_router)
    api.add_router("/payments", payments_router)
    api.add_router("/amocrm", amocrm_router)
    api.add_router("/widget", widget_router)
    api.add_router("/sms", sms_router)
    api.add_router("/developer", developer_router)
    api.add_router("/v1", v1_router)
    api.add_router("/billing", billing_router)
    api.add_router("/audit", audit_router)
    api.add_router("/documents", documents_router)
    api.add_router("/realty", realty_router)
    api.add_router("/realty", showroom_router)
