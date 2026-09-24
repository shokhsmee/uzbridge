import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react'
import { useState } from 'react'
import { useT } from '../lib/i18n'

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'ghost' | 'danger'; busy?: boolean }

export function Button({ variant = 'primary', busy, className = '', children, disabled, ...rest }: BtnProps) {
  const styles = {
    primary: 'bg-accent text-white hover:bg-accent-ink',
    ghost: 'bg-surface text-ink border border-line hover:border-accent',
    danger: 'bg-surface text-bad border border-line hover:border-bad',
  }[variant]
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-4 h-10 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${styles} ${className}`}
      disabled={disabled || busy}
      {...rest}
    >
      {busy && <span className="size-3.5 rounded-full border-2 border-current border-r-transparent animate-spin" aria-hidden />}
      {children}
    </button>
  )
}

export function Field({ label, hint, error, children }: { label: string; hint?: ReactNode; error?: string; children: ReactNode }) {
  return (
    <label className="grid gap-1.5 text-sm">
      <span className="font-medium">{label}</span>
      {children}
      {error ? <span className="text-bad text-xs">{error}</span> : hint ? <span className="text-muted text-xs">{hint}</span> : null}
    </label>
  )
}

export function Input({ className = '', ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`h-10 w-full rounded-lg border border-line bg-surface px-3 text-sm placeholder:text-muted/70 focus:border-accent focus:outline-none ${className}`}
      {...rest}
    />
  )
}

export function Select({ className = '', children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={`h-10 w-full rounded-lg border border-line bg-surface px-3 text-sm focus:border-accent focus:outline-none ${className}`}
      {...rest}
    >
      {children}
    </select>
  )
}

export function Toggle({ checked, onChange, label, id }: { checked: boolean; onChange: (v: boolean) => void; label: string; id: string }) {
  return (
    <label htmlFor={id} className="inline-flex items-center gap-2.5 text-sm cursor-pointer select-none">
      <span className={`relative h-5 w-9 rounded-full transition-colors ${checked ? 'bg-accent' : 'bg-line'}`}>
        <input id={id} type="checkbox" className="peer sr-only" checked={checked} onChange={(e) => onChange(e.target.checked)} />
        <span className={`absolute top-0.5 size-4 rounded-full bg-white shadow transition-all ${checked ? 'left-4.5' : 'left-0.5'}`} />
      </span>
      {label}
    </label>
  )
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-xl border border-line bg-surface ${className}`}>{children}</section>
}

export function PageHeader({ title, lede, action }: { title: string; lede?: string; action?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4 mb-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-balance">{title}</h1>
        {lede && <p className="text-muted mt-1 max-w-2xl">{lede}</p>}
      </div>
      {action}
    </header>
  )
}

const pillTone = {
  pending: 'bg-warn-soft text-warn',
  paid: 'bg-ok-soft text-ok',
  cancelled: 'bg-ground text-muted',
  refunded: 'bg-bad-soft text-bad',
  active: 'bg-ok-soft text-ok',
  error: 'bg-bad-soft text-bad',
  neutral: 'bg-ground text-muted',
  accent: 'bg-accent-soft text-accent-ink',
} as const

export function Pill({ tone, children }: { tone: keyof typeof pillTone; children: ReactNode }) {
  return <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap ${pillTone[tone]}`}>{children}</span>
}

export function StatusPill({ status }: { status: 'pending' | 'paid' | 'cancelled' | 'refunded' }) {
  const { t } = useT()
  return <Pill tone={status}>{t(`status.${status}`)}</Pill>
}

export function CopyField({ value }: { value: string }) {
  const { t } = useT()
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard refused: the field is selectable */
    }
  }
  return (
    <div className="flex gap-2">
      <input readOnly value={value} onFocus={(e) => e.target.select()} className="h-9 flex-1 min-w-0 rounded-lg border border-line bg-ground px-3 font-mono text-xs" />
      <Button type="button" variant="ghost" className="h-9" onClick={copy}>
        {copied ? t('pr.copied') : t('pr.copy')}
      </Button>
    </div>
  )
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null
  const msg = error instanceof Error ? error.message : String(error)
  return <p className="rounded-lg bg-bad-soft text-bad text-sm px-3 py-2">{msg}</p>
}

export function LangSwitch() {
  const { lang, setLang } = useT()
  return (
    <div className="inline-flex rounded-lg border border-line bg-surface p-0.5 text-xs">
      {(['uz', 'ru'] as const).map((l) => (
        <button key={l} onClick={() => setLang(l)} className={`rounded-md px-2 py-1 ${lang === l ? 'bg-ink text-white' : 'text-muted'}`}>
          {l === 'uz' ? 'Oʻz' : 'Ру'}
        </button>
      ))}
    </div>
  )
}

export function Logo() {
  return (
    <span className="inline-flex items-center gap-2 font-semibold tracking-tight">
      <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden>
        <rect x="1" y="1" width="20" height="20" rx="6" fill="var(--color-accent)" />
        <path d="M5 14c2.5-5 9.5-5 12 0" stroke="#fff" strokeWidth="2" fill="none" strokeLinecap="round" />
        <path d="M7 14v3M15 14v3M11 11v6" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
      </svg>
      uzbridge
    </span>
  )
}
