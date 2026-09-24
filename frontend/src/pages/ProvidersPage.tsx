import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { Me } from '../App'
import { Button, Card, CopyField, ErrorNote, Field, Input, PageHeader, Pill, Toggle } from '../components/ui'
import { get, put } from '../lib/api'
import { useT } from '../lib/i18n'

type ProviderKey = 'payme' | 'click' | 'uzum'
type Provider = {
  provider: ProviderKey
  label: string
  exists: boolean
  is_enabled: boolean
  is_configured: boolean
  test_mode: boolean
  merchant_id: string
  service_id: string
  merchant_user_id: string
  secret_masked: string
  test_secret_masked: string
  auto_fiscal: boolean
  callback_url: string
}
type Fiscal = { ikpu_code: string; package_code: string; vat_percent: number; units: string }

// Field names as each provider's cabinet calls them.
const SPEC: Record<ProviderKey, { plain: { key: 'merchant_id' | 'service_id' | 'merchant_user_id'; label: string }[]; secrets: { key: 'secret' | 'test_secret'; label: string }[]; color: string; note: { uz: string; ru: string } }> = {
  payme: {
    plain: [{ key: 'merchant_id', label: 'Merchant ID (ID кассы)' }],
    secrets: [
      { key: 'secret', label: 'Key (боевой ключ)' },
      { key: 'test_secret', label: 'TEST_KEY (песочница)' },
    ],
    color: '#33cccc',
    note: {
      uz: 'Payme biznes kabinetida kassa sozlamalarida “Endpoint URL” ga quyidagi manzilni qoʻying. Hisob maydoni: order_id.',
      ru: 'В бизнес-кабинете Payme в настройках кассы укажите этот адрес как Endpoint URL. Поле счёта: order_id.',
    },
  },
  click: {
    plain: [
      { key: 'service_id', label: 'Service ID' },
      { key: 'merchant_id', label: 'Merchant ID' },
      { key: 'merchant_user_id', label: 'Merchant User ID (fiscal)' },
    ],
    secrets: [{ key: 'secret', label: 'Secret key' }],
    color: '#0a6cf5',
    note: {
      uz: 'Click merchant kabinetida Prepare va Complete URL uchun bitta manzil — quyidagisini qoʻying.',
      ru: 'В кабинете Click укажите этот адрес и для Prepare URL, и для Complete URL.',
    },
  },
  uzum: {
    plain: [{ key: 'merchant_id', label: 'Terminal ID (X-Terminal-Id)' }],
    secrets: [{ key: 'secret', label: 'API key (X-API-Key)' }],
    color: '#7b2ff7',
    note: {
      uz: 'Uzum Checkout menejeringizga ushbu callback manzilini terminal uchun sozlashni ayting.',
      ru: 'Попросите менеджера Uzum Checkout указать этот callback-адрес для терминала.',
    },
  },
}

export default function ProvidersPage({ me }: { me: Me }) {
  const { t } = useT()
  const canManage = me.role !== 'member'
  const q = useQuery({ queryKey: ['providers'], queryFn: () => get<Provider[]>('/payments/providers') })
  return (
    <>
      <PageHeader title={t('pr.title')} lede={t('pr.lede')} />
      <div className="grid gap-5">
        {q.data?.map((p) => <ProviderCard key={p.provider} p={p} canManage={canManage} />)}
        <FiscalCard canManage={canManage} />
      </div>
    </>
  )
}

function ProviderCard({ p, canManage }: { p: Provider; canManage: boolean }) {
  const { t, lang } = useT()
  const qc = useQueryClient()
  const spec = SPEC[p.provider]
  const [plain, setPlain] = useState({ merchant_id: p.merchant_id, service_id: p.service_id, merchant_user_id: p.merchant_user_id })
  const [secrets, setSecrets] = useState({ secret: '', test_secret: '' })
  const [flags, setFlags] = useState({ is_enabled: p.exists ? p.is_enabled : true, test_mode: p.test_mode, auto_fiscal: p.auto_fiscal })
  const [open, setOpen] = useState(!p.is_configured)

  const save = useMutation({
    mutationFn: () =>
      put<Provider>(`/payments/providers/${p.provider}`, {
        ...plain,
        ...flags,
        ...(secrets.secret ? { secret: secrets.secret } : {}),
        ...(secrets.test_secret ? { test_secret: secrets.test_secret } : {}),
      }),
    onSuccess: () => {
      setSecrets({ secret: '', test_secret: '' })
      qc.invalidateQueries({ queryKey: ['providers'] })
      qc.invalidateQueries({ queryKey: ['overview'] })
    },
  })

  return (
    <Card>
      <button type="button" onClick={() => setOpen(!open)} className="w-full flex items-center gap-4 p-5 text-left">
        <span className="size-3 rounded-full" style={{ background: spec.color }} aria-hidden />
        <span className="font-semibold">{p.label}</span>
        {p.is_configured ? <Pill tone={p.is_enabled ? 'active' : 'neutral'}>{t('pr.ready')}</Pill> : <Pill tone="neutral">{t('pr.incomplete')}</Pill>}
        {p.test_mode && p.exists && <Pill tone="pending">{t('pr.test_mode')}</Pill>}
        <span className="ml-auto text-muted text-sm">{open ? '−' : '+'}</span>
      </button>
      {open && (
        <form
          className="border-t border-line p-5 grid gap-5"
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate()
          }}
        >
          <div className="flex flex-wrap gap-6">
            <Toggle id={`${p.provider}-enabled`} checked={flags.is_enabled} onChange={(v) => setFlags((f) => ({ ...f, is_enabled: v }))} label={t('pr.enabled')} />
            <Toggle id={`${p.provider}-test`} checked={flags.test_mode} onChange={(v) => setFlags((f) => ({ ...f, test_mode: v }))} label={t('pr.test_mode')} />
            {p.provider === 'uzum' && (
              <Toggle id="uzum-fiscal" checked={flags.auto_fiscal} onChange={(v) => setFlags((f) => ({ ...f, auto_fiscal: v }))} label="Auto-fiscalization" />
            )}
          </div>
          <div className="grid sm:grid-cols-2 gap-4">
            {spec.plain.map((f) => (
              <Field key={f.key} label={f.label}>
                <Input id={`${p.provider}-${f.key}`} className="font-mono" value={plain[f.key]} disabled={!canManage} onChange={(e) => setPlain((s) => ({ ...s, [f.key]: e.target.value }))} />
              </Field>
            ))}
            {spec.secrets.map((f) => {
              const masked = f.key === 'secret' ? p.secret_masked : p.test_secret_masked
              return (
                <Field key={f.key} label={f.label} hint={masked ? `${masked} · ${t('pr.keep')}` : undefined}>
                  <Input
                    id={`${p.provider}-${f.key}`}
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
          {p.callback_url && (
            <div className="grid gap-2 rounded-lg bg-accent-soft/60 p-4">
              <p className="text-sm font-medium">{t('pr.callback')}</p>
              <CopyField value={p.callback_url} />
              <p className="text-xs text-muted">{spec.note[lang]}</p>
            </div>
          )}
          <ErrorNote error={save.error} />
          <div>
            <Button type="submit" busy={save.isPending} disabled={!canManage}>
              {t('amo.save')}
            </Button>
          </div>
        </form>
      )}
    </Card>
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
