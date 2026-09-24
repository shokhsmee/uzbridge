import { useQueryClient } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import type { Me } from '../App'
import { useT, type Key } from '../lib/i18n'
import { LangSwitch, Logo } from './ui'
import { useQuery } from '@tanstack/react-query'
import { get, post, soum } from '../lib/api'
import { BillingBanner, type Billing } from '../pages/CabinetPage'

type Item = { to: string; key: Key; end?: boolean }
// Grouped so payments, SMS and each integration live on their own page.
const NAV: { title?: Key; items: Item[] }[] = [
  {
    items: [
      { to: '/', key: 'nav.overview', end: true },
      { to: '/payments', key: 'nav.payments' },
      { to: '/sms', key: 'nav.sms' },
    ],
  },
  {
    title: 'nav.integrations',
    items: [
      { to: '/integrations/amocrm', key: 'nav.amocrm' },
      { to: '/integrations/odoo', key: 'nav.odoo' },
      { to: '/developers', key: 'nav.api' },
      { to: '/integrations', key: 'nav.all_integrations', end: true },
    ],
  },
  {
    title: 'nav.settings',
    items: [
      { to: '/cabinet', key: 'nav.cabinet' },
      { to: '/providers', key: 'nav.providers' },
    ],
  },
]

export default function Shell({ me, children }: { me: Me; children: ReactNode }) {
  const { t } = useT()
  const qc = useQueryClient()
  const nav = useNavigate()
  const logout = async () => {
    await post('/auth/logout')
    qc.clear()
    nav('/login')
  }
  return (
    <div className="min-h-full md:grid md:grid-cols-[232px_1fr]">
      <aside className="border-b md:border-b-0 md:border-r border-line bg-surface px-4 py-4 md:py-6 md:sticky md:top-0 md:h-screen flex md:flex-col gap-4 md:gap-6 items-center md:items-stretch overflow-x-auto">
        <div className="md:px-2 shrink-0">
          <Logo />
          <p className="hidden md:block text-xs text-muted mt-1 truncate font-mono">{me.company.slug}</p>
        </div>
        <nav className="flex md:flex-col gap-1 md:gap-4 text-sm">
          {NAV.map((group, i) => (
            <div key={i} className="flex md:flex-col gap-1">
              {group.title && <p className="hidden md:block px-3 pt-1 text-[11px] uppercase tracking-wider text-muted/80">{t(group.title)}</p>}
              {group.items.map((n) => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  end={n.end}
                  className={({ isActive }) =>
                    `whitespace-nowrap rounded-lg px-3 py-2 ${isActive ? 'bg-accent-soft text-accent-ink font-medium' : 'text-muted hover:text-ink'}`
                  }
                >
                  {t(n.key)}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="ml-auto md:ml-0 md:mt-auto md:px-2 grid gap-3 shrink-0">
          <div className="hidden md:block text-sm">
            <BalanceChip />
            <p className="font-medium truncate">{me.company.name}</p>
            <p className="text-muted text-xs truncate">{me.email}</p>
          </div>
          <div className="flex items-center gap-2">
            <LangSwitch />
            <button onClick={logout} className="text-xs text-muted hover:text-ink">
              {t('nav.logout')}
            </button>
          </div>
        </div>
      </aside>
      <main className="px-4 md:px-10 py-8 max-w-6xl w-full">
        <BillingBanner />
        {children}
      </main>
    </div>
  )
}

function BalanceChip() {
  const { t } = useT()
  const s = useQuery({ queryKey: ['billing'], queryFn: () => get<Billing>('/billing/summary') })
  if (!s.data || s.data.state === 'platform') return null
  return (
    <NavLink to="/cabinet#balance" className="mb-2 block rounded-lg border border-line px-3 py-2 hover:border-accent">
      <span className="block text-[11px] uppercase tracking-wider text-muted">{t('cab.balance')}</span>
      <span className={`font-mono tabular font-semibold ${s.data.balance_tiyin < 0 ? 'text-bad' : ''}`}>{soum(s.data.balance_tiyin)} soʻm</span>
    </NavLink>
  )
}
