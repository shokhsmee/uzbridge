import logging

from odoo import api, fields, models

from ..tools.uzbridge_api import UzbridgeClient, UzbridgeError

_logger = logging.getLogger(__name__)


class UzbridgeSmsTemplate(models.Model):
    """SMS texts approved by the company's gateway (Eskiz moderation), synced from uzbridge.

    Eskiz only delivers texts that match an approved template, so the SMS composer
    offers these. Placeholders: {name} {company} {amount} {number} {link}, plus the company's own
    keywords (uzbridge.sms.variable), each read from a field of the record.
    """

    _name = 'uzbridge.sms.template'
    _description = "uzbridge SMS template"
    _order = 'sequence, id'

    name = fields.Char(compute='_compute_name', store=True)
    body = fields.Text(required=True)
    uzbridge_id = fields.Integer(index=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    active = fields.Boolean(default=True)

    @api.depends('body')
    def _compute_name(self):
        for t in self:
            text = (t.body or '').replace('\n', ' ')
            t.name = text if len(text) <= 70 else text[:67] + '…'

    @api.model
    def _uzbridge_sync(self, company=None):
        """Replace the company's templates with uzbridge's approved list."""
        company = company or self.env.company
        rows = UzbridgeClient(company).request('GET', '/sms/templates')
        existing = {t.uzbridge_id: t for t in self.with_context(active_test=False).search([('company_id', '=', company.id)])}
        seen = set()
        for i, row in enumerate(rows):
            seen.add(row['id'])
            vals = {'body': row['text'], 'sequence': i, 'active': True}
            if row['id'] in existing:
                existing[row['id']].write(vals)
            else:
                self.create({**vals, 'uzbridge_id': row['id'], 'company_id': company.id})
        for uid, t in existing.items():
            if uid not in seen:
                t.active = False
        self.env['uzbridge.sms.variable']._uzbridge_sync(company)
        return len(rows)

    @api.model
    def _cron_uzbridge_sync(self):
        for company in self.env['res.company'].sudo().search([('uzbridge_api_key', '!=', False)]):
            try:
                self.sudo()._uzbridge_sync(company)
            except UzbridgeError as e:
                _logger.warning("uzbridge template sync failed for %s: %s", company.name, e)


    @api.model
    def _uzbridge_fill(self, text, record=None, values=None):
        """Fill {keywords}: the given values, then the company's own keywords read from `record`.

        Unknown keywords stay as typed, so a missing one is visible, not silently blank.
        """
        values = dict(values or {})
        values.setdefault('company', self.env.company.name)
        if record:
            variables = self.env['uzbridge.sms.variable'].search([('company_id', '=', self.env.company.id)])
            for var in variables:
                values.setdefault(var.key, variables._value(record, var.path))
        for key, value in values.items():
            text = text.replace('{%s}' % key, '' if value is None else str(value))
        return text


class UzbridgeSmsVariable(models.Model):
    """A company {keyword} set on the uzbridge website, read from a field path of
    the record the SMS is written from (e.g. partner_id.name, invoice_date_due)."""

    _name = 'uzbridge.sms.variable'
    _description = "uzbridge SMS keyword"
    _order = 'key'

    key = fields.Char(required=True)
    path = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)

    @api.model
    def _uzbridge_sync(self, company):
        rows = UzbridgeClient(company).request('GET', '/sms/variables')
        self.search([('company_id', '=', company.id)]).unlink()
        self.create([{'key': r['key'], 'path': r['path'], 'company_id': company.id} for r in rows])
        return len(rows)

    @api.model
    def _value(self, record, path):
        """Follow a field path on the record; unknown or empty fields give ''."""
        value = record
        for name in path.split('.'):
            if not value or name not in value._fields:
                return ''
            value = value[:1][name]
        if isinstance(value, models.BaseModel):
            return ', '.join(value.mapped('display_name'))
        if value is False or value is None:
            return ''
        if isinstance(value, float):
            fmt = '{:,.0f}' if value == int(value) else '{:,.2f}'
            return fmt.format(value).replace(',', ' ')
        if hasattr(value, 'strftime'):
            return value.strftime('%d.%m.%Y')
        return str(value)
