from django.contrib import admin
from django.urls import path

from amocrm import views as amo_views
from core.api import api, register_routers
from payments import views as pay_views
from sms import views as sms_views

register_routers()

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
    # Provider callbacks (configured in each provider's merchant cabinet).
    path("cb/payme/<uuid:public_id>/", pay_views.payme_callback, name="cb-payme"),
    path("cb/click/<uuid:public_id>/", pay_views.click_callback, name="cb-click"),
    path("cb/uzum/<uuid:public_id>/", pay_views.uzum_callback, name="cb-uzum"),
    # SMS delivery reports; Playmobile appends "status" to the URL it's given.
    path("cb/sms/eskiz/<uuid:public_id>/", sms_views.eskiz_dlr, name="cb-sms-eskiz"),
    path("cb/sms/playmobile/<uuid:public_id>/status", sms_views.playmobile_dlr, name="cb-sms-playmobile"),
    # Customer pay page on the company subdomain.
    path("p/<uuid:public_id>/", pay_views.pay_page, name="pay-page"),
    path("p/<uuid:public_id>/go/<str:provider>/", pay_views.pay_go, name="pay-go"),
    # amoCRM OAuth redirect and uninstall hook (on app.*).
    path("oauth/amocrm/callback", amo_views.oauth_callback, name="amocrm-oauth-callback"),
    path("oauth/amocrm/uninstall", amo_views.uninstall_hook, name="amocrm-uninstall"),
    path("oauth/amocrm/secrets", amo_views.install_secrets, name="amocrm-secrets"),
    path("oauth/amocrm/hook/<str:token>/", amo_views.lead_hook, name="amocrm-hook"),
    path("oauth/amocrm/dp/", amo_views.dp_hook, name="amocrm-dp"),
]
