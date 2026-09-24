from django.contrib import admin
from django.urls import path

from amocrm import views as amo_views
from core.api import api, register_routers
from payments import views as pay_views

register_routers()

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
    # Provider callbacks (configured in each provider's merchant cabinet).
    path("cb/payme/<uuid:public_id>/", pay_views.payme_callback, name="cb-payme"),
    path("cb/click/<uuid:public_id>/", pay_views.click_callback, name="cb-click"),
    path("cb/uzum/<uuid:public_id>/", pay_views.uzum_callback, name="cb-uzum"),
    # Customer pay page on the company subdomain.
    path("p/<uuid:public_id>/", pay_views.pay_page, name="pay-page"),
    path("p/<uuid:public_id>/go/<str:provider>/", pay_views.pay_go, name="pay-go"),
    # amoCRM OAuth redirect and uninstall hook (on app.*).
    path("oauth/amocrm/callback", amo_views.oauth_callback, name="amocrm-oauth-callback"),
    path("oauth/amocrm/uninstall", amo_views.uninstall_hook, name="amocrm-uninstall"),
]
