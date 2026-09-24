// /s/<key>: the showroom. A project's public key (buyers look) or a signed deal
// key from the amoCRM widget (the manager picks units for that deal).
import { useCallback, useEffect, useMemo, useState } from 'react'
import { LangSwitch } from '../components/ui'
import { useT } from '../lib/i18n'
import { area, Board, money, roomsLabel, UnitCard, useW, type Unit } from './board'

type Project = {
  id: number
  name: string
  currency: string
  address: string
  stats: { counts: Record<string, number>; total: number; sold_pct: number }
}
type Data = { mode: 'public' | 'deal'; lead_id: number | null; projects: Project[]; units: Unit[] }

const S = {
  pick: { uz: 'Bitimga biriktirish', ru: 'Добавить в сделку' },
  unpick: { uz: 'Bitimdan olib tashlash', ru: 'Убрать из сделки' },
  deal: { uz: 'Bitim', ru: 'Сделка' },
  deal_hint: { uz: 'Obyektni tanlang va “Bitimga biriktirish”ni bosing: narx byudjetga, maʼlumotlar bitimning uzbridge boʻlimiga yoziladi.', ru: 'Выберите объект и нажмите «Добавить в сделку»: цена попадёт в бюджет, данные — во вкладку uzbridge сделки.' },
  in_deal: { uz: 'Bitimda', ru: 'В сделке' },
  taken: { uz: 'Bu obyekt boshqa bitimda', ru: 'Этот объект в другой сделке' },
  sold: { uz: 'Sotilgan — biriktirib boʻlmaydi', ru: 'Продано — добавить нельзя' },
  closed: { uz: 'Sotuvda emas', ru: 'Не в продаже' },
  done: { uz: 'Bitimga biriktirildi', ru: 'Добавлено в сделку' },
  removed: { uz: 'Bitimdan olib tashlandi', ru: 'Убрано из сделки' },
  close: { uz: 'Yopish', ru: 'Закрыть' },
  sold_pct: { uz: 'sotilgan', ru: 'продано' },
  free: { uz: 'boʻsh', ru: 'свободно' },
  load_err: { uz: 'Showroom ochilmadi', ru: 'Не удалось открыть шоурум' },
} as const

async function call<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api/realty/showroom/${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { Accept: 'application/json', ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const json = await res.json().catch(() => null)
  if (!res.ok) throw new Error((json && typeof json.detail === 'string' && json.detail) || `Error ${res.status}`)
  return json as T
}

// Tell the amoCRM widget around us (if any) to refresh the deal.
function notifyParent(action: string, unit: Unit) {
  if (window.parent !== window) window.parent.postMessage({ type: 'uzbridge-realty', action, unit: unit.id }, '*')
}

export default function Showroom({ keyParam }: { keyParam: string }) {
  const { lang } = useT()
  const s = (k: keyof typeof S) => S[k][lang]
  const w = useW()
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState('')
  const [projectId, setProjectId] = useState<number | null>(null)
  const [picked, setPicked] = useState<Unit | null>(null)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState('')

  const load = useCallback(async () => {
    try {
      const d = await call<Data>(encodeURIComponent(keyParam))
      setData(d)
      setProjectId((p) => p ?? d.projects[0]?.id ?? null)
      setPicked((u) => (u ? (d.units.find((x) => x.id === u.id) ?? null) : null))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [keyParam])
  useEffect(() => {
    load()
  }, [load])
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(''), 3500)
    return () => clearTimeout(t)
  }, [toast])

  const project = data?.projects.find((p) => p.id === projectId) ?? data?.projects[0]
  const units = useMemo(() => (data?.units ?? []).filter((u) => !project || u.project === project.id), [data, project])
  const mine = useMemo(() => (data?.units ?? []).filter((u) => u.mine), [data])
  useEffect(() => {
    if (project) document.title = project.name
  }, [project])

  const act = async (u: Unit, action: 'attach' | 'detach') => {
    setBusy(true)
    setError('')
    try {
      await call(`${encodeURIComponent(keyParam)}/${action}`, { unit_id: u.id })
      notifyParent(action, u)
      setToast(action === 'attach' ? s('done') : s('removed'))
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (!data) {
    return (
      <div className="grid min-h-screen place-items-center p-6 text-center">
        {error ? (
          <div>
            <p className="font-semibold">{s('load_err')}</p>
            <p className="mt-1 text-sm text-muted">{error}</p>
          </div>
        ) : (
          <span className="size-6 animate-spin rounded-full border-2 border-accent border-r-transparent" />
        )}
      </div>
    )
  }
  const currency = project?.currency ?? 'UZS'
  const deal = data.mode === 'deal'
  const free = project?.stats.counts.free ?? 0

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-line bg-surface/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold tracking-tight">{project?.name ?? '—'}</h1>
            {project && (
              <p className="truncate text-sm text-muted">
                {project.address && `${project.address} · `}
                <span className="text-[#1f9254] font-medium">
                  {free} {s('free')}
                </span>
                {' · '}
                {project.stats.sold_pct}% {s('sold_pct')}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            {deal && data.lead_id && (
              <span className="rounded-lg bg-accent-soft px-2.5 py-1 text-sm font-medium text-accent-ink">
                {s('deal')} #{data.lead_id}
              </span>
            )}
            <LangSwitch />
          </div>
        </div>
        {data.projects.length > 1 && (
          <nav className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-4 pb-2 sm:px-6">
            {data.projects.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => {
                  setProjectId(p.id)
                  setPicked(null)
                }}
                className={`shrink-0 rounded-lg px-3 py-1.5 text-sm font-medium ${p.id === project?.id ? 'bg-ink text-white' : 'text-muted hover:bg-ground'}`}
              >
                {p.name}
              </button>
            ))}
          </nav>
        )}
      </header>

      <main className="mx-auto grid max-w-7xl grid-cols-[minmax(0,1fr)] gap-4 px-4 py-5 sm:px-6">
        {deal && (
          <div className="grid gap-3 rounded-xl border border-accent/30 bg-accent-soft/60 p-4 text-sm">
            <p>{s('deal_hint')}</p>
            {mine.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {mine.map((u) => (
                  <button
                    key={u.id}
                    type="button"
                    onClick={() => {
                      setProjectId(u.project ?? projectId)
                      setPicked(u)
                    }}
                    className="rounded-lg border border-line bg-surface px-3 py-1.5 text-left hover:border-ink"
                  >
                    <b>
                      {s('in_deal')}: №{u.number}
                    </b>{' '}
                    <span className="text-muted">
                      {roomsLabel(u.rooms, w)} · {area(u.area)} · {money(u.price, data.projects.find((p) => p.id === u.project)?.currency ?? currency)}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        {error && <p className="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{error}</p>}
        <Board key={project?.id} units={units} currency={currency} selected={picked?.id} onPick={setPicked} renderPlan={(u) => <img src={u.plan} alt="" className="max-h-full max-w-full object-contain" loading="lazy" />} />
      </main>

      {picked && (
        <UnitCard unit={picked} currency={currency} planSrc={picked.plan} onClose={() => setPicked(null)} projectName={project?.name}>
          {deal && (
            <div className="sticky bottom-0 -mx-5 -mb-5 border-t border-line bg-surface p-5">
              {picked.mine ? (
                <button
                  type="button"
                  disabled={busy || picked.status === 'sold'}
                  onClick={() => act(picked, 'detach')}
                  className="h-11 w-full rounded-lg border border-line font-medium text-bad hover:border-bad disabled:opacity-50"
                >
                  {s('unpick')}
                </button>
              ) : picked.taken || picked.status === 'sold' || picked.status === 'closed' ? (
                <p className="text-center text-sm text-muted">{picked.taken ? s('taken') : picked.status === 'sold' ? s('sold') : s('closed')}</p>
              ) : (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => act(picked, 'attach')}
                  className="h-11 w-full rounded-lg bg-accent font-medium text-white hover:bg-accent-ink disabled:opacity-50"
                >
                  {busy ? '…' : s('pick')}
                </button>
              )}
            </div>
          )}
        </UnitCard>
      )}
      {toast && (
        <div className="fixed bottom-5 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-ink px-4 py-2.5 text-sm text-white shadow-lg" role="status">
          {toast}
        </div>
      )}
    </div>
  )
}
