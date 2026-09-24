from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_uzbridge_link_enabled = fields.Boolean(related='pos_config_id.uzbridge_link_enabled', readonly=False)
    pos_uzbridge_sms_enabled = fields.Boolean(related='pos_config_id.uzbridge_sms_enabled', readonly=False)
