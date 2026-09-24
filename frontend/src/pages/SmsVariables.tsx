import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Button, Card, ErrorNote, Input } from '../components/ui'
import { get, put } from '../lib/api'
import { useT } from '../lib/i18n'

type Row = { key: string; source: string; label: string }
type Vars = { builtins: string[]; variables: Row[] }

// Common Odoo field paths; any path on the record the SMS is written from works.
const ODOO_PATHS = [
  'partner_id.name',
  'partner_id.phone',
  'partner_id.street',
  'partner_id.vat',
  'name',
  'amount_total',
  'amount_residual',
  'invoice_date',
  'invoice_date_due',
  'date_order',
  'user_id.name',
  'company_id.name',
]

/** The company's own {keywords} for Odoo SMS texts, each read from a field of the record. */
export function OdooVariablesCard({ canManage }: { canManage: boolean }) {
  const { t } = useT()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['sms-vars', 'odoo'], queryFn: () => get<Vars>('/sms/variables/odoo') })
  const [rows, setRows] = useState<Row[]>([])
  const [saved, setSaved] = useState(false)
  useEffect(() => {
    if (q.data) setRows(q.data.variables)
  }, [q.data])
  const save = useMutation({
    mutationFn: () => put<Vars>('/sms/variables/odoo', rows.filter((r) => r.key || r.source)),
    onSuccess: (d) => {
      qc.setQueryData(['sms-vars', 'odoo'], d)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    },
  })
  const set = (i: number, patch: Partial<Row>) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))

  return (
    <Card>
      <div className="p-5 border-b border-line">
        <h2 className="font-semibold">{t('vars.title')}</h2>
        <p className="text-sm text-muted mt-1 max-w-2xl">{t('vars.odoo_lede')}</p>
        <div className="flex flex-wrap items-center gap-1.5 mt-3 text-xs">
          <span className="text-muted mr-1">{t('vars.builtin')}:</span>
          {q.data?.builtins.map((b) => (
            <code key={b} className="rounded-md bg-ground px-1.5 py-0.5 font-mono">{`{${b}}`}</code>
          ))}
        </div>
      </div>
      <div className="p-5 grid gap-3">
        {rows.length > 0 && (
          <div className="hidden sm:grid grid-cols-[minmax(0,10rem)_minmax(0,1fr)_minmax(0,12rem)_2.5rem] gap-3 text-xs text-muted">
            <span>{t('vars.key')}</span>
            <span>{t('vars.odoo_path')}</span>
            <span>{t('vars.label')}</span>
            <span />
          </div>
        )}
        {rows.map((r, i) => (
          <div key={i} className="grid sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)_minmax(0,12rem)_2.5rem] gap-3 items-center">
            <div className="flex items-center rounded-lg border border-line bg-surface focus-within:border-accent">
              <span className="pl-3 text-muted font-mono text-sm">{'{'}</span>
              <input
                aria-label={t('vars.key')}
                className="h-10 w-full bg-transparent px-1 font-mono text-sm focus:outline-none"
                placeholder="muddat"
                value={r.key}
                disabled={!canManage}
                onChange={(e) => set(i, { key: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '') })}
              />
              <span className="pr-3 text-muted font-mono text-sm">{'}'}</span>
            </div>
            <Input
              aria-label={t('vars.odoo_path')}
              className="font-mono"
              list="odoo-paths"
              placeholder="invoice_date_due"
              value={r.source}
              disabled={!canManage}
              onChange={(e) => set(i, { source: e.target.value.trim() })}
            />
            <Input aria-label={t('vars.label')} placeholder={t('vars.label_ph')} value={r.label} disabled={!canManage} onChange={(e) => set(i, { label: e.target.value })} />
            {canManage ? (
              <button type="button" aria-label={t('vars.remove')} className="h-10 rounded-lg border border-line text-muted hover:border-bad hover:text-bad" onClick={() => setRows(rows.filter((_, j) => j !== i))}>
                ✕
              </button>
            ) : (
              <span />
            )}
          </div>
        ))}
        {!rows.length && q.isSuccess && <p className="text-sm text-muted">{t('vars.empty')}</p>}
        <datalist id="odoo-paths">
          {ODOO_PATHS.map((p) => (
            <option key={p} value={p} />
          ))}
        </datalist>
        <ErrorNote error={q.error || save.error} />
        {canManage && (
          <div className="flex flex-wrap items-center gap-3">
            <Button type="button" variant="ghost" onClick={() => setRows([...rows, { key: '', source: '', label: '' }])}>
              + {t('vars.add')}
            </Button>
            <Button type="button" busy={save.isPending} onClick={() => save.mutate()}>
              {t('vars.save')}
            </Button>
            {saved && <span className="text-sm text-ok">{t('vars.saved')}</span>}
          </div>
        )}
        <p className="text-xs text-muted">{t('vars.odoo_sync')}</p>
      </div>
    </Card>
  )
}
