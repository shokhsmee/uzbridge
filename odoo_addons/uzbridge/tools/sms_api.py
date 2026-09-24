"""Odoo SMS transport through uzbridge (Eskiz / Playmobile), following sms_twilio's pattern."""

import logging

from odoo import _
from odoo.addons.sms.tools.sms_api import SmsApiBase

from .uzbridge_api import UzbridgeClient, UzbridgeError

_logger = logging.getLogger(__name__)


class SmsApiUzbridge(SmsApiBase):
    PROVIDER_TO_SMS_FAILURE_TYPE = SmsApiBase.PROVIDER_TO_SMS_FAILURE_TYPE | {
        'uzbridge_rejected': 'unknown',
    }

    def _send_sms_batch(self, messages, delivery_reports_url=False):
        """See sms/tools/sms_api.py: returns [{'uuid', 'state', 'failure_reason'}]."""
        batch = [
            {'phone': n['number'], 'text': m.get('content') or '', 'ref': n['uuid']}
            for m in messages for n in (m.get('numbers') or [])
        ]
        if not batch:
            return []
        try:
            result = UzbridgeClient(self.company or self.env.company).request('POST', '/sms', json={'messages': batch})
        except UzbridgeError as e:
            return [{'uuid': b['ref'], 'state': 'server_error', 'failure_reason': str(e)} for b in batch]
        res = []
        for row in result.get('messages', []):
            if row.get('status') in ('queued', 'sent'):
                res.append({'uuid': row['ref'], 'state': 'success', 'failure_reason': False})
            elif 'Uzbek mobile' in (row.get('error') or ''):
                res.append({'uuid': row['ref'], 'state': 'wrong_number_format', 'failure_reason': row.get('error')})
            else:
                res.append({'uuid': row['ref'], 'state': 'uzbridge_rejected',
                            'failure_reason': row.get('error') or _("uzbridge refused the message")})
        return res

    def _get_sms_api_error_messages(self):
        return {
            **super()._get_sms_api_error_messages(),
            'uzbridge_rejected': _("uzbridge / the SMS gateway refused the message."),
        }
