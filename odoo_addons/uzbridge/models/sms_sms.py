from collections import defaultdict

from odoo import models


class SmsSms(models.Model):
    _inherit = 'sms.sms'

    def _split_by_api(self):
        # Company-dependent transport, like sms_twilio: uzbridge companies skip IAP.
        by_company = defaultdict(lambda: self.env['sms.sms'])
        rest = self.browse()
        for sms in self:
            by_company[sms._get_sms_company()] += sms
        for company, company_sms in by_company.items():
            if company.uzbridge_sms:
                sms_api = company._get_sms_api_class()(self.env)
                sms_api._set_company(company)
                yield sms_api, company_sms
            else:
                rest += company_sms
        if rest:
            yield from super(SmsSms, rest)._split_by_api()
