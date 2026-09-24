{
    'name': 'uzbridge for Point of Sale',
    'version': '19.0.1.0.0',
    'category': 'Sales/Point of Sale',
    'summary': 'Payme · Click · Uzum by QR at the till, plus payment links and SMS from the POS',
    'description': """
Bridges uzbridge and the Point of Sale:

* QR payment: a POS payment method of type "Online" with the uzbridge provider
  shows a QR on the till and on the customer display; the customer scans it,
  pays with Payme, Click or Uzum Bank, and the order turns paid on both screens.
* Optional "Payment link" and "Send SMS" buttons on the payment screen, with the
  approved SMS templates and {keywords} ({link}, {amount}, {number}, {name}...).
""",
    'author': 'uzbridge',
    'website': 'https://uzbridge.shokhsmee.uz',
    'depends': ['uzbridge', 'pos_online_payment'],
    'data': [
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'uzbridge_pos/static/src/**/*',
        ],
        'web.assets_tests': [
            'uzbridge_pos/static/tests/tours/**/*',
        ],
    },
    'auto_install': True,
    'license': 'LGPL-3',
}
