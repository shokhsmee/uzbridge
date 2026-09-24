import json
import logging

from werkzeug.exceptions import Forbidden

from odoo import http
from odoo.http import request

from .. import const
from ..tools.uzbridge_api import UzbridgeError, verify_signature

_logger = logging.getLogger(__name__)


class UzbridgeController(http.Controller):

    @http.route(const.RETURN_ROUTE, type='http', methods=['GET'], auth='public')
    def uzbridge_return(self, reference=None, **_kw):
        """The customer comes back from the uzbridge pay page: re-read the status from uzbridge."""
        tx = request.env['payment.transaction'].sudo().search(
            [('reference', '=', reference or ''), ('provider_code', '=', 'uzbridge')], limit=1
        )
        if tx and tx.provider_reference and tx.state in ('draft', 'pending'):
            try:
                tx._process('uzbridge', tx._uzbridge_fetch())
            except UzbridgeError as e:
                _logger.warning("uzbridge status check failed for %s: %s", tx.reference, e)
        return request.redirect('/payment/status')

    @http.route(const.WEBHOOK_ROUTE, type='http', methods=['POST'], auth='public', csrf=False)
    def uzbridge_webhook(self):
        body = request.httprequest.get_data()
        try:
            event = json.loads(body)
        except ValueError:
            return request.make_json_response({'error': 'bad json'}, status=400)
        data = event.get('data') or {}
        companies = request.env['res.company'].sudo().search([('uzbridge_webhook_secret', '!=', False)])
        signature = request.httprequest.headers.get('X-Uzbridge-Signature', '')
        company = next((c for c in companies if verify_signature(c.uzbridge_webhook_secret, body, signature)), None)
        if company is None:
            _logger.warning("uzbridge webhook with a bad signature (event %s)", event.get('type'))
            raise Forbidden()

        kind = event.get('type', '')
        if kind.startswith('invoice.'):
            self._invoice_event(company, kind, data)
        elif kind == 'sms.status':
            self._sms_event(data)
        return request.make_json_response({'ok': True})

    def _invoice_event(self, company, kind, data):
        Tx = request.env['payment.transaction'].sudo()
        tx = Tx.search([('reference', '=', data.get('reference') or ''), ('provider_code', '=', 'uzbridge'),
                        ('company_id', '=', company.id)], limit=1)
        if not tx:
            return
        if kind in ('invoice.paid', 'invoice.cancelled'):
            tx._process('uzbridge', data)
            if tx.state == 'done' and not tx.is_post_processed:
                # Book the payment and reconcile the invoice now, rather than when the
                # customer lands on /payment/status or the post-processing cron runs.
                tx._post_process()
        elif kind == 'invoice.refunded':
            # Refund made in uzbridge / the Payme cabinet: close the pending refund tx if there is one.
            refund = Tx.search([('source_transaction_id', '=', tx.id), ('operation', '=', 'refund'),
                                ('state', 'in', ('draft', 'pending'))], limit=1)
            if refund:
                refund._set_done(state_message="Refunded through uzbridge")
            else:
                tx._log_message_on_linked_documents(f"uzbridge: payment {data.get('number')} was refunded.")

    def _sms_event(self, data):
        tracker = request.env['sms.tracker'].sudo().search([('sms_uuid', '=', data.get('ref') or '')], limit=1)
        if not tracker:
            return
        status = data.get('status')
        if status == 'delivered':
            tracker._action_update_from_sms_state('sent')
        elif status == 'failed':
            tracker._action_update_from_provider_error('sms_not_delivered')
        request.env['sms.sms'].sudo().search([('uuid', '=', data.get('ref'))]).to_delete = True
