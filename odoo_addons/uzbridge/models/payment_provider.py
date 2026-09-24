from odoo import api, fields, models

from .. import const


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(selection_add=[('uzbridge', "Payme · Click · Uzum (uzbridge)")], ondelete={'uzbridge': 'set default'})

    @api.depends('code')
    def _compute_feature_support_fields(self):
        super()._compute_feature_support_fields()
        # uzbridge refunds the whole payment (Click/Uzum by API; Payme from its cabinet).
        self.filtered(lambda p: p.code == 'uzbridge').update({'support_refund': 'full_only'})

    def _get_supported_currencies(self):
        currencies = super()._get_supported_currencies()
        if self.code == 'uzbridge':
            currencies = currencies.filtered(lambda c: c.name in const.SUPPORTED_CURRENCIES)
        return currencies

    def _get_default_payment_method_codes(self):
        self.ensure_one()
        if self.code != 'uzbridge':
            return super()._get_default_payment_method_codes()
        return const.DEFAULT_PAYMENT_METHOD_CODES

    def _get_compatible_providers(self, *args, is_validation=False, report=None, **kwargs):
        # No card-on-file validation: every uzbridge payment is a real invoice.
        providers = super()._get_compatible_providers(*args, is_validation=is_validation, report=report, **kwargs)
        if is_validation:
            providers = providers.filtered(lambda p: p.code != 'uzbridge')
        return providers
