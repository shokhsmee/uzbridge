import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { Me } from '../App'
import { Button, Card, CopyField, ErrorNote, Field, Input, PageHeader, Pill, Toggle } from '../components/ui'
import { api, get, post, put } from '../lib/api'
import { useT } from '../lib/i18n'

type ProviderKey = 'payme' | 'click' | 'uzum'
export type Account = {
  id: number
  provider: ProviderKey
  provider_label: string
  label: string
  is_enabled: boolean
  is_configured: boolean
  test_mode: boolean
  merchant_id: string
  service_id: string
  merchant_user_id: string
  secret_masked: string
  test_secret_masked: string
  auto_fiscal: boolean
  account_field: string
  callback_url: string
  has_payments: boolean
}
type Fiscal = { ikpu_code: string; package_code: string; vat_percent: number; units: string }

export const PROVIDER_LOGO: Record<ProviderKey, string> = { payme: '/brands/payme.png', click: '/brands/click.svg', uzum: '/brands/uzum.png' }
const PROVIDERS: { key: ProviderKey; name: string }[] = [
  { key: 'payme', name: 'Payme' },
  { key: 'click', name: 'Click' },
  { key: 'uzum', name: 'Uzum Bank' },
]

// Field names as each provider's cabinet calls them.
const SPEC: Record<ProviderKey, { plain: { key: 'merchant_id' | 'service_id' | 'merchant_user_id' | 'account_field'; label: string }[]; secrets: { key: 'secret' | 'test_secret'; label: string }[]; note: { uz: string; ru: string } }> = {
  payme: {
    plain: [
      { key: 'merchant_id', label: 'Merchant ID (ID кассы)' },
      { key: 'account_field', label: 'Поле счёта (account)' },
    ],
    secrets: [
      { key: 'secret', label: 'Key (боевой ключ)' },
      { key: 'test_secret', label: 'TEST_KEY (песочница)' },
    ],
    note: {
      uz: 'Payme biznes kabinetida kassa sozlamalarida “Endpoint URL” ga quyidagi manzilni qoʻying. “Поле счёта” kassadagi nom bilan bir xil boʻlsin (odatda order_id).',
      ru: 'В бизнес-кабинете Payme в настройках кассы укажите этот адрес как Endpoint URL. «Поле счёта» должно совпадать с названием в кассе (обычно order_id).',
    },
  },
  click: {
    plain: [
      { key: 'service_id', label: 'Service ID' },
      { key: 'merchant_id', label: 'Merchant ID' },
      { key: 'merchant_user_id', label: 'Merchant User ID (fiscal)' },
    ],
    secrets: [{ key: 'secret', label: 'Secret key' }],
    note: {
      uz: 'Click merchant kabinetida Prepare va Complete URL uchun bitta manzil — quyidagisini qoʻying.',
      ru: 'В кабинете Click укажите этот адрес и для Prepare URL, и для Complete URL.',
    },
  },
  uzum: {
    plain: [{ key: 'merchant_id', label: 'Terminal ID (X-Terminal-Id)' }],
    secrets: [{ key: 'secret', label: 'API key (X-API-Key)' }],
    note: {
      uz: 'Uzum Checkout menejeringizga ushbu callback manzilini terminal uchun sozlashni ayting.',
      ru: 'Попросите менеджера Uzum Checkout указать этот callback-адрес для терминала.',
    },
  },
}

export default function ProvidersPage({ me }: { me: Me }) {
  const { t } = useT()
  const canManage = me.role !== 'member'
  const q = useQuery({ queryKey: ['providers'], queryFn: () => get<Account[]>('/payments/providers') })
  return (
    <>
      <PageHeader title={t('pr.title')} lede={t('pr.lede')} />
      <div className="grid gap-5">
        {q.data && PROVIDERS.map((p) => <ProviderCard key={p.key} provider={p.key} name={p.name} accounts={q.data.filter((a) => a.provider === p.key)} canManage={canManage} />)}
        <ErrorNote error={q.error} />
        <FiscalCard canManage={canManage} />
      </div>
    </>
  )
}

/** One provider, all of its accounts. Nothing is on until its keys are entered. */
function ProviderCard({ provider, name, accounts, canManage }: { provider: ProviderKey; name: string; accounts: Account[]; canManage: boolean }) {
  const { t } = useT()
  const [adding, setAdding] = useState(false)
  const [openId, setOpenId] = useState<number | null>(null)
  const any = accounts.length > 0
  const on = accounts.some((a) => a.is_enabled)
  return (
    <Card>
      <div className="flex items-center gap-4 p-5">
        <img src={PROVIDER_LOGO[provider]} alt="" className="size-11 shrink-0 rounded-xl border border-line bg-white object-contain p-1" />
        <div className="min-w-0">
          <h2 className="font-semibold">{name}</h2>
          <p className="text-xs text-muted">
            {any ? t('pr.accounts_n').replace('{n}', String(accounts.length)) : t('pr.off_hint')}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-3">
          {on ? <Pill tone="active">{t('pr.on')}</Pill> : <Pill tone="neutral">{t('pr.off')}</Pill>}
          {!any && canManage && (
            // Switching a provider on means adding its first account: ask for the keys.
            <Toggle id={`${provider}-first`} checked={adding} onChange={(v) => setAdding(v)} label="" />
          )}
        </div>
      </div>
      {accounts.map((a) => (
        <AccountRow key={a.id} a={a} open={openId === a.id} onToggleOpen={() => setOpenId(openId === a.id ? null : a.id)} canManage={canManage} />
      ))}
      {adding && (
        <div className="border-t border-line">
          <AccountForm provider={provider} onDone={() => setAdding(false)} canManage={canManage} />
        </div>
      )}
      {any && canManage && !adding && (
        <div className="border-t border-line px-5 py-3">
          <button type="button" className="text-sm font-medium text-accent hover:text-accent-ink" onClick={() => setAdding(true)}>
            + {t('pr.add_account')}
          </button>
        </div>
      )}
    </Card>
  )
}

function AccountRow({ a, open, onToggleOpen, canManage }: { a: Account; open: boolean; onToggleOpen: () => void; canManage: boolean }) {
  const { t } = useT()
  const qc = useQueryClient()
  const flip = useMutation({
    mutationFn: (is_enabled: boolean) => put<Account>(`/payments/providers/${a.id}`, { ...editable(a), is_enabled }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['providers'] })
      qc.invalidateQueries({ queryKey: ['overview'] })
      qc.invalidateQueries({ queryKey: ['billing'] })
    },
  })
  return (
    <div className="border-t border-line">
      <div className="flex flex-wrap items-center gap-3 px-5 py-3">
        <button type="button" onClick={onToggleOpen} className="flex min-w-0 flex-1 items-center gap-3 text-left">
          <span className="text-muted text-sm w-3">{open ? '−' : '+'}</span>
          <span className="min-w-0">
            <span className="block font-medium truncate">{a.label || a.provider_label}</span>
            <span className="block text-xs text-muted font-mono truncate">{a.merchant_id || t('pr.no_keys')}</span>
          </span>
        </button>
        {a.test_mode && a.is_configured && <Pill tone="pending">{t('pr.test_mode')}</Pill>}
        {!a.is_configured && <Pill tone="neutral">{t('pr.incomplete')}</Pill>}
        {canManage && (
          <Toggle
            id={`acc-${a.id}`}
            checked={a.is_enabled}
            onChange={(v) => (a.is_configured || !v ? flip.mutate(v) : onToggleOpen())}
            label={a.is_enabled ? t('pr.on') : t('pr.off')}
          />
        )}
      </div>
      {flip.error && (
        <div className="px-5 pb-3">
          <ErrorNote error={flip.error} />
        </div>
      )}
      {open && <AccountForm provider={a.provider} account={a} onDone={onToggleOpen} canManage={canManage} />}
    </div>
  )
}

function editable(a: Account) {
  return { label: a.label, test_mode: a.test_mode, auto_fiscal: a.auto_fiscal, merchant_id: a.merchant_id, service_id: a.service_id, merchant_user_id: a.merchant_user_id, account_field: a.account_field }
}

/** Keys of one account. New accounts are switched on when saved with their keys. */
function AccountForm({ provider, account, onDone, canManage }: { provider: ProviderKey; account?: Account; onDone: () => void; canManage: boolean }) {
  const { t, lang } = useT()
  const qc = useQueryClient()
  const spec = SPEC[provider]
  const [plain, setPlain] = useState({
    label: account?.label ?? '',
    merchant_id: account?.merchant_id ?? '',
    service_id: account?.service_id ?? '',
    merchant_user_id: account?.merchant_user_id ?? '',
    account_field: account?.account_field || 'order_id',
  })
  const [secrets, setSecrets] = useState({ secret: '', test_secret: '' })
  const [flags, setFlags] = useState({ test_mode: account?.test_mode ?? true, auto_fiscal: account?.auto_fiscal ?? false })
  const save = useMutation({
    mutationFn: () => {
      const body = {
        ...plain,
        ...flags,
        // a new account is being switched on; an existing one keeps its state (or turns on once complete)
        is_enabled: account ? account.is_enabled || !account.is_configured : true,
        ...(secrets.secret ? { secret: secrets.secret } : {}),
        ...(secrets.test_secret ? { test_secret: secrets.test_secret } : {}),
      }
      return account ? put<Account>(`/payments/providers/${account.id}`, body) : post<Account>('/payments/providers', { provider, ...body })
    },
    onSuccess: () => {
      setSecrets({ secret: '', test_secret: '' })
      qc.invalidateQueries({ queryKey: ['providers'] })
      qc.invalidateQueries({ queryKey: ['overview'] })
      qc.invalidateQueries({ queryKey: ['billing'] })
      onDone()
    },
  })
  const remove = useMutation({
    mutationFn: () => api(`/payments/providers/${account!.id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['providers'] }),
  })
  return (
    <form
      className="p-5 grid gap-5 bg-ground/40"
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate()
      }}
    >
      {!account && <p className="text-sm text-muted">{t('pr.new_hint')}</p>}
      <div className="grid sm:grid-cols-2 gap-4">
        <Field label={t('pr.label')} hint={t('pr.label_hint')}>
          <Input id={`${provider}-${account?.id ?? 'new'}-label`} value={plain.label} disabled={!canManage} placeholder={t('pr.label_ph')} onChange={(e) => setPlain((s) => ({ ...s, label: e.target.value }))} />
        </Field>
        <div className="flex flex-wrap items-end gap-6 pb-2">
          <Toggle id={`${provider}-${account?.id ?? 'new'}-test`} checked={flags.test_mode} onChange={(v) => setFlags((f) => ({ ...f, test_mode: v }))} label={t('pr.test_mode')} />
          {provider === 'uzum' && (
            <Toggle id={`uzum-${account?.id ?? 'new'}-fiscal`} checked={flags.auto_fiscal} onChange={(v) => setFlags((f) => ({ ...f, auto_fiscal: v }))} label="Auto-fiscalization" />
          )}
        </div>
        {spec.plain.map((f) => (
          <Field key={f.key} label={f.label}>
            <Input id={`${provider}-${account?.id ?? 'new'}-${f.key}`} className="font-mono" value={plain[f.key]} disabled={!canManage} onChange={(e) => setPlain((s) => ({ ...s, [f.key]: e.target.value }))} />
          </Field>
        ))}
        {spec.secrets.map((f) => {
          const masked = account ? (f.key === 'secret' ? account.secret_masked : account.test_secret_masked) : ''
          return (
            <Field key={f.key} label={f.label} hint={masked ? `${masked} · ${t('pr.keep')}` : undefined}>
              <Input
                id={`${provider}-${account?.id ?? 'new'}-${f.key}`}
                type="password"
                autoComplete="off"
                className="font-mono"
                placeholder={masked || ''}
                value={secrets[f.key]}
                disabled={!canManage}
                onChange={(e) => setSecrets((s) => ({ ...s, [f.key]: e.target.value }))}
              />
            </Field>
          )
        })}
      </div>
      {account?.callback_url ? (
        <div className="grid gap-2 rounded-lg bg-accent-soft/60 p-4">
          <p className="text-sm font-medium">{t('pr.callback')}</p>
          <CopyField value={account.callback_url} />
          <p className="text-xs text-muted">{spec.note[lang]}</p>
        </div>
      ) : (
        <p className="text-xs text-muted">{t('pr.callback_after')}</p>
      )}
      <ErrorNote error={save.error || remove.error} />
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" busy={save.isPending} disabled={!canManage}>
          {account ? t('amo.save') : t('pr.save_on')}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          {t('pr.cancel')}
        </Button>
        {account && canManage && !account.has_payments && (
          <Button type="button" variant="danger" className="ml-auto" busy={remove.isPending} onClick={() => confirm(t('pr.delete_q')) && remove.mutate()}>
            {t('pr.delete')}
          </Button>
        )}
      </div>
    </form>
  )
}

function FiscalCard({ canManage }: { canManage: boolean }) {
  const q = useQuery({ queryKey: ['fiscal'], queryFn: () => get<Fiscal>('/payments/fiscal') })
  if (!q.data) return null
  return <FiscalForm initial={q.data} canManage={canManage} />
}

function FiscalForm({ initial, canManage }: { initial: Fiscal; canManage: boolean }) {
  const { t } = useT()
  const qc = useQueryClient()
  const [f, setF] = useState(initial)
  const [saved, setSaved] = useState(false)
  const save = useMutation({
    mutationFn: () => put<Fiscal>('/payments/fiscal', f),
    onSuccess: (d) => {
      qc.setQueryData(['fiscal'], d)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    },
  })
  return (
    <Card className="p-5 grid gap-4">
      <div>
        <h2 className="font-semibold">{t('pr.fiscal')}</h2>
        <p className="text-sm text-muted mt-1">{t('pr.fiscal_lede')}</p>
      </div>
      <div className="grid sm:grid-cols-4 gap-4">
        <Field label="MXIK / IKPU" hint="17">
          <Input id="ikpu" className="font-mono" maxLength={17} value={f.ikpu_code} disabled={!canManage} onChange={(e) => setF({ ...f, ikpu_code: e.target.value.replace(/\D/g, '') })} />
        </Field>
        <Field label="Package code">
          <Input id="package" className="font-mono" value={f.package_code} disabled={!canManage} onChange={(e) => setF({ ...f, package_code: e.target.value })} />
        </Field>
        <Field label="QQS / НДС %">
          <Input id="vat" type="number" min={0} max={100} value={f.vat_percent} disabled={!canManage} onChange={(e) => setF({ ...f, vat_percent: Number(e.target.value) })} />
        </Field>
        <Field label="Units">
          <Input id="units" className="font-mono" value={f.units} disabled={!canManage} onChange={(e) => setF({ ...f, units: e.target.value })} />
        </Field>
      </div>
      <ErrorNote error={save.error} />
      <div className="flex items-center gap-3">
        <Button busy={save.isPending} onClick={() => save.mutate()} disabled={!canManage}>
          {t('amo.save')}
        </Button>
        {saved && <span className="text-sm text-ok">✓ {t('amo.saved')}</span>}
      </div>
    </Card>
  )
}
