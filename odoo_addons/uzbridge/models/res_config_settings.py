from odoo import _, fields, models
from odoo.exceptions import UserError

from ..const import WEBHOOK_ROUTE
from ..tools.uzbridge_api import UzbridgeClient


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    uzbridge_url = fields.Char(related='company_id.uzbridge_url', readonly=False)
    uzbridge_api_key = fields.Char(related='company_id.uzbridge_api_key', readonly=False)
    uzbridge_account = fields.Char(related='company_id.uzbridge_account')
    uzbridge_sms = fields.Boolean(related='company_id.uzbridge_sms', readonly=False)

    def action_uzbridge_connect(self):
        """Check the key and register this database's webhook URL with uzbridge."""
        self.ensure_one()
        self.execute()  # save the URL / key typed in first
        company = self.company_id.sudo()
        client = UzbridgeClient(company)
        info = client.request('GET', '/ping')
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        if not base_url.startswith('https://') and client.base.startswith('https://'):
            raise UserError(_(
                "uzbridge must be able to reach this Odoo to report payments, but its address is %(url)s.\n\n"
                "Set Settings → Technical → System Parameters → web.base.url to this database's public https "
                "address (and add web.base.url.freeze = True so logging in from another address doesn't change it), "
                "then press Connect again.", url=base_url or '—'))
        hook = client.request('POST', '/webhooks', json={'url': base_url.rstrip('/') + WEBHOOK_ROUTE, 'label': 'odoo'})
        providers = ', '.join(p.capitalize() for p in info.get('providers') or []) or _("no payment methods yet")
        sms = (info.get('sms') or _("no SMS provider")).capitalize()
        company.write({
            'uzbridge_webhook_secret': hook['secret'],
            'uzbridge_account': f"{info['company']} ({info['slug']}) · {providers} · SMS: {sms}",
        })
        try:
            count = self.env['uzbridge.sms.template'].sudo()._uzbridge_sync(company)
        except Exception:  # templates are a convenience; never block connecting
            count = 0
        provider = self.env['payment.provider'].sudo().search(
            [('code', '=', 'uzbridge'), ('company_id', '=', company.id)], limit=1
        )
        if provider and provider.state == 'disabled':
            provider.state = 'test' if not info.get('providers') else 'enabled'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("uzbridge connected"),
                'message': _("%(account)s · %(n)s approved SMS templates", account=company.uzbridge_account, n=count),
                'type': 'success',
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_uzbridge_sync_templates(self):
        n = self.env['uzbridge.sms.template'].sudo()._uzbridge_sync(self.company_id)
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _("SMS templates synced"), 'message': _("%s approved templates", n), 'type': 'success'}}

    def action_uzbridge_disconnect(self):
        self.company_id.sudo().write({'uzbridge_api_key': False, 'uzbridge_webhook_secret': False,
                                       'uzbridge_account': False, 'uzbridge_sms': False})
        if not self.company_id.sudo().uzbridge_api_key:
            return {'type': 'ir.actions.client', 'tag': 'reload'}
        raise UserError(_("Could not disconnect."))
