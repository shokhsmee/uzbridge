import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'
import { setCompanySlug } from './lib/api'
import { LangProvider } from './lib/i18n'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
})

// Top-level paths that belong to the platform, never to a company.
const RESERVED = new Set(['api', 'cb', 'p', 'oauth', 'admin', 'static', 'assets', 'auth', 'login', '@fs'])

async function boot() {
  let tenancy = 'subdomain'
  try {
    tenancy = (await fetch('/api/auth/config').then((r) => r.json())).tenancy
  } catch {
    /* keep subdomain */
  }
  const first = window.location.pathname.split('/')[1] ?? ''
  const slug = tenancy === 'path' && first && !RESERVED.has(first) ? first : null
  setCompanySlug(slug)

  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <LangProvider>
          <BrowserRouter basename={slug ? `/${slug}` : undefined}>
            <App tenancy={tenancy} />
          </BrowserRouter>
        </LangProvider>
      </QueryClientProvider>
    </StrictMode>,
  )
}

boot()
