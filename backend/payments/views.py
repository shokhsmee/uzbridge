"""Provider callbacks and the customer-facing pay page (plain Django views)."""

import json
import logging

from django.conf import settings
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.tenancy import path_mode, pay_url

from .models import Invoice, Provider, ProviderAccount
from .providers import click, payme, uzum
from .services import accounts_for
from .tasks import verify_uzum

log = logging.getLogger(__name__)


def _account(public_id, provider) -> ProviderAccount:
    return get_object_or_404(ProviderAccount.objects.select_related("company"), public_id=public_id, provider=provider)


def _client_ip(request) -> str:
    fwd = request.META.get("HTTP_X_FORWARDED_FOR")
    return fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR", "")


# ---------------------------------------------------------------- callbacks


@csrf_exempt
def payme_callback(request, public_id):
    if request.method != "POST":
        return JsonResponse(payme.rpc_error(-32300))
    account = _account(public_id, Provider.PAYME)
    # The allowlist is Payme's production range; the sandbox may call from elsewhere.
    if settings.PAYME_ALLOWED_IPS and not account.test_mode and _client_ip(request) not in settings.PAYME_ALLOWED_IPS:
        return JsonResponse(payme.rpc_error(-32504))
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(payme.rpc_error(-32700))
    return JsonResponse(payme.handle(account, body, request.META.get("HTTP_AUTHORIZATION", "")))


@csrf_exempt
@require_POST
def click_callback(request, public_id):
    account = _account(public_id, Provider.CLICK)
    return JsonResponse(click.handle(account, request.POST.dict()))


@csrf_exempt
@require_POST
def uzum_callback(request, public_id):
    account = _account(public_id, Provider.UZUM)
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponse(status=400)
    txn_id = uzum.handle_callback(account, payload)
    if txn_id and "operationState" in payload:
        verify_uzum.delay(txn_id)
    return HttpResponse(status=200)


# ---------------------------------------------------------------- pay page


def _invoice_for_page(request, public_id) -> Invoice:
    qs = Invoice.objects.select_related("company")
    if path_mode():
        # One host for everyone: the unguessable uuid is the only key.
        return get_object_or_404(qs, public_id=public_id)
    if request.company is None:
        raise Http404
    return get_object_or_404(qs, public_id=public_id, company=request.company)


@require_GET
def pay_page(request, public_id):
    invoice = _invoice_for_page(request, public_id)
    providers = [a.provider for a in accounts_for(invoice)] if invoice.status == Invoice.Status.PENDING else []
    lang = request.GET.get("lang", "uz") if request.GET.get("lang") in ("uz", "ru") else "uz"
    return render(
        request,
        "payments/pay.html",
        {
            "invoice": invoice,
            "providers": providers,
            "lang": lang,
            "t": PAGE_TEXT[lang],
            "returned": request.GET.get("r"),
            "amount": f"{invoice.amount_tiyin // 100:,}".replace(",", " "),
        },
    )


@require_GET
def pay_go(request, public_id, provider):
    invoice = _invoice_for_page(request, public_id)
    back = pay_url(invoice)
    if invoice.status != Invoice.Status.PENDING:
        return HttpResponseRedirect(invoice.return_url or back)
    account = next((a for a in accounts_for(invoice) if a.provider == provider), None)
    if account is None:
        raise Http404
    lang = request.GET.get("lang", "uz")
    # Back to the shop (e.g. Odoo re-checks the status there), else to our page.
    done = invoice.return_url or back + "?r=1"
    if provider == Provider.PAYME:
        url = payme.checkout_url(account, invoice, return_url=done, lang=lang)
    elif provider == Provider.CLICK:
        url = click.pay_url(account, invoice, return_url=done)
    else:
        try:
            url = uzum.redirect_url(account, invoice, success_url=done, failure_url=back + "?r=0", lang=lang)
        except Exception:
            log.exception("uzum register failed for invoice %s", invoice.pk)
            return HttpResponseRedirect(back + "?r=err")
    return HttpResponseRedirect(url)


PAGE_TEXT = {
    "uz": {
        "title": "Toʻlov",
        "pay_with": "Toʻlov usulini tanlang",
        "paid": "Toʻlandi",
        "paid_note": "Rahmat! Toʻlov qabul qilindi.",
        "cancelled": "Hisob bekor qilingan",
        "refunded": "Toʻlov qaytarilgan",
        "none": "Hozircha toʻlov usullari ulanmagan.",
        "checking": "Toʻlov tekshirilmoqda — sahifani birozdan soʻng yangilang.",
        "error": "Toʻlov sahifasini ochib boʻlmadi. Boshqa usulni tanlang yoki keyinroq urinib koʻring.",
        "invoice": "Hisob",
        "sum": "soʻm",
        "back": "Doʻkonga qaytish",
    },
    "ru": {
        "title": "Оплата",
        "pay_with": "Выберите способ оплаты",
        "paid": "Оплачено",
        "paid_note": "Спасибо! Оплата получена.",
        "cancelled": "Счёт отменён",
        "refunded": "Оплата возвращена",
        "none": "Способы оплаты пока не подключены.",
        "checking": "Проверяем оплату — обновите страницу через минуту.",
        "error": "Не удалось открыть страницу оплаты. Выберите другой способ или попробуйте позже.",
        "invoice": "Счёт",
        "sum": "сум",
        "back": "Вернуться в магазин",
    },
}
