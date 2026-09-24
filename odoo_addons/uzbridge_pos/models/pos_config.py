from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    uzbridge_link_enabled = fields.Boolean(
        string="uzbridge: payment link button",
        help="Show a button on the payment screen that makes a Payme / Click / Uzum link for the order.",
    )
    uzbridge_sms_enabled = fields.Boolean(
        string="uzbridge: send SMS button",
        help="Show a button that sends the customer an approved SMS template with the payment link.",
    )
