from odoo import fields, models

from ..const import DEFAULT_URL


class ResCompany(models.Model):
    _inherit = 'res.company'

    uzbridge_url = fields.Char("uzbridge URL", default=DEFAULT_URL)
    uzbridge_api_key = fields.Char("uzbridge API key", groups='base.group_system', copy=False)
    # Secret uzbridge signs its webhooks with, returned when we register our URL.
    uzbridge_webhook_secret = fields.Char(groups='base.group_system', copy=False)
    uzbridge_account = fields.Char("uzbridge account", readonly=True, copy=False)
    uzbridge_sms = fields.Boolean(
        "Send SMS through uzbridge",
        help="Send Odoo's SMS through the company's Eskiz or Playmobile account (set up in uzbridge) instead of Odoo IAP.",
    )

    def _get_sms_api_class(self):
        self.ensure_one()
        if self.uzbridge_sms:
            from ..tools.sms_api import SmsApiUzbridge

            return SmsApiUzbridge
        return super()._get_sms_api_class()
