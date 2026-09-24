import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { Me } from '../App'
import { Button, Card, CopyField, ErrorNote, Field, Input, PageHeader, Pill, Select, Toggle } from '../components/ui'
import { get, post, put, when } from '../lib/api'
import { AccountPicker } from '../components/AccountPicker'
import { useT } from '../lib/i18n'

type Status = { id: number; name: string; color?: string; type?: number }
type Pipeline = { id: number; name: string; is_main?: boolean; statuses: Status[] }
type Amo = {
  id?: number
  payment_accounts?: number[] | null
  sms_account_id?: number | null
  connected: boolean
  status?: 'active' | 'error' | 'disconnected'
  last_error?: string
  account_id?: number
  host?: string
  connected_at?: string
  pipelines?: Pipeline[]
  pipelines_synced_at?: string
  paid_stages?: Record<string, number>
  link_stages?: Record<string, number>
  widget_client_id?: string
  add_notes?: boolean
  link_field_id?: number | null
  status_field_id?: number | null
}
type CustomField = { id: number; name: string; type: string }
type Conn = { id: number; host: string; status: string; connected_at: string }

// A company may connect several amoCRM accounts; every call names the one on screen.
const ConnQs = createContext('')
const useQs = () => useContext(ConnQs)

export default function AmoCrmPage({ me }: { me: Me }) {
  const { t } = useT()
  const qc = useQueryClient()
  const canManage = me.role !== 'member'
  const conns = useQuery({ queryKey: ['amocrm', 'connections'], queryFn: () => get<Conn[]>('/amocrm/connections') })
  const [picked, setPicked] = useState<number | null>(null)
  const [adding, setAdding] = useState(false)
  const list = conns.data ?? []
  const connId = list.find((c) => c.id === picked)?.id ?? list[0]?.id
  const qs = connId ? `?conn=${connId}` : ''
  const q = useQuery({ queryKey: ['amocrm', connId ?? 0], queryFn: () => get<Amo>('/amocrm/status' + qs), enabled: conns.isSuccess })
  const [connectError, setConnectError] = useState<unknown>(null)

  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (e.data?.source !== 'uzbridge-amocrm') return
      if (!e.data.ok) setConnectError(new Error(e.data.message))
      else setAdding(false)
      qc.invalidateQueries({ queryKey: ['amocrm'] })
      qc.invalidateQueries({ queryKey: ['overview'] })
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [qc])

  const data = q.data
  const showConnect = adding || (data && !data.connected)
  return (
    <ConnQs.Provider value={qs}>
      <PageHeader title={t('amo.title')} lede={t('amo.lede')} logo="/brands/amocrm.png" />
      {list.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 mb-5">
          {list.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => {
                setPicked(c.id)
                setAdding(false)
              }}
              className={`inline-flex items-center gap-2 rounded-lg border px-3 h-9 text-sm ${c.id === connId && !adding ? 'border-accent bg-accent-soft text-accent-ink font-medium' : 'border-line bg-surface text-muted hover:text-ink'}`}
            >
              <span className={`size-2 rounded-full ${c.status === 'active' ? 'bg-ok' : 'bg-bad'}`} aria-hidden />
              {c.host}
            </button>
          ))}
          {canManage && (
            <button
              type="button"
              onClick={() => setAdding(true)}
              className={`rounded-lg border border-dashed px-3 h-9 text-sm font-medium ${adding ? 'border-accent text-accent-ink' : 'border-line text-accent hover:border-accent'}`}
            >
              + {t('amo.add_conn')}
            </button>
          )}
        </div>
      )}
      {!data && !adding ? null : showConnect ? (
        <Card className="p-6 grid gap-4 max-w-xl">
          <ol className="grid gap-2 text-sm text-muted list-decimal pl-5">
            <li>{t('amo.how1')}</li>
            <li>{t('amo.how2')}</li>
            <li>{t('amo.how3')}</li>
          </ol>
          <ErrorNote error={connectError} />
          {canManage ? <AmoButton onError={setConnectError} /> : null}
        </Card>
      ) : null}
      {!data || !data.connected || adding ? (
        <></>
      ) : (
        <div className="grid gap-6">
          <Card className="p-5 flex flex-wrap items-center justify-between gap-4">
            <div className="grid gap-1">
              <p className="text-xs uppercase tracking-wider text-muted">{t('amo.account')}</p>
              <p className="font-mono text-sm">
                {data.host} · #{data.account_id}
              </p>
              <p className="text-xs text-muted">{when(data.connected_at)}</p>
            </div>
            <div className="flex items-center gap-3">
              {data.status === 'active' ? <Pill tone="active">{t('int.connected')}</Pill> : <Pill tone="error">{t('int.error')}</Pill>}
              {canManage && <Disconnect />}
            </div>
            {data.status === 'error' && (
              <div className="basis-full grid gap-2">
                <p className="text-sm text-bad">{data.last_error}</p>
                <AmoButton onError={setConnectError} />
              </div>
            )}
          </Card>
          <AccountsCard key={`acc-${connId}`} data={data} canManage={canManage} />
          <SettingsForm key={`set-${connId}`} data={data} canManage={canManage} />
        </div>
      )}
      {data && canManage && (
        <ManualConnect
          key={adding ? 'new' : `m-${connId}`}
          connected={data.connected && !adding}
          host={data.connected && !adding ? data.host : ''}
          widgetId={data.connected && !adding ? data.widget_client_id : ''}
          onConnected={() => setAdding(false)}
        />
      )}
    </ConnQs.Provider>
  )
}

/** Which Payme / Click / Uzum cash desk and which SMS account this amoCRM account uses. */
function AccountsCard({ data, canManage }: { data: Amo; canManage: boolean }) {
  const { t } = useT()
  const qc = useQueryClient()
  const qs = useQs()
  return (
    <Card className="p-5 grid gap-4">
      <div>
        <h2 className="font-semibold">{t('amo.accounts')}</h2>
        <p className="text-sm text-muted mt-1">{t('amo.accounts_lede')}</p>
      </div>
      <AccountPicker
        value={{ payment_accounts: data.payment_accounts ?? null, sms_account_id: data.sms_account_id ?? null }}
        canManage={canManage}
        onSave={(v) => put<Amo>('/amocrm/accounts' + qs, v).then(() => qc.invalidateQueries({ queryKey: ['amocrm'] }))}
      />
    </Card>
  )
}

/** Hand-made integration: the only kind amoCRM lets carry our widget archive. */
function ManualConnect({ connected, host = '', widgetId = '', onConnected }: { connected: boolean; host?: string; widgetId?: string; onConnected?: () => void }) {
  const { t } = useT()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  // Already connected: the widget's integration needs only its ID and secret, the API tokens stay.
  const keysOnly = connected && !!host
  const [f, setF] = useState({ host, client_id: '', client_secret: '', code: '' })
  const origin = window.location.origin
  const save = useMutation({
    mutationFn: () => post('/amocrm/connect-manual', keysOnly ? { ...f, host, code: '' } : f),
    onSuccess: () => {
      setF({ host, client_id: '', client_secret: '', code: '' })
      setOpen(false)
      onConnected?.()
      qc.invalidateQueries({ queryKey: ['amocrm'] })
      qc.invalidateQueries({ queryKey: ['overview'] })
    },
  })
  return (
    <Card className="mt-6">
      <button type="button" onClick={() => setOpen(!open)} className="w-full flex items-center gap-3 p-5 text-left">
        <span className="font-semibold">{t('amo.widget_title')}</span>
        {connected && <span className="text-sm text-muted">{t('amo.widget_sub')}</span>}
        {widgetId && <Pill tone="active">{t('amo.widget_on')}</Pill>}
        <span className="ml-auto text-muted text-sm">{open ? '−' : '+'}</span>
      </button>
      {open && (
        <div className="border-t border-line p-5 grid gap-5">
          <ol className="grid gap-3 text-sm list-decimal pl-5">
            <li>
              {t('amo.w1')}{' '}
              <a className="text-accent font-medium" href="/uzbridge-widget.zip" download>
                uzbridge-widget.zip ↓
              </a>
            </li>
            <li>{t('amo.w2')}</li>
            <li className="grid gap-2">
              {t('amo.w3')}
              <CopyField value={`${origin}/oauth/amocrm/callback`} />
              <span className="text-muted">{t('amo.w3b')}</span>
              <CopyField value={`${origin}/oauth/amocrm/uninstall`} />
            </li>
            <li>{t('amo.w4')}</li>
            <li>{t(keysOnly ? 'amo.w5_keys' : 'amo.w5')}</li>
          </ol>
          <form
            className="grid gap-4"
            onSubmit={(e) => {
              e.preventDefault()
              save.mutate()
            }}
          >
            <div className="grid sm:grid-cols-2 gap-4">
              <Field label={t('amo.f_host')}>
                <Input id="m-host" placeholder="mycompany.amocrm.ru" value={keysOnly ? host : f.host} readOnly={keysOnly} onChange={(e) => setF({ ...f, host: e.target.value })} />
              </Field>
              <Field label={t('amo.f_id')}>
                <Input id="m-id" className="font-mono" value={f.client_id} onChange={(e) => setF({ ...f, client_id: e.target.value })} />
              </Field>
              <Field label={t('amo.f_secret')}>
                <Input id="m-secret" type="password" autoComplete="off" className="font-mono" value={f.client_secret} onChange={(e) => setF({ ...f, client_secret: e.target.value })} />
              </Field>
              {!keysOnly && (
                <Field label={t('amo.f_code')} hint={t('amo.f_code_hint')}>
                  <Input id="m-code" className="font-mono" value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} />
                </Field>
              )}
            </div>
            <ErrorNote error={save.error} />
            <div>
              <Button type="submit" busy={save.isPending} disabled={!(keysOnly || f.host) || !f.client_id || !f.client_secret || !(keysOnly || f.code)}>
                {t(keysOnly ? 'amo.f_save_keys' : 'amo.f_connect')}
              </Button>
            </div>
          </form>
        </div>
      )}
    </Card>
  )
}

type ButtonParams = { state: string; redirect_uri: string; secrets_uri: string; logo: string; name: string; description: string; scopes: string }

/** amoCRM's own button without a client_id: amoCRM asks which account, creates
 *  an integration there and sends us its keys (developers/content/oauth/button). */
function AmoButton({ onError }: { onError: (e: unknown) => void }) {
  const { t } = useT()
  const box = useRef<HTMLDivElement>(null)
  const [params, setParams] = useState<ButtonParams | null>(null)

  useEffect(() => {
    post<ButtonParams>('/amocrm/connect-button').then(setParams).catch(onError)
  }, [onError])

  useEffect(() => {
    if (!params || !box.current) return
    ;(window as unknown as Record<string, unknown>).uzbridgeAmoError = () => onError(new Error(t('amo.denied')))
    const s = document.createElement('script')
    s.className = 'amocrm_oauth'
    s.charset = 'utf-8'
    const attrs: Record<string, string> = {
      'data-name': params.name,
      'data-description': params.description,
      'data-redirect_uri': params.redirect_uri,
      'data-secrets_uri': params.secrets_uri,
      'data-logo': params.logo,
      'data-scopes': params.scopes,
      'data-title': t('amo.connect'),
      'data-compact': 'false',
      'data-color': 'blue',
      'data-state': params.state,
      'data-error-callback': 'uzbridgeAmoError',
      'data-mode': 'post_message',
    }
    Object.entries(attrs).forEach(([k, v]) => s.setAttribute(k, v))
    s.src = 'https://www.amocrm.ru/auth/button.min.js'
    // amoCRM's script only draws its buttons from window.onload, which has long
    // fired in an SPA, so run that hook ourselves once the script is in.
    s.onload = () => {
      const init = window.onload as ((this: Window, ev: Event) => void) | null
      init?.call(window, new Event('load'))
    }
    const el = box.current
    el.innerHTML = ''
    el.appendChild(s)
    return () => {
      el.innerHTML = ''
    }
    // t changes identity every render; re-injecting would reset amoCRM's button.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params, onError])

  return <div ref={box} className="min-h-10" aria-live="polite" />
}

function Disconnect() {
  const { t } = useT()
  const qc = useQueryClient()
  const qs = useQs()
  const [confirm, setConfirm] = useState(false)
  const m = useMutation({
    mutationFn: () => post('/amocrm/disconnect' + qs),
    onSuccess: () => qc.invalidateQueries(),
  })
  if (!confirm)
    return (
      <Button variant="danger" onClick={() => setConfirm(true)}>
        {t('amo.disconnect')}
      </Button>
    )
  return (
    <span className="flex items-center gap-2">
      <Button variant="danger" busy={m.isPending} onClick={() => m.mutate()}>
        {t('amo.disconnect')} ✓
      </Button>
      <Button variant="ghost" onClick={() => setConfirm(false)}>
        {t('common.close')}
      </Button>
    </span>
  )
}

function SettingsForm({ data, canManage }: { data: Amo; canManage: boolean }) {
  const { t } = useT()
  const qc = useQueryClient()
  const qs = useQs()
  const [stages, setStages] = useState<Record<string, number>>(data.paid_stages ?? {})
  const [linkStages, setLinkStages] = useState<Record<string, number>>(data.link_stages ?? {})
  const [addNotes, setAddNotes] = useState(data.add_notes ?? true)
  const [linkField, setLinkField] = useState<number | null>(data.link_field_id ?? null)
  const [statusField, setStatusField] = useState<number | null>(data.status_field_id ?? null)
  const [saved, setSaved] = useState(false)

  const fields = useQuery({ queryKey: ['amocrm-fields', qs], queryFn: () => get<CustomField[]>('/amocrm/custom-fields' + qs), enabled: data.status === 'active' })
  const refresh = useMutation({
    mutationFn: () => post<Amo>('/amocrm/pipelines/refresh' + qs),
    onSuccess: (d) => {
      qc.setQueryData(['amocrm'], d)
      setStages(d.paid_stages ?? {})
      setLinkStages(d.link_stages ?? {})
    },
  })
  const makeFields = useMutation({
    mutationFn: () => post<Amo>('/amocrm/fields/create' + qs),
    onSuccess: (d) => {
      qc.setQueryData(['amocrm'], d)
      setLinkField(d.link_field_id ?? null)
      setStatusField(d.status_field_id ?? null)
      qc.invalidateQueries({ queryKey: ['amocrm-fields'] })
    },
  })
  const save = useMutation({
    mutationFn: () => put<Amo>('/amocrm/settings' + qs, { paid_stages: stages, link_stages: linkStages, add_notes: addNotes, link_field_id: linkField, status_field_id: statusField }),
    onSuccess: (d) => {
      qc.setQueryData(['amocrm'], d)
      qc.invalidateQueries({ queryKey: ['overview'] })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    },
  })

  return (
    <Card className="p-5 grid gap-5">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-semibold">{t('amo.pipelines')}</h2>
        <Button variant="ghost" className="h-8" busy={refresh.isPending} onClick={() => refresh.mutate()} disabled={!canManage}>
          ↻ {t('amo.refresh')}
        </Button>
      </div>
      <div className="grid gap-3">
        <div className="hidden sm:grid sm:grid-cols-[1fr_240px_240px] gap-2 text-xs uppercase tracking-wider text-muted">
          <span />
          <span>{t('amo.link_stage')}</span>
          <span>{t('amo.paid_stage')}</span>
        </div>
        {(data.pipelines ?? []).map((p) => (
          <div key={p.id} className="grid sm:grid-cols-[1fr_240px_240px] gap-2 sm:items-center">
            <span className="text-sm">
              {p.name} {p.is_main && <span className="text-muted text-xs">· main</span>}
            </span>
            <Select
              id={`link-stage-${p.id}`}
              value={linkStages[String(p.id)] ?? ''}
              disabled={!canManage}
              onChange={(e) =>
                setLinkStages((s) => {
                  const next = { ...s }
                  if (e.target.value) next[String(p.id)] = Number(e.target.value)
                  else delete next[String(p.id)]
                  return next
                })
              }
            >
              <option value="">{t('amo.link_off')}</option>
              {p.statuses.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
            <Select
              id={`stage-${p.id}`}
              value={stages[String(p.id)] ?? 142}
              disabled={!canManage}
              onChange={(e) => setStages((s) => ({ ...s, [String(p.id)]: Number(e.target.value) }))}
            >
              {p.statuses.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          </div>
        ))}
      </div>
      <hr className="border-line" />
      <Toggle id="add-notes" checked={addNotes} onChange={setAddNotes} label={t('amo.notes')} />
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" className="h-8" busy={makeFields.isPending} onClick={() => makeFields.mutate()} disabled={!canManage}>
          + {t('amo.make_fields')}
        </Button>
        <span className="text-xs text-muted">{t('amo.make_fields_hint')}</span>
      </div>
      <div className="grid sm:grid-cols-2 gap-4">
        <Field label={t('amo.link_field')}>
          <Select id="link-field" value={linkField ?? ''} disabled={!canManage} onChange={(e) => setLinkField(e.target.value ? Number(e.target.value) : null)}>
            <option value="">{t('amo.none')}</option>
            {fields.data?.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name} ({f.type})
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t('amo.status_field')}>
          <Select id="status-field" value={statusField ?? ''} disabled={!canManage} onChange={(e) => setStatusField(e.target.value ? Number(e.target.value) : null)}>
            <option value="">{t('amo.none')}</option>
            {fields.data
              ?.filter((f) => f.type !== 'url')
              .map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name} ({f.type})
                </option>
              ))}
          </Select>
        </Field>
      </div>
      <ErrorNote error={save.error || refresh.error || makeFields.error} />
      <div className="flex items-center gap-3">
        <Button busy={save.isPending} onClick={() => save.mutate()} disabled={!canManage}>
          {t('amo.save')}
        </Button>
        {saved && <span className="text-sm text-ok">✓ {t('amo.saved')}</span>}
      </div>
    </Card>
  )
}
