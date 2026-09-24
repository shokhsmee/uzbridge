import { useEffect, useState, type FormEvent } from 'react'
import { get, post } from '../lib/api'
import { useT } from '../lib/i18n'
import { Button, ErrorNote, Field, Input, LangSwitch, Logo } from '../components/ui'

type Found = { name: string; slug: string; url: string; enter: string }

const suffix = () => {
  const host = window.location.host.split('.').slice(1).join('.')
  return `.${host || window.location.host}`
}

function slugify(s: string) {
  return s
    .toLowerCase()
    .replace(/[ʻʼ'`’]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 32)
}

export default function PlatformHome() {
  const { t } = useT()
  const [mode, setMode] = useState<'signup' | 'login'>('signup')
  return (
    <div className="min-h-full grid lg:grid-cols-[1fr_480px]">
      <section className="hidden lg:flex flex-col justify-between bg-ink text-white p-12">
        <Logo />
        <div className="max-w-md">
          <p className="text-3xl font-semibold leading-tight text-balance">{t('auth.signup.lede')}</p>
          <ul className="mt-8 grid gap-3 text-white/70 text-sm">
            <li>① amoCRM — bitim kartasidan havola · ссылка из карточки сделки</li>
            <li>② Payme · Click · Uzum — bitta sahifada · на одной странице</li>
            <li>③ Toʻlov → bitim “Toʻlandi” · оплата → сделка «Оплачено»</li>
          </ul>
        </div>
        <p className="text-white/40 text-xs">MXIK / IKPU fiskal cheklar bilan · с фискальными чеками</p>
      </section>
      <section className="flex flex-col px-4 sm:px-10 py-8">
        <div className="flex items-center justify-between">
          <span className="lg:hidden">
            <Logo />
          </span>
          <span className="ml-auto">
            <LangSwitch />
          </span>
        </div>
        <div className="my-auto w-full max-w-sm mx-auto py-10">
          {mode === 'signup' ? <Signup /> : <PlatformLogin />}
          <p className="mt-6 text-sm text-muted">
            {mode === 'signup' ? t('auth.have_account') : t('auth.no_account')}{' '}
            <button className="text-accent font-medium" onClick={() => setMode(mode === 'signup' ? 'login' : 'signup')}>
              {mode === 'signup' ? t('auth.login') : t('auth.create')}
            </button>
          </p>
        </div>
      </section>
    </div>
  )
}

function Signup() {
  const { t } = useT()
  const [form, setForm] = useState({ company_name: '', slug: '', full_name: '', email: '', password: '' })
  const [slugTouched, setSlugTouched] = useState(false)
  const [slugState, setSlugState] = useState<{ available: boolean; reason: string } | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [preparing, setPreparing] = useState(false)

  useEffect(() => {
    if (form.slug.length < 3) return setSlugState(null)
    const id = setTimeout(() => {
      get<{ available: boolean; reason: string }>(`/auth/slug-available?slug=${encodeURIComponent(form.slug)}`)
        .then(setSlugState)
        .catch(() => setSlugState(null))
    }, 300)
    return () => clearTimeout(id)
  }, [form.slug])

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value
    setForm((f) => ({ ...f, [k]: v, ...(k === 'company_name' && !slugTouched ? { slug: slugify(v) } : {}) }))
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const r = await post<{ redirect: string; slug: string }>('/auth/signup', form)
      setPreparing(true)
      // A new subdomain needs its TLS certificate before the browser can open it.
      for (let i = 0; i < 60; i++) {
        const { ready } = await get<{ ready: boolean }>(`/auth/host-ready?slug=${encodeURIComponent(r.slug)}`)
        if (ready) break
        await new Promise((res) => setTimeout(res, 3000))
      }
      window.location.href = r.redirect
    } catch (err) {
      setError(err)
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="grid gap-4">
      <h1 className="text-2xl font-semibold tracking-tight">{t('auth.signup.title')}</h1>
      <Field label={t('auth.company')}>
        <Input id="company_name" required value={form.company_name} onChange={set('company_name')} placeholder="Nur Savdo" />
      </Field>
      <Field
        label={t('auth.slug')}
        error={slugState && !slugState.available ? slugState.reason : undefined}
        hint={slugState?.available ? `✓ ${t('auth.slug_free')}` : undefined}
      >
        <div className="flex items-center rounded-lg border border-line bg-surface focus-within:border-accent">
          <input
            id="slug"
            required
            value={form.slug}
            onChange={(e) => {
              setSlugTouched(true)
              setForm((f) => ({ ...f, slug: slugify(e.target.value) }))
            }}
            className="h-10 min-w-0 flex-1 bg-transparent px-3 text-sm font-mono focus:outline-none"
            placeholder="nur-savdo"
          />
          <span className="pr-3 text-sm text-muted font-mono">{suffix()}</span>
        </div>
      </Field>
      <Field label={t('auth.name')}>
        <Input id="full_name" value={form.full_name} onChange={set('full_name')} autoComplete="name" />
      </Field>
      <Field label={t('auth.email')}>
        <Input id="email" type="email" required value={form.email} onChange={set('email')} autoComplete="email" />
      </Field>
      <Field label={t('auth.password')}>
        <Input id="password" type="password" required minLength={8} value={form.password} onChange={set('password')} autoComplete="new-password" />
      </Field>
      <ErrorNote error={error} />
      {preparing && <p className="rounded-lg bg-accent-soft text-accent-ink text-sm px-3 py-2">{t('auth.preparing')}</p>}
      <Button type="submit" busy={busy} disabled={slugState?.available === false}>
        {t('auth.create')}
      </Button>
    </form>
  )
}

function PlatformLogin() {
  const { t } = useT()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [found, setFound] = useState<Found[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const r = await post<{ companies: Found[] }>('/auth/login', { email, password })
      if (r.companies.length === 1) window.location.href = r.companies[0].enter
      else setFound(r.companies)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  if (found) {
    return (
      <div className="grid gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">{t('auth.choose_company')}</h1>
        {found.map((c) => (
          <a key={c.slug} href={c.enter} className="rounded-xl border border-line bg-surface px-4 py-3 hover:border-accent">
            <p className="font-medium">{c.name}</p>
            <p className="text-xs text-muted font-mono">{new URL(c.url).host}</p>
          </a>
        ))}
      </div>
    )
  }
  return (
    <form onSubmit={submit} className="grid gap-4">
      <h1 className="text-2xl font-semibold tracking-tight">{t('auth.login.title')}</h1>
      <Field label={t('auth.email')}>
        <Input id="login_email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
      </Field>
      <Field label={t('auth.password')}>
        <Input id="login_password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
      </Field>
      <ErrorNote error={error} />
      <Button type="submit" busy={busy}>
        {t('auth.login')}
      </Button>
    </form>
  )
}
