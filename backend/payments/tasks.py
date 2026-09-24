import logging

from celery import shared_task

from .models import Provider, ProviderTransaction

log = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def submit_fiscal_receipt(self, txn_id: int):
    """Click needs the receipt lines sent separately; Payme takes them in
    CheckPerformTransaction and Uzum in the registered cart."""
    txn = ProviderTransaction.objects.select_related("account", "invoice__company").get(pk=txn_id)
    if txn.provider != Provider.CLICK or txn.fiscal.get("submitted"):
        return
    if not (txn.account.merchant_user_id and txn.meta.get("paydoc_id")):
        log.info("click txn %s: no merchant_user_id or paydoc id, skipping fiscal submit", txn_id)
        return
    from .providers.click import submit_fiscal_items

    try:
        result = submit_fiscal_items(txn.account, txn)
    except Exception as exc:  # network / 5xx: try again later
        raise self.retry(exc=exc)
    txn.fiscal = {**txn.fiscal, "submitted": True, "result": result}
    txn.save(update_fields=["fiscal"])


@shared_task(bind=True, max_retries=8, default_retry_delay=15)
def verify_uzum(self, txn_id: int):
    from .providers import uzum

    try:
        state = uzum.verify(txn_id)
    except Exception as exc:
        raise self.retry(exc=exc)
    if state in ("REGISTERED", "AUTHORIZED"):
        # Callback came before Uzum finished; look again shortly.
        raise self.retry(countdown=20)
