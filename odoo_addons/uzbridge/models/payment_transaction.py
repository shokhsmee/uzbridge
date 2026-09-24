import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import urls

from .. import const
from ..tools.uzbridge_api import UzbridgeClient, UzbridgeError

_logger = logging.getLogger(__name__)


def _tiyin(amount):
    return int(round(amount * 100))


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    # The uzbridge pay page for this transaction (lets e.g. POS send the customer straight there).
    uzbridge_pay_url = fields.Char(readonly=True, copy=False)

    # ------------------------------------------------------------ redirect

    def _uzbridge_receipt_lines(self):
        """(product, name, qty, total incl. tax, taxes) for what is being paid."""
        lines = []
        if 'invoice_ids' in self._fields and self.invoice_ids:
            for line in self.invoice_ids.invoice_line_ids.filtered(lambda l: l.display_type == 'product'):
                lines.append((line.product_id, line.name, line.quantity, line.price_total, line.tax_ids))
        elif 'sale_order_ids' in self._fields and self.sale_order_ids:
            for line in self.sale_order_ids.order_line.filtered(lambda l: not l.display_type):
                lines.append((line.product_id, line.name, line.product_uom_qty, line.price_total, line.tax_ids))
        return lines

    def _uzbridge_receipt_items(self):
        """Receipt lines from the paid invoice/order, only if they add up to the amount.

        Partial payments, discounts that don't split evenly, etc. fall back to
        uzbridge's single default line (the company's default MXIK code).
        """
        items = []
        for product, name, qty, total, taxes in self._uzbridge_receipt_lines():
            if not total:
                continue
            total_t = _tiyin(total)
            count = int(qty) if qty == int(qty) and qty > 0 and total_t % int(qty) == 0 else 1
            vat = next((int(t.amount) for t in taxes if t.amount_type == 'percent'), 0)
            tmpl = product.product_tmpl_id
            items.append({
                'title': (name or product.display_name or '')[:63],
                'price_tiyin': total_t // count,
                'count': count,
                'ikpu_code': tmpl.uz_ikpu_code or '',
                'package_code': tmpl.uz_package_code or '',
                'vat_percent': vat,
            })
        if sum(i['price_tiyin'] * i['count'] for i in items) != _tiyin(self.amount):
            return []
        return items

    def _get_specific_rendering_values(self, processing_values):
        res = super()._get_specific_rendering_values(processing_values)
        if self.provider_code != 'uzbridge':
            return res
        base_url = self.provider_id.get_base_url()
        payload = {
            'amount_tiyin': _tiyin(self.amount),
            'reference': self.reference,
            'source': 'odoo',
            'description': self.reference,
            'customer_phone': self.partner_phone or '',
            'return_url': urls.urljoin(base_url, f"{const.RETURN_ROUTE}?reference={self.reference}"),
            'items': self._uzbridge_receipt_items(),
        }
        try:
            invoice = UzbridgeClient(self.company_id).request('POST', '/invoices', json=payload)
        except UzbridgeError as e:
            self._set_error(str(e))
            return {}
        self.provider_reference = invoice['id']
        self.uzbridge_pay_url = invoice['url']
        return {'api_url': invoice['url']}

    # ------------------------------------------------------------ processing

    @api.model
    def _extract_reference(self, provider_code, payment_data):
        if provider_code != 'uzbridge':
            return super()._extract_reference(provider_code, payment_data)
        return payment_data.get('reference')

    def _extract_amount_data(self, payment_data):
        if self.provider_code != 'uzbridge':
            return super()._extract_amount_data(payment_data)
        return {'amount': payment_data['amount_tiyin'] / 100, 'currency_code': payment_data.get('currency', 'UZS')}

    def _apply_updates(self, payment_data):
        if self.provider_code != 'uzbridge':
            return super()._apply_updates(payment_data)
        self.provider_reference = payment_data.get('id') or self.provider_reference
        state = const.STATUS_MAPPING.get(payment_data.get('status'))
        via = (payment_data.get('paid_via') or '').capitalize()
        if state == 'done':
            self._set_done(state_message=_("Paid via %s", via) if via else None)
        elif state == 'pending':
            self._set_pending()
        elif state == 'cancel':
            self._set_canceled()
        else:
            self._set_error(_("Unknown uzbridge status: %s", payment_data.get('status')))

    def _uzbridge_fetch(self):
        """Server-side truth for this transaction's invoice."""
        self.ensure_one()
        return UzbridgeClient(self.company_id).request('GET', f'/invoices/{self.provider_reference}')

    # ------------------------------------------------------------ refunds

    def _send_refund_request(self):
        if self.provider_code != 'uzbridge':
            return super()._send_refund_request()
        source = self.source_transaction_id
        try:
            data = UzbridgeClient(self.company_id).request('POST', f'/invoices/{source.provider_reference}/refund')
        except UzbridgeError as e:
            raise ValidationError(str(e)) from e
        if data.get('status') == 'refunded':
            self.provider_reference = source.provider_reference
            self._set_done(state_message=_("Refunded through uzbridge"))
