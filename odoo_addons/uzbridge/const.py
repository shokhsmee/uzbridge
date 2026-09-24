DEFAULT_URL = 'https://uzbridge.shokhsmee.uz'
SUPPORTED_CURRENCIES = ('UZS',)
DEFAULT_PAYMENT_METHOD_CODES = {'uzbridge'}
WEBHOOK_ROUTE = '/uzbridge/webhook'
RETURN_ROUTE = '/payment/uzbridge/return'
# uzbridge invoice status -> transaction state
STATUS_MAPPING = {
    'pending': 'pending',
    'paid': 'done',
    'cancelled': 'cancel',
    'refunded': 'done',  # the payment itself happened; the refund is its own transaction
}
