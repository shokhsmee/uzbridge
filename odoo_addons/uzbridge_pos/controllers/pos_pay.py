from odoo import http
from odoo.http import request

from odoo.addons.pos_online_payment.controllers.payment_portal import PaymentPortal


class UzbridgePosPortal(PaymentPortal):
    """One scan, straight to Payme / Click / Uzum.

    When the order's online method offers only uzbridge, the customer skips
    Odoo's "choose a payment method" page: the transaction is made here and the
    browser goes to the uzbridge pay page. Anything else keeps Odoo's form.
    """

    @http.route()
    def pos_order_pay(self, pos_order_id, access_token=None, exit_route=None):
        pos_order_sudo = self._check_order_access(pos_order_id, access_token)
        self._ensure_session_open(pos_order_sudo)
        amount = self._get_amount_to_pay(pos_order_sudo)
        currency = pos_order_sudo.currency_id
        partner_sudo = pos_order_sudo.partner_id or pos_order_sudo.company_id._get_public_user().partner_id
        if not (currency.active and self._is_valid_amount(amount, currency)):
            return super().pos_order_pay(pos_order_id, access_token=access_token, exit_route=exit_route)
        providers = self._get_allowed_providers_sudo(pos_order_sudo, partner_sudo.id, amount)
        if len(providers) != 1 or providers.code != 'uzbridge':
            return super().pos_order_pay(pos_order_id, access_token=access_token, exit_route=exit_route)

        # Scanned twice (or reloaded): reuse the open transaction for the same amount.
        tx_sudo = request.env['payment.transaction'].sudo().search([
            ('pos_order_id', '=', pos_order_sudo.id),
            ('provider_id', '=', providers.id),
            ('state', 'in', ('draft', 'pending')),
            ('uzbridge_pay_url', '!=', False),
        ], order='id desc', limit=1)
        if tx_sudo and currency.compare_amounts(tx_sudo.amount, amount) == 0:
            return request.redirect(tx_sudo.uzbridge_pay_url, local=False)

        method = providers.payment_method_ids[:1]
        tx_sudo = self._create_transaction(
            provider_id=providers.id,
            payment_method_id=method.id,
            token_id=None,
            amount=amount,
            currency_id=currency.id,
            partner_id=partner_sudo.id,
            flow='redirect',
            tokenization_requested=False,
            landing_route='',
            reference_prefix=None,
            custom_create_values={'pos_order_id': pos_order_sudo.id, 'tokenize': False},
        )
        tx_sudo.landing_route = self._get_landing_route(
            pos_order_sudo.id, access_token, exit_route=exit_route, tx_id=tx_sudo.id
        )
        tx_sudo._get_processing_values()  # asks uzbridge for the invoice and its pay page
        if not tx_sudo.uzbridge_pay_url:
            return super().pos_order_pay(pos_order_id, access_token=access_token, exit_route=exit_route)
        return request.redirect(tx_sudo.uzbridge_pay_url, local=False)
