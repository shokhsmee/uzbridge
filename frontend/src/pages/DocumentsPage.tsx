import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import type { Me } from '../App'
import { RichEditor } from '../components/RichEditor'
import { Button, Card, ErrorNote, Field, Input, PageHeader, Pill, Select, Toggle } from '../components/ui'
import { api, downloadPost, get, post, put, upload, when } from '../lib/api'
import { useT } from '../lib/i18n'
import { Tabs } from './IntegrationLogs'

type Template = {
  id: number
  name: string
  kind: 'docx' | 'html'
  html: string
  docx_name: string
  has_file: boolean
  default_format: 'docx' | 'pdf'
  prefix: string
  padding: number
  next_number: number
  next_label: string
  use_in_amocrm: boolean
  keywords: string[]
  unknown_keywords: string[]
  bindings: Record<string, Binding>
  can_edit_word: boolean
  documents: number
}
type Binding =
  | { type: 'amo'; source: string }
  | { type: 'number' }
  | { type: 'date'; offset_days: number; style: 'short' | 'long' | 'ru' }
  | { type: 'builtin'; key: string }
  | { type: 'text'; value: string }
type Source = { value: string; group: string; label: string }
const KEY_RE = /\{([a-z][a-z0-9_]{0,29})\}/g
const keysIn = (html: string) => [...new Set([...html.matchAll(KEY_RE)].map((m) => m[1]))]
type Keywords = { builtins: { key: string; label: string }[]; own: { key: string; label: string; source: string }[] }
type Doc = { id: number; number: string; template: string; format: string; lead_id: number; lead_url: string; url: string; created_by: string; created_at: string; updated_at: string }

const STARTER = '<h1 style="text-align: center">SHARTNOMA № {number}</h1><p style="text-align: right">{date}</p><p>{company_legal_name} (keyingi oʻrinlarda “Ijrochi”) va {name} (keyingi oʻrinlarda “Buyurtmachi”) quyidagilar haqida ushbu shartnomani tuzdilar:</p><h2>1. Shartnoma predmeti</h2><p>{lead_name}. Shartnoma summasi: {amount} ({amount_words}) soʻm.</p><h2>2. Tomonlarning rekvizitlari</h2><table><tbody><tr><td><p><strong>Ijrochi</strong></p><p>{company_legal_name}</p><p>STIR: {company_tin}</p><p>{company_address}</p><p>{company_bank}, MFO {company_mfo}</p><p>H/r: {company_account}</p><p>Direktor: {company_director}</p></td><td><p><strong>Buyurtmachi</strong></p><p>{name}</p><p>Tel: {phone}</p></td></tr></tbody></table>'

const TABS = ['templates', 'keywords', 'made'] as const

export default function DocumentsPage({ me }: { me: Me }) {
  const { t } = useT()
  const canManage = me.role !== 'member'
  const [tab, setTab] = useState<(typeof TABS)[number]>('templates')
  return (
    <>
      <PageHeader title={t('doc.title')} lede={t('doc.lede')} />
      <Tabs tabs={TABS} value={tab} onChange={setTab} label={(k) => t(`doc.tab.${k}`)} />
      {tab === 'templates' && <TemplatesTab canManage={canManage} />}
      {tab === 'keywords' && <KeywordsTab canManage={canManage} />}
      {tab === 'made' && <MadeTab />}
    </>
  )
}

// ---------------------------------------------------------------- templates

function TemplatesTab({ canManage }: { canManage: boolean }) {
  const { t } = useT()
  const qc = useQueryClient()
  const list = useQuery({ queryKey: ['doc-templates'], queryFn: () => get<Template[]>('/documents/templates') })
  const kw = useQuery({ queryKey: ['doc-keywords'], queryFn: () => get<Keywords>('/documents/keywords') })
  const [openId, setOpenId] = useState<number | null>(null)
  const create = useMutation({
    mutationFn: (kind: 'docx' | 'html') =>
      post<Template>('/documents/templates', {
        name: kind === 'html' ? t('doc.new_contract') : t('doc.new_word'),
        kind,
        html: kind === 'html' ? STARTER : '',
        default_format: kind === 'html' ? 'pdf' : 'docx',
        prefix: 'DOG-',
      }),
    onSuccess: (tpl) => {
      qc.invalidateQueries({ queryKey: ['doc-templates'] })
      setOpenId(tpl.id)
    },
  })
  const templates = list.data ?? []
  const open = templates.find((x) => x.id === openId)
  const keywords = [...(kw.data?.builtins ?? []), ...(kw.data?.own ?? [])]

  return (
    <div className="grid gap-5">
      <Card className="p-5 flex flex-wrap items-center gap-3">
        <div className="mr-auto">
          <h2 className="font-semibold">{t('doc.templates')}</h2>
          <p className="text-sm text-muted">{t('doc.templates_hint')}</p>
        </div>
        {canManage && (
          <>
            <Button variant="ghost" busy={create.isPending && create.variables === 'docx'} onClick={() => create.mutate('docx')}>
              + {t('doc.add_word')}
            </Button>
            <Button busy={create.isPending && create.variables === 'html'} onClick={() => create.mutate('html')}>
              + {t('doc.add_site')}
            </Button>
          </>
        )}
      </Card>
      <ErrorNote error={list.error || create.error} />
      {templates.length === 0 && list.isSuccess && <p className="text-sm text-muted">{t('doc.none')}</p>}
      <div className="grid gap-3">
        {templates.map((tpl) => (
          <Card key={tpl.id}>
            <button type="button" className="w-full flex flex-wrap items-center gap-3 p-4 text-left" onClick={() => setOpenId(openId === tpl.id ? null : tpl.id)}>
              <span className="grid size-10 place-items-center rounded-lg bg-accent-soft text-accent-ink text-xs font-semibold">{tpl.kind === 'docx' ? 'DOCX' : 'HTML'}</span>
              <span className="min-w-0 mr-auto">
                <span className="block font-medium truncate">{tpl.name}</span>
                <span className="block text-xs text-muted">
                  {tpl.kind === 'docx' ? t('doc.kind_word') : t('doc.kind_site')} · {t('doc.next')} <span className="font-mono">{tpl.next_label}</span> · {tpl.documents} {t('doc.made_n')}
                </span>
              </span>
              {tpl.unknown_keywords.length > 0 && <Pill tone="pending">{t('doc.unknown_n').replace('{n}', String(tpl.unknown_keywords.length))}</Pill>}
              {tpl.kind === 'docx' && !tpl.has_file && <Pill tone="error">{t('doc.no_file')}</Pill>}
              {tpl.use_in_amocrm ? <Pill tone="active">amoCRM</Pill> : <Pill tone="neutral">{t('doc.off')}</Pill>}
              <span className="text-muted text-sm">{openId === tpl.id ? '−' : '+'}</span>
            </button>
            {open?.id === tpl.id && <TemplateEditor key={`${tpl.id}-${tpl.kind}-${tpl.has_file}`} tpl={tpl} keywords={keywords} canManage={canManage} onDeleted={() => setOpenId(null)} />}
          </Card>
        ))}
      </div>
    </div>
  )
}

function TemplateEditor({ tpl, keywords, canManage, onDeleted }: { tpl: Template; keywords: { key: string; label: string }[]; canManage: boolean; onDeleted: () => void }) {
  const { t } = useT()
  const qc = useQueryClient()
  const [f, setF] = useState({
    name: tpl.name,
    prefix: tpl.prefix,
    padding: tpl.padding,
    next_number: tpl.next_number,
    default_format: tpl.default_format,
    use_in_amocrm: tpl.use_in_amocrm,
    html: tpl.html || STARTER,
  })
  const [bindings, setBindings] = useState<Record<string, Binding>>(tpl.bindings || {})
  const [saved, setSaved] = useState(false)
  const [lead, setLead] = useState('')
  const [fmt, setFmt] = useState<'docx' | 'pdf'>(tpl.default_format)
  const fileRef = useRef<HTMLInputElement>(null)
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['doc-templates'] })
  }
  const save = useMutation({
    mutationFn: () =>
      put<Template>(`/documents/templates/${tpl.id}`, {
        ...f,
        kind: tpl.kind,
        next_number: f.next_number !== tpl.next_number ? f.next_number : undefined,
        // only keywords still in the template keep a binding
        bindings: Object.fromEntries(Object.entries(bindings).filter(([k]) => used.includes(k))),
      }),
    onSuccess: () => {
      refresh()
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    },
  })
  const send = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return upload<Template>(`/documents/templates/${tpl.id}/upload`, form)
    },
    onSuccess: refresh,
  })
  const remove = useMutation({ mutationFn: () => api(`/documents/templates/${tpl.id}`, { method: 'DELETE' }), onSuccess: () => (refresh(), onDeleted()) })
  const toSite = useMutation({ mutationFn: () => post<Template>(`/documents/templates/${tpl.id}/edit-on-site`), onSuccess: refresh })
  const toWord = useMutation({ mutationFn: () => post<Template>(`/documents/templates/${tpl.id}/use-word`), onSuccess: refresh })
  // Keywords of this template: from the Word file, or live from the editor.
  const used = tpl.kind === 'html' ? keysIn(f.html) : tpl.keywords
  const sample = useMutation({
    mutationFn: () => downloadPost(`/documents/templates/${tpl.id}/preview`, { lead_id: Number(lead), format: fmt }, `namuna.${fmt}`),
  })
  const number = `${f.prefix}${String(f.next_number).padStart(f.padding, '0')}`

  return (
    <div className="border-t border-line p-5 grid gap-5">
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Field label={t('doc.name')}>
          <Input value={f.name} disabled={!canManage} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </Field>
        <Field label={t('doc.prefix')} hint={t('doc.prefix_hint')}>
          <Input className="font-mono" value={f.prefix} placeholder="DOG-" disabled={!canManage} onChange={(e) => setF({ ...f, prefix: e.target.value })} />
        </Field>
        <Field label={t('doc.digits')}>
          <Select value={f.padding} disabled={!canManage} onChange={(e) => setF({ ...f, padding: Number(e.target.value) })}>
            {[1, 2, 3, 4, 5, 6].map((n) => (
              <option key={n} value={n}>
                {n} — {String(1).padStart(n, '0')}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t('doc.next_no')} hint={`${t('doc.next_hint')} ${number}`}>
          <Input type="number" min={1} value={f.next_number} disabled={!canManage} onChange={(e) => setF({ ...f, next_number: Math.max(1, Number(e.target.value) || 1) })} />
        </Field>
        <Field label={t('doc.format')}>
          <Select value={f.default_format} disabled={!canManage} onChange={(e) => setF({ ...f, default_format: e.target.value as 'docx' | 'pdf' })}>
            <option value="pdf">PDF</option>
            <option value="docx">Word (.docx)</option>
          </Select>
        </Field>
        <div className="flex items-end pb-2">
          <Toggle id={`doc-amo-${tpl.id}`} checked={f.use_in_amocrm} onChange={(v) => setF({ ...f, use_in_amocrm: v })} label={t('doc.in_amocrm')} />
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_22rem] items-start">
      <div className="grid gap-3 min-w-0">
      {tpl.kind === 'docx' ? (
        <div className="grid gap-3 rounded-lg bg-ground/60 p-4">
          <p className="text-sm">{t('doc.word_hint')}</p>
          <div className="flex flex-wrap items-center gap-3">
            {canManage && (
              <Button variant="ghost" busy={send.isPending} onClick={() => fileRef.current?.click()}>
                {tpl.has_file ? t('doc.replace') : t('doc.upload')}
              </Button>
            )}
            <input
              ref={fileRef}
              type="file"
              accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) send.mutate(file)
                e.target.value = ''
              }}
            />
            {tpl.has_file && (
              <a className="text-sm text-accent font-medium" href={`/api/documents/templates/${tpl.id}/file`}>
                {tpl.docx_name} ↓
              </a>
            )}
            {tpl.has_file && canManage && (
              <Button variant="ghost" busy={toSite.isPending} onClick={() => confirm(t('doc.to_site_q')) && toSite.mutate()}>
                {t('doc.to_site')}
              </Button>
            )}
          </div>
          <ErrorNote error={send.error || toSite.error} />
        </div>
      ) : (
        <>
          {tpl.can_edit_word && canManage && (
            <div className="flex flex-wrap items-center gap-3 rounded-lg bg-ground/60 px-4 py-2 text-sm">
              <span className="text-muted">{t('doc.from_word')}</span>
              <button type="button" className="text-accent font-medium" onClick={() => confirm(t('doc.to_word_q')) && toWord.mutate()}>
                {t('doc.to_word')}
              </button>
            </div>
          )}
          <RichEditor value={f.html} onChange={(html) => setF((s) => ({ ...s, html }))} keywords={keywords} disabled={!canManage} />
        </>
      )}
      </div>
      <BindingsPanel used={used} bindings={bindings} onChange={setBindings} keywords={keywords} canManage={canManage} />
      </div>

      <ErrorNote error={save.error || remove.error} />
      {canManage && (
        <div className="flex flex-wrap items-center gap-3">
          <Button busy={save.isPending} onClick={() => save.mutate()}>
            {t('amo.save')}
          </Button>
          {saved && <span className="text-sm text-ok">✓ {t('amo.saved')}</span>}
          {tpl.documents === 0 && (
            <Button variant="danger" className="ml-auto" busy={remove.isPending} onClick={() => confirm(t('pr.delete_q')) && remove.mutate()}>
              {t('pr.delete')}
            </Button>
          )}
        </div>
      )}

      <div className="grid gap-3 rounded-lg border border-line p-4">
        <p className="font-medium text-sm">{t('doc.try')}</p>
        <p className="text-xs text-muted">{t('doc.try_hint')}</p>
        <div className="flex flex-wrap items-end gap-3">
          <Field label={t('doc.lead_id')}>
            <Input className="w-40 font-mono" inputMode="numeric" placeholder="67937149" value={lead} onChange={(e) => setLead(e.target.value.replace(/\D/g, ''))} />
          </Field>
          <Field label={t('doc.format')}>
            <Select className="w-36" value={fmt} onChange={(e) => setFmt(e.target.value as 'docx' | 'pdf')}>
              <option value="pdf">PDF</option>
              <option value="docx">Word</option>
            </Select>
          </Field>
          <Button variant="ghost" busy={sample.isPending} disabled={!lead} onClick={() => sample.mutate()}>
            {t('doc.make_sample')} ↓
          </Button>
        </div>
        <ErrorNote error={sample.error} />
      </div>
    </div>
  )
}

/** Every keyword of the template, and where each one takes its value from. */
function BindingsPanel({ used, bindings, onChange, keywords, canManage }: { used: string[]; bindings: Record<string, Binding>; onChange: (b: Record<string, Binding>) => void; keywords: { key: string; label: string }[]; canManage: boolean }) {
  const { t } = useT()
  const vars = useQuery({ queryKey: ['amo-vars'], queryFn: () => get<AmoVars>('/amocrm/variables'), retry: false })
  const sources: Source[] = vars.data?.sources ?? []
  const known = new Map(keywords.map((k) => [k.key, k.label]))
  const set = (key: string, b: Binding | null) => {
    const next = { ...bindings }
    if (b) next[key] = b
    else delete next[key]
    onChange(next)
  }
  return (
    <div className="rounded-xl border border-line bg-surface">
      <div className="border-b border-line px-4 py-3">
        <p className="font-medium text-sm">{t('doc.kw_title')}</p>
        <p className="text-xs text-muted mt-0.5">{t('doc.kw_hint')}</p>
      </div>
      {!used.length && <p className="px-4 py-3 text-sm text-muted">{t('doc.no_keywords')}</p>}
      <ul className="divide-y divide-line">
        {used.map((key) => {
          const b = bindings[key]
          const auto = known.get(key)
          const type = b?.type ?? 'auto'
          return (
            <li key={key} className="grid gap-2 px-4 py-3">
              <div className="grid gap-1.5 min-w-0">
                <code className={`justify-self-start rounded-md px-1.5 py-0.5 font-mono text-xs ${!b && !auto ? 'bg-warn-soft text-warn' : 'bg-ground'}`}>{`{${key}}`}</code>
                <select
                  aria-label={t('doc.kw_source')}
                  className="h-9 w-full min-w-0 rounded-md border border-line bg-surface px-2 text-sm"
                  value={type}
                  disabled={!canManage}
                  onChange={(e) => {
                    const v = e.target.value
                    set(
                      key,
                      v === 'auto'
                        ? null
                        : v === 'amo'
                          ? { type: 'amo', source: '' }
                          : v === 'date'
                            ? { type: 'date', offset_days: 0, style: 'short' }
                            : v === 'builtin'
                              ? { type: 'builtin', key: 'company_legal_name' }
                              : v === 'text'
                                ? { type: 'text', value: '' }
                                : { type: 'number' },
                    )
                  }}
                >
                  <option value="auto">{auto ? `${t('doc.src_auto')}: ${auto}` : t('doc.src_unset')}</option>
                  <option value="amo">{t('doc.src_amo')}</option>
                  <option value="number">{t('doc.src_number')}</option>
                  <option value="date">{t('doc.src_date')}</option>
                  <option value="builtin">{t('doc.src_builtin')}</option>
                  <option value="text">{t('doc.src_text')}</option>
                </select>
              </div>
              {b?.type === 'amo' && (
                <select className="h-9 w-full min-w-0 rounded-md border border-line bg-surface px-2 text-sm" value={b.source} disabled={!canManage} onChange={(e) => set(key, { type: 'amo', source: e.target.value })}>
                  <option value="">{vars.error ? t('doc.amo_missing') : t('doc.pick_field')}</option>
                  <optgroup label={t('doc.lead')}>
                    {sources.filter((x) => x.group === 'lead').map((x) => (
                      <option key={x.value} value={x.value}>
                        {x.label}
                      </option>
                    ))}
                  </optgroup>
                  <optgroup label={t('doc.contact')}>
                    {sources.filter((x) => x.group === 'contact').map((x) => (
                      <option key={x.value} value={x.value}>
                        {x.label}
                      </option>
                    ))}
                  </optgroup>
                </select>
              )}
              {b?.type === 'date' && (
                <div className="grid grid-cols-[1fr_1fr] gap-2">
                  <label className="flex items-center gap-1.5 text-xs text-muted">
                    {t('doc.date_plus')}
                    <input type="number" className="h-9 w-16 rounded-md border border-line bg-surface px-2 text-sm text-ink" value={b.offset_days} disabled={!canManage}
                      onChange={(e) => set(key, { ...b, offset_days: Math.max(-3650, Math.min(3650, Number(e.target.value) || 0)) })} />
                    {t('doc.days')}
                  </label>
                  <select className="h-9 rounded-md border border-line bg-surface px-2 text-sm" value={b.style} disabled={!canManage} onChange={(e) => set(key, { ...b, style: e.target.value as 'short' | 'long' | 'ru' })}>
                    <option value="short">25.09.2026</option>
                    <option value="long">25-sentyabr 2026-yil</option>
                    <option value="ru">25 сентября 2026 г.</option>
                  </select>
                </div>
              )}
              {b?.type === 'builtin' && (
                <select className="h-9 w-full min-w-0 rounded-md border border-line bg-surface px-2 text-sm" value={b.key} disabled={!canManage} onChange={(e) => set(key, { type: 'builtin', key: e.target.value })}>
                  {keywords.filter((k) => BUILTIN_KEYS.has(k.key)).map((k) => (
                    <option key={k.key} value={k.key}>
                      {k.label}
                    </option>
                  ))}
                </select>
              )}
              {b?.type === 'text' && (
                <input className="h-9 rounded-md border border-line bg-surface px-2 text-sm" value={b.value} placeholder={t('doc.text_ph')} disabled={!canManage} onChange={(e) => set(key, { type: 'text', value: e.target.value })} />
              )}
              {b?.type === 'number' && <p className="text-xs text-muted">{t('doc.src_number_hint')}</p>}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

const BUILTIN_KEYS = new Set([
  'number', 'date', 'company', 'company_legal_name', 'company_tin', 'company_address', 'company_director', 'company_phone',
  'company_bank', 'company_mfo', 'company_account', 'lead_name', 'lead_id', 'amount', 'amount_words', 'name', 'phone', 'link',
])

// ---------------------------------------------------------------- keywords (amoCRM fields)

type AmoVars = { variables: { key: string; source: string; label: string }[]; sources: { value: string; group: string; label: string }[] }

function KeywordsTab({ canManage }: { canManage: boolean }) {
  const { t } = useT()
  const qc = useQueryClient()
  const kw = useQuery({ queryKey: ['doc-keywords'], queryFn: () => get<Keywords>('/documents/keywords') })
  const vars = useQuery({ queryKey: ['amo-vars'], queryFn: () => get<AmoVars>('/amocrm/variables'), retry: false })
  const [rows, setRows] = useState<{ key: string; source: string; label: string }[]>([])
  const [saved, setSaved] = useState(false)
  useEffect(() => {
    if (vars.data) setRows(vars.data.variables)
  }, [vars.data])
  const save = useMutation({
    mutationFn: () => put<AmoVars>('/amocrm/variables', rows.filter((r) => r.key || r.source)),
    onSuccess: (d) => {
      qc.setQueryData(['amo-vars'], d)
      qc.invalidateQueries({ queryKey: ['doc-keywords'] })
      qc.invalidateQueries({ queryKey: ['doc-templates'] })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    },
  })
  const sources = vars.data?.sources ?? []
  const group = (g: string) => sources.filter((s) => s.group === g)

  return (
    <div className="grid gap-5">
      <Card>
        <div className="p-5 border-b border-line">
          <h2 className="font-semibold">{t('doc.own_title')}</h2>
          <p className="text-sm text-muted mt-1 max-w-2xl">{t('doc.own_hint')}</p>
        </div>
        <div className="p-5 grid gap-3">
          {vars.error ? (
            <ErrorNote error={vars.error} />
          ) : (
            <>
              {rows.map((r, i) => (
                <div key={i} className="grid sm:grid-cols-[minmax(0,11rem)_minmax(0,1fr)_2.5rem] gap-3 items-center">
                  <div className="flex items-center rounded-lg border border-line bg-surface focus-within:border-accent">
                    <span className="pl-3 text-muted font-mono text-sm">{'{'}</span>
                    <input
                      aria-label={t('vars.key')}
                      className="h-10 w-full bg-transparent px-1 font-mono text-sm focus:outline-none"
                      placeholder="muddat"
                      value={r.key}
                      disabled={!canManage}
                      onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, key: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '') } : x)))}
                    />
                    <span className="pr-3 text-muted font-mono text-sm">{'}'}</span>
                  </div>
                  <Select value={r.source} disabled={!canManage} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, source: e.target.value } : x)))}>
                    <option value="">{t('doc.pick_field')}</option>
                    <optgroup label={t('doc.lead')}>
                      {group('lead').map((s) => (
                        <option key={s.value} value={s.value}>
                          {s.label}
                        </option>
                      ))}
                    </optgroup>
                    <optgroup label={t('doc.contact')}>
                      {group('contact').map((s) => (
                        <option key={s.value} value={s.value}>
                          {s.label}
                        </option>
                      ))}
                    </optgroup>
                  </Select>
                  {canManage ? (
                    <button type="button" aria-label={t('vars.remove')} className="h-10 rounded-lg border border-line text-muted hover:border-bad hover:text-bad" onClick={() => setRows(rows.filter((_, j) => j !== i))}>
                      ✕
                    </button>
                  ) : (
                    <span />
                  )}
                </div>
              ))}
              {!rows.length && vars.isSuccess && <p className="text-sm text-muted">{t('vars.empty')}</p>}
              <ErrorNote error={save.error} />
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
            </>
          )}
        </div>
      </Card>
      <Card className="p-5 grid gap-3">
        <h2 className="font-semibold">{t('doc.builtin_title')}</h2>
        <div className="grid sm:grid-cols-2 gap-x-6 gap-y-1.5">
          {kw.data?.builtins.map((b) => (
            <div key={b.key} className="flex items-baseline gap-3 text-sm">
              <code className="rounded-md bg-ground px-1.5 py-0.5 font-mono text-xs">{`{${b.key}}`}</code>
              <span className="text-muted">{b.label}</span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------- made

function MadeTab() {
  const { t } = useT()
  const q = useQuery({ queryKey: ['doc-made'], queryFn: () => get<Doc[]>('/documents/documents') })
  if (q.data && !q.data.length) return <p className="text-sm text-muted">{t('doc.made_none')}</p>
  return (
    <Card>
      <ul className="divide-y divide-line">
        {q.data?.map((d) => (
          <li key={d.id} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm">
            <span className="font-mono font-medium">№ {d.number}</span>
            <span className="text-muted">{d.template}</span>
            <Pill tone="neutral">{d.format === 'pdf' ? 'PDF' : 'Word'}</Pill>
            {d.lead_url && (
              <a className="text-accent" href={d.lead_url} target="_blank" rel="noopener">
                #{d.lead_id} ↗
              </a>
            )}
            <span className="text-xs text-muted ml-auto">
              {d.created_by && `${d.created_by} · `}
              {when(d.updated_at)}
            </span>
            <a className="text-accent font-medium" href={d.url} target="_blank" rel="noopener">
              {t('doc.open')} ↓
            </a>
          </li>
        ))}
      </ul>
      <div className="px-5 pb-4">
        <ErrorNote error={q.error} />
      </div>
    </Card>
  )
}
