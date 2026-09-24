import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { post } from '../lib/api'
import { useT } from '../lib/i18n'

export default function Handoff() {
  const { t } = useT()
  const [params] = useSearchParams()
  const nav = useNavigate()
  const qc = useQueryClient()
  const [error, setError] = useState('')
  const once = useRef(false)

  useEffect(() => {
    if (once.current) return // the token is single use; StrictMode would spend it twice
    once.current = true
    post(`/auth/handoff?token=${encodeURIComponent(params.get('token') ?? '')}`)
      .then(() => {
        qc.invalidateQueries({ queryKey: ['me'] })
        nav('/', { replace: true })
      })
      .catch((e: Error) => setError(e.message))
  }, [params, nav, qc])

  return (
    <div className="p-10 text-center">
      {error ? (
        <p className="text-bad">
          {error} <Link className="text-accent" to="/login">{t('auth.login')}</Link>
        </p>
      ) : (
        <p className="text-muted">{t('auth.signing_in')}</p>
      )}
    </div>
  )
}
