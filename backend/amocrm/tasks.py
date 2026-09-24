import logging
from datetime import timedelta

from celery import shared_task
from django.db import models
from django.utils import timezone

from payments.models import Invoice

from . import oauth, services
from .client import AmoClient
from .models import AmoConnection

log = logging.getLogger(__name__)


def _conn_for(invoice: Invoice) -> AmoConnection | None:
    """The amoCRM account the invoice came from (older invoices: the company's first one)."""
    if invoice.amo_connection_id:
        return AmoConnection.objects.filter(pk=invoice.amo_connection_id, status=AmoConnection.Status.ACTIVE).first()
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
    if conn.bills_enabled:
        create_amo_bill.delay(invoice.pk)


@shared_task(bind=True, max_retries=4, default_retry_delay=60)
def create_amo_bill(self, invoice_id: int):
    """Mirror the payment link in amoCRM's "Счета/покупки" and link it to the lead."""
    from .bills import create_bill

    invoice = Invoice.objects.select_related("company").get(pk=invoice_id)
    conn = _conn_for(invoice)
    if conn is None or not conn.bills_enabled or invoice.amo_bill_id:
        return
    try:
        create_bill(conn, invoice)
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=6, default_retry_delay=60)
def mark_amo_bill_paid(self, invoice_id: int):
    from .bills import mark_bill_paid

    invoice = Invoice.objects.select_related("company").get(pk=invoice_id)
    conn = _conn_for(invoice)
    if conn is None or not invoice.amo_bill_id:
        return
    try:
        mark_bill_paid(conn, invoice)
    except Exception as exc:
        raise self.retry(exc=exc)


def open_invoice_for(conn: AmoConnection, lead_id: int) -> Invoice | None:
    # Lead ids are per amoCRM account, so two accounts of a company can share one.
    return (
        Invoice.objects.filter(
            company=conn.company, source=Invoice.Source.AMOCRM, external_id=str(lead_id), status=Invoice.Status.PENDING
        )
        .filter(models.Q(amo_connection=conn) | models.Q(amo_connection=None))
        .first()
    )


def invoice_lead(conn: AmoConnection, client: AmoClient, lead: dict) -> Invoice | None:
    """Invoice the lead's budget; leaves a note and returns None when it can't."""
    from payments.services import create_invoice

    from .services import amo_accounts

    lead_id = int(lead["id"])
    price = int(lead.get("price") or 0)
    if price <= 0:
        client.add_note(lead_id, "⚠️ bitim byudjeti boʻsh — summani kiriting va bosqichni qayta tanlang.")
        return None
    if not amo_accounts(conn):
        client.add_note(lead_id, "⚠️ toʻlov usullari sozlanmagan (Payme / Click / Uzum).")
        return None
    try:
        _, phone = client.lead_contact(lead_id)
    except Exception:
        phone = ""
    invoice = create_invoice(
        conn.company,
        customer_phone=phone,
        amount_tiyin=price * 100,
        description=(lead.get("name") or "")[:255],
        source=Invoice.Source.AMOCRM,
        external_id=str(lead_id),
        external_name=(lead.get("name") or "")[:255],
        created_by_label="amoCRM",
        amo_connection=conn,
    )
    post_link_note.delay(invoice.pk)
    return invoice


@shared_task(bind=True, max_retries=5, default_retry_delay=30)
def create_link_for_lead(self, conn_id: int, lead_id: int):
    """The lead entered the "create payment link" stage: invoice its budget."""
    conn = AmoConnection.objects.select_related("company").get(pk=conn_id)
    if open_invoice_for(conn, lead_id) is not None:
        return  # moved back and forth: the existing link still stands
    try:
        client = AmoClient(conn)
        lead = client.lead(lead_id)
        if lead is None:
            return
        if str(conn.link_stages.get(str(lead["pipeline_id"]), "")) != str(lead["status_id"]):
            return  # already moved on by the time we looked
        invoice_lead(conn, client, lead)
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=20)
def send_sms_from_lead(self, conn_id: int, lead_id: int):
    """A manager picked a template in the lead's "SMS shablon" field."""
    from sms.gateways import SmsError
    from sms.models import SmsTemplate
    from sms.services import recently_sent

    conn = AmoConnection.objects.select_related("company").get(pk=conn_id)
    if not conn.sms_field_id:
        return
    try:
        client = AmoClient(conn)
        lead = client.lead(lead_id)
        if lead is None:
            return
        chosen = None
        for f in lead.get("custom_fields_values") or []:
            if f.get("field_id") == conn.sms_field_id and f.get("values"):
                chosen = f["values"][0].get("enum_id")
        if not chosen:
            return  # field empty: nothing picked, or our own reset below
        template = SmsTemplate.objects.filter(company=conn.company, amo_enum_id=chosen).first()
        # Reset first, so a manager can pick the same template again later.
        client.update_lead(lead_id, {"custom_fields_values": [{"field_id": conn.sms_field_id, "values": None}]})
        if template is None or not template.is_approved or not (conn.sms_enabled and template.use_in_amocrm):
            client.add_note(lead_id, "⚠️ bu shablon endi tasdiqlanmagan — SMS yuborilmadi.")
            return
        if recently_sent(conn.company, lead_id, template):
            return
        try:
            send_template_to_lead(conn, client, lead_id, template)
        except SmsError as e:
            client.add_note(lead_id, f"⚠️ uzbridge SMS: {e}")
    except Exception as exc:
        raise self.retry(exc=exc)


def send_template_to_lead(conn: AmoConnection, client: AmoClient, lead_id: int, template, phone: str = ""):
    """Render an approved template for the lead's contact and queue it. Raises SmsError."""
    from sms.gateways import SmsError
    from sms.models import SmsMessage
    from sms.services import queue, render

    name, contact_phone = client.lead_contact(lead_id)
    phone = phone or contact_phone
    if not phone:
        raise SmsError("Kontaktda telefon raqami yoʻq — SMS yuborilmadi.")
    invoice = (
        Invoice.objects.filter(company=conn.company, source=Invoice.Source.AMOCRM, external_id=str(lead_id))
        .filter(models.Q(amo_connection=conn) | models.Q(amo_connection=None))
        .order_by("-created_at")
        .first()
    )
    from .variables import values_for_lead

    text = render(
        template.text, company=conn.company, invoice=invoice, name=name, extra=values_for_lead(conn, client, lead_id)
    )
    msg = queue(
        conn.company,
        phone,
        text,
        event=SmsMessage.Event.AMOCRM,
        template=template,
        lead_id=lead_id,
        invoice=invoice,
        account=conn.sms_account,
    )
    if conn.add_notes:
        client.add_note(lead_id, f"📱 SMS → +{msg.phone} ({msg.get_provider_display()}):\n{text}")
    return msg


@shared_task(bind=True, max_retries=3, default_retry_delay=20)
def note_sms(self, conn_id: int, entity: str, entity_id: int, text: str):
    """Leave a note on the lead or contact an SMS was written from."""
    conn = AmoConnection.objects.get(pk=conn_id)
    path = {"lead": "leads", "contact": "contacts"}[entity]
    try:
        AmoClient(conn).request(
            "POST",
            f"/api/v4/{path}/{entity_id}/notes",
            json=[{"note_type": "service_message", "params": {"service": "uzbridge", "text": text}}],
        )
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
    if invoice.amo_bill_id:
        mark_amo_bill_paid.delay(invoice.pk)


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


# ------------------------------------------------ Digital Pipeline actions


def run_automation(job) -> str:
    """Do one Digital Pipeline action; returns what happened (kept on the job)."""
    from sms.gateways import SmsError
    from sms.models import SmsTemplate

    from .models import AmoAutomationJob as Job
    from .services import amo_templates

    conn = job.conn
    if conn.status != AmoConnection.Status.ACTIVE:
        return "amoCRM is not connected"
    client = AmoClient(conn)
    lead = client.lead(job.lead_id)
    if lead is None:
        return "lead no longer exists"
    if job.delay_minutes and job.status_id and int(lead.get("status_id") or 0) != job.status_id:
        return "skipped: the lead moved to another stage before the delay ended"
    result = []
    if job.action in (Job.Action.LINK, Job.Action.LINK_SMS):
        if open_invoice_for(conn, job.lead_id) is not None:
            result.append("link already open")
        else:
            invoice = invoice_lead(conn, client, lead)
            result.append(f"link {invoice.display_number}" if invoice else "no link (empty budget or no provider)")
            if invoice is None and job.action == Job.Action.LINK_SMS:
                return "; ".join(result)
    if job.action in (Job.Action.SMS, Job.Action.LINK_SMS):
        template = SmsTemplate.objects.filter(company=conn.company, pk=job.template_id).first()
        if template is None or template not in amo_templates(conn):
            client.add_note(
                job.lead_id, "⚠️ avtomatik SMS yuborilmadi — shablon oʻchirilgan yoki tasdiqlanmagan."
            )
            result.append("sms: template off")
        else:
            try:
                msg = send_template_to_lead(conn, client, job.lead_id, template)
                result.append(f"sms → +{msg.phone}")
            except SmsError as e:
                client.add_note(job.lead_id, f"⚠️ uzbridge SMS: {e}")
                result.append(f"sms: {e}")
    return "; ".join(result)[:300]


@shared_task
def run_automation_job(job_id: int):
    from .models import AmoAutomationJob as Job

    # Claim it first (done_at doubles as the lock) so two workers never both run it,
    # and so no transaction is held while invoices and follow-up tasks are created.
    if not Job.objects.filter(pk=job_id, done_at=None).update(done_at=timezone.now()):
        return
    job = Job.objects.select_related("conn__company").get(pk=job_id)
    try:
        result = run_automation(job)
    except Exception as exc:
        log.exception("automation job %s failed", job_id)
        result = f"error: {exc}"
    Job.objects.filter(pk=job_id).update(result=result[:300], done_at=timezone.now())


@shared_task
def run_due_automations():
    from .models import AmoAutomationJob as Job

    for job_id in Job.objects.filter(done_at=None, run_at__lte=timezone.now()).values_list("pk", flat=True)[:200]:
        run_automation_job.delay(job_id)
