"""The tool catalog a company picks from. Only amoCRM is live in phase 1."""

from ninja import Router

from amocrm.models import AmoConnection
from core.api import member_auth
from payments.models import FiscalDefaults, ProviderAccount

router = Router(tags=["integrations"], auth=member_auth)

CATALOG = [
    {"key": "amocrm", "name": "amoCRM", "kind": "crm", "available": True},
    {"key": "bitrix24", "name": "Bitrix24", "kind": "crm", "available": False},
    {"key": "odoo", "name": "Odoo", "kind": "erp", "available": False},
    {"key": "uysot", "name": "UySot", "kind": "crm", "available": False},
    {"key": "telegram", "name": "Telegram", "kind": "messenger", "available": False},
]


@router.get("")
def catalog(request):
    amo = AmoConnection.objects.filter(company=request.company).first()
    status = {"amocrm": (amo.status if amo else "not_connected")}
    return [{**item, "status": status.get(item["key"], "coming_soon")} for item in CATALOG]


@router.get("/overview")
def overview(request):
    """What the onboarding checklist on the dashboard needs."""
    amo = AmoConnection.objects.filter(company=request.company).first()
    providers = [a for a in ProviderAccount.objects.filter(company=request.company, is_enabled=True) if a.is_configured]
    return {
        "crm_connected": bool(amo and amo.status == AmoConnection.Status.ACTIVE),
        "crm_status": amo.status if amo else "not_connected",
        "providers_ready": [a.provider for a in providers],
        "paid_stage_set": bool(amo and amo.paid_stages),
        # Payme and Click receipts need an MXIK code on every line.
        "fiscal_ready": FiscalDefaults.objects.filter(company=request.company).exclude(ikpu_code="").exists(),
    }
