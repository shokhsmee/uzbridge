from odoo import models


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    def _uzbridge_receipt_lines(self):
        # A POS order: the receipt carries its lines (MXIK codes from the products).
        if self.pos_order_id:
            return [
                (line.product_id, line.full_product_name or line.product_id.display_name, line.qty,
                 line.price_subtotal_incl, line.tax_ids_after_fiscal_position)
                for line in self.pos_order_id.lines
            ]
        return super()._uzbridge_receipt_lines()
