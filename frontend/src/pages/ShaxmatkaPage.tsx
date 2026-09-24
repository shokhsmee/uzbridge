import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import type { Me } from '../App'
import { Button, Card, CopyField, ErrorNote, Field, Input, PageHeader, Pill, Select, Toggle } from '../components/ui'
import { api, downloadGet, fetchBlob, get, post, put, upload, when } from '../lib/api'
import { useT } from '../lib/i18n'
import { Board, money, STATUSES, UnitCard, useW, type Status, type Unit } from '../realty/board'
import { Tabs } from './IntegrationLogs'

type Stats = { counts: Record<Status, number>; total: number; sold_pct: number; sold_sum: number; left_sum: number }
type Project = {
  id: number
  name: string
  currency: 'UZS' | 'USD'
  address: string
  is_public: boolean
  show_sold_prices: boolean
  booking_hours: number
  use_in_amocrm: boolean
  sheet_url: string
  showroom_url: string
  last_sync_at: string | null
  last_sync: { created?: number; updated?: number; archived?: number; total?: number; errors?: string[] }
  stats: Stats
  apps_script: string
  google_sheet: boolean
}
type Event = { from: string; to: string; source: string; lead_id: number | null; note: string; at: string }

const L = {
  title: { uz: 'Shaxmatka', ru: 'Шахматка' },
  lede: {
    uz: 'Obyektlar Google Sheets’dan sinxronlanadi. Bu yerda planirovka, tavsif va narxlarni tahrirlaysiz; amoCRM bitimidan showroom ochiladi.',
    ru: 'Объекты синхронизируются из Google Sheets. Здесь — планировки, описания и цены; из сделки amoCRM открывается шоурум.',
  },
  new: { uz: 'Yangi loyiha', ru: 'Новый проект' },
  new_name: { uz: 'Yangi turar-joy majmuasi', ru: 'Новый ЖК' },
  none: { uz: 'Hali loyiha yoʻq. Birinchisini yarating — keyin Google Sheet ulaysiz.', ru: 'Проектов пока нет. Создайте первый — затем подключите Google Sheet.' },
  tab_units: { uz: 'Obyektlar', ru: 'Объекты' },
  tab_sheet: { uz: 'Google Sheets', ru: 'Google Sheets' },
  tab_settings: { uz: 'Sozlamalar', ru: 'Настройки' },
  total: { uz: 'Jami', ru: 'Всего' },
  sold_sum: { uz: 'Sotilgan summa', ru: 'Продано на' },
  left_sum: { uz: 'Sotuvda qolgan', ru: 'Осталось в продаже' },
  sold_pct: { uz: 'sotilgan', ru: 'продано' },
  no_units: { uz: 'Obyektlar Google Sheet sinxronlanganda paydo boʻladi.', ru: 'Объекты появятся после синхронизации Google Sheet.' },
  open_sheet_tab: { uz: 'Google Sheet’ni ulash', ru: 'Подключить Google Sheet' },
  // sheet
  step1: { uz: 'Shablonni yuklab oling va yangi Google Sheet’ga import qiling (Fayl → Import).', ru: 'Скачайте шаблон и импортируйте в новую Google-таблицу (Файл → Импорт).' },
  step1_hint: { uz: 'Ustunlar: ID, Turi, Blok, Podyezd, Qavat, Raqam, Xonalar, Maydon, Narx, Holat… Oʻzingizning ustunlaringiz ham “Qoʻshimcha” boʻlib keladi.', ru: 'Столбцы: ID, Тип, Корпус, Подъезд, Этаж, Номер, Комнат, Площадь, Цена, Статус… Ваши собственные столбцы тоже придут как «Дополнительно».' },
  template: { uz: 'Shablon (CSV)', ru: 'Шаблон (CSV)' },
  step2: { uz: 'Jadvalda Kengaytmalar → Apps Script’ni oching, bor kodni oʻchirib, quyidagini qoʻying va saqlang.', ru: 'В таблице откройте Расширения → Apps Script, замените код на этот и сохраните.' },
  copy_script: { uz: 'Kodni nusxalash', ru: 'Скопировать код' },
  copied: { uz: 'Nusxalandi', ru: 'Скопировано' },
  step3: { uz: 'Jadvalni yangilang: “uzbridge” menyusi paydo boʻladi → “Sinxronlash”. Birinchi marta Google ruxsat soʻraydi.', ru: 'Обновите таблицу: появится меню «uzbridge» → «Синхронизировать». В первый раз Google попросит доступ.' },
  step3_hint: { uz: 'Holat ustunini jadvalda oʻzgartirsangiz — u gʻolib. amoCRM’da oʻzgargan holat va bitim havolasi keyingi sinxronlashda jadvalga yoziladi. “Avto-sinxron” har 10 daqiqada ishlaydi.', ru: 'Статус, изменённый в таблице, побеждает. Статусы из amoCRM и ссылки на сделки записываются в таблицу при следующей синхронизации. «Автосинхронизация» — каждые 10 минут.' },
  last_sync: { uz: 'Oxirgi sinxron', ru: 'Последняя синхронизация' },
  never: { uz: 'Hali sinxronlanmagan', ru: 'Ещё не синхронизировано' },
  created: { uz: 'yangi', ru: 'новых' },
  updated: { uz: 'yangilandi', ru: 'обновлено' },
  archived: { uz: 'arxivga', ru: 'в архив' },
  open_sheet: { uz: 'Jadvalni ochish', ru: 'Открыть таблицу' },
  key_warn: { uz: 'Kodda loyihaning maxfiy kaliti bor — uni faqat shu jadvalga qoʻying.', ru: 'В коде секретный ключ проекта — вставляйте его только в эту таблицу.' },
  // settings
  name: { uz: 'Nomi', ru: 'Название' },
  address: { uz: 'Manzil', ru: 'Адрес' },
  currency: { uz: 'Valyuta', ru: 'Валюта' },
  currency_hint: { uz: 'Narxlar shu valyutada; amoCRM byudjetiga narx oʻzgarishsiz yoziladi.', ru: 'Цены в этой валюте; в бюджет amoCRM цена пишется как есть.' },
  booking: { uz: 'Bron muddati, soat', ru: 'Срок брони, часов' },
  booking_hint: { uz: '0 = cheklanmagan. Muddat oʻtsa “Band” obyekt boʻshaydi va bitimga izoh yoziladi.', ru: '0 = без ограничения. По истечении «Бронь» освобождается, в сделку пишется примечание.' },
  public: { uz: 'Ochiq showroom (xaridorlar uchun havola)', ru: 'Публичный шоурум (ссылка для покупателей)' },
  sold_prices: { uz: 'Sotilganlar narxini koʻrsatish', ru: 'Показывать цены проданных' },
  in_amo: { uz: 'amoCRM bitimida koʻrsatish', ru: 'Показывать в сделке amoCRM' },
  showroom: { uz: 'Showroom havolasi', ru: 'Ссылка на шоурум' },
  showroom_off: { uz: 'Ochiq showroom oʻchiq — havola ishlamaydi.', ru: 'Публичный шоурум выключен — ссылка не работает.' },
  open: { uz: 'Ochish', ru: 'Открыть' },
  save: { uz: 'Saqlash', ru: 'Сохранить' },
  saved: { uz: 'Saqlandi', ru: 'Сохранено' },
  delete: { uz: 'Loyihani oʻchirish', ru: 'Удалить проект' },
  delete_confirm: { uz: 'Loyiha va uning barcha obyektlari oʻchiriladi. Davom etasizmi?', ru: 'Проект и все его объекты будут удалены. Продолжить?' },
  stages_hint: { uz: 'Bitim bosqichi → obyekt holati amoCRM’da: Настройки → uzbridge → Shaxmatka.', ru: 'Этап сделки → статус объекта настраивается в amoCRM: Настройки → uzbridge → Shaxmatka.' },
  // unit editor
  edit: { uz: 'Tahrirlash', ru: 'Редактирование' },
  plan: { uz: 'Planirovka rasmi', ru: 'Изображение планировки' },
  plan_hint: { uz: 'PNG, JPG, WEBP yoki SVG, 3 MB gacha', ru: 'PNG, JPG, WEBP или SVG, до 3 МБ' },
  upload: { uz: 'Yuklash', ru: 'Загрузить' },
  replace: { uz: 'Almashtirish', ru: 'Заменить' },
  remove: { uz: 'Oʻchirish', ru: 'Удалить' },
  same_layout: { uz: 'Shu planirovkadagi barchasiga', ru: 'Всем с этой планировкой' },
  copied_n: { uz: 'ta obyektga qoʻyildi', ru: 'объектам назначено' },
  layout: { uz: 'Planirovka turi', ru: 'Тип планировки' },
  description: { uz: 'Tavsif', ru: 'Описание' },
  price: { uz: 'Narx', ru: 'Цена' },
  old_price: { uz: 'Eski narx (chizilgan)', ru: 'Старая цена (зачёркнутая)' },
  rooms: { uz: 'Xonalar (0 = studiya)', ru: 'Комнат (0 = студия)' },
  area: { uz: 'Maydon, m²', ru: 'Площадь, м²' },
  status: { uz: 'Holat', ru: 'Статус' },
  status_hint: { uz: 'Jadvalga keyingi sinxronlashda yoziladi.', ru: 'Попадёт в таблицу при следующей синхронизации.' },
  sheet_note: { uz: 'Narx, maydon va xonalar keyingi sinxronlashda jadvaldagi qiymat bilan almashadi — ularni jadvalda oʻzgartirgan maʼqul. Planirovka rasmi va tavsif saqlanib qoladi.', ru: 'Цена, площадь и комнаты при следующей синхронизации заменятся значениями из таблицы — лучше менять их там. Изображение и описание сохраняются.' },
  deal: { uz: 'amoCRM bitimi', ru: 'Сделка amoCRM' },
  history: { uz: 'Tarix', ru: 'История' },
  src_sheet: { uz: 'jadval', ru: 'таблица' },
  src_amocrm: { uz: 'amoCRM', ru: 'amoCRM' },
  src_site: { uz: 'sayt', ru: 'сайт' },
  src_timer: { uz: 'bron muddati', ru: 'срок брони' },
  // Google
  g_title: { uz: 'Google Sheets bilan ishlash', ru: 'Работа через Google Sheets' },
  g_lede: { uz: 'uzbridge sizning Google Drive’ingizda tayyor jadval yaratadi — sotuv boʻlimi obyektlarni oʻsha yerda yuritadi.', ru: 'uzbridge создаст готовую таблицу в вашем Google Drive — отдел продаж ведёт объекты в ней.' },
  g_step1: { uz: 'Google hisobingizga kirasiz — uzbridge faqat oʻzi yaratgan jadvallarni koʻradi.', ru: 'Войдите в Google — uzbridge видит только таблицы, которые создал сам.' },
  g_step2: { uz: 'Jadval ustunlari, holat roʻyxati va ranglari bilan yaratiladi va darhol ochiladi.', ru: 'Таблица создаётся со столбцами, списком статусов и цветами и сразу открывается.' },
  g_step3: { uz: 'Jadvalning birinchi qatoridagi “🔄 Sinxronlash” tugmasi obyektlarni bu yerga olib keladi.', ru: 'Кнопка «🔄 Sinxronlash» в первой строке таблицы переносит объекты сюда.' },
  g_connect: { uz: 'Google bilan ulash va jadval yaratish', ru: 'Подключить Google и создать таблицу' },
  g_create: { uz: 'Jadval yaratish', ru: 'Создать таблицу' },
  g_disconnect: { uz: 'Googleni uzish', ru: 'Отключить Google' },
  g_linked: { uz: 'Jadval ulangan', ru: 'Таблица подключена' },
  g_off: { uz: 'Google ulanishi bu serverda hali yoqilmagan. Quyidagi “Apps Script” usulidan foydalaning yoki administratorga murojaat qiling.', ru: 'Подключение Google на этом сервере ещё не включено. Используйте способ «Apps Script» ниже или обратитесь к администратору.' },
  g_how1: { uz: 'Jadvaldagi “🔄 Sinxronlash” — darhol sinxronlaydi', ru: '«🔄 Sinxronlash» в таблице — синхронизирует сразу' },
  g_how2: { uz: 'Har 5 daqiqada avtomatik tekshiriladi', ru: 'Автоматическая проверка каждые 5 минут' },
  g_how3: { uz: 'amoCRM yoki saytda oʻzgargan holat jadvalga bir necha soniyada yoziladi', ru: 'Статус из amoCRM или с сайта попадает в таблицу за несколько секунд' },
  g_how4: { uz: 'Jadvalda holatni oʻzgartirsangiz — u gʻolib', ru: 'Статус, изменённый в таблице, побеждает' },
  g_unlink: { uz: 'Jadvalni uzish', ru: 'Отвязать таблицу' },
  g_unlink_hint: { uz: 'Jadval Google Drive’da qoladi, faqat sinxronlash toʻxtaydi.', ru: 'Таблица останется в Google Drive, остановится только синхронизация.' },
  g_unlink_confirm: { uz: 'Jadval bilan sinxronlash toʻxtatilsinmi? Obyektlar saytda qoladi.', ru: 'Остановить синхронизацию с таблицей? Объекты останутся на сайте.' },
  sync_now: { uz: 'Hozir sinxronlash', ru: 'Синхронизировать' },
  units_n: { uz: 'ta obyekt', ru: 'объектов' },
  fb_title: { uz: 'Boshqa usul: oʻz jadvalingiz', ru: 'Другой способ: своя таблица' },
  fb_lede: { uz: 'Apps Script kodini qoʻlda qoʻyish', ru: 'вставить код Apps Script вручную' },
  // settings rows
  sec_project: { uz: 'Loyiha', ru: 'Проект' },
  sec_show: { uz: 'Koʻrinish va amoCRM', ru: 'Показ и amoCRM' },
  hours: { uz: 'soat', ru: 'ч' },
  in_amo_hint: { uz: 'Menejer bitim ichida shu loyihaning shaxmatkasini ochadi.', ru: 'Менеджер открывает шахматку этого проекта в сделке.' },
  public_hint: { uz: 'Havola orqali xaridorlar boʻsh obyektlarni koʻradi (bitimlarsiz).', ru: 'По ссылке покупатели видят свободные объекты (без сделок).' },
  sold_prices_hint: { uz: 'Oʻchiq boʻlsa ochiq showroom’da sotilganlar narxi “soʻrov boʻyicha”.', ru: 'Если выключено, в публичном шоуруме цена проданных — «по запросу».' },
} as const
type LK = keyof typeof L

function useL() {
  const { lang } = useT()
  return (k: LK) => L[k][lang]
}

export default function ShaxmatkaPage({ me }: { me: Me }) {
  const l = useL()
  const qc = useQueryClient()
  const canManage = me.role !== 'member'
  const projects = useQuery({ queryKey: ['realty-projects'], queryFn: () => get<Project[]>('/realty/projects') })
  const [id, setId] = useState<number | null>(null)
  const [tab, setTab] = useState<'units' | 'sheet' | 'settings'>('units')
  const list = projects.data ?? []
  const project = list.find((p) => p.id === id) ?? list[0]

  const create = useMutation({
    mutationFn: () => post<Project>('/realty/projects', { name: l('new_name'), currency: 'UZS' }),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ['realty-projects'] })
      setId(p.id)
      setTab('settings')
    },
  })

  return (
    <>
      <PageHeader
        title={l('title')}
        lede={l('lede')}
        action={
          canManage && (
            <Button onClick={() => create.mutate()} busy={create.isPending}>
              + {l('new')}
            </Button>
          )
        }
      />
      <ErrorNote error={create.error ?? projects.error} />
      {projects.isSuccess && !list.length && (
        <Card className="p-8 text-center text-muted">
          <p>{l('none')}</p>
        </Card>
      )}
      {project && (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-5">
          {list.length > 1 && (
            <div className="flex gap-1 overflow-x-auto">
              {list.map((p) => (
                <button
                  key={p.id}
                  onClick={() => setId(p.id)}
                  className={`shrink-0 rounded-lg px-3 py-1.5 text-sm font-medium ${p.id === project.id ? 'bg-ink text-white' : 'bg-surface border border-line text-muted hover:text-ink'}`}
                >
                  {p.name}
                </button>
              ))}
            </div>
          )}
          <StatsRow project={project} />
          <Tabs
            tabs={['units', 'sheet', 'settings'] as const}
            value={tab}
            onChange={setTab}
            label={(k) => l(k === 'units' ? 'tab_units' : k === 'sheet' ? 'tab_sheet' : 'tab_settings')}
          />
          {tab === 'units' && <UnitsTab project={project} canManage={canManage} onSheet={() => setTab('sheet')} />}
          {tab === 'sheet' && <SheetTab project={project} canManage={canManage} />}
          {tab === 'settings' && <SettingsTab key={project.id} project={project} canManage={canManage} onDeleted={() => setId(null)} />}
        </div>
      )}
    </>
  )
}

function StatsRow({ project }: { project: Project }) {
  const l = useL()
  const w = useW()
  const s = project.stats
  return (
    <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
      <Card className="p-4">
        <p className="text-xs text-muted">{l('total')}</p>
        <p className="mt-1 text-2xl font-semibold tabular">{s.total}</p>
        <div className="mt-2 flex h-1.5 overflow-hidden rounded-full bg-ground">
          {STATUSES.map((st) =>
            s.counts[st] ? (
              <span
                key={st}
                title={`${w(st)}: ${s.counts[st]}`}
                style={{ width: `${(100 * s.counts[st]) / s.total}%` }}
                className={{ free: 'bg-[#1f9254]', interest: 'bg-[#2f6fd0]', reserved: 'bg-[#e0a21b]', sold: 'bg-[#aab3b2]', closed: 'bg-line' }[st]}
              />
            ) : null,
          )}
        </div>
      </Card>
      <Card className="p-4">
        <p className="text-xs text-muted">{w('free')}</p>
        <p className="mt-1 text-2xl font-semibold tabular text-[#1f9254]">{s.counts.free}</p>
        <p className="text-xs text-muted">
          {w('interest')} {s.counts.interest} · {w('reserved')} {s.counts.reserved}
        </p>
      </Card>
      <Card className="p-4">
        <p className="text-xs text-muted">{l('sold_sum')}</p>
        <p className="mt-1 text-xl font-semibold tabular">{money(s.sold_sum, project.currency)}</p>
        <p className="text-xs text-muted">
          {s.counts.sold} · {s.sold_pct}% {l('sold_pct')}
        </p>
      </Card>
      <Card className="p-4">
        <p className="text-xs text-muted">{l('left_sum')}</p>
        <p className="mt-1 text-xl font-semibold tabular">{money(s.left_sum, project.currency)}</p>
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------- units

/** Plan images need the company header, so they're fetched as blobs. */
function usePlan(path: string): string {
  const [src, setSrc] = useState('')
  useEffect(() => {
    if (!path) return setSrc('')
    if (!path.startsWith('/api/')) return setSrc(path) // a plan link from the sheet
    let url = ''
    let live = true
    fetchBlob(path.slice(4))
      .then((b) => {
        url = URL.createObjectURL(b)
        if (live) setSrc(url)
      })
      .catch(() => live && setSrc(''))
    return () => {
      live = false
      if (url) URL.revokeObjectURL(url)
    }
  }, [path])
  return src
}

function PlanImg({ unit }: { unit: Unit }) {
  const src = usePlan(unit.plan)
  return src ? <img src={src} alt="" className="max-h-full max-w-full object-contain" /> : null
}

function UnitsTab({ project, canManage, onSheet }: { project: Project; canManage: boolean; onSheet: () => void }) {
  const l = useL()
  const units = useQuery({ queryKey: ['realty-units', project.id], queryFn: () => get<Unit[]>(`/realty/projects/${project.id}/units`) })
  const [pickedId, setPickedId] = useState<number | null>(null)
  const picked = units.data?.find((u) => u.id === pickedId) ?? null
  if (units.isLoading) return null
  if (!units.data?.length) {
    return (
      <Card className="grid justify-items-center gap-3 p-10 text-center">
        <p className="text-muted">{l('no_units')}</p>
        <Button variant="ghost" onClick={onSheet}>
          {l('open_sheet_tab')}
        </Button>
      </Card>
    )
  }
  return (
    <>
      <Board units={units.data} currency={project.currency} selected={pickedId ?? undefined} onPick={(u) => setPickedId(u.id)} renderPlan={(u) => <PlanImg unit={u} />} />
      {picked && <UnitDrawer key={picked.id} unit={picked} project={project} canManage={canManage} onClose={() => setPickedId(null)} />}
    </>
  )
}

function UnitDrawer({ unit, project, canManage, onClose }: { unit: Unit; project: Project; canManage: boolean; onClose: () => void }) {
  const l = useL()
  const w = useW()
  const qc = useQueryClient()
  const src = usePlan(unit.plan)
  const fileRef = useRef<HTMLInputElement>(null)
  const [form, setForm] = useState({
    layout: unit.layout,
    description: unit.description,
    price: String(unit.price ?? ''),
    old_price: unit.old_price == null ? '' : String(unit.old_price),
    rooms: String(unit.rooms),
    area: String(unit.area),
    status: unit.status,
  })
  const [note, setNote] = useState('')
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['realty-units', project.id] })
    qc.invalidateQueries({ queryKey: ['realty-projects'] })
    qc.invalidateQueries({ queryKey: ['realty-events', unit.id] })
  }
  const events = useQuery({ queryKey: ['realty-events', unit.id], queryFn: () => get<Event[]>(`/realty/units/${unit.id}/events`) })
  const save = useMutation({
    mutationFn: () => put<Unit>(`/realty/units/${unit.id}`, { ...form, rooms: Number(form.rooms) || 0 }),
    onSuccess: () => {
      setNote(l('saved'))
      refresh()
    },
  })
  const uploadPlan = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      return upload<Unit>(`/realty/units/${unit.id}/plan`, fd)
    },
    onSuccess: refresh,
  })
  const removePlan = useMutation({ mutationFn: () => api(`/realty/units/${unit.id}/plan`, { method: 'DELETE' }), onSuccess: refresh })
  const toLayout = useMutation({
    mutationFn: () => post<{ copied: number }>(`/realty/units/${unit.id}/plan/same-layout`),
    onSuccess: (r) => {
      setNote(`${r.copied} ${l('copied_n')}`)
      refresh()
    },
  })
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value })
  const src_words: Record<string, LK> = { sheet: 'src_sheet', amocrm: 'src_amocrm', site: 'src_site', timer: 'src_timer' }

  return (
    <UnitCard unit={unit} currency={project.currency} planSrc={src} onClose={onClose} projectName={project.name}>
      {unit.lead_url && (
        <a href={unit.lead_url} target="_blank" rel="noopener" className="text-sm font-medium text-accent-ink hover:underline">
          {l('deal')} #{unit.lead_id} ↗
        </a>
      )}
      {canManage && (
        <div className="grid gap-4 border-t border-line pt-5">
          <h3 className="font-semibold">{l('edit')}</h3>
          <Field label={l('plan')} hint={l('plan_hint')}>
            <div className="flex flex-wrap gap-2">
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/webp,image/svg+xml"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) uploadPlan.mutate(f)
                  e.target.value = ''
                }}
              />
              <Button type="button" variant="ghost" className="h-9" busy={uploadPlan.isPending} onClick={() => fileRef.current?.click()}>
                {unit.has_plan ? l('replace') : l('upload')}
              </Button>
              {unit.has_plan && (
                <>
                  {unit.layout && (
                    <Button type="button" variant="ghost" className="h-9" busy={toLayout.isPending} onClick={() => toLayout.mutate()}>
                      {l('same_layout')} ({unit.layout})
                    </Button>
                  )}
                  <Button type="button" variant="danger" className="h-9" busy={removePlan.isPending} onClick={() => removePlan.mutate()}>
                    {l('remove')}
                  </Button>
                </>
              )}
            </div>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={l('layout')}>
              <Input value={form.layout} onChange={set('layout')} placeholder="2A" />
            </Field>
            <Field label={l('status')} hint={l('status_hint')}>
              <Select value={form.status} onChange={set('status')}>
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {w(s)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={`${l('price')}, ${project.currency === 'USD' ? '$' : 'soʻm'}`}>
              <Input value={form.price} onChange={set('price')} inputMode="decimal" />
            </Field>
            <Field label={l('old_price')}>
              <Input value={form.old_price} onChange={set('old_price')} inputMode="decimal" />
            </Field>
            <Field label={l('rooms')}>
              <Input value={form.rooms} onChange={set('rooms')} inputMode="numeric" />
            </Field>
            <Field label={l('area')}>
              <Input value={form.area} onChange={set('area')} inputMode="decimal" />
            </Field>
          </div>
          <Field label={l('description')}>
            <textarea
              value={form.description}
              onChange={set('description')}
              rows={4}
              className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm focus:border-accent focus:outline-none"
            />
          </Field>
          <p className="text-xs text-muted">{l('sheet_note')}</p>
          <ErrorNote error={save.error ?? uploadPlan.error ?? removePlan.error ?? toLayout.error} />
          <div className="flex items-center gap-3">
            <Button onClick={() => save.mutate()} busy={save.isPending}>
              {l('save')}
            </Button>
            {note && <span className="text-sm text-ok">{note}</span>}
          </div>
        </div>
      )}
      {!!events.data?.length && (
        <div className="grid gap-2 border-t border-line pt-5 text-sm">
          <h3 className="font-semibold">{l('history')}</h3>
          {events.data.map((e, i) => (
            <div key={i} className="flex justify-between gap-3">
              <span>
                {e.from ? `${w(e.from as Status)} → ` : ''}
                <b>{w(e.to as Status)}</b>
                <span className="text-muted"> · {src_words[e.source] ? l(src_words[e.source]) : e.source}</span>
                {e.lead_id && <span className="text-muted"> · #{e.lead_id}</span>}
              </span>
              <span className="shrink-0 text-muted tabular">{when(e.at)}</span>
            </div>
          ))}
        </div>
      )}
    </UnitCard>
  )
}

// ---------------------------------------------------------------- Google Sheets

type GoogleState = { configured: boolean; connected: boolean; email: string }

function SheetsIcon({ className = 'size-11' }: { className?: string }) {
  return (
    <svg viewBox="0 0 48 48" className={className} aria-hidden>
      <path fill="#0f9d58" d="M29 4H12a4 4 0 0 0-4 4v32a4 4 0 0 0 4 4h24a4 4 0 0 0 4-4V15z" />
      <path fill="#87ceac" d="M29 4v8a3 3 0 0 0 3 3h8z" />
      <path fill="#fff" d="M15 21h18v14H15zm2 2v3h6v-3zm8 0v3h6v-3zm-8 5v5h6v-5zm8 0v5h6v-5z" />
    </svg>
  )
}

/** Open the tab now (a click), point it at Google once we know where: popup blockers allow that. */
async function openInNewTab(getUrl: () => Promise<string>) {
  const tab = window.open('', '_blank')
  try {
    const url = await getUrl()
    if (tab) tab.location.href = url
    else window.location.href = url
  } catch (e) {
    tab?.close()
    throw e
  }
}

function SheetTab({ project, canManage }: { project: Project; canManage: boolean }) {
  const l = useL()
  const qc = useQueryClient()
  const g = useQuery({ queryKey: ['realty-google'], queryFn: () => get<GoogleState>('/realty/google'), refetchOnWindowFocus: true })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['realty-google'] })
    qc.invalidateQueries({ queryKey: ['realty-projects'] })
    qc.invalidateQueries({ queryKey: ['realty-units', project.id] })
  }
  // Coming back from Google's tab: pick up the new sheet.
  useEffect(() => {
    const onFocus = () => refresh()
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  })
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
      refresh()
    }
  }
  const connectAndCreate = () => run(() => openInNewTab(async () => (await post<{ url: string }>('/realty/google/connect', { project_id: project.id })).url))
  const create = () => run(() => openInNewTab(async () => (await post<{ url: string }>(`/realty/projects/${project.id}/sheet`)).url))
  const sync = useMutation({ mutationFn: () => post<Project>(`/realty/projects/${project.id}/sheet/sync`), onSettled: refresh })
  const unlink = useMutation({ mutationFn: () => api(`/realty/projects/${project.id}/sheet`, { method: 'DELETE' }), onSettled: refresh })
  const disconnect = useMutation({ mutationFn: () => api('/realty/google', { method: 'DELETE' }), onSettled: refresh })
  const s = project.last_sync || {}
  const state = !g.data ? null : !g.data.configured ? 'off' : project.google_sheet ? 'linked' : g.data.connected ? 'connected' : 'new'

  return (
    <div className="grid gap-5">
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-4 border-b border-line p-5">
          <SheetsIcon />
          <div className="min-w-0 flex-1">
            <h3 className="text-base font-semibold">{state === 'linked' ? `${project.name} · Shaxmatka` : l('g_title')}</h3>
            <p className="text-sm text-muted">
              {state === 'linked' ? (
                <>
                  {l('g_linked')}
                  {g.data?.email && <> · {g.data.email}</>}
                </>
              ) : (
                l('g_lede')
              )}
            </p>
          </div>
          {state === 'linked' && (
            <div className="flex flex-wrap gap-2">
              <a
                href={project.sheet_url}
                target="_blank"
                rel="noopener"
                className="inline-flex h-10 items-center gap-2 rounded-lg bg-accent px-4 text-sm font-medium text-white hover:bg-accent-ink"
              >
                {l('open_sheet')} ↗
              </a>
              {canManage && (
                <Button variant="ghost" busy={sync.isPending} onClick={() => sync.mutate()}>
                  🔄 {l('sync_now')}
                </Button>
              )}
            </div>
          )}
        </div>

        {state === 'off' && <p className="p-5 text-sm text-muted">{l('g_off')}</p>}

        {(state === 'new' || state === 'connected') && (
          <div className="grid gap-5 p-5 md:grid-cols-[1fr_auto] md:items-center">
            <ol className="grid gap-2.5 text-sm">
              {(['g_step1', 'g_step2', 'g_step3'] as const).map((k, i) => (
                <li key={k} className="flex gap-3">
                  <span className="grid size-6 shrink-0 place-items-center rounded-full bg-accent-soft text-xs font-semibold text-accent-ink">{i + 1}</span>
                  <span className="pt-0.5">{l(k)}</span>
                </li>
              ))}
            </ol>
            {canManage && (
              <div className="grid justify-items-start gap-2 md:justify-items-end">
                <Button busy={busy} onClick={state === 'new' ? connectAndCreate : create} className="h-11 px-5">
                  <span className="grid size-5 place-items-center rounded bg-white">
                    <SheetsIcon className="size-4" />
                  </span>
                  {state === 'new' ? l('g_connect') : l('g_create')}
                </Button>
                {state === 'connected' && (
                  <span className="text-xs text-muted">
                    {g.data?.email}{' '}
                    <button className="text-bad hover:underline" onClick={() => disconnect.mutate()}>
                      · {l('g_disconnect')}
                    </button>
                  </span>
                )}
              </div>
            )}
          </div>
        )}

        {state === 'linked' && (
          <div className="grid gap-5 p-5 md:grid-cols-2">
            <div className="grid content-start gap-2 text-sm">
              <p className="text-xs font-medium uppercase tracking-wide text-muted">{l('last_sync')}</p>
              {project.last_sync_at ? (
                <>
                  <p className="text-lg font-semibold tabular">{when(project.last_sync_at)}</p>
                  <div className="flex flex-wrap gap-1.5">
                    <Pill tone="neutral">
                      {s.total ?? 0} {l('units_n')}
                    </Pill>
                    {!!s.created && (
                      <Pill tone="active">
                        +{s.created} {l('created')}
                      </Pill>
                    )}
                    {!!s.archived && (
                      <Pill tone="pending">
                        {s.archived} {l('archived')}
                      </Pill>
                    )}
                  </div>
                  {!!s.errors?.length && (
                    <ul className="grid gap-1 rounded-lg bg-bad-soft p-3 text-xs text-bad">
                      {s.errors.map((e) => (
                        <li key={e}>{e}</li>
                      ))}
                    </ul>
                  )}
                </>
              ) : (
                <p className="text-muted">{l('never')}</p>
              )}
            </div>
            <ul className="grid content-start gap-2.5 text-sm">
              {(['g_how1', 'g_how2', 'g_how3', 'g_how4'] as const).map((k) => (
                <li key={k} className="flex gap-2.5">
                  <span className="text-accent">✓</span>
                  <span>{l(k)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="px-5 pb-5 empty:hidden">
          <ErrorNote error={error ?? sync.error ?? unlink.error ?? disconnect.error} />
        </div>
        {state === 'linked' && canManage && (
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line bg-ground/60 px-5 py-3 text-xs text-muted">
            <span>{l('g_unlink_hint')}</span>
            <button className="font-medium text-bad hover:underline" onClick={() => window.confirm(l('g_unlink_confirm')) && unlink.mutate()}>
              {l('g_unlink')}
            </button>
          </div>
        )}
      </Card>

      {state !== 'linked' && <AppsScriptFallback project={project} />}
    </div>
  )
}

/** The old way: the company's own sheet with a pasted Apps Script. */
function AppsScriptFallback({ project }: { project: Project }) {
  const l = useL()
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(project.apps_script)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* the code box is selectable */
    }
  }
  return (
    <details className="group rounded-xl border border-line bg-surface">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 text-sm">
        <span>
          <b>{l('fb_title')}</b> <span className="text-muted">— {l('fb_lede')}</span>
        </span>
        <span className="text-muted transition-transform group-open:rotate-180">⌄</span>
      </summary>
      <div className="grid gap-4 border-t border-line p-5 text-sm">
        <p>1. {l('step1')}</p>
        <div>
          <Button variant="ghost" className="h-9" onClick={() => downloadGet(`/realty/projects/${project.id}/template.csv`, 'shaxmatka-shablon.csv')}>
            ↓ {l('template')}
          </Button>
        </div>
        <p>2. {l('step2')}</p>
        <div className="relative">
          <pre className="max-h-48 overflow-auto rounded-lg border border-line bg-ground p-3 font-mono text-[11px] leading-relaxed">{project.apps_script}</pre>
          <Button className="absolute right-2 top-2 h-8" onClick={copy}>
            {copied ? l('copied') : l('copy_script')}
          </Button>
        </div>
        <p className="text-xs text-warn">{l('key_warn')}</p>
        <p>3. {l('step3')}</p>
      </div>
    </details>
  )
}

// ---------------------------------------------------------------- settings

/** One setting per line: what it is on the left, the control on the right. */
function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-2 border-t border-line px-5 py-4 first:border-t-0 md:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] md:items-center md:gap-8">
      <div>
        <p className="text-sm font-medium">{label}</p>
        {hint && <p className="mt-0.5 text-xs leading-relaxed text-muted">{hint}</p>}
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  )
}

function Switch({ checked, onChange, disabled, id }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; id: string }) {
  return (
    <div className="flex md:justify-end">
      <Toggle id={id} checked={checked} onChange={(v) => !disabled && onChange(v)} label="" />
    </div>
  )
}

function SettingsTab({ project, canManage, onDeleted }: { project: Project; canManage: boolean; onDeleted: () => void }) {
  const l = useL()
  const qc = useQueryClient()
  const [f, setF] = useState({
    name: project.name,
    currency: project.currency,
    address: project.address,
    booking_hours: String(project.booking_hours),
    is_public: project.is_public,
    show_sold_prices: project.show_sold_prices,
    use_in_amocrm: project.use_in_amocrm,
  })
  const [ok, setOk] = useState(false)
  const set = (patch: Partial<typeof f>) => {
    setOk(false)
    setF({ ...f, ...patch })
  }
  const save = useMutation({
    mutationFn: () => put<Project>(`/realty/projects/${project.id}`, { ...f, booking_hours: Number(f.booking_hours) || 0 }),
    onSuccess: () => {
      setOk(true)
      qc.invalidateQueries({ queryKey: ['realty-projects'] })
    },
  })
  const del = useMutation({
    mutationFn: () => api(`/realty/projects/${project.id}`, { method: 'DELETE' }),
    onSuccess: () => {
      onDeleted()
      qc.invalidateQueries({ queryKey: ['realty-projects'] })
    },
  })
  const ro = !canManage
  return (
    <div className="grid gap-5">
      <Card>
        <div className="border-b border-line px-5 py-4">
          <h3 className="font-semibold">{l('sec_project')}</h3>
        </div>
        <Row label={l('name')}>
          <Input value={f.name} onChange={(e) => set({ name: e.target.value })} disabled={ro} />
        </Row>
        <Row label={l('address')}>
          <Input value={f.address} onChange={(e) => set({ address: e.target.value })} disabled={ro} placeholder="Toshkent, Olmazor tumani" />
        </Row>
        <Row label={l('currency')} hint={l('currency_hint')}>
          <div className="inline-flex rounded-lg border border-line bg-ground p-0.5">
            {(['UZS', 'USD'] as const).map((c) => (
              <button
                key={c}
                type="button"
                disabled={ro}
                onClick={() => set({ currency: c })}
                className={`h-9 rounded-md px-4 text-sm font-medium ${f.currency === c ? 'bg-surface text-ink shadow-sm' : 'text-muted hover:text-ink'}`}
              >
                {c === 'UZS' ? 'UZS · soʻm' : 'USD · $'}
              </button>
            ))}
          </div>
        </Row>
        <Row label={l('booking')} hint={l('booking_hint')}>
          <div className="flex max-w-48 items-center rounded-lg border border-line bg-surface focus-within:border-accent">
            <input
              className="h-10 w-full min-w-0 rounded-lg bg-transparent px-3 text-sm focus:outline-none tabular"
              value={f.booking_hours}
              inputMode="numeric"
              onChange={(e) => set({ booking_hours: e.target.value.replace(/\D/g, '') })}
              disabled={ro}
            />
            <span className="px-3 text-sm text-muted">{l('hours')}</span>
          </div>
        </Row>
      </Card>

      <Card>
        <div className="border-b border-line px-5 py-4">
          <h3 className="font-semibold">{l('sec_show')}</h3>
        </div>
        <Row label={l('in_amo')} hint={l('in_amo_hint')}>
          <Switch id="rl-amo" checked={f.use_in_amocrm} onChange={(v) => set({ use_in_amocrm: v })} disabled={ro} />
        </Row>
        <Row label={l('public')} hint={l('public_hint')}>
          <Switch id="rl-public" checked={f.is_public} onChange={(v) => set({ is_public: v })} disabled={ro} />
        </Row>
        <Row label={l('sold_prices')} hint={l('sold_prices_hint')}>
          <Switch id="rl-sold" checked={f.show_sold_prices} onChange={(v) => set({ show_sold_prices: v })} disabled={ro} />
        </Row>
        <Row label={l('showroom')} hint={project.is_public ? undefined : l('showroom_off')}>
          <div className="flex items-center gap-2">
            <div className="min-w-0 flex-1">
              <CopyField value={project.showroom_url} />
            </div>
            {project.is_public && (
              <a href={project.showroom_url} target="_blank" rel="noopener" className="shrink-0 text-sm font-medium text-accent-ink hover:underline">
                {l('open')} ↗
              </a>
            )}
          </div>
        </Row>
        <p className="border-t border-line px-5 py-3 text-xs text-muted">{l('stages_hint')}</p>
      </Card>

      <ErrorNote error={save.error ?? del.error} />
      {canManage && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Button onClick={() => save.mutate()} busy={save.isPending}>
              {l('save')}
            </Button>
            {ok && !save.isPending && <span className="text-sm text-ok">✓ {l('saved')}</span>}
          </div>
          <Button variant="danger" busy={del.isPending} onClick={() => window.confirm(l('delete_confirm')) && del.mutate()}>
            {l('delete')}
          </Button>
        </div>
      )}
    </div>
  )
}
