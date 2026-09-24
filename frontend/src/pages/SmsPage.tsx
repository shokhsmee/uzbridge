import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { Me } from '../App'
import { Button, Card, CopyField, ErrorNote, Field, Input, PageHeader, Pill, Select, Toggle } from '../components/ui'
import { api, get, post, put, when } from '../lib/api'
import { useT } from '../lib/i18n'

type Provider = 'eskiz' | 'playmobile'
type Account = {
  id: number
  provider: Provider
  provider_label: string
  label: string
  is_enabled: boolean
  is_configured: boolean
  login: string
  secret_masked: string
  sender: string
  balance: string
  checked_at: string | null
  last_error: string
  dlr_url: string
}
type Template = { id: number; provider: Provider; account_id: number | null; text: string; status: string; approved: boolean; in_amocrm: boolean }
type Settings = { provider: string; account_id: number | null; link_template_id: number | null; paid_template_id: number | null }
const GATEWAYS: { key: Provider; name: string; logo: string }[] = [
  { key: 'eskiz', name: 'Eskiz', logo: '/brands/eskiz.svg' },
  { key: 'playmobile', name: 'Playmobile', logo: '/brands/playmobile.png' },
]
const accountName = (a: Account) => (a.label ? `${a.provider_label} · ${a.label}` : a.provider_label)
type Message = {
  id: number
  provider: Provider
  account: string
  phone: string
  text: string
  event: 'manual' | 'link' | 'paid' | 'amocrm' | 'api'
  status: 'queued' | 'sent' | 'delivered' | 'failed'
  provider_status: string
  error: string
  invoice: string
  created_at: string
}

const TABS = ['keys', 'templates', 'history'] as const
type Tab = (typeof TABS)[number]

export default function SmsPage({ me }: { me: Me }) {
  const { t } = useT()
  const canManage = me.role !== 'member'
  const [tab, setTab] = useState<Tab>('keys')
  return (
    <>
      <PageHeader title={t('sms.title')} lede={t('sms.lede')} />
      <div className="inline-flex rounded-lg border border-line bg-surface p-0.5 text-sm mb-6">
        {TABS.map((k) => (
          <button key={k} onClick={() => setTab(k)} className={`rounded-md px-4 py-1.5 ${tab === k ? 'bg-ink text-white' : 'text-muted hover:text-ink'}`}>
            {t(`sms.tab.${k}`)}
          </button>
        ))}
      </div>
      {tab === 'keys' && <Keys canManage={canManage} />}
      {tab === 'templates' && <Templates canManage={canManage} />}
      {tab === 'history' && <History />}
    </>
  )
}

// ---------------------------------------------------------------- keys

function Keys({ canManage }: { canManage: boolean }) {
  const { t } = useT()
  const accounts = useQuery({ queryKey: ['sms-accounts'], queryFn: () => get<Account[]>('/sms/accounts') })
  const settings = useQuery({ queryKey: ['sms-settings'], queryFn: () => get<Settings>('/sms/settings') })
  return (
    <div className="grid gap-5">
      {accounts.data &&
        GATEWAYS.map((g) => <GatewayCard key={g.key} gateway={g} accounts={accounts.data.filter((a) => a.provider === g.key)} canManage={canManage} />)}
      {settings.data && accounts.data && <DefaultAccount settings={settings.data} accounts={accounts.data} canManage={canManage} />}
      <TestSend canManage={canManage} />
      <p className="text-xs text-muted">{t('sms.keys_note')}</p>
    </div>
  )
}

/** One gateway and all of its accounts; off until an account's login is entered. */
function GatewayCard({ gateway, accounts, canManage }: { gateway: (typeof GATEWAYS)[number]; accounts: Account[]; canManage: boolean }) {
  const { t } = useT()
  const [adding, setAdding] = useState(false)
  const [openId, setOpenId] = useState<number | null>(null)
  const any = accounts.length > 0
  const on = accounts.some((a) => a.is_enabled)
  return (
    <Card>
      <div className="flex items-center gap-4 p-5">
        <img src={gateway.logo} alt="" className="size-11 shrink-0 rounded-xl border border-line bg-white object-contain p-1" />
        <div className="min-w-0">
          <h2 className="font-semibold">{gateway.name}</h2>
          <p className="text-xs text-muted">{any ? t('pr.accounts_n').replace('{n}', String(accounts.length)) : t('sms.off_hint')}</p>
        </div>
        <div className="ml-auto flex items-center gap-3">
          {on ? <Pill tone="active">{t('pr.on')}</Pill> : <Pill tone="neutral">{t('pr.off')}</Pill>}
          {!any && canManage && <Toggle id={`${gateway.key}-first`} checked={adding} onChange={setAdding} label="" />}
        </div>
      </div>
      {accounts.map((a) => (
        <SmsAccountRow key={a.id} a={a} open={openId === a.id} onToggleOpen={() => setOpenId(openId === a.id ? null : a.id)} canManage={canManage} />
      ))}
      {adding && (
        <div className="border-t border-line">
          <SmsAccountForm provider={gateway.key} onDone={() => setAdding(false)} canManage={canManage} />
        </div>
      )}
      {any && canManage && !adding && (
        <div className="border-t border-line px-5 py-3">
          <button type="button" className="text-sm font-medium text-accent hover:text-accent-ink" onClick={() => setAdding(true)}>
            + {t('sms.add_account')}
          </button>
        </div>
      )}
    </Card>
  )
}

function SmsAccountRow({ a, open, onToggleOpen, canManage }: { a: Account; open: boolean; onToggleOpen: () => void; canManage: boolean }) {
  const { t } = useT()
  const qc = useQueryClient()
  const flip = useMutation({
    mutationFn: (is_enabled: boolean) => put<Account>(`/sms/accounts/${a.id}`, { label: a.label, login: a.login, sender: a.sender, is_enabled }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sms-accounts'] })
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
            <span className="block text-xs text-muted truncate">{a.login || t('pr.no_keys')}</span>
          </span>
        </button>
        {a.provider === 'eskiz' && a.balance !== '' && (
          <span className="text-sm font-mono tabular text-muted">
            {t('sms.balance')}: <strong className="text-ink">{Number(a.balance).toLocaleString('ru-RU')}</strong>
          </span>
        )}
        {!a.is_configured && <Pill tone="neutral">{t('pr.incomplete')}</Pill>}
        {canManage && (
          <Toggle id={`sms-${a.id}`} checked={a.is_enabled} onChange={(v) => (a.is_configured || !v ? flip.mutate(v) : onToggleOpen())} label={a.is_enabled ? t('pr.on') : t('pr.off')} />
        )}
      </div>
      {flip.error && (
        <div className="px-5 pb-3">
          <ErrorNote error={flip.error} />
        </div>
      )}
      {open && <SmsAccountForm provider={a.provider} account={a} onDone={onToggleOpen} canManage={canManage} />}
    </div>
  )
}

function SmsAccountForm({ provider, account, onDone, canManage }: { provider: Provider; account?: Account; onDone: () => void; canManage: boolean }) {
  const { t } = useT()
  const qc = useQueryClient()
  const [label, setLabel] = useState(account?.label ?? '')
  const [login, setLogin] = useState(account?.login ?? '')
  const [secret, setSecret] = useState('')
  const [sender, setSender] = useState(account?.sender ?? '')
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['sms-accounts'] })
    qc.invalidateQueries({ queryKey: ['billing'] })
  }
  const save = useMutation({
    mutationFn: () => {
      const body = { label, login, sender, is_enabled: account ? account.is_enabled || !account.is_configured : true, ...(secret ? { secret } : {}) }
      return account ? put<Account>(`/sms/accounts/${account.id}`, body) : post<Account>('/sms/accounts', { provider, ...body })
    },
    onSuccess: () => {
      setSecret('')
      refresh()
      onDone()
    },
  })
  const check = useMutation({ mutationFn: () => post<Account>(`/sms/accounts/${account!.id}/check`), onSuccess: refresh })
  const remove = useMutation({ mutationFn: () => api(`/sms/accounts/${account!.id}`, { method: 'DELETE' }), onSuccess: refresh })
  const isEskiz = provider === 'eskiz'
  const idp = `${provider}-${account?.id ?? 'new'}`
  return (
    <form
      className="p-5 grid gap-4 bg-ground/40"
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate()
      }}
    >
      {!account && <p className="text-sm text-muted">{t('sms.new_hint')}</p>}
      <div className="grid sm:grid-cols-2 gap-4">
        <Field label={t('pr.label')} hint={t('pr.label_hint')}>
          <Input id={`${idp}-label`} value={label} disabled={!canManage} placeholder={t('pr.label_ph')} onChange={(e) => setLabel(e.target.value)} />
        </Field>
        <Field label={isEskiz ? 'Email' : 'Login'}>
          <Input id={`${idp}-login`} value={login} disabled={!canManage} onChange={(e) => setLogin(e.target.value)} autoComplete="off" />
        </Field>
        <Field label={isEskiz ? t('sms.password') : 'Password'} hint={account?.secret_masked ? `${account.secret_masked} · ${t('pr.keep')}` : undefined}>
          <Input id={`${idp}-secret`} type="password" autoComplete="new-password" value={secret} disabled={!canManage} placeholder={account?.secret_masked} onChange={(e) => setSecret(e.target.value)} />
        </Field>
        <Field label={isEskiz ? t('sms.sender_eskiz') : t('sms.sender_pm')} hint={isEskiz ? t('sms.sender_hint') : undefined}>
          <Input id={`${idp}-sender`} className="font-mono" maxLength={11} value={sender} disabled={!canManage} onChange={(e) => setSender(e.target.value)} placeholder={isEskiz ? '4546' : ''} />
        </Field>
      </div>
      {!isEskiz && account?.dlr_url && (
        <div className="grid gap-2 rounded-lg bg-accent-soft/60 p-4">
          <p className="text-sm font-medium">{t('sms.dlr')}</p>
          <CopyField value={account.dlr_url} />
          <p className="text-xs text-muted">{t('sms.dlr_hint')}</p>
        </div>
      )}
      {account?.last_error && <p className="rounded-lg bg-bad-soft text-bad text-sm px-3 py-2">{account.last_error}</p>}
      <ErrorNote error={save.error || check.error || remove.error} />
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" busy={save.isPending} disabled={!canManage}>
          {account ? t('amo.save') : t('pr.save_on')}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          {t('pr.cancel')}
        </Button>
        {isEskiz && account?.is_configured && (
          <Button type="button" variant="ghost" busy={check.isPending} onClick={() => check.mutate()}>
            {t('sms.check')}
          </Button>
        )}
        {account?.checked_at && <span className="text-xs text-muted">{when(account.checked_at)}</span>}
        {account && canManage && (
          <Button type="button" variant="danger" className="ml-auto" busy={remove.isPending} onClick={() => confirm(t('pr.delete_q')) && remove.mutate()}>
            {t('pr.delete')}
          </Button>
        )}
      </div>
    </form>
  )
}

/** Which account sends when an integration hasn't picked its own. */
function DefaultAccount({ settings, accounts, canManage }: { settings: Settings; accounts: Account[]; canManage: boolean }) {
  const { t } = useT()
  const qc = useQueryClient()
  const save = useMutation({
    mutationFn: (account_id: number) => put<Settings>('/sms/settings', { ...settings, account_id }),
    onSuccess: (d) => {
      qc.setQueryData(['sms-settings'], d)
      qc.invalidateQueries({ queryKey: ['sms-templates'] })
    },
  })
  const ready = accounts.filter((a) => a.is_configured && a.is_enabled)
  if (ready.length < 2) return null
  return (
    <Card className="p-5 grid sm:grid-cols-[1fr_260px] gap-3 items-center">
      <div>
        <p className="font-semibold">{t('sms.active')}</p>
        <p className="text-sm text-muted">{t('sms.active_hint')}</p>
      </div>
      <Select id="sms-default" value={settings.account_id ?? ready[0].id} disabled={!canManage} onChange={(e) => save.mutate(Number(e.target.value))}>
        {ready.map((a) => (
          <option key={a.id} value={a.id}>
            {accountName(a)}
          </option>
        ))}
      </Select>
    </Card>
  )
}

function TestSend({ canManage }: { canManage: boolean }) {
  const { t } = useT()
  const qc = useQueryClient()
  const [phone, setPhone] = useState('')
  const [text, setText] = useState('Bu Eskiz dan test')
  const [ok, setOk] = useState(false)
  const send = useMutation({
    mutationFn: () => post('/sms/test', { phone, text }),
    onSuccess: () => {
      setOk(true)
      setTimeout(() => setOk(false), 3000)
      qc.invalidateQueries({ queryKey: ['sms-messages'] })
    },
  })
  return (
    <Card className="p-5 grid gap-4">
      <h2 className="font-semibold">{t('sms.test')}</h2>
      <div className="grid sm:grid-cols-[200px_1fr] gap-4">
        <Field label={t('sms.phone')}>
          <Input id="test-phone" inputMode="tel" placeholder="+998 90 123 45 67" value={phone} onChange={(e) => setPhone(e.target.value)} />
        </Field>
        <Field label={t('sms.text')} hint={t('sms.test_hint')}>
          <Input id="test-text" value={text} onChange={(e) => setText(e.target.value)} />
        </Field>
      </div>
      <ErrorNote error={send.error} />
      <div className="flex items-center gap-3">
        <Button busy={send.isPending} disabled={!canManage || !phone || !text} onClick={() => send.mutate()}>
          {t('sms.send')}
        </Button>
        {ok && <span className="text-sm text-ok">✓ {t('sms.queued')}</span>}
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------- templates

function Templates({ canManage }: { canManage: boolean }) {
  const { t } = useT()
  const qc = useQueryClient()
  const list = useQuery({ queryKey: ['sms-templates'], queryFn: () => get<Template[]>('/sms/templates') })
  const settings = useQuery({ queryKey: ['sms-settings'], queryFn: () => get<Settings>('/sms/settings') })
  const accounts = useQuery({ queryKey: ['sms-accounts'], queryFn: () => get<Account[]>('/sms/accounts') })
  const amo = useQuery({ queryKey: ['sms-amocrm'], queryFn: () => get<{ connected: boolean; field_id: number | null }>('/sms/amocrm') })
  const [draft, setDraft] = useState('')
  const ready = (accounts.data ?? []).filter((a) => a.is_configured && a.is_enabled)
  const [picked, setPicked] = useState<number | null>(null)
  const current = ready.find((a) => a.id === picked) ?? ready.find((a) => a.id === settings.data?.account_id) ?? ready[0]
  const active: Provider = current?.provider ?? 'eskiz'
  // Unlinked (older) templates count for every account of their gateway.
  const mine = (list.data ?? []).filter((x) => (current ? x.account_id === current.id || (x.account_id === null && x.provider === active) : false))
  const approved = mine.filter((x) => x.approved)
  const pending = mine.filter((x) => !x.approved)
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['sms-templates'] })
    qc.invalidateQueries({ queryKey: ['sms-amocrm'] })
  }

  const sync = useMutation({ mutationFn: () => post<Template[]>('/sms/templates/sync'), onSuccess: refresh })
  const add = useMutation({
    mutationFn: () => post<Template[]>('/sms/templates', { text: draft, account_id: current?.id }),
    onSuccess: () => {
      setDraft('')
      refresh()
    },
  })
  const remove = useMutation({ mutationFn: (id: number) => api_delete(`/sms/templates/${id}`), onSuccess: refresh })
  const toAmo = useMutation({ mutationFn: () => post('/sms/amocrm/sync'), onSuccess: refresh })
  const auto = useMutation({
    mutationFn: (patch: Partial<Settings>) => put<Settings>('/sms/settings', { ...settings.data, ...patch }),
    onSuccess: (d) => qc.setQueryData(['sms-settings'], d),
  })

  return (
    <div className="grid gap-5">
      <Card className="p-5 grid gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold">{t('sms.approved')}</h2>
            <p className="text-sm text-muted">{active === 'eskiz' ? t('sms.approved_hint') : t('sms.local_hint')}</p>
          </div>
          {ready.length > 1 && (
            <Select id="tpl-account" className="w-auto min-w-52" value={current?.id} onChange={(e) => setPicked(Number(e.target.value))}>
              {ready.map((a) => (
                <option key={a.id} value={a.id}>
                  {accountName(a)}
                </option>
              ))}
            </Select>
          )}
          {active === 'eskiz' && (
            <Button variant="ghost" className="h-8" busy={sync.isPending} disabled={!canManage} onClick={() => sync.mutate()}>
              ↻ {t('sms.sync')}
            </Button>
          )}
        </div>
        {approved.length === 0 ? (
          <p className="text-sm text-muted">{t('sms.none')}</p>
        ) : (
          <ul className="grid gap-2">
            {approved.map((x) => (
              <li key={x.id} className="flex items-start gap-3 rounded-lg border border-line px-3 py-2.5">
                <span className="flex-1 text-sm whitespace-pre-wrap">{x.text}</span>
                {x.in_amocrm && <Pill tone="accent">amoCRM</Pill>}
                {x.status === 'reklama' && <Pill tone="pending">reklama</Pill>}
                {x.status === 'local' && canManage && (
                  <button className="text-xs text-bad" onClick={() => remove.mutate(x.id)}>
                    ✕
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
        {pending.length > 0 && <p className="text-xs text-muted">{t('sms.pending').replace('{n}', String(pending.length))}</p>}
        <div className="grid sm:grid-cols-[1fr_auto] gap-2 items-end">
          <Field label={active === 'eskiz' ? t('sms.submit') : t('sms.add')} hint={t('sms.placeholders')}>
            <Input id="tpl-new" value={draft} disabled={!canManage} onChange={(e) => setDraft(e.target.value)} placeholder="{company}: toʻlov uchun havola {link}" />
          </Field>
          <Button busy={add.isPending} disabled={!canManage || !draft.trim()} onClick={() => add.mutate()}>
            {active === 'eskiz' ? t('sms.to_moderation') : t('sms.add_btn')}
          </Button>
        </div>
        <ErrorNote error={sync.error || add.error || remove.error} />
      </Card>

      <Card className="p-5 grid gap-3">
        <h2 className="font-semibold">amoCRM</h2>
        <p className="text-sm text-muted">{t('sms.amo_hint')}</p>
        {amo.data && !amo.data.connected ? (
          <p className="text-sm text-warn">{t('sms.amo_off')}</p>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <Button busy={toAmo.isPending} disabled={!canManage || approved.length === 0} onClick={() => toAmo.mutate()}>
              {amo.data?.field_id ? t('sms.amo_update') : t('sms.amo_create')}
            </Button>
            {amo.data?.field_id && <Pill tone="active">“SMS shablon” ✓</Pill>}
          </div>
        )}
        <ErrorNote error={toAmo.error} />
      </Card>

      {settings.data && (
        <Card className="p-5 grid gap-4">
          <h2 className="font-semibold">{t('sms.auto')}</h2>
          <div className="grid sm:grid-cols-2 gap-4">
            <Field label={t('sms.auto_link')} hint={t('sms.auto_link_hint')}>
              <Select
                id="auto-link"
                value={settings.data.link_template_id ?? ''}
                disabled={!canManage}
                onChange={(e) => auto.mutate({ link_template_id: e.target.value ? Number(e.target.value) : null })}
              >
                <option value="">{t('amo.link_off')}</option>
                {approved
                  .filter((x) => x.text.includes('{link}'))
                  .map((x) => (
                    <option key={x.id} value={x.id}>
                      {x.text.slice(0, 70)}
                    </option>
                  ))}
              </Select>
            </Field>
            <Field label={t('sms.auto_paid')}>
              <Select
                id="auto-paid"
                value={settings.data.paid_template_id ?? ''}
                disabled={!canManage}
                onChange={(e) => auto.mutate({ paid_template_id: e.target.value ? Number(e.target.value) : null })}
              >
                <option value="">{t('amo.link_off')}</option>
                {approved.map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.text.slice(0, 70)}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <ErrorNote error={auto.error} />
        </Card>
      )}
    </div>
  )
}

const api_delete = (path: string) => api(path, { method: 'DELETE' })

// ---------------------------------------------------------------- history

const STATUS_TONE = { queued: 'neutral', sent: 'pending', delivered: 'paid', failed: 'refunded' } as const

function History() {
  const { t } = useT()
  const q = useQuery({ queryKey: ['sms-messages'], queryFn: () => get<Message[]>('/sms/messages?limit=200'), refetchInterval: 15000 })
  const [open, setOpen] = useState<number | null>(null)
  return (
    <Card className="overflow-x-auto">
      <table className="w-full text-sm min-w-[720px]">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wider text-muted border-b border-line">
            <th className="px-4 py-3 font-medium">{t('sms.when')}</th>
            <th className="px-4 py-3 font-medium">{t('sms.phone')}</th>
            <th className="px-4 py-3 font-medium">{t('sms.text')}</th>
            <th className="px-4 py-3 font-medium">{t('sms.source')}</th>
            <th className="px-4 py-3 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {q.data?.map((m) => (
            <tr key={m.id} className="border-b border-line last:border-0 align-top hover:bg-ground cursor-pointer" onClick={() => setOpen(open === m.id ? null : m.id)}>
              <td className="px-4 py-3 text-xs text-muted whitespace-nowrap">{when(m.created_at)}</td>
              <td className="px-4 py-3 font-mono text-xs whitespace-nowrap">+{m.phone}</td>
              <td className="px-4 py-3 max-w-[380px]">
                <p className={open === m.id ? 'whitespace-pre-wrap' : 'truncate'}>{m.text}</p>
                {open === m.id && m.error && <p className="text-xs text-bad mt-1">{m.error}</p>}
              </td>
              <td className="px-4 py-3 text-xs text-muted whitespace-nowrap">
                {t(`sms.ev.${m.event}`)}
                {m.invoice && ` · ${m.invoice}`} · {m.account || (m.provider === 'eskiz' ? 'Eskiz' : 'Playmobile')}
              </td>
              <td className="px-4 py-3">
                <Pill tone={STATUS_TONE[m.status] ?? 'neutral'}>{t(`sms.st.${m.status}`)}</Pill>
              </td>
            </tr>
          ))}
          {q.data && q.data.length === 0 && (
            <tr>
              <td colSpan={5} className="px-4 py-10 text-center text-muted">
                {t('sms.no_history')}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </Card>
  )
}
