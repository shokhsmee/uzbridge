import { useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import type { CompanyInfo } from '../App'
import { Button, ErrorNote, Field, Input, LangSwitch, Logo } from '../components/ui'
import { post } from '../lib/api'
import { useT } from '../lib/i18n'

export default function LoginPage({ company }: { company: CompanyInfo }) {
  const { t } = useT()
  const nav = useNavigate()
  const qc = useQueryClient()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await post('/auth/login', { email, password })
      await qc.invalidateQueries({ queryKey: ['me'] })
      nav('/', { replace: true })
    } catch (err) {
      setError(err)
      setBusy(false)
    }
  }

  return (
    <div className="min-h-full flex flex-col px-4 py-8">
      <div className="flex justify-between items-center max-w-sm w-full mx-auto">
        <Logo />
        <LangSwitch />
      </div>
      <form onSubmit={submit} className="my-auto grid gap-4 max-w-sm w-full mx-auto">
        <div>
          <p className="text-sm text-muted font-mono">{new URL(company.url).host}</p>
          <h1 className="text-2xl font-semibold tracking-tight">{company.name}</h1>
        </div>
        <Field label={t('auth.email')}>
          <Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
        </Field>
        <Field label={t('auth.password')}>
          <Input id="password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </Field>
        <ErrorNote error={error} />
        <Button type="submit" busy={busy}>
          {t('auth.login')}
        </Button>
      </form>
    </div>
  )
}
