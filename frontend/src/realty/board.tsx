// Shaxmatka views shared by the public/deal showroom and the dashboard:
// the chessboard (blocks → sections → floors), the list, the layouts, and the unit card.
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useT, type Lang } from '../lib/i18n'

export type Status = 'free' | 'interest' | 'reserved' | 'sold' | 'closed'
export const STATUSES: Status[] = ['free', 'interest', 'reserved', 'sold', 'closed']

export type Unit = {
  id: number
  project?: number
  ext_id: string
  kind: string
  block: string
  section: string
  floor: number
  number: string
  rooms: number
  area: number
  price: number | null
  price_m2: number | null
  old_price: number | null
  layout: string
  status: Status
  description: string
  plan: string
  extra: Record<string, string>
  mine?: boolean
  taken?: boolean
  lead_id?: number | null
  lead_url?: string
  has_plan?: boolean
  reserved_until?: string | null
}

// ------------------------------------------------------------------ words

const W = {
  free: { uz: 'Boʻsh', ru: 'Свободно' },
  interest: { uz: 'Qiziqish', ru: 'Интерес' },
  reserved: { uz: 'Band', ru: 'Бронь' },
  sold: { uz: 'Sotilgan', ru: 'Продано' },
  closed: { uz: 'Sotuvda emas', ru: 'Не в продаже' },
  block: { uz: 'Blok', ru: 'Корпус' },
  section: { uz: 'Podyezd', ru: 'Подъезд' },
  floor: { uz: 'Qavat', ru: 'Этаж' },
  number: { uz: '№', ru: '№' },
  rooms: { uz: 'Xonalar', ru: 'Комнат' },
  area: { uz: 'Maydon', ru: 'Площадь' },
  price: { uz: 'Narx', ru: 'Цена' },
  per_m2: { uz: 'm² narxi', ru: 'Цена за м²' },
  status: { uz: 'Holat', ru: 'Статус' },
  studio: { uz: 'Studiya', ru: 'Студия' },
  n_rooms: { uz: '-xonali', ru: '-комн.' },
  layout: { uz: 'Planirovka', ru: 'Планировка' },
  no_plan: { uz: 'Planirovka hali yuklanmagan', ru: 'Планировка ещё не загружена' },
  from: { uz: 'dan', ru: 'от' },
  free_of: { uz: 'boʻsh', ru: 'свободно' },
  view_grid: { uz: 'Shaxmatka', ru: 'Шахматка' },
  view_list: { uz: 'Roʻyxat', ru: 'Список' },
  view_plans: { uz: 'Planirovkalar', ru: 'Планировки' },
  free_only: { uz: 'Faqat boʻshlar', ru: 'Только свободные' },
  reset: { uz: 'Tozalash', ru: 'Сбросить' },
  found: { uz: 'ta topildi', ru: 'найдено' },
  all_blocks: { uz: 'Barcha bloklar', ru: 'Все корпуса' },
  min: { uz: 'dan', ru: 'от' },
  max: { uz: 'gacha', ru: 'до' },
  hidden: { uz: 'soʻrov boʻyicha', ru: 'по запросу' },
  nothing: { uz: 'Filtrga mos obyekt yoʻq', ru: 'Нет объектов по фильтру' },
  empty: { uz: 'Hali obyektlar yoʻq', ru: 'Объектов пока нет' },
  yours: { uz: 'Shu bitimda', ru: 'В этой сделке' },
  taken: { uz: 'Boshqa bitimda', ru: 'В другой сделке' },
  until: { uz: 'Bron muddati', ru: 'Бронь до' },
  more: { uz: 'Qoʻshimcha', ru: 'Дополнительно' },
} as const

export type Word = keyof typeof W
export function useW() {
  const { lang } = useT()
  return (k: Word) => W[k][lang]
}

// ------------------------------------------------------------------ format

export function money(v: number | null | undefined, currency: string): string {
  if (v == null) return '—'
  const s = Math.round(v).toLocaleString('ru-RU').replace(/\s/g, ' ')
  return currency === 'USD' ? `$${s}` : `${s} soʻm`
}

export function short(v: number | null | undefined, currency: string, lang: Lang): string {
  if (v == null) return '—'
  if (currency === 'USD') return v >= 1000 ? `$${Math.round(v / 1000)}k` : `$${Math.round(v)}`
  const mln = lang === 'uz' ? 'mln' : 'млн'
  return v >= 1e6 ? `${(v / 1e6).toFixed(v >= 1e8 ? 0 : 1).replace('.', ',')} ${mln}` : money(v, currency)
}

export const area = (v: number) => `${String(Math.round(v * 10) / 10).replace('.', ',')} m²`

export function roomsLabel(n: number, w: (k: Word) => string) {
  return n === 0 ? w('studio') : `${n}${w('n_rooms')}`
}

const natural = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' })

// Solid, readable colours: free units must stand out, sold ones step back.
export const TONE: Record<Status, string> = {
  free: 'bg-[#1f9254] text-white hover:bg-[#177a45]',
  interest: 'bg-[#2f6fd0] text-white hover:bg-[#2459ab]',
  reserved: 'bg-[#e0a21b] text-[#3b2a00] hover:bg-[#c98f10]',
  sold: 'bg-[#d5dbda] text-[#6b7775]',
  closed: 'bg-[repeating-linear-gradient(45deg,#eef1f1,#eef1f1_4px,#e2e7e6_4px,#e2e7e6_8px)] text-[#8a9593]',
}
export const DOT: Record<Status, string> = {
  free: 'bg-[#1f9254]',
  interest: 'bg-[#2f6fd0]',
  reserved: 'bg-[#e0a21b]',
  sold: 'bg-[#c3cbca]',
  closed: 'bg-[#e2e7e6] border border-line',
}

export function StatusBadge({ status }: { status: Status }) {
  const w = useW()
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-ground px-2.5 py-0.5 text-xs font-medium">
      <span className={`size-2 rounded-full ${DOT[status]}`} />
      {w(status)}
    </span>
  )
}

// ------------------------------------------------------------------ filters

export type Filters = {
  rooms: number[] // 4 = 4 and more
  priceMin: string
  priceMax: string
  areaMin: string
  areaMax: string
  floorMin: string
  floorMax: string
  freeOnly: boolean
  block: string
  layout: string
}
export const NO_FILTERS: Filters = {
  rooms: [],
  priceMin: '',
  priceMax: '',
  areaMin: '',
  areaMax: '',
  floorMin: '',
  floorMax: '',
  freeOnly: false,
  block: '',
  layout: '',
}

const num = (s: string) => (s.trim() === '' ? null : Number(s.replace(/\s/g, '').replace(',', '.')))

export function matches(u: Unit, f: Filters): boolean {
  if (f.rooms.length && !f.rooms.some((r) => (r === 4 ? u.rooms >= 4 : u.rooms === r))) return false
  if (f.freeOnly && u.status !== 'free') return false
  if (f.block && u.block !== f.block) return false
  if (f.layout && (u.layout || `${u.rooms}`) !== f.layout) return false
  const within = (v: number | null, lo: string, hi: string) => {
    const a = num(lo)
    const b = num(hi)
    if (a == null && b == null) return true
    if (v == null) return false
    return (a == null || v >= a) && (b == null || v <= b)
  }
  return within(u.price, f.priceMin, f.priceMax) && within(u.area, f.areaMin, f.areaMax) && within(u.floor, f.floorMin, f.floorMax)
}

export function isFiltered(f: Filters) {
  return JSON.stringify(f) !== JSON.stringify(NO_FILTERS)
}

function RangeInput({ label, lo, hi, onLo, onHi }: { label: string; lo: string; hi: string; onLo: (v: string) => void; onHi: (v: string) => void }) {
  const w = useW()
  const cls = 'h-9 w-full min-w-0 rounded-lg border border-line bg-surface px-2.5 text-sm focus:border-accent focus:outline-none tabular'
  return (
    <div className="grid gap-1 min-w-0">
      <span className="text-xs font-medium text-muted">{label}</span>
      <div className="flex items-center gap-1.5">
        <input className={cls} inputMode="decimal" placeholder={w('min')} value={lo} onChange={(e) => onLo(e.target.value)} />
        <span className="text-muted">–</span>
        <input className={cls} inputMode="decimal" placeholder={w('max')} value={hi} onChange={(e) => onHi(e.target.value)} />
      </div>
    </div>
  )
}

export function FilterBar({ units, filters, onChange, currency, found }: { units: Unit[]; filters: Filters; onChange: (f: Filters) => void; currency: string; found: number }) {
  const w = useW()
  const set = (patch: Partial<Filters>) => onChange({ ...filters, ...patch })
  const roomsHere = useMemo(() => [...new Set(units.map((u) => Math.min(u.rooms, 4)))].sort(), [units])
  const blocks = useMemo(() => [...new Set(units.map((u) => u.block).filter(Boolean))].sort(natural), [units])
  const toggleRoom = (r: number) => set({ rooms: filters.rooms.includes(r) ? filters.rooms.filter((x) => x !== r) : [...filters.rooms, r] })
  return (
    <div className="rounded-xl border border-line bg-surface p-4 grid gap-4">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-4">
        <div className="grid gap-1">
          <span className="text-xs font-medium text-muted">{w('rooms')}</span>
          <div className="flex gap-1.5">
            {roomsHere.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => toggleRoom(r)}
                className={`h-9 min-w-9 rounded-lg border px-2.5 text-sm font-medium transition-colors ${
                  filters.rooms.includes(r) ? 'border-ink bg-ink text-white' : 'border-line bg-surface hover:border-ink'
                }`}
              >
                {r === 0 ? 'S' : r === 4 ? '4+' : r}
              </button>
            ))}
          </div>
        </div>
        {blocks.length > 1 && (
          <label className="grid gap-1">
            <span className="text-xs font-medium text-muted">{w('block')}</span>
            <select
              className="h-9 rounded-lg border border-line bg-surface px-2.5 text-sm focus:border-accent focus:outline-none"
              value={filters.block}
              onChange={(e) => set({ block: e.target.value })}
            >
              <option value="">{w('all_blocks')}</option>
              {blocks.map((b) => (
                <option key={b} value={b}>
                  {w('block')} {b}
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="w-56 max-w-full">
          <RangeInput label={`${w('price')}, ${currency === 'USD' ? '$' : 'soʻm'}`} lo={filters.priceMin} hi={filters.priceMax} onLo={(v) => set({ priceMin: v })} onHi={(v) => set({ priceMax: v })} />
        </div>
        <div className="w-40 max-w-full">
          <RangeInput label={`${w('area')}, m²`} lo={filters.areaMin} hi={filters.areaMax} onLo={(v) => set({ areaMin: v })} onHi={(v) => set({ areaMax: v })} />
        </div>
        <div className="w-36 max-w-full">
          <RangeInput label={w('floor')} lo={filters.floorMin} hi={filters.floorMax} onLo={(v) => set({ floorMin: v })} onHi={(v) => set({ floorMax: v })} />
        </div>
        <label className="inline-flex h-9 items-center gap-2 text-sm cursor-pointer select-none">
          <input type="checkbox" className="size-4 accent-[#1f9254]" checked={filters.freeOnly} onChange={(e) => set({ freeOnly: e.target.checked })} />
          {w('free_only')}
        </label>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
        <span className="text-muted">
          <b className="text-ink tabular">{found}</b> {w('found')}
          {filters.layout && (
            <>
              {' · '}
              {w('layout')} <b className="text-ink">{filters.layout}</b>
            </>
          )}
        </span>
        {isFiltered(filters) && (
          <button type="button" className="text-accent-ink font-medium hover:underline" onClick={() => onChange(NO_FILTERS)}>
            {w('reset')}
          </button>
        )}
      </div>
    </div>
  )
}

export function Legend({ units }: { units: Unit[] }) {
  const w = useW()
  const counts = useMemo(() => {
    const c: Partial<Record<Status, number>> = {}
    units.forEach((u) => (c[u.status] = (c[u.status] ?? 0) + 1))
    return c
  }, [units])
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
      {STATUSES.filter((s) => counts[s]).map((s) => (
        <span key={s} className="inline-flex items-center gap-1.5">
          <span className={`size-3 rounded-[4px] ${DOT[s]}`} />
          {w(s)} <span className="text-muted tabular">{counts[s]}</span>
        </span>
      ))}
    </div>
  )
}

// ------------------------------------------------------------------ chessboard

type Pick = (u: Unit) => void

function Cell({ u, dim, selected, onPick, currency }: { u: Unit; dim: boolean; selected: boolean; onPick: Pick; currency: string }) {
  const w = useW()
  const { lang } = useT()
  const tip = [
    `№${u.number} · ${roomsLabel(u.rooms, w)} · ${area(u.area)}`,
    `${w('floor')} ${u.floor}${u.block ? ` · ${w('block')} ${u.block}` : ''}`,
    u.price != null ? money(u.price, currency) : '',
    w(u.status),
  ]
    .filter(Boolean)
    .join('\n')
  return (
    <button
      type="button"
      title={tip}
      onClick={() => onPick(u)}
      className={`relative flex h-11 w-11 shrink-0 flex-col items-center justify-center rounded-md leading-none transition-all ${TONE[u.status]} ${
        dim ? 'opacity-20' : ''
      } ${selected ? 'ring-2 ring-ink ring-offset-2' : ''} ${u.mine ? 'outline-2 outline-offset-1 outline-ink' : ''}`}
    >
      <span className="text-[13px] font-semibold">{u.rooms === 0 ? 'S' : u.rooms}</span>
      <span className="mt-0.5 text-[9px] opacity-80 tabular">{u.status === 'free' || u.status === 'interest' ? short(u.price, currency, lang).replace(' soʻm', '') : Math.round(u.area)}</span>
      {u.mine && <span className="absolute -right-1 -top-1 size-3 rounded-full border-2 border-white bg-ink" />}
    </button>
  )
}

export function Chessboard({ units, filters, selected, onPick, currency }: { units: Unit[]; filters: Filters; selected?: number; onPick: Pick; currency: string }) {
  const w = useW()
  const blocks = useMemo(() => {
    const byBlock = new Map<string, Map<string, Unit[]>>()
    for (const u of units) {
      if (filters.block && u.block !== filters.block) continue
      const sections = byBlock.get(u.block) ?? new Map<string, Unit[]>()
      byBlock.set(u.block, sections)
      sections.set(u.section, [...(sections.get(u.section) ?? []), u])
    }
    return [...byBlock.entries()]
      .sort(([a], [b]) => natural(a, b))
      .map(([block, sections]) => {
        const list = [...sections.entries()].sort(([a], [b]) => natural(a, b))
        const floors = list.flatMap(([, us]) => us.map((u) => u.floor))
        const top = Math.max(...floors)
        const bottom = Math.min(...floors)
        return {
          block,
          floors: Array.from({ length: top - bottom + 1 }, (_, i) => top - i),
          sections: list.map(([section, us]) => {
            const perFloor = new Map<number, Unit[]>()
            us.forEach((u) => perFloor.set(u.floor, [...(perFloor.get(u.floor) ?? []), u]))
            perFloor.forEach((row) => row.sort((a, b) => natural(a.number, b.number)))
            const width = Math.max(...[...perFloor.values()].map((r) => r.length))
            return { section, perFloor, width }
          }),
        }
      })
  }, [units, filters.block])

  if (!units.length) return <p className="py-16 text-center text-muted">{w('empty')}</p>
  const CELL = 44
  const GAP = 6
  return (
    <div className="flex flex-wrap items-start gap-4">
      {blocks.map((b) => (
        <div key={b.block || '-'} className="max-w-full rounded-xl border border-line bg-surface p-4">
          {b.block && <h3 className="mb-3 text-base font-semibold">{w('block')} {b.block}</h3>}
          <div className="overflow-x-auto pb-2">
            <div className="inline-grid gap-[6px]">
              <div className="flex gap-6 pl-9">
                {b.sections.map((s) => (
                  <div key={s.section} className="text-xs font-medium text-muted" style={{ width: s.width * CELL + (s.width - 1) * GAP }}>
                    {s.section ? `${w('section')} ${s.section}` : ''}
                  </div>
                ))}
              </div>
              {b.floors.map((floor) => (
                <div key={floor} className="flex items-center gap-6">
                  <span className="w-3 text-right text-xs text-muted tabular">{floor}</span>
                  {b.sections.map((s) => (
                    <div key={s.section} className="flex gap-[6px]" style={{ width: s.width * CELL + (s.width - 1) * GAP }}>
                      {(s.perFloor.get(floor) ?? []).map((u) => (
                        <Cell key={u.id} u={u} dim={!matches(u, filters)} selected={selected === u.id} onPick={onPick} currency={currency} />
                      ))}
                    </div>
                  ))}
                  <span className="w-3 text-xs text-muted tabular">{floor}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

// ------------------------------------------------------------------ list

type SortKey = 'number' | 'block' | 'floor' | 'rooms' | 'area' | 'price' | 'price_m2' | 'status'

export function UnitList({ units, filters, onPick, currency, selected }: { units: Unit[]; filters: Filters; onPick: Pick; currency: string; selected?: number }) {
  const w = useW()
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'price', dir: 1 })
  const rows = useMemo(() => {
    const list = units.filter((u) => matches(u, filters))
    const val = (u: Unit) => (sort.key === 'status' ? STATUSES.indexOf(u.status) : (u[sort.key] ?? Infinity))
    return list.sort((a, b) => {
      const x = val(a)
      const y = val(b)
      return (typeof x === 'string' && typeof y === 'string' ? natural(x, y) : Number(x) - Number(y)) * sort.dir
    })
  }, [units, filters, sort])
  const cols: [SortKey, string, string][] = [
    ['number', w('number'), 'text-left'],
    ['block', w('block'), 'text-left'],
    ['floor', w('floor'), 'text-right'],
    ['rooms', w('rooms'), 'text-left'],
    ['area', w('area'), 'text-right'],
    ['price', w('price'), 'text-right'],
    ['price_m2', w('per_m2'), 'text-right hidden md:table-cell'],
    ['status', w('status'), 'text-left'],
  ]
  if (!rows.length) return <p className="py-16 text-center text-muted">{w('nothing')}</p>
  return (
    <div className="overflow-x-auto rounded-xl border border-line bg-surface">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line text-xs text-muted">
            {cols.map(([key, label, cls]) => (
              <th key={key} className={`px-3 py-2.5 font-medium whitespace-nowrap ${cls}`}>
                <button type="button" className="hover:text-ink" onClick={() => setSort((s) => ({ key, dir: s.key === key ? ((-s.dir) as 1 | -1) : 1 }))}>
                  {label} {sort.key === key ? (sort.dir === 1 ? '↑' : '↓') : ''}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((u) => (
            <tr
              key={u.id}
              onClick={() => onPick(u)}
              className={`cursor-pointer border-b border-line last:border-0 hover:bg-ground ${selected === u.id ? 'bg-accent-soft' : ''}`}
            >
              <td className="px-3 py-2.5 font-medium whitespace-nowrap">
                {u.number}
                {u.mine && <span className="ml-1.5 text-xs text-accent-ink">● {w('yours')}</span>}
              </td>
              <td className="px-3 py-2.5">{[u.block, u.section].filter(Boolean).join(' / ') || '—'}</td>
              <td className="px-3 py-2.5 text-right tabular">{u.floor}</td>
              <td className="px-3 py-2.5 whitespace-nowrap">{roomsLabel(u.rooms, w)}</td>
              <td className="px-3 py-2.5 text-right tabular whitespace-nowrap">{area(u.area)}</td>
              <td className="px-3 py-2.5 text-right tabular whitespace-nowrap font-medium">{u.price == null ? w('hidden') : money(u.price, currency)}</td>
              <td className="px-3 py-2.5 text-right tabular whitespace-nowrap text-muted hidden md:table-cell">{money(u.price_m2, currency)}</td>
              <td className="px-3 py-2.5">
                <StatusBadge status={u.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ------------------------------------------------------------------ layouts

export function Layouts({ units, filters, currency, onLayout, renderPlan }: { units: Unit[]; filters: Filters; currency: string; onLayout: (layout: string) => void; renderPlan: (u: Unit) => ReactNode }) {
  const w = useW()
  const { lang } = useT()
  const groups = useMemo(() => {
    const m = new Map<string, Unit[]>()
    units.filter((u) => matches(u, { ...filters, layout: '' })).forEach((u) => {
      const k = u.layout || `${u.rooms}`
      m.set(k, [...(m.get(k) ?? []), u])
    })
    return [...m.entries()].sort(([, a], [, b]) => a[0].rooms - b[0].rooms || a[0].area - b[0].area)
  }, [units, filters])
  if (!groups.length) return <p className="py-16 text-center text-muted">{w('nothing')}</p>
  return (
    <div className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(230px,1fr))]">
      {groups.map(([key, us]) => {
        const withPlan = us.find((u) => u.plan)
        const free = us.filter((u) => u.status === 'free')
        const prices = free.map((u) => u.price).filter((p): p is number => p != null)
        const areas = us.map((u) => u.area)
        const lo = Math.min(...areas)
        const hi = Math.max(...areas)
        return (
          <button
            key={key}
            type="button"
            onClick={() => onLayout(key)}
            className={`group overflow-hidden rounded-xl border bg-surface text-left transition-shadow hover:shadow-md ${filters.layout === key ? 'border-ink' : 'border-line'}`}
          >
            <div className="flex aspect-[4/3] items-center justify-center bg-ground p-3">
              {withPlan ? (
                renderPlan(withPlan)
              ) : (
                <span className="text-4xl font-semibold text-line">{us[0].rooms === 0 ? 'S' : us[0].rooms}</span>
              )}
            </div>
            <div className="grid gap-1 p-3">
              <div className="flex items-baseline justify-between gap-2">
                <b>{roomsLabel(us[0].rooms, w)}</b>
                {us[0].layout && <span className="text-xs text-muted">{us[0].layout}</span>}
              </div>
              <span className="text-sm text-muted tabular">{lo === hi ? area(lo) : `${area(lo).replace(' m²', '')}–${area(hi)}`}</span>
              <div className="flex items-baseline justify-between gap-2 text-sm">
                <span className="font-semibold tabular">{prices.length ? `${w('from')} ${short(Math.min(...prices), currency, lang)}` : '—'}</span>
                <span className={free.length ? 'text-[#1f9254]' : 'text-muted'}>
                  {free.length} / {us.length} {w('free_of')}
                </span>
              </div>
            </div>
          </button>
        )
      })}
    </div>
  )
}

// ------------------------------------------------------------------ the unit card

export function UnitCard({ unit, currency, planSrc, onClose, children, projectName }: { unit: Unit; currency: string; planSrc: string; onClose: () => void; children?: ReactNode; projectName?: string }) {
  const w = useW()
  const place = [unit.block && `${w('block')} ${unit.block}`, unit.section && `${w('section')} ${unit.section}`, `${w('floor')} ${unit.floor}`].filter(Boolean).join(' · ')
  const extra = Object.entries(unit.extra || {})
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-ink/30" onClick={onClose}>
      <aside
        className="flex h-full w-full max-w-md flex-col overflow-y-auto bg-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={`№${unit.number}`}
      >
        <div className="flex items-start justify-between gap-3 border-b border-line p-5">
          <div>
            {projectName && <p className="text-xs font-medium text-muted">{projectName}</p>}
            <h2 className="text-xl font-semibold">
              №{unit.number} · {roomsLabel(unit.rooms, w)}
            </h2>
            <p className="mt-0.5 text-sm text-muted">{place}</p>
          </div>
          <button type="button" onClick={onClose} className="-m-1 rounded-lg p-1 text-2xl leading-none text-muted hover:text-ink" aria-label="close">
            ×
          </button>
        </div>
        <div className="flex aspect-[4/3] items-center justify-center bg-ground p-4">
          {planSrc ? (
            <img src={planSrc} alt={w('layout')} className="max-h-full max-w-full object-contain" />
          ) : (
            <span className="text-sm text-muted">{w('no_plan')}</span>
          )}
        </div>
        <div className="grid gap-5 p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-2xl font-semibold tabular">{unit.price == null ? w('hidden') : money(unit.price, currency)}</p>
              {unit.old_price != null && unit.old_price > (unit.price ?? 0) && (
                <p className="text-sm text-muted line-through tabular">{money(unit.old_price, currency)}</p>
              )}
              {unit.price_m2 != null && (
                <p className="mt-0.5 text-sm text-muted tabular">
                  {money(unit.price_m2, currency)} / m²
                </p>
              )}
            </div>
            <StatusBadge status={unit.status} />
          </div>
          <dl className="grid grid-cols-3 gap-3 text-sm">
            <div className="rounded-lg bg-ground p-3">
              <dt className="text-xs text-muted">{w('area')}</dt>
              <dd className="font-semibold tabular">{area(unit.area)}</dd>
            </div>
            <div className="rounded-lg bg-ground p-3">
              <dt className="text-xs text-muted">{w('rooms')}</dt>
              <dd className="font-semibold">{unit.rooms === 0 ? w('studio') : unit.rooms}</dd>
            </div>
            <div className="rounded-lg bg-ground p-3">
              <dt className="text-xs text-muted">{w('floor')}</dt>
              <dd className="font-semibold tabular">{unit.floor}</dd>
            </div>
          </dl>
          {unit.reserved_until && unit.status === 'reserved' && (
            <p className="text-sm text-warn">
              {w('until')}: {new Date(unit.reserved_until).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}
            </p>
          )}
          {unit.description && <p className="whitespace-pre-line text-sm leading-relaxed">{unit.description}</p>}
          {extra.length > 0 && (
            <div className="grid gap-1.5 text-sm">
              <p className="text-xs font-medium text-muted">{w('more')}</p>
              {extra.map(([k, v]) => (
                <div key={k} className="flex justify-between gap-3 border-b border-line pb-1.5 last:border-0">
                  <span className="text-muted">{k}</span>
                  <span className="text-right">{v}</span>
                </div>
              ))}
            </div>
          )}
          {children}
        </div>
      </aside>
    </div>
  )
}

// ------------------------------------------------------------------ the three views together

export type View = 'grid' | 'list' | 'plans'

export function ViewSwitch({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  const w = useW()
  const items: [View, Word][] = [
    ['grid', 'view_grid'],
    ['list', 'view_list'],
    ['plans', 'view_plans'],
  ]
  return (
    <div className="inline-flex rounded-lg border border-line bg-surface p-0.5 text-sm">
      {items.map(([v, k]) => (
        <button key={v} type="button" onClick={() => onChange(v)} className={`rounded-md px-3 py-1.5 font-medium ${view === v ? 'bg-ink text-white' : 'text-muted hover:text-ink'}`}>
          {w(k)}
        </button>
      ))}
    </div>
  )
}

/** Filters + view switch + the chosen view; the parent owns the selected unit. */
export function Board({ units, currency, selected, onPick, renderPlan }: { units: Unit[]; currency: string; selected?: number; onPick: Pick; renderPlan: (u: Unit) => ReactNode }) {
  const [filters, setFilters] = useState<Filters>(NO_FILTERS)
  const [view, setView] = useState<View>('grid')
  const found = useMemo(() => units.filter((u) => matches(u, filters)).length, [units, filters])
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4">
      <FilterBar units={units} filters={filters} onChange={setFilters} currency={currency} found={found} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <ViewSwitch view={view} onChange={setView} />
        <Legend units={units} />
      </div>
      {view === 'grid' && <Chessboard units={units} filters={filters} selected={selected} onPick={onPick} currency={currency} />}
      {view === 'list' && <UnitList units={units} filters={filters} onPick={onPick} currency={currency} selected={selected} />}
      {view === 'plans' && (
        <Layouts
          units={units}
          filters={filters}
          currency={currency}
          renderPlan={renderPlan}
          onLayout={(layout) => {
            setFilters({ ...filters, layout: filters.layout === layout ? '' : layout })
            setView('grid')
          }}
        />
      )}
    </div>
  )
}
