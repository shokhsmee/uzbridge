from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    uz_ikpu_code = fields.Char(
        "MXIK / IKPU code", size=17,
        help="17-digit product classifier code (tasnif.soliq.uz) printed on the fiscal receipt.",
    )
    uz_package_code = fields.Char("Package code", help="Package (unit) code from the same classifier.")
