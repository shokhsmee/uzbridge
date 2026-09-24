import { useQuery } from '@tanstack/react-query'
import { Navigate, Route, Routes } from 'react-router-dom'
import Shell from './components/Shell'
import { get } from './lib/api'
import { useT } from './lib/i18n'
import AmoCrmPage from './pages/AmoCrmPage'
import Handoff from './pages/Handoff'
import IntegrationsPage from './pages/IntegrationsPage'
import LoginPage from './pages/LoginPage'
import OverviewPage from './pages/OverviewPage'
import PaymentsPage from './pages/PaymentsPage'
import PlatformHome from './pages/PlatformHome'
import ProvidersPage from './pages/ProvidersPage'

export type CompanyInfo = { name: string; slug: string; url: string }
export type Me = { email: string; full_name: string; role: 'owner' | 'admin' | 'member'; company: CompanyInfo }

export default function App() {
  const { t } = useT()
  // Also sets the csrftoken cookie for this host.
  const ctx = useQuery({ queryKey: ['ctx'], queryFn: () => get<{ company: CompanyInfo | null }>('/auth/csrf') })

  if (ctx.isLoading) return <p className="p-8 text-muted">{t('common.loading')}</p>
  if (ctx.isError) return <p className="p-8 text-bad">This company address doesn’t exist.</p>

  const company = ctx.data?.company
  if (!company) {
    // app.* (or the bare domain): sign up and pick a company.
    return <PlatformHome />
  }
  return (
    <Routes>
      <Route path="/auth/handoff" element={<Handoff />} />
      <Route path="/login" element={<LoginPage company={company} />} />
      <Route path="/*" element={<Tenant />} />
    </Routes>
  )
}

function Tenant() {
  const me = useQuery({ queryKey: ['me'], queryFn: () => get<Me>('/auth/me') })
  if (me.isLoading) return null
  if (me.isError) return <Navigate to="/login" replace />
  return (
    <Shell me={me.data!}>
      <Routes>
        <Route index element={<OverviewPage />} />
        <Route path="integrations" element={<IntegrationsPage />} />
        <Route path="integrations/amocrm" element={<AmoCrmPage me={me.data!} />} />
        <Route path="providers" element={<ProvidersPage me={me.data!} />} />
        <Route path="payments" element={<PaymentsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  )
}
