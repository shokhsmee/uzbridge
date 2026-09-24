import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Button, Card, CopyField, ErrorNote, Field, Input, Pill } from '../components/ui'
import { AccountPicker } from '../components/AccountPicker'
import { get, post, put, when } from '../lib/api'
import { useT } from '../lib/i18n'

export type Integration = 'odoo' | 'api'
type Key = { id: number; name: string; prefix: string; created_at: string; last_used_at: string | null; revoked: boolean; payment_accounts: number[] | null; sms_account_id: number | null }
type Hook = {
  id: number
  url: string
  label: string
  is_enabled: boolean
  last: { event: string; status_code: number | null; delivered: boolean; at: string; error: string } | null
}
type Delivery = { id: number; event: string; url: string; status_code: number | null; attempts: number; delivered: boolean; error: string; created_at: string; summary: string }

export function KeysCard({ integration, canManage, defaultName }: { integration: Integration; canManage: boolean; defaultName: string }) {
  const { t } = useT()
  const qc = useQueryClient()
  const keys = useQuery({ queryKey: ['dev-keys', integration], queryFn: () => get<Key[]>(`/developer/keys?integration=${integration}`) })
  const [name, setName] = useState(defaultName)
  const [fresh, setFresh] = useState<string | null>(null)
  const [openKey, setOpenKey] = useState<number | null>(null)
  const create = useMutation({
    mutationFn: () => post<{ key: string }>('/developer/keys', { name, integration }),
    onSuccess: (d) => {
      setFresh(d.key)
      qc.invalidateQueries({ queryKey: ['dev-keys', integration] })
    },
  })
  const revoke = useMutation({
    mutationFn: (id: number) => post(`/developer/keys/${id}/revoke`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['dev-keys', integration] }),
  })
  return (
    <Card className="p-5 grid gap-4">
      <h2 className="font-semibold">{t('dev.keys')}</h2>
      {fresh && (
        <div className="grid gap-2 rounded-lg bg-warn-soft p-4">
          <p className="text-sm font-medium text-warn">{t('dev.once')}</p>
          <CopyField value={fresh} />
        </div>
      )}
      <ul className="grid gap-2">
        {keys.data?.map((k) => (
          <li key={k.id} className="flex flex-wrap items-center gap-3 rounded-lg border border-line px-3 py-2 text-sm">
            <span className="font-medium">{k.name}</span>
            <span className="font-mono text-xs text-muted">{k.prefix}…</span>
            {k.revoked ? <Pill tone="neutral">{t('dev.revoked')}</Pill> : <Pill tone="active">{t('dev.active')}</Pill>}
            <span className="text-xs text-muted">
              {t('dev.used')}: {when(k.last_used_at)}
            </span>
            {!k.revoked && (
              <button className="ml-auto text-xs text-accent font-medium" onClick={() => setOpenKey(openKey === k.id ? null : k.id)}>
                {t('dev.key_accounts')} {openKey === k.id ? '−' : '+'}
              </button>
            )}
            {!k.revoked && canManage && (
              <button className="text-xs text-bad" onClick={() => revoke.mutate(k.id)}>
                {t('dev.revoke')}
              </button>
            )}
            {openKey === k.id && (
              <div className="basis-full border-t border-line pt-3 mt-1 grid gap-2">
                <p className="text-xs text-muted">{t('dev.key_accounts_hint')}</p>
                <AccountPicker
                  value={{ payment_accounts: k.payment_accounts, sms_account_id: k.sms_account_id }}
                  canManage={canManage}
                  onSave={(v) => put(`/developer/keys/${k.id}/accounts`, v).then(() => qc.invalidateQueries({ queryKey: ['dev-keys', integration] }))}
                />
              </div>
            )}
          </li>
        ))}
        {keys.data?.length === 0 && <li className="text-sm text-muted">—</li>}
      </ul>
      <div className="grid sm:grid-cols-[1fr_auto] gap-2 items-end">
        <Field label={t('dev.key_name')}>
          <Input id={`key-name-${integration}`} value={name} disabled={!canManage} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Button busy={create.isPending} disabled={!canManage || !name.trim()} onClick={() => create.mutate()}>
          + {t('dev.new_key')}
        </Button>
      </div>
      <ErrorNote error={create.error || revoke.error} />
    </Card>
  )
}

export function HooksCard({ integration, canManage }: { integration: Integration; canManage: boolean }) {
  const { t } = useT()
  const qc = useQueryClient()
  const hooks = useQuery({ queryKey: ['dev-hooks', integration], queryFn: () => get<Hook[]>(`/developer/webhooks?integration=${integration}`) })
  const toggle = useMutation({
    mutationFn: (id: number) => post(`/developer/webhooks/${id}/toggle`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['dev-hooks', integration] }),
  })
  return (
    <Card className="p-5 grid gap-3">
      <h2 className="font-semibold">{t('dev.hooks')}</h2>
      <p className="text-sm text-muted">{integration === 'odoo' ? t('odoo.hook_hint') : t('dev.hooks_hint')}</p>
      {hooks.data?.length === 0 && <p className="text-sm text-warn">{integration === 'odoo' ? t('odoo.no_hook') : '—'}</p>}
      {hooks.data?.map((h) => (
        <div key={h.id} className="rounded-lg border border-line px-3 py-2.5 grid gap-1 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs break-all">{h.url}</span>
            <Pill tone={h.is_enabled ? 'active' : 'neutral'}>{h.is_enabled ? t('dev.active') : t('dev.off')}</Pill>
            {canManage && (
              <button className="ml-auto text-xs text-muted hover:text-ink" onClick={() => toggle.mutate(h.id)}>
                {h.is_enabled ? t('dev.disable') : t('dev.enable')}
              </button>
            )}
          </div>
          {h.last && (
            <span className={`text-xs ${h.last.delivered ? 'text-ok' : 'text-bad'}`}>
              {t('dev.last')}: {h.last.event} · HTTP {h.last.status_code ?? '—'} · {when(h.last.at)}
            </span>
          )}
        </div>
      ))}
    </Card>
  )
}

/** Webhook log of one integration, payment events and SMS events apart. */
export function EventsLog({ integration, kind }: { integration: Integration; kind: 'payment' | 'sms' }) {
  const { t } = useT()
  const log = useQuery({
    queryKey: ['dev-deliveries', integration, kind],
    queryFn: () => get<Delivery[]>(`/developer/deliveries?integration=${integration}&kind=${kind}&limit=100`),
    refetchInterval: 15000,
  })
  return (
    <Card className="overflow-x-auto">
      <p className="px-4 pt-4 text-sm text-muted">{kind === 'payment' ? t('ev.payment_hint') : t('ev.sms_hint')}</p>
      <table className="w-full text-sm min-w-[680px]">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wider text-muted border-b border-line">
            <th className="px-4 py-3 font-medium">{t('sms.when')}</th>
            <th className="px-4 py-3 font-medium">{t('ev.event')}</th>
            <th className="px-4 py-3 font-medium">{t('ev.what')}</th>
            <th className="px-4 py-3 font-medium">{t('ev.delivery')}</th>
          </tr>
        </thead>
        <tbody>
          {log.data?.map((d) => (
            <tr key={d.id} className="border-b border-line last:border-0 align-top">
              <td className="px-4 py-2.5 text-xs text-muted whitespace-nowrap">{when(d.created_at)}</td>
              <td className="px-4 py-2.5 font-mono text-xs whitespace-nowrap">{d.event}</td>
              <td className="px-4 py-2.5 text-xs">
                {d.summary || '—'}
                {d.error && <p className="text-bad mt-1">{d.error.slice(0, 160)}</p>}
              </td>
              <td className="px-4 py-2.5 whitespace-nowrap">
                <Pill tone={d.delivered ? 'paid' : d.attempts ? 'refunded' : 'neutral'}>
                  {d.delivered ? t('ev.ok') : d.attempts ? t('ev.failed') : t('ev.waiting')} · HTTP {d.status_code ?? '—'}
                  {d.attempts > 1 ? ` ×${d.attempts}` : ''}
                </Pill>
              </td>
            </tr>
          ))}
          {log.data && log.data.length === 0 && (
            <tr>
              <td colSpan={4} className="px-4 py-10 text-center text-muted">
                {t('dev.no_deliveries')}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </Card>
  )
}

export function Tabs<T extends string>({ tabs, value, onChange, label }: { tabs: readonly T[]; value: T; onChange: (t: T) => void; label: (t: T) => string }) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-surface p-0.5 text-sm mb-6">
      {tabs.map((k) => (
        <button key={k} onClick={() => onChange(k)} className={`rounded-md px-4 py-1.5 ${value === k ? 'bg-ink text-white' : 'text-muted hover:text-ink'}`}>
          {label(k)}
        </button>
      ))}
    </div>
  )
}
