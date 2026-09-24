import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { Me } from '../App'
import { Button, Card, ErrorNote, Field, Input, PageHeader, Pill, Toggle } from '../components/ui'
import { get, post, put, soum, when } from '../lib/api'
import { useT, type Key } from '../lib/i18n'
import { Tabs } from './IntegrationLogs'

type EntityType = 'legal' | 'sole' | 'person'
type Profile = {
  entity_type: EntityType | ''
  legal_name: string
  tin: string
  pinfl: string
  legal_address: string
  director: string
  contact_phone: string
  bank_name: string
  bank_mfo: string
  bank_account: string
  oked: string
  complete: boolean
  missing: string[]
  required: Record<EntityType, string[]>
}
export type Billing = {
  state: 'inactive' | 'active' | 'grace' | 'paused' | 'platform' | 'exempt'
  balance_tiyin: number
  period_start: string | null
  period_end: string | null
  grace_until: string | null
  units: { payment: number; sms: number }
  monthly_fee_tiyin: number
  lines: { kind: 'payment' | 'sms'; units: number; first_tiyin: number; extra_tiyin: number; total_tiyin: number }[]
}
type Entry = { id: number; kind: string; amount_tiyin: number; balance_after: number; description: string; created_at: string }

const TABS = ['profile', 'balance', 'tariff', 'security'] as const
const FIELDS: { key: keyof Profile; label: Key; digits?: number }[] = [
  { key: 'legal_name', label: 'cab.legal_name' },
  { key: 'tin', label: 'cab.tin', digits: 9 },
  { key: 'pinfl', label: 'cab.pinfl', digits: 14 },
  { key: 'director', label: 'cab.director' },
  { key: 'legal_address', label: 'cab.address' },
  { key: 'contact_phone', label: 'cab.phone' },
  { key: 'bank_name', label: 'cab.bank' },
  { key: 'bank_mfo', label: 'cab.mfo', digits: 5 },
  { key: 'bank_account', label: 'cab.account', digits: 20 },
  { key: 'oked', label: 'cab.oked' },
]

export default function CabinetPage({ me }: { me: Me }) {
  const { t } = useT()
  const [tab, setTab] = useState<(typeof TABS)[number]>(() => {
    const h = window.location.hash.slice(1)
    return (TABS as readonly string[]).includes(h) ? (h as (typeof TABS)[number]) : 'profile'
  })
  const canManage = me.role !== 'member'
  return (
    <>
      <PageHeader title={t('cab.title')} lede={t('cab.lede')} />
      <Tabs tabs={TABS} value={tab} onChange={setTab} label={(k) => t(`cab.tab.${k}`)} />
      {tab === 'profile' && <ProfileTab canManage={canManage} />}
      {tab === 'balance' && <BalanceTab canManage={canManage} />}
      {tab === 'tariff' && <TariffTab />}
      {tab === 'security' && <SecurityTab canManage={canManage} />}
    </>
  )
}

function ProfileTab({ canManage }: { canManage: boolean }) {
  const { t } = useT()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['profile'], queryFn: () => get<Profile>('/billing/profile') })
  if (!q.data) return null
  return <ProfileForm initial={q.data} canManage={canManage} onSaved={(p) => qc.setQueryData(['profile'], p)} t={t} />
}

function ProfileForm({ initial, canManage, onSaved, t }: { initial: Profile; canManage: boolean; onSaved: (p: Profile) => void; t: (k: Key) => string }) {
  const [p, setP] = useState(initial)
  const [saved, setSaved] = useState(false)
  const save = useMutation({
    mutationFn: () => put<Profile>('/billing/profile', p),
    onSuccess: (d) => {
      setP(d)
      onSaved(d)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    },
  })
  const type = p.entity_type
  const required = type ? p.required[type] : []
  const shown = FIELDS.filter((f) => !type || required.includes(f.key as string) || f.key === 'oked' || (type === 'sole' && f.key === 'tin'))
  return (
    <Card className="p-5 grid gap-5">
      {initial.complete ? (
        <p className="rounded-lg bg-ok-soft text-ok text-sm px-3 py-2">✓ {t('cab.complete')}</p>
      ) : (
        <p className="rounded-lg bg-warn-soft text-warn text-sm px-3 py-2">{t('cab.incomplete')}</p>
      )}
      <div className="grid gap-2">
        <p className="text-sm font-medium">{t('cab.type')}</p>
        <div className="flex flex-wrap gap-2">
          {(['legal', 'sole', 'person'] as const).map((k) => (
            <button
              key={k}
              type="button"
              disabled={!canManage}
              onClick={() => setP({ ...p, entity_type: k })}
              className={`rounded-lg border px-4 py-2.5 text-sm text-left ${type === k ? 'border-accent bg-accent-soft text-accent-ink' : 'border-line bg-surface hover:border-accent'}`}
            >
              <span className="font-medium block">{t(`cab.type.${k}`)}</span>
              <span className="text-xs text-muted">{t(`cab.type.${k}.hint`)}</span>
            </button>
          ))}
        </div>
      </div>
      {type && (
        <div className="grid sm:grid-cols-2 gap-4">
          {shown.map((f) => (
            <Field key={f.key} label={`${t(f.label)}${required.includes(f.key as string) ? ' *' : ''}`} hint={f.digits ? `${f.digits} ${t('cab.digits')}` : undefined}>
              <Input
                id={`cab-${f.key}`}
                value={(p[f.key] as string) ?? ''}
                disabled={!canManage}
                inputMode={f.digits ? 'numeric' : undefined}
                maxLength={f.digits}
                className={f.digits ? 'font-mono' : ''}
                onChange={(e) => setP({ ...p, [f.key]: f.digits ? e.target.value.replace(/\D/g, '') : e.target.value })}
              />
            </Field>
          ))}
        </div>
      )}
      <ErrorNote error={save.error} />
      <div className="flex items-center gap-3">
        <Button busy={save.isPending} disabled={!canManage || !type} onClick={() => save.mutate()}>
          {t('amo.save')}
        </Button>
        {saved && <span className="text-sm text-ok">✓ {t('amo.saved')}</span>}
      </div>
    </Card>
  )
}

function BalanceTab({ canManage }: { canManage: boolean }) {
  const { t } = useT()
  const s = useQuery({ queryKey: ['billing'], queryFn: () => get<Billing>('/billing/summary') })
  const ledger = useQuery({ queryKey: ['ledger'], queryFn: () => get<Entry[]>('/billing/ledger') })
  const [amount, setAmount] = useState('')
  const topup = useMutation({
    mutationFn: () => post<{ url: string }>('/billing/topup', { amount: Number(amount.replace(/\D/g, '')) }),
    onSuccess: (d) => {
      window.location.href = d.url
    },
  })
  const b = s.data
  return (
    <div className="grid gap-5">
      <div className="grid gap-4 sm:grid-cols-3">
        <Card className="p-5">
          <p className="text-xs uppercase tracking-wider text-muted">{t('cab.balance')}</p>
          <p className={`mt-2 text-2xl font-semibold font-mono tabular ${b && b.balance_tiyin < 0 ? 'text-bad' : ''}`}>
            <span className="whitespace-nowrap">{b ? soum(b.balance_tiyin) : '—'}</span> <span className="text-sm text-muted font-sans font-normal">soʻm</span>
          </p>
        </Card>
        <Card className="p-5">
          <p className="text-xs uppercase tracking-wider text-muted">{t('cab.monthly')}</p>
          <p className="mt-2 text-2xl font-semibold font-mono tabular">
            <span className="whitespace-nowrap">{b ? soum(b.monthly_fee_tiyin) : '—'}</span> <span className="text-sm text-muted font-sans font-normal">soʻm</span>
          </p>
        </Card>
        <Card className="p-5">
          <p className="text-xs uppercase tracking-wider text-muted">{t('cab.next')}</p>
          <p className="mt-2 text-lg font-semibold">{b?.period_end ? when(b.period_end) : '—'}</p>
          {b && <StatePill state={b.state} />}
        </Card>
      </div>
      <Card className="p-5 grid gap-3">
        <h2 className="font-semibold">{t('cab.topup')}</h2>
        <div className="grid sm:grid-cols-[240px_auto] gap-2 items-end">
          <Field label={t('pay.amount')}>
            <Input id="topup-amount" inputMode="numeric" className="font-mono" placeholder="500 000" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </Field>
          <Button busy={topup.isPending} disabled={!canManage || !amount} onClick={() => topup.mutate()}>
            {t('cab.topup_btn')} → Payme · Click
          </Button>
        </div>
        <div className="flex flex-wrap gap-2">
          {[500_000, 800_000, 1_000_000, 2_000_000].map((v) => (
            <button key={v} className="rounded-full border border-line px-3 py-1 text-xs font-mono hover:border-accent" onClick={() => setAmount(String(v))}>
              {soum(v * 100)}
            </button>
          ))}
        </div>
        <ErrorNote error={topup.error} />
      </Card>
      <Card className="overflow-x-auto">
        <table className="w-full text-sm min-w-[600px]">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-muted border-b border-line">
              <th className="px-4 py-3 font-medium">{t('sms.when')}</th>
              <th className="px-4 py-3 font-medium">{t('pay.description')}</th>
              <th className="px-4 py-3 font-medium text-right">{t('pay.amount')}</th>
              <th className="px-4 py-3 font-medium text-right">{t('cab.balance')}</th>
            </tr>
          </thead>
          <tbody>
            {ledger.data?.map((e) => (
              <tr key={e.id} className="border-b border-line last:border-0">
                <td className="px-4 py-2.5 text-xs text-muted whitespace-nowrap">{when(e.created_at)}</td>
                <td className="px-4 py-2.5">{e.description}</td>
                <td className={`px-4 py-2.5 text-right font-mono tabular ${e.amount_tiyin < 0 ? 'text-bad' : 'text-ok'}`}>
                  {e.amount_tiyin > 0 ? '+' : '−'}
                  {soum(Math.abs(e.amount_tiyin))}
                </td>
                <td className="px-4 py-2.5 text-right font-mono tabular text-muted">{soum(e.balance_after)}</td>
              </tr>
            ))}
            {ledger.data && ledger.data.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-muted">
                  {t('cab.no_ledger')}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  )
}

export function StatePill({ state }: { state: Billing['state'] }) {
  const { t } = useT()
  const tone = { active: 'active', grace: 'pending', paused: 'error', inactive: 'neutral', platform: 'accent', exempt: 'accent' } as const
  return <Pill tone={tone[state] ?? 'neutral'}>{t(`cab.state.${state}`)}</Pill>
}

function TariffTab() {
  const { t } = useT()
  const s = useQuery({ queryKey: ['billing'], queryFn: () => get<Billing>('/billing/summary') })
  const b = s.data
  if (!b) return null
  return (
    <div className="grid gap-5">
      <div className="grid gap-4 sm:grid-cols-3">
        {([
          { k: 'payment', first: 500_000, extra: 200_000 },
          { k: 'sms', first: 300_000, extra: 100_000 },
          { k: 'free', first: 0, extra: 0 },
        ] as const).map((p) => (
          <Card key={p.k} className="p-5 grid gap-2">
            <p className="font-semibold">{t(`cab.plan.${p.k}`)}</p>
            {p.k === 'free' ? (
              <p className="text-2xl font-semibold font-mono">0 <span className="text-sm text-muted font-sans font-normal">soʻm</span></p>
            ) : (
              <>
                <p className="text-2xl font-semibold font-mono tabular">
                  {soum(p.first * 100)} <span className="text-sm text-muted font-sans font-normal">soʻm / 30 kun</span>
                </p>
                <p className="text-sm text-muted">
                  + {soum(p.extra * 100)} soʻm {t('cab.each_extra')}
                </p>
              </>
            )}
            <p className="text-xs text-muted">{t(`cab.plan.${p.k}.hint`)}</p>
          </Card>
        ))}
      </div>
      <Card className="p-5 grid gap-3">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">{t('cab.your_plan')}</h2>
          <StatePill state={b.state} />
        </div>
        {b.lines.map((l) => (
          <div key={l.kind} className="flex justify-between text-sm border-b border-line pb-2">
            <span>
              {t(`cab.plan.${l.kind}`)} × {l.units}
            </span>
            <span className="font-mono tabular">{soum(l.total_tiyin)} soʻm</span>
          </div>
        ))}
        <div className="flex justify-between font-semibold">
          <span>{t('cab.monthly')}</span>
          <span className="font-mono tabular">{soum(b.monthly_fee_tiyin)} soʻm</span>
        </div>
        <p className="text-xs text-muted">{t('cab.rules')}</p>
      </Card>
    </div>
  )
}

/** Shown on every page when the subscription needs money. */
export function BillingBanner() {
  const { t } = useT()
  const s = useQuery({ queryKey: ['billing'], queryFn: () => get<Billing>('/billing/summary'), refetchInterval: 300000 })
  const b = s.data
  if (!b || (b.state !== 'grace' && b.state !== 'paused')) return null
  return (
    <Link to="/cabinet#balance" className={`block mb-6 rounded-xl px-4 py-3 text-sm ${b.state === 'paused' ? 'bg-bad-soft text-bad' : 'bg-warn-soft text-warn'}`}>
      {b.state === 'paused' ? t('cab.banner_paused') : `${t('cab.banner_grace')} ${when(b.grace_until)}.`} <strong>{t('cab.topup_btn')} →</strong>
    </Link>
  )
}

type Sess = { id: number; user: string; ip: string | null; user_agent: string; created_at: string; last_seen: string; current: boolean }
type Cb = { id: number; source: string; path: string; ip: string | null; status_code: number; ok: boolean; blocked: boolean; note: string; created_at: string }

function device(ua: string) {
  const os = /iPhone|iPad/.test(ua) ? 'iOS' : /Android/.test(ua) ? 'Android' : /Mac OS/.test(ua) ? 'macOS' : /Windows/.test(ua) ? 'Windows' : /Linux/.test(ua) ? 'Linux' : ''
  const br = /Edg\//.test(ua) ? 'Edge' : /Chrome\//.test(ua) ? 'Chrome' : /Firefox\//.test(ua) ? 'Firefox' : /Safari\//.test(ua) ? 'Safari' : ''
  return [br, os].filter(Boolean).join(' · ') || ua.slice(0, 40) || '—'
}

function SecurityTab({ canManage }: { canManage: boolean }) {
  const { t } = useT()
  const qc = useQueryClient()
  const s = useQuery({ queryKey: ['sessions'], queryFn: () => get<{ single_session: boolean; sessions: Sess[] }>('/auth/sessions') })
  const [source, setSource] = useState('')
  const [failed, setFailed] = useState(false)
  const cb = useQuery({
    queryKey: ['callbacks', source, failed],
    queryFn: () => get<{ stats_24h: { total: number; failed: number; blocked: number }; items: Cb[] }>(`/audit/callbacks?source=${source}&failed=${failed}`),
    refetchInterval: 20000,
  })
  const single = useMutation({
    mutationFn: (v: boolean) => put('/auth/security', { single_session: v }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sessions'] }),
  })
  const end = useMutation({
    mutationFn: (id: number) => post(`/auth/sessions/${id}/end`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sessions'] }),
  })
  return (
    <div className="grid gap-5">
      <Card className="p-5 grid gap-4">
        <h2 className="font-semibold">{t('sec.sessions')}</h2>
        {s.data && (
          <Toggle id="single-session" checked={s.data.single_session} onChange={(v) => canManage && single.mutate(v)} label={t('sec.single')} />
        )}
        <p className="text-xs text-muted">{t('sec.single_hint')}</p>
        <ul className="grid gap-2">
          {s.data?.sessions.map((x) => (
            <li key={x.id} className="flex flex-wrap items-center gap-3 rounded-lg border border-line px-3 py-2.5 text-sm">
              <span className="font-medium">{device(x.user_agent)}</span>
              {x.current && <Pill tone="accent">{t('sec.this')}</Pill>}
              <span className="text-xs text-muted">{x.user}</span>
              <span className="font-mono text-xs text-muted">{x.ip ?? '—'}</span>
              <span className="text-xs text-muted">{t('sec.seen')}: {when(x.last_seen)}</span>
              {!x.current && (
                <button className="ml-auto text-xs text-bad" onClick={() => end.mutate(x.id)}>
                  {t('sec.end')}
                </button>
              )}
            </li>
          ))}
        </ul>
        <ErrorNote error={single.error || end.error} />
      </Card>

      <Card className="overflow-x-auto">
        <div className="p-5 grid gap-3">
          <h2 className="font-semibold">{t('sec.callbacks')}</h2>
          <p className="text-sm text-muted">{t('sec.callbacks_hint')}</p>
          {cb.data && (
            <div className="flex flex-wrap gap-2 text-sm">
              <Pill tone="neutral">24h: {cb.data.stats_24h.total}</Pill>
              <Pill tone={cb.data.stats_24h.failed ? 'refunded' : 'neutral'}>{t('sec.failed')}: {cb.data.stats_24h.failed}</Pill>
              <Pill tone={cb.data.stats_24h.blocked ? 'error' : 'neutral'}>{t('sec.blocked')}: {cb.data.stats_24h.blocked}</Pill>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <select id="cb-source" className="h-9 rounded-lg border border-line bg-surface px-2 text-sm" value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="">{t('pay.all')}</option>
              {['payme', 'click', 'uzum', 'eskiz', 'playmobile', 'amocrm'].map((x) => (
                <option key={x} value={x}>
                  {x}
                </option>
              ))}
            </select>
            <Toggle id="cb-failed" checked={failed} onChange={setFailed} label={t('sec.only_failed')} />
          </div>
        </div>
        <table className="w-full text-sm min-w-[680px]">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-muted border-y border-line">
              <th className="px-4 py-3 font-medium">{t('sms.when')}</th>
              <th className="px-4 py-3 font-medium">{t('sms.source')}</th>
              <th className="px-4 py-3 font-medium">IP</th>
              <th className="px-4 py-3 font-medium">{t('ev.what')}</th>
              <th className="px-4 py-3 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {cb.data?.items.map((c) => (
              <tr key={c.id} className="border-b border-line last:border-0">
                <td className="px-4 py-2.5 text-xs text-muted whitespace-nowrap">{when(c.created_at)}</td>
                <td className="px-4 py-2.5 font-mono text-xs">{c.source}</td>
                <td className="px-4 py-2.5 font-mono text-xs">{c.ip ?? '—'}</td>
                <td className="px-4 py-2.5 text-xs">{c.note || t('ev.ok')}</td>
                <td className="px-4 py-2.5">
                  <Pill tone={c.blocked ? 'error' : c.ok ? 'paid' : 'refunded'}>
                    {c.blocked ? t('sec.blocked') : c.ok ? 'OK' : t('sec.failed')} · {c.status_code}
                  </Pill>
                </td>
              </tr>
            ))}
            {cb.data && cb.data.items.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-muted">
                  {t('dev.no_deliveries')}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  )
}
