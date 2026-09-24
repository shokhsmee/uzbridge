import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import type { Me } from '../App'
import { Button, Card, ErrorNote, Field, PageHeader, Pill, Select, Toggle } from '../components/ui'
import { get, post, put, when } from '../lib/api'
import { useT } from '../lib/i18n'

type Status = { id: number; name: string; color?: string; type?: number }
type Pipeline = { id: number; name: string; is_main?: boolean; statuses: Status[] }
type Amo = {
  connected: boolean
  configured: boolean
  status?: 'active' | 'error' | 'disconnected'
  last_error?: string
  account_id?: number
  host?: string
  connected_at?: string
  pipelines?: Pipeline[]
  pipelines_synced_at?: string
  paid_stages?: Record<string, number>
  add_notes?: boolean
  link_field_id?: number | null
  status_field_id?: number | null
}
type CustomField = { id: number; name: string; type: string }

export default function AmoCrmPage({ me }: { me: Me }) {
  const { t } = useT()
  const qc = useQueryClient()
  const canManage = me.role !== 'member'
  const q = useQuery({ queryKey: ['amocrm'], queryFn: () => get<Amo>('/amocrm/status') })
  const [connectError, setConnectError] = useState<unknown>(null)

  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (e.data?.source !== 'uzbridge-amocrm') return
      if (!e.data.ok) setConnectError(new Error(e.data.message))
      qc.invalidateQueries({ queryKey: ['amocrm'] })
      qc.invalidateQueries({ queryKey: ['overview'] })
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [qc])

  const connect = async () => {
    setConnectError(null)
    try {
      const { url } = await get<{ url: string }>('/amocrm/connect-url')
      const w = 720, h = 720
      const popup = window.open(url, 'amocrm-oauth', `width=${w},height=${h},left=${(screen.width - w) / 2},top=${(screen.height - h) / 2}`)
      if (!popup) window.location.href = url
    } catch (e) {
      setConnectError(e)
    }
  }

  const data = q.data
  return (
    <>
      <PageHeader title={t('amo.title')} lede={t('amo.lede')} />
      {!data ? null : !data.connected ? (
        <Card className="p-6 grid gap-4 max-w-xl">
          {!data.configured && <p className="rounded-lg bg-warn-soft text-warn text-sm px-3 py-2">{t('amo.not_configured')}</p>}
          <ErrorNote error={connectError} />
          <div>
            <Button onClick={connect} disabled={!canManage || !data.configured}>
              {t('amo.connect')}
            </Button>
          </div>
        </Card>
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
                <div>
                  <Button variant="ghost" onClick={connect}>
                    {t('amo.connect')}
                  </Button>
                </div>
              </div>
            )}
          </Card>
          <SettingsForm data={data} canManage={canManage} />
        </div>
      )}
    </>
  )
}

function Disconnect() {
  const { t } = useT()
  const qc = useQueryClient()
  const [confirm, setConfirm] = useState(false)
  const m = useMutation({
    mutationFn: () => post('/amocrm/disconnect'),
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
  const [stages, setStages] = useState<Record<string, number>>(data.paid_stages ?? {})
  const [addNotes, setAddNotes] = useState(data.add_notes ?? true)
  const [linkField, setLinkField] = useState<number | null>(data.link_field_id ?? null)
  const [statusField, setStatusField] = useState<number | null>(data.status_field_id ?? null)
  const [saved, setSaved] = useState(false)

  const fields = useQuery({ queryKey: ['amocrm-fields'], queryFn: () => get<CustomField[]>('/amocrm/custom-fields'), enabled: data.status === 'active' })
  const refresh = useMutation({
    mutationFn: () => post<Amo>('/amocrm/pipelines/refresh'),
    onSuccess: (d) => {
      qc.setQueryData(['amocrm'], d)
      setStages(d.paid_stages ?? {})
    },
  })
  const save = useMutation({
    mutationFn: () => put<Amo>('/amocrm/settings', { paid_stages: stages, add_notes: addNotes, link_field_id: linkField, status_field_id: statusField }),
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
        {(data.pipelines ?? []).map((p) => (
          <div key={p.id} className="grid sm:grid-cols-[1fr_280px] gap-2 sm:items-center">
            <span className="text-sm">
              {p.name} {p.is_main && <span className="text-muted text-xs">· main</span>}
            </span>
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
      <ErrorNote error={save.error || refresh.error} />
      <div className="flex items-center gap-3">
        <Button busy={save.isPending} onClick={() => save.mutate()} disabled={!canManage}>
          {t('amo.save')}
        </Button>
        {saved && <span className="text-sm text-ok">✓ {t('amo.saved')}</span>}
      </div>
    </Card>
  )
}
