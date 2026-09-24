import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Card, PageHeader, Pill } from '../components/ui'
import { get } from '../lib/api'
import { useT } from '../lib/i18n'

type Item = { key: string; name: string; kind: string; available: boolean; status: string }

const MARK: Record<string, { bg: string; text: string }> = {
  amocrm: { bg: '#1c6fd1', text: 'amo' },
  bitrix24: { bg: '#2fc6f6', text: 'B24' },
  odoo: { bg: '#714b67', text: 'odoo' },
  uysot: { bg: '#e8742a', text: 'UY' },
  telegram: { bg: '#2aabee', text: 'TG' },
}

export default function IntegrationsPage() {
  const { t } = useT()
  const q = useQuery({ queryKey: ['integrations'], queryFn: () => get<Item[]>('/integrations') })
  return (
    <>
      <PageHeader title={t('int.title')} lede={t('int.lede')} />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {q.data?.map((it) => {
          const mark = MARK[it.key]
          const connected = it.status === 'active'
          return (
            <Card key={it.key} className={`p-5 flex flex-col gap-4 ${it.available ? '' : 'opacity-60'}`}>
              <div className="flex items-start justify-between gap-3">
                <span className="grid size-11 place-items-center rounded-xl text-white text-xs font-bold" style={{ background: mark?.bg }}>
                  {mark?.text}
                </span>
                {!it.available ? (
                  <Pill tone="neutral">{t('int.soon')}</Pill>
                ) : connected ? (
                  <Pill tone="active">{t('int.connected')}</Pill>
                ) : it.status === 'error' ? (
                  <Pill tone="error">{t('int.error')}</Pill>
                ) : null}
              </div>
              <div>
                <h2 className="font-semibold">{it.name}</h2>
                <p className="text-xs text-muted uppercase tracking-wider mt-0.5">{it.kind}</p>
              </div>
              {it.available && (
                <Link
                  to={`/integrations/${it.key}`}
                  className="mt-auto inline-flex h-9 items-center justify-center rounded-lg border border-line text-sm font-medium hover:border-accent"
                >
                  {connected || it.status === 'error' ? t('int.open') : t('int.connect')}
                </Link>
              )}
            </Card>
          )
        })}
      </div>
    </>
  )
}
