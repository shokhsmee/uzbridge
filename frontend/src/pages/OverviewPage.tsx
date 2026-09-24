import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Card, PageHeader } from '../components/ui'
import { get, soum } from '../lib/api'
import { useT } from '../lib/i18n'

type Overview = { crm_connected: boolean; crm_status: string; providers_ready: string[]; paid_stage_set: boolean; fiscal_ready: boolean }
type Stats = {
  created: number
  paid: number
  paid_tiyin: number
  pending_tiyin: number
  by_provider: Record<string, { count: number; tiyin: number }>
}

const PROVIDER_LABEL: Record<string, string> = { payme: 'Payme', click: 'Click', uzum: 'Uzum Bank' }

export default function OverviewPage() {
  const { t } = useT()
  const ov = useQuery({ queryKey: ['overview'], queryFn: () => get<Overview>('/integrations/overview') })
  const st = useQuery({ queryKey: ['stats'], queryFn: () => get<Stats>('/payments/stats?days=30') })

  const steps = ov.data
    ? [
        { done: ov.data.crm_connected, label: t('ov.step.crm'), to: '/integrations/amocrm' },
        { done: ov.data.providers_ready.length > 0, label: t('ov.step.providers'), to: '/providers' },
        { done: ov.data.paid_stage_set, label: t('ov.step.stage'), to: '/integrations/amocrm' },
        { done: ov.data.fiscal_ready, label: t('ov.step.fiscal'), to: '/providers' },
      ]
    : []
  const allDone = steps.length > 0 && steps.every((s) => s.done)
  const s = st.data
  const byProvider = s ? Object.entries(s.by_provider) : []
  const maxTiyin = Math.max(1, ...byProvider.map(([, v]) => v.tiyin))

  return (
    <>
      <PageHeader title={t('ov.title')} />
      {!allDone && steps.length > 0 && (
        <Card className="p-5 mb-6">
          <h2 className="font-semibold mb-3">{t('ov.setup')}</h2>
          <ol className="grid gap-2">
            {steps.map((step) => (
              <li key={step.label} className="flex items-center gap-3 text-sm">
                <span
                  className={`grid size-6 place-items-center rounded-full text-xs font-semibold ${step.done ? 'bg-ok-soft text-ok' : 'bg-ground text-muted border border-line'}`}
                >
                  {step.done ? '✓' : ''}
                </span>
                {step.done ? (
                  <span className="text-muted line-through">{step.label}</span>
                ) : (
                  <Link to={step.to} className="text-accent font-medium">
                    {step.label} →
                  </Link>
                )}
              </li>
            ))}
          </ol>
        </Card>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label={t('ov.paid30')} value={s ? soum(s.paid_tiyin) : '—'} unit="soʻm" />
        <Stat label={t('ov.pending')} value={s ? soum(s.pending_tiyin) : '—'} unit="soʻm" />
        <Stat label={t('ov.invoices')} value={s ? String(s.created) : '—'} />
        <Stat label={t('ov.conversion')} value={s && s.created ? `${Math.round((s.paid / s.created) * 100)}%` : '—'} />
      </div>
      {byProvider.length > 0 && (
        <Card className="p-5 mt-6">
          <h2 className="font-semibold mb-4">{t('ov.by_provider')}</h2>
          <div className="grid gap-3">
            {byProvider.map(([p, v]) => (
              <div key={p} className="grid grid-cols-[96px_1fr_auto] items-center gap-3 text-sm">
                <span>{PROVIDER_LABEL[p] ?? p}</span>
                <span className="h-2 rounded-full bg-ground overflow-hidden">
                  <span className="block h-full rounded-full bg-accent" style={{ width: `${(v.tiyin / maxTiyin) * 100}%` }} />
                </span>
                <span className="font-mono tabular text-xs text-muted">
                  {soum(v.tiyin)} · {v.count}
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </>
  )
}

function Stat({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <Card className="p-5">
      <p className="text-xs uppercase tracking-wider text-muted">{label}</p>
      <p className="mt-2 text-xl font-semibold tabular font-mono tracking-tight">
        <span className="whitespace-nowrap">{value}</span> {unit && <span className="text-sm text-muted font-sans font-normal">{unit}</span>}
      </p>
    </Card>
  )
}
