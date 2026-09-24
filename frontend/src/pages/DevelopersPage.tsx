import { useState } from 'react'
import type { Me } from '../App'
import { Card, CopyField, PageHeader } from '../components/ui'
import { useT } from '../lib/i18n'
import { EventsLog, HooksCard, KeysCard, Tabs } from './IntegrationLogs'

const TABS = ['connect', 'payment', 'sms'] as const

/** Custom systems (websites, 1C, n8n) talking to /api/v1; Odoo has its own page. */
export default function DevelopersPage({ me }: { me: Me }) {
  const { t } = useT()
  const canManage = me.role !== 'member'
  const [tab, setTab] = useState<(typeof TABS)[number]>('connect')
  return (
    <>
      <PageHeader title={t('dev.title')} lede={t('dev.lede')} />
      <Tabs tabs={TABS} value={tab} onChange={setTab} label={(k) => t(`int.tab.${k}`)} />
      {tab === 'connect' && (
        <div className="grid gap-5">
          <Card className="p-5 grid gap-2">
            <p className="text-sm font-medium">API</p>
            <CopyField value={`${window.location.origin}/api/v1`} />
            <p className="text-xs text-muted">{t('dev.api_hint')}</p>
          </Card>
          <KeysCard integration="api" canManage={canManage} defaultName="" />
          <HooksCard integration="api" canManage={canManage} />
        </div>
      )}
      {tab === 'payment' && <EventsLog integration="api" kind="payment" />}
      {tab === 'sms' && <EventsLog integration="api" kind="sms" />}
    </>
  )
}
