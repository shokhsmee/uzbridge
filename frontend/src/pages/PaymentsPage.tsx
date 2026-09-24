import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Button, Card, CopyField, ErrorNote, Field, Input, PageHeader, StatusPill } from '../components/ui'
import { get, post, soum, when } from '../lib/api'
import { useT } from '../lib/i18n'

type InvStatus = 'pending' | 'paid' | 'cancelled' | 'refunded'
type Invoice = {
  id: string
  number: string
  amount_tiyin: number
  description: string
  source: 'manual' | 'amocrm'
  external_id: string
  external_name: string
  status: InvStatus
  paid_via: string
  paid_at: string | null
  created_at: string
  created_by: string
  crm_synced_at: string | null
  crm_sync_error: string
  url: string
  transactions?: { provider: string; provider_txn_id: string; state: number; reason: number | null; created_at: string; performed_at: string | null; cancelled_at: string | null }[]
}

const PROVIDER: Record<string, string> = { payme: 'Payme', click: 'Click', uzum: 'Uzum' }
const TXN_STATE: Record<number, string> = { 1: 'created', 2: 'performed', [-1]: 'cancelled', [-2]: 'refunded' }

export default function PaymentsPage() {
  const { t } = useT()
  const [status, setStatus] = useState<'' | InvStatus>('')
  const [q, setQ] = useState('')
  const [openId, setOpenId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const list = useQuery({
    queryKey: ['invoices', status, q],
    queryFn: () => get<{ total: number; items: Invoice[] }>(`/payments/invoices?status=${status}&q=${encodeURIComponent(q)}`),
  })

  return (
    <>
      <PageHeader title={t('pay.title')} action={<Button onClick={() => setCreating(true)}>+ {t('pay.new')}</Button>} />
      <div className="flex flex-wrap gap-3 mb-4">
        <Input id="search" className="max-w-xs" placeholder={t('pay.search')} value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="inline-flex rounded-lg border border-line bg-surface p-0.5 text-sm">
          {(['', 'pending', 'paid', 'cancelled', 'refunded'] as const).map((s) => (
            <button key={s} onClick={() => setStatus(s)} className={`rounded-md px-3 py-1.5 ${status === s ? 'bg-ink text-white' : 'text-muted hover:text-ink'}`}>
              {s ? t(`status.${s}`) : t('pay.all')}
            </button>
          ))}
        </div>
      </div>
      <Card className="overflow-x-auto">
        <table className="w-full text-sm min-w-[720px]">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-muted border-b border-line">
              <th className="px-4 py-3 font-medium">№</th>
              <th className="px-4 py-3 font-medium">{t('pay.description')}</th>
              <th className="px-4 py-3 font-medium text-right">{t('pay.amount')}</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">{t('pay.lead')}</th>
              <th className="px-4 py-3 font-medium">Date</th>
            </tr>
          </thead>
          <tbody>
            {list.data?.items.map((inv) => (
              <tr key={inv.id} onClick={() => setOpenId(inv.id)} className="border-b border-line last:border-0 hover:bg-ground cursor-pointer">
                <td className="px-4 py-3 font-mono text-xs">{inv.number}</td>
                <td className="px-4 py-3 max-w-[260px] truncate">{inv.description || inv.external_name || '—'}</td>
                <td className="px-4 py-3 text-right font-mono tabular">{soum(inv.amount_tiyin)}</td>
                <td className="px-4 py-3">
                  <span className="inline-flex items-center gap-2">
                    <StatusPill status={inv.status} />
                    {inv.paid_via && <span className="text-xs text-muted">{PROVIDER[inv.paid_via]}</span>}
                  </span>
                </td>
                <td className="px-4 py-3 text-xs text-muted">{inv.source === 'amocrm' ? `amoCRM #${inv.external_id}` : '—'}</td>
                <td className="px-4 py-3 text-xs text-muted whitespace-nowrap">{when(inv.created_at)}</td>
              </tr>
            ))}
            {list.data && list.data.items.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-muted">
                  {t('pay.empty')}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
      {openId && <Drawer id={openId} onClose={() => setOpenId(null)} />}
      {creating && <NewInvoice onClose={() => setCreating(false)} onCreated={(id) => { setCreating(false); setOpenId(id) }} />}
    </>
  )
}

function Overlay({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-20 flex justify-end bg-ink/30" onClick={onClose}>
      <div className="h-full w-full max-w-md bg-surface shadow-xl overflow-y-auto p-6" onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>
  )
}

function Drawer({ id, onClose }: { id: string; onClose: () => void }) {
  const { t } = useT()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['invoice', id], queryFn: () => get<Invoice>(`/payments/invoices/${id}`) })
  const cancel = useMutation({
    mutationFn: () => post(`/payments/invoices/${id}/cancel`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['invoice', id] })
      qc.invalidateQueries({ queryKey: ['invoices'] })
    },
  })
  const inv = q.data
  return (
    <Overlay onClose={onClose}>
      <div className="flex justify-between items-start">
        <p className="font-mono text-sm text-muted">{inv?.number}</p>
        <button onClick={onClose} className="text-muted text-sm">
          {t('common.close')} ✕
        </button>
      </div>
      {inv && (
        <div className="grid gap-5 mt-2">
          <div>
            <p className="text-3xl font-semibold font-mono tabular tracking-tight">
              {soum(inv.amount_tiyin)} <span className="text-base text-muted font-sans font-normal">soʻm</span>
            </p>
            <p className="text-muted mt-1">{inv.description || inv.external_name}</p>
            <div className="mt-3 flex items-center gap-2">
              <StatusPill status={inv.status} />
              {inv.paid_via && <span className="text-sm">{PROVIDER[inv.paid_via]} · {when(inv.paid_at)}</span>}
            </div>
          </div>
          <div className="grid gap-2">
            <p className="text-sm font-medium">{t('pay.link')}</p>
            <CopyField value={inv.url} />
          </div>
          {inv.source === 'amocrm' && (
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
              <dt className="text-muted">{t('pay.lead')}</dt>
              <dd className="font-mono">#{inv.external_id} {inv.external_name}</dd>
              <dt className="text-muted">{t('pay.crm_sync')}</dt>
              <dd>{inv.crm_synced_at ? when(inv.crm_synced_at) : inv.crm_sync_error ? <span className="text-bad">{inv.crm_sync_error}</span> : '—'}</dd>
            </dl>
          )}
          <div>
            <p className="text-sm font-medium mb-2">{t('pay.txns')}</p>
            {inv.transactions?.length ? (
              <ol className="grid gap-2">
                {inv.transactions.map((tx) => (
                  <li key={`${tx.provider}-${tx.provider_txn_id}`} className="rounded-lg border border-line px-3 py-2 text-xs grid gap-0.5">
                    <span className="flex justify-between">
                      <strong>{PROVIDER[tx.provider]}</strong>
                      <span className={tx.state === 2 ? 'text-ok' : tx.state < 0 ? 'text-bad' : 'text-warn'}>{TXN_STATE[tx.state]}</span>
                    </span>
                    <span className="font-mono text-muted truncate">{tx.provider_txn_id}</span>
                    <span className="text-muted">{when(tx.created_at)}</span>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-sm text-muted">—</p>
            )}
          </div>
          {inv.status === 'pending' && (
            <div>
              <Button variant="danger" busy={cancel.isPending} onClick={() => cancel.mutate()}>
                {t('pay.cancel')}
              </Button>
              <ErrorNote error={cancel.error} />
            </div>
          )}
        </div>
      )}
    </Overlay>
  )
}

function NewInvoice({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const { t } = useT()
  const qc = useQueryClient()
  const [amount, setAmount] = useState('')
  const [description, setDescription] = useState('')
  const create = useMutation({
    mutationFn: () => post<Invoice>('/payments/invoices', { amount, description }),
    onSuccess: (inv) => {
      qc.invalidateQueries({ queryKey: ['invoices'] })
      qc.invalidateQueries({ queryKey: ['stats'] })
      onCreated(inv.id)
    },
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    create.mutate()
  }
  return (
    <Overlay onClose={onClose}>
      <form onSubmit={submit} className="grid gap-4">
        <div className="flex justify-between">
          <h2 className="text-lg font-semibold">{t('pay.new')}</h2>
          <button type="button" onClick={onClose} className="text-muted text-sm">
            ✕
          </button>
        </div>
        <Field label={t('pay.amount')}>
          <Input id="new-amount" inputMode="decimal" required value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="1 500 000" className="font-mono" />
        </Field>
        <Field label={t('pay.description')}>
          <Input id="new-description" value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <ErrorNote error={create.error} />
        <Button type="submit" busy={create.isPending}>
          {t('pay.create')}
        </Button>
      </form>
    </Overlay>
  )
}
