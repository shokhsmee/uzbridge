import hashlib
import hmac
import json
import time
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.payment.tests.common import PaymentCommon
from odoo.addons.payment.tests.http_common import PaymentHttpCommon

SECRET = 'whsec_test'


def signed(body: bytes):
    ts = int(time.time())
    mac = hmac.new(SECRET.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


class UzbridgeCommon(PaymentCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uzs = cls.env.ref('base.UZS')
        cls.uzs.active = True
        cls.company.write({'uzbridge_api_key': 'uzb_test', 'uzbridge_webhook_secret': SECRET, 'currency_id': cls.uzs.id})
        cls.provider = cls._prepare_provider('uzbridge')
        cls.currency = cls.uzs
        cls.amount = 150000.0


@tagged('post_install', '-at_install')
class TestUzbridgeTransaction(UzbridgeCommon):

    def _fake(self, captured):
        def request(_self, method, path, json=None):
            captured.append((method, path, json))
            if path == '/invoices':
                return {'id': 'inv-uuid', 'url': 'https://uzbridge.test/p/inv-uuid/', 'status': 'pending'}
            return {}
        return request

    def test_redirect_creates_uzbridge_invoice(self):
        tx = self._create_transaction('redirect')
        calls = []
        with patch('odoo.addons.uzbridge.tools.uzbridge_api.UzbridgeClient.request', self._fake(calls)):
            values = tx._get_specific_rendering_values(None)
        self.assertEqual(values['api_url'], 'https://uzbridge.test/p/inv-uuid/')
        method, path, body = calls[0]
        self.assertEqual((method, path, body['amount_tiyin'], body['reference'], body['source']),
                         ('POST', '/invoices', 15000000, tx.reference, 'odoo'))
        self.assertIn('/payment/uzbridge/return?reference=', body['return_url'])
        self.assertEqual(tx.provider_reference, 'inv-uuid')

    def test_paid_data_sets_done(self):
        tx = self._create_transaction('redirect', provider_reference='inv-uuid')
        tx._process('uzbridge', {'reference': tx.reference, 'id': 'inv-uuid', 'status': 'paid',
                                 'amount_tiyin': 15000000, 'currency': 'UZS', 'paid_via': 'payme'})
        self.assertEqual(tx.state, 'done')

    @mute_logger('odoo.addons.payment.models.payment_transaction')
    def test_amount_mismatch_is_error(self):
        tx = self._create_transaction('redirect')
        tx._process('uzbridge', {'reference': tx.reference, 'status': 'paid', 'amount_tiyin': 100, 'currency': 'UZS'})
        self.assertEqual(tx.state, 'error')

    def test_only_uzs(self):
        self.assertEqual(self.provider._get_supported_currencies().mapped('name'), ['UZS'])


@tagged('post_install', '-at_install')
class TestUzbridgeWebhook(UzbridgeCommon, PaymentHttpCommon):

    def _post(self, event, signature=None):
        body = json.dumps(event).encode()
        return self.url_open('/uzbridge/webhook', data=body, headers={
            'Content-Type': 'application/json', 'X-Uzbridge-Signature': signature or signed(body)})

    @mute_logger('odoo.addons.uzbridge.controllers.main')
    def test_webhook_signature_and_paid(self):
        tx = self._create_transaction('redirect', provider_reference='inv-uuid')
        event = {'type': 'invoice.paid', 'data': {'reference': tx.reference, 'id': 'inv-uuid', 'status': 'paid',
                                                   'amount_tiyin': 15000000, 'currency': 'UZS', 'paid_via': 'click'}}
        self.assertEqual(self._post(event, signature='t=1,v1=bad').status_code, 403)
        self.assertEqual(tx.state, 'draft')
        self.assertEqual(self._post(event).status_code, 200)
        self.assertEqual(tx.state, 'done')


@tagged('post_install', '-at_install')
class TestUzbridgeSms(UzbridgeCommon):

    def test_sms_goes_through_uzbridge(self):
        self.company.uzbridge_sms = True
        partner = self.env['res.partner'].create({'name': 'Aziz', 'phone': '+998901234567'})
        sent = []

        def request(_self, method, path, json=None):
            sent.append(json)
            return {'messages': [{'ref': m['ref'], 'status': 'queued'} for m in json['messages']]}

        with patch('odoo.addons.uzbridge.tools.uzbridge_api.UzbridgeClient.request', request):
            sms = self.env['sms.sms'].create({'number': '+998901234567', 'body': 'Salom', 'partner_id': partner.id})
            sms.send()
        self.assertEqual(sent[0]['messages'][0]['text'], 'Salom')
        self.assertEqual(sent[0]['messages'][0]['ref'], sms.uuid)
        self.assertEqual(sms.state, 'pending')


@tagged('post_install', '-at_install')
class TestUzbridgeSmsTemplates(UzbridgeCommon):

    def test_sync_and_composer_fills_text(self):
        self.company.uzbridge_sms = True

        def request(_self, method, path, json=None):
            if path == '/sms/variables':
                return [{'key': 'telefon', 'path': 'phone'}, {'key': 'kompaniya', 'path': 'parent_id.name'}]
            return [
                {'id': 7, 'text': '{company}: salom {name}! {telefon} {kompaniya}{yoq}'},
                {'id': 8, 'text': 'Ikkinchi'},
            ]

        with patch('odoo.addons.uzbridge.tools.uzbridge_api.UzbridgeClient.request', request):
            self.assertEqual(self.env['uzbridge.sms.template']._uzbridge_sync(self.company), 2)
        tpl = self.env['uzbridge.sms.template'].search([('uzbridge_id', '=', 7)])
        partner = self.env['res.partner'].create({'name': 'Aziz', 'phone': '+998901234567'})
        composer = self.env['sms.composer'].with_context(
            active_model='res.partner', active_id=partner.id, default_composition_mode='comment',
        ).new({'res_model': 'res.partner', 'res_id': partner.id})
        composer.uzbridge_template_id = tpl
        composer._onchange_uzbridge_template_id()
        # Own keywords come from the record's fields; an empty relation gives "",
        # an unknown keyword stays as typed.
        self.assertEqual(composer.body, f"{self.company.name}: salom Aziz! +998901234567 {{yoq}}")

        # Templates that disappear from uzbridge (no longer approved) are archived.
        with patch('odoo.addons.uzbridge.tools.uzbridge_api.UzbridgeClient.request', lambda _s, m, path, json=None: [] if path == '/sms/variables' else [{'id': 8, 'text': 'Ikkinchi'}]):
            self.env['uzbridge.sms.template']._uzbridge_sync(self.company)
        self.assertFalse(tpl.active)
