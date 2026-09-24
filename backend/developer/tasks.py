import httpx
from celery import shared_task

from . import webhooks
from .models import WebhookDelivery


@shared_task(bind=True, max_retries=8)
def deliver_webhook(self, delivery_id: int):
    d = WebhookDelivery.objects.select_related("endpoint").get(pk=delivery_id)
    if d.delivered_at:
        return
    body = webhooks.body_of(d)
    try:
        resp = httpx.post(
            d.endpoint.url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Uzbridge-Event": d.event,
                "X-Uzbridge-Signature": webhooks.sign(d.endpoint.secret, body),
                "User-Agent": "uzbridge-webhooks/1",
            },
            timeout=15,
        )
    except httpx.HTTPError as exc:
        webhooks.mark(d, None, f"network: {exc}")
        raise self.retry(countdown=min(3600, 30 * 2**self.request.retries))
    webhooks.mark(d, resp.status_code, "" if resp.is_success else resp.text[:500])
    if not resp.is_success:
        raise self.retry(countdown=min(3600, 30 * 2**self.request.retries))
