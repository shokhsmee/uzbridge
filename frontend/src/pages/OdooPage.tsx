import { useState } from 'react'
import type { Me } from '../App'
import { Card, PageHeader } from '../components/ui'
import { useT } from '../lib/i18n'
import { EventsLog, HooksCard, KeysCard, Tabs } from './IntegrationLogs'
import { OdooVariablesCard } from './SmsVariables'

const TABS = ['connect', 'keywords', 'payment', 'sms'] as const

export default function OdooPage({ me }: { me: Me }) {
  const { t } = useT()
  const canManage = me.role !== 'member'
  const [tab, setTab] = useState<(typeof TABS)[number]>('connect')
  return (
    <>
      <PageHeader title="Odoo" lede={t('odoo.lede')} logo="/brands/odoo.svg" />
      <Tabs tabs={TABS} value={tab} onChange={setTab} label={(k) => t(`int.tab.${k}`)} />
      {tab === 'connect' && (
        <div className="grid gap-5">
          <Card className="p-5 grid gap-3">
            <ol className="grid gap-3 text-sm list-decimal pl-5">
              <li>
                {t('odoo.s1')}{' '}
                <a className="text-accent font-medium" href="/uzbridge-odoo.zip" download>
                  uzbridge-odoo.zip ↓
                </a>{' '}
                <span className="text-muted">(Odoo 19 · Community &amp; Enterprise)</span>
              </li>
              <li>{t('odoo.s2')}</li>
              <li>{t('odoo.s3')}</li>
              <li>{t('odoo.s4')}</li>
              <li>{t('odoo.s5')}</li>
            </ol>
          </Card>
          <KeysCard integration="odoo" canManage={canManage} defaultName="Odoo" />
          <HooksCard integration="odoo" canManage={canManage} />
        </div>
      )}
      {tab === 'keywords' && <OdooVariablesCard canManage={canManage} />}
      {tab === 'payment' && <EventsLog integration="odoo" kind="payment" />}
      {tab === 'sms' && <EventsLog integration="odoo" kind="sms" />}
    </>
  )
}
