import logging

from celery import shared_task

from . import gateways, services
from .models import SmsMessage

log = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def deliver(self, message_id: int):
    msg = SmsMessage.objects.select_related("account").get(pk=message_id)
    if msg.status != SmsMessage.Status.QUEUED:
        return
    try:
        msg.provider_id = gateways.send(msg.account, msg.phone, msg.text, services.dlr_url(msg.account))
    except gateways.SmsError as exc:
        # Provider said no (bad credentials, unapproved text, no balance): don't retry blindly.
        msg.status, msg.error = SmsMessage.Status.FAILED, str(exc)[:1000]
        msg.save(update_fields=["status", "error", "updated_at"])
        _emit_status(msg)
        return
    except Exception as exc:  # network
        if self.request.retries >= self.max_retries:
            msg.status, msg.error = SmsMessage.Status.FAILED, f"network: {exc}"[:1000]
            msg.save(update_fields=["status", "error", "updated_at"])
            return
        raise self.retry(exc=exc)
    msg.status, msg.error = SmsMessage.Status.SENT, ""
    msg.save(update_fields=["provider_id", "status", "error", "updated_at"])
    _emit_status(msg)


def _emit_status(msg: SmsMessage) -> None:
    if msg.external_ref:
        from developer.webhooks import emit

        data = {"id": msg.pk, "ref": msg.external_ref, "phone": msg.phone, "status": msg.status, "error": msg.error}
        emit(msg.company, "sms.status", data)
