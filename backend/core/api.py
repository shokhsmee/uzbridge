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
        request.membership = membership
        return user


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
    from integrations.api import router as integrations_router
    from payments.api import router as payments_router

    api.add_router("/auth", accounts_router)
    api.add_router("/integrations", integrations_router)
    api.add_router("/payments", payments_router)
    api.add_router("/amocrm", amocrm_router)
    api.add_router("/widget", widget_router)
