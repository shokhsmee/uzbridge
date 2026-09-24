import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from payments.models import Invoice

from . import oauth, services
from .client import AmoClient
from .models import AmoConnection

log = logging.getLogger(__name__)


def _conn_for(invoice: Invoice) -> AmoConnection | None:
    return AmoConnection.objects.filter(company_id=invoice.company_id, status=AmoConnection.Status.ACTIVE).first()


def _custom_fields(conn: AmoConnection, invoice: Invoice, status_text: str) -> list[dict]:
    out = []
    if conn.link_field_id:
        out.append({"field_id": conn.link_field_id, "values": [{"value": services.pay_link(invoice)}]})
    if conn.status_field_id:
        out.append({"field_id": conn.status_field_id, "values": [{"value": status_text}]})
    return out


@shared_task(bind=True, max_retries=6, default_retry_delay=30)
def post_link_note(self, invoice_id: int):
    invoice = Invoice.objects.select_related("company").get(pk=invoice_id)
    conn = _conn_for(invoice)
    if conn is None or not invoice.external_id:
        return
    try:
        client = AmoClient(conn)
        lead_id = int(invoice.external_id)
        if conn.add_notes:
            client.add_note(lead_id, services.note_created(invoice))
        fields = _custom_fields(conn, invoice, f"Awaiting payment · {invoice.display_number}")
        if fields:
            client.update_lead(lead_id, {"custom_fields_values": fields})
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=10, default_retry_delay=30)
def sync_invoice_paid(self, invoice_id: int):
    invoice = Invoice.objects.select_related("company").get(pk=invoice_id)
    if invoice.crm_synced_at or invoice.status != Invoice.Status.PAID:
        return
    conn = _conn_for(invoice)
    if conn is None:
        Invoice.objects.filter(pk=invoice_id).update(crm_sync_error="amoCRM is not connected.")
        return
    try:
        client = AmoClient(conn)
        lead_id = int(invoice.external_id)
        lead = client.lead(lead_id)
        if lead is None:
            Invoice.objects.filter(pk=invoice_id).update(crm_sync_error=f"Lead {lead_id} no longer exists.")
            return
        pipeline_id = lead["pipeline_id"]
        fields = {"pipeline_id": pipeline_id, "status_id": conn.paid_stage_for(pipeline_id)}
        cf = _custom_fields(conn, invoice, f"Paid · {invoice.get_paid_via_display()} · {invoice.display_number}")
        if cf:
            fields["custom_fields_values"] = cf
        client.update_lead(lead_id, fields)
        if conn.add_notes:
            client.add_note(lead_id, services.note_paid(invoice))
    except Exception as exc:
        Invoice.objects.filter(pk=invoice_id).update(crm_sync_error=str(exc)[:500])
        raise self.retry(exc=exc)
    Invoice.objects.filter(pk=invoice_id).update(crm_synced_at=timezone.now(), crm_sync_error="")


@shared_task(bind=True, max_retries=6, default_retry_delay=30)
def sync_invoice_refunded(self, invoice_id: int):
    invoice = Invoice.objects.select_related("company").get(pk=invoice_id)
    conn = _conn_for(invoice)
    if conn is None:
        return
    try:
        client = AmoClient(conn)
        lead_id = int(invoice.external_id)
        if conn.add_notes:
            client.add_note(lead_id, services.note_refunded(invoice))
        cf = _custom_fields(conn, invoice, f"Refunded · {invoice.display_number}")
        if cf:
            client.update_lead(lead_id, {"custom_fields_values": cf})
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task
def refresh_expiring_tokens():
    soon = timezone.now() + timedelta(hours=6)
    for conn_id in AmoConnection.objects.filter(status=AmoConnection.Status.ACTIVE, expires_at__lt=soon).values_list(
        "pk", flat=True
    ):
        try:
            oauth.refresh(conn_id, force=True)
        except Exception:
            log.exception("amocrm token refresh failed for connection %s", conn_id)
