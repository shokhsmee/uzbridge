import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { get } from '../lib/api'
import { useT } from '../lib/i18n'
import { Button, ErrorNote, Field, Select } from './ui'

type PayAcc = { id: number; provider: 'payme' | 'click' | 'uzum'; provider_label: string; label: string; is_enabled: boolean; is_configured: boolean }
type SmsAcc = { id: number; provider_label: string; label: string; is_enabled: boolean; is_configured: boolean }
export type AccountChoice = { payment_accounts: number[] | null; sms_account_id: number | null }

const LOGO = { payme: '/brands/payme.png', click: '/brands/click.svg', uzum: '/brands/uzum.png' } as const
const NAMES = { payme: 'Payme', click: 'Click', uzum: 'Uzum Bank' } as const

/**
 * Which cash desk per provider and which SMS account one connection uses
 * (one amoCRM account, one Odoo). `payment_accounts: null` = not chosen yet,
 * which means the company's first working account of each provider.
 */
export function AccountPicker({ value, onSave, canManage }: { value: AccountChoice; onSave: (v: AccountChoice) => Promise<unknown>; canManage: boolean }) {
  const { t } = useT()
  const pay = useQuery({ queryKey: ['providers'], queryFn: () => get<PayAcc[]>('/payments/providers') })
  const sms = useQuery({ queryKey: ['sms-accounts'], queryFn: () => get<SmsAcc[]>('/sms/accounts') })
  const [choice, setChoice] = useState<Record<string, number> | null>(null)
  const [smsChoice, setSmsChoice] = useState<number | null>(value.sms_account_id)
  const [saved, setSaved] = useState(false)
  const save = useMutation({
    mutationFn: (v: AccountChoice) => onSave(v),
    onSuccess: () => {
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    },
  })
  if (!pay.data || !sms.data) return null
  const usable = pay.data.filter((a) => a.is_enabled && a.is_configured)
  const smsUsable = sms.data.filter((a) => a.is_enabled && a.is_configured)
  const initial: Record<string, number> = {}
  for (const prov of ['payme', 'click', 'uzum'] as const) {
    const of = usable.filter((a) => a.provider === prov)
    const chosen = value.payment_accounts == null ? of[0]?.id : of.find((a) => value.payment_accounts!.includes(a.id))?.id
    initial[prov] = chosen ?? 0
  }
  const current = choice ?? initial
  return (
    <div className="grid gap-4">
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {(['payme', 'click', 'uzum'] as const).map((prov) => {
          const of = usable.filter((a) => a.provider === prov)
          return (
            <Field key={prov} label={NAMES[prov]}>
              <div className="flex items-center gap-2">
                <img src={LOGO[prov]} alt="" className="size-8 shrink-0 rounded-lg border border-line bg-white object-contain p-0.5" />
                <Select value={current[prov] ?? 0} disabled={!canManage || !of.length} onChange={(e) => setChoice({ ...current, [prov]: Number(e.target.value) })}>
                  <option value={0}>{of.length ? t('amo.acc_off') : t('amo.acc_none')}</option>
                  {of.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.label || a.provider_label}
                    </option>
                  ))}
                </Select>
              </div>
            </Field>
          )
        })}
        <Field label="SMS">
          <Select value={smsChoice ?? 0} disabled={!canManage || !smsUsable.length} onChange={(e) => setSmsChoice(Number(e.target.value) || null)}>
            <option value={0}>{smsUsable.length ? t('amo.acc_default') : t('amo.acc_none')}</option>
            {smsUsable.map((a) => (
              <option key={a.id} value={a.id}>
                {a.label ? `${a.provider_label} · ${a.label}` : a.provider_label}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      <ErrorNote error={save.error} />
      {canManage && (
        <div className="flex items-center gap-3">
          <Button type="button" busy={save.isPending} onClick={() => save.mutate({ payment_accounts: Object.values(current).filter(Boolean), sms_account_id: smsChoice })}>
            {t('amo.save')}
          </Button>
          {saved && <span className="text-sm text-ok">✓ {t('amo.saved')}</span>}
        </div>
      )}
    </div>
  )
}
