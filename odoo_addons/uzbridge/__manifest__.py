{
    'name': "uzbridge: Payme, Click, Uzum & Eskiz/Playmobile SMS",
    'version': '19.0.1.1.0',
    'category': 'Accounting/Payment Providers',
    'summary': "Uzbek payments (Payme, Click, Uzum Bank) with fiscal receipts, and SMS via Eskiz or Playmobile.",
    'description': """
Connects Odoo to uzbridge (https://uzbridge.shokhsmee.uz).

- Payment provider "Payme, Click, Uzum" for portal invoices, eCommerce and payment links.
  The customer picks the wallet; the fiscal receipt is built from the invoice lines
  (MXIK/IKPU code per product).
- Odoo SMS (contacts, marketing, automations, reminders) sent through the company's
  own Eskiz or Playmobile account instead of Odoo IAP.
- Works on Community and Enterprise; depends only on Community modules.
""",
    'author': "uzbridge",
    'website': "https://uzbridge.shokhsmee.uz",
    'license': 'LGPL-3',
    'depends': ['payment', 'account_payment', 'sms'],
    'data': [
        'security/ir.model.access.csv',
        'views/payment_uzbridge_templates.xml',
        'views/payment_provider_views.xml',
        'views/sms_composer_views.xml',
        'views/res_config_settings_views.xml',
        'views/product_template_views.xml',
        'views/account_move_views.xml',
        'data/ir_cron_data.xml',
        'data/payment_method_data.xml',
        'data/payment_provider_data.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'application': False,
}
