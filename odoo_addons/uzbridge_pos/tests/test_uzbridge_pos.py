import inspect
import unittest
from unittest.mock import patch

from odoo import Command
from odoo.tests import tagged

from odoo.addons.pos_online_payment.tests.test_frontend import TestUi

PAY_URL = 'https://uzbridge.test/p/3f2a/'
REQUEST = 'odoo.addons.uzbridge.tools.uzbridge_api.UzbridgeClient.request'


class FakeUzbridge:
    """Stands in for the uzbridge API: records what Odoo sends."""

    def __init__(self):
        self.calls = []

    def request(self, method, path, json=None):
        self.calls.append((method, path, json))
        if path == '/invoices':
            return {'id': f'inv-{len(self.calls)}', 'url': PAY_URL}
        if path == '/sms':
            return {'messages': [{'ref': m['ref'], 'id': 1, 'status': 'queued'} for m in json['messages']]}
        return []


@tagged('post_install', '-at_install')
class TestUzbridgePos(TestUi):
    """The online-payment POS setup of pos_online_payment, with uzbridge as the provider."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.write({'uzbridge_api_key': 'uzb_test', 'uzbridge_sms': True})
        cls.uzbridge = cls._prepare_provider('uzbridge', update_values={
            'company_id': cls.company.id,
            'journal_id': cls.company_data['default_journal_bank'].id,
            'is_published': True,
        })
        # The test company isn't in soʻm; let the provider take its currency.
        cls.uzbridge.available_currency_ids |= cls.company.currency_id
        cls.online_payment_method.online_payment_provider_ids = [Command.set([cls.uzbridge.id])]
        cls.pos_config.write({'uzbridge_link_enabled': True, 'uzbridge_sms_enabled': True})
        cls.letter_tray.product_tmpl_id.uz_ikpu_code = '10202001001000000'


# The inherited tours test pos_online_payment itself; here only uzbridge's part runs.
def _skipped(self):
    pass


_skipped = unittest.skip("covered by pos_online_payment")(_skipped)
for _name in [n for n in dir(TestUi) if n.startswith('test_') and inspect.isfunction(getattr(TestUi, n))]:
    setattr(TestUzbridgePos, _name, _skipped)


def _tests(cls):
    def test_one_scan_goes_straight_to_uzbridge(self):
        order = self._open_session_fake_cashier_unpaid_order()
        fake = FakeUzbridge()
        with patch(REQUEST, fake.request):
            url = order.with_user(self.pos_user).uzbridge_payment_link()
            first = self.url_open(url, allow_redirects=False)
            again = self.url_open(url, allow_redirects=False)
        self.assertEqual(first.headers['Location'], PAY_URL)
        self.assertEqual(again.headers['Location'], PAY_URL)
        invoices = [c for c in fake.calls if c[1] == '/invoices']
        self.assertEqual(len(invoices), 1, "a second scan reuses the open transaction")
        payload = invoices[0][2]
        # The receipt carries the POS lines with their MXIK codes.
        self.assertEqual(payload['items'][0]['ikpu_code'], '10202001001000000')
        self.assertEqual(sum(i['price_tiyin'] * i['count'] for i in payload['items']), payload['amount_tiyin'])

        tx = self.env['payment.transaction'].sudo().search([('pos_order_id', '=', order.id)])
        self.assertEqual(len(tx), 1)
        self.assertEqual(tx.uzbridge_pay_url, PAY_URL)
        # uzbridge's webhook marks it done and post-processes: the till sees a paid order.
        tx._set_done()
        tx._post_process()
        self.assertEqual(order.state, 'paid')
        self.assertTrue(order.payment_ids.online_account_payment_id)
        self.assertIn('paid_order', order.with_user(self.pos_user).get_and_set_online_payments_data())

    def test_send_sms_fills_keywords_and_link(self):
        order = self._open_session_fake_cashier_unpaid_order()
        tpl = self.env['uzbridge.sms.template'].create({
            'body': '{company}: {number} uchun {amount} soʻm. Toʻlov: {link} {kassir}',
            'uzbridge_id': 7,
            'company_id': self.company.id,
        })
        self.env['uzbridge.sms.variable'].create({'key': 'kassir', 'path': 'user_id.name', 'company_id': self.company.id})
        pos = order.with_user(self.pos_user)
        listed = pos.uzbridge_sms_templates()
        self.assertEqual([t['id'] for t in listed], [tpl.id])
        self.assertTrue(listed[0]['has_link'])

        fake = FakeUzbridge()
        with patch(REQUEST, fake.request):
            sent = pos.uzbridge_send_sms('+998 90 123 45 67', tpl.id)
        body = sent['body']
        self.assertIn(f"/pos/pay/{order.id}?access_token={order.access_token}", body)
        self.assertIn(order.pos_reference, body)
        self.assertIn(self.pos_user.name, body)
        self.assertNotIn('{', body)
        sms_calls = [c for c in fake.calls if c[1] == '/sms']
        self.assertEqual(sms_calls[0][2]['messages'][0]['text'], body)
        self.assertEqual(pos.uzbridge_sms_preview(tpl.id), body)

        with self.assertRaises(Exception):
            pos.uzbridge_send_sms('12', tpl.id)  # not a phone number

    def test_till_buttons_tour(self):
        """The optional buttons on the payment screen: link with QR, SMS with its template."""
        self.env['uzbridge.sms.template'].create({
            'body': '{number}: {amount} soʻm — {link}',
            'uzbridge_id': 8,
            'company_id': self.company.id,
        })
        self.pos_config.with_user(self.pos_user).open_ui()
        fake = FakeUzbridge()
        with patch(REQUEST, fake.request):
            self.start_pos_tour('UzbridgePosButtonsTour', login="pos_op_user")
        sent = [c for c in fake.calls if c[1] == '/sms']
        self.assertEqual(len(sent), 1)
        self.assertIn('/pos/pay/', sent[0][2]['messages'][0]['text'])

    cls.test_one_scan_goes_straight_to_uzbridge = test_one_scan_goes_straight_to_uzbridge
    cls.test_send_sms_fills_keywords_and_link = test_send_sms_fills_keywords_and_link
    cls.test_till_buttons_tour = test_till_buttons_tour


_tests(TestUzbridgePos)
