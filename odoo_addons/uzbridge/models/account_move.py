from odoo import _, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_uzbridge_payment_link(self):
        """Post Odoo's portal payment link (where Payme · Click · Uzum is offered)
        in the chatter, and text it to the customer when SMS goes through uzbridge."""
        self.ensure_one()
        if self.state != 'posted' or self.move_type not in ('out_invoice', 'out_receipt'):
            raise UserError(_("Only posted customer invoices can be paid online."))
        if self.currency_id.name != 'UZS':
            raise UserError(_("Payme, Click and Uzum take payments in UZS only."))
        link = self._get_portal_payment_link()
        self.message_post(body=_("Payment link (Payme · Click · Uzum): %s", link))
        phone = self.partner_id.phone or getattr(self.partner_id, 'mobile', False)
        sent = False
        if phone and self.company_id.uzbridge_sms:
            body = _("%(company)s: %(amount)s so'm to'lov uchun havola %(link)s",
                     company=self.company_id.name, amount=f"{self.amount_residual:,.0f}".replace(',', ' '), link=link)
            self._message_sms(body, sms_numbers=[phone])
            sent = True
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Payment link ready — send it to the customer"),
                # The invoice turns paid only when the customer pays through this
                # link (uzbridge then calls back). "Pay" / Register Payment is
                # Odoo's manual entry for money already received, not uzbridge.
                'message': (_("Sent by SMS to %s. ", phone) if sent else "") + "%s",
                'links': [{'label': link, 'url': link}],
                'type': 'success',
                'sticky': True,
            },
        }
