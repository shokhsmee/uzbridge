from odoo import _, api, models
from odoo.exceptions import AccessError, UserError


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _uzbridge_check_user(self):
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_("Only Point of Sale users can do this."))

    def _uzbridge_pay_link(self):
        """The customer's pay link: /pos/pay opens the uzbridge page (Payme / Click / Uzum) directly."""
        self.ensure_one()
        if not self.online_payment_method_id:
            raise UserError(_("This Point of Sale has no online payment method with uzbridge."))
        self._ensure_access_token()
        return f"{self.get_base_url()}/pos/pay/{self.id}?access_token={self.access_token}"

    def _uzbridge_values(self):
        self.ensure_one()
        amount = self.get_amount_unpaid() if self.state == 'draft' else self.amount_total
        return {
            'name': self.partner_id.name or '',
            'amount': f"{amount:,.0f}".replace(',', ' '),
            'number': self.pos_reference or self.name or '',
            'link': self._uzbridge_pay_link(),
        }

    # ------------------------------------------------------------ called from the POS

    def uzbridge_payment_link(self):
        self._uzbridge_check_user()
        return self._uzbridge_pay_link()

    @api.model
    def uzbridge_sms_templates(self):
        """Approved templates of the company, for the POS "Send SMS" dialog."""
        self._uzbridge_check_user()
        if not self.env.company.uzbridge_sms:
            raise UserError(_("SMS through uzbridge is not switched on (Settings → uzbridge)."))
        templates = self.env['uzbridge.sms.template'].search([('company_id', '=', self.env.company.id)])
        return [{'id': t.id, 'name': t.name, 'has_link': '{link}' in (t.body or '')} for t in templates]

    def uzbridge_sms_preview(self, template_id):
        self._uzbridge_check_user()
        template = self._uzbridge_template(template_id)
        return self.env['uzbridge.sms.template']._uzbridge_fill(template.body, self, self._uzbridge_values())

    def uzbridge_send_sms(self, phone, template_id):
        """Send the template to `phone` with the order's keywords filled in; noted on the order."""
        self._uzbridge_check_user()
        self.ensure_one()
        phone = (phone or '').strip()
        if len(''.join(ch for ch in phone if ch.isdigit())) < 9:
            raise UserError(_("Enter the customer's phone number."))
        template = self._uzbridge_template(template_id)
        body = self.env['uzbridge.sms.template']._uzbridge_fill(template.body, self, self._uzbridge_values())
        self._message_sms(body, sms_numbers=[phone])
        return {'phone': phone, 'body': body}

    def _uzbridge_template(self, template_id):
        template = self.env['uzbridge.sms.template'].browse(int(template_id)).exists()
        if not template or template.company_id != self.env.company:
            raise UserError(_("Pick an approved SMS template."))
        return template
