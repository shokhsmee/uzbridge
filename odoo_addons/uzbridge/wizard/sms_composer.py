from odoo import api, fields, models


class SmsComposer(models.TransientModel):
    _inherit = 'sms.composer'

    uzbridge_active = fields.Boolean(compute='_compute_uzbridge_active')
    uzbridge_template_id = fields.Many2one(
        'uzbridge.sms.template', string="uzbridge template",
        domain="[('company_id', '=', current_company_id)]",
        help="Approved texts from your SMS gateway (Eskiz only delivers approved templates).",
    )
    current_company_id = fields.Many2one('res.company', compute='_compute_uzbridge_active')

    @api.depends_context('company')
    def _compute_uzbridge_active(self):
        for c in self:
            c.current_company_id = self.env.company
            c.uzbridge_active = self.env.company.uzbridge_sms

    @api.onchange('uzbridge_template_id')
    def _onchange_uzbridge_template_id(self):
        if self.uzbridge_template_id:
            self.body = self._uzbridge_render(self.uzbridge_template_id.body)

    def _uzbridge_render(self, text):
        values = {'company': self.env.company.name, 'name': '', 'amount': '', 'number': '', 'link': ''}
        record = self.env[self.res_model].browse(self.res_id) if self.res_model and self.res_id else None
        if record:
            partner = record if record._name == 'res.partner' else getattr(record, 'partner_id', False)
            values['name'] = (partner and partner.name) or ''
            if record._name == 'account.move':
                values.update(
                    amount=f"{record.amount_residual:,.0f}".replace(',', ' '),
                    number=record.name or '',
                    link=record._get_portal_payment_link() if record.state == 'posted' else '',
                )
        if record:
            for var in self.env['uzbridge.sms.variable'].search([('company_id', '=', self.env.company.id)]):
                values.setdefault(var.key, self.env['uzbridge.sms.variable']._value(record, var.path))
        for key, value in values.items():
            text = text.replace('{%s}' % key, value)
        return text
