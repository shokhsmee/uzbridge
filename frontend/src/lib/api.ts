export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

// Path tenancy (uzbridge.uz/acme/...): the company travels in a header.
let companySlug: string | null = null
export function setCompanySlug(slug: string | null) {
  companySlug = slug
}

function csrfToken(): string {
  return document.cookie.match(/(?:^|; )csrftoken=([^;]+)/)?.[1] ?? ''
}

function messageOf(body: unknown, status: number): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const d = (body as { detail: unknown }).detail
    if (typeof d === 'string') return d
    if (d && typeof d === 'object') {
      const first = Object.values(d as Record<string, unknown>)[0]
      if (Array.isArray(first)) {
        const f = first[0]
        return typeof f === 'string' ? f : (f as { msg?: string })?.msg ?? 'Invalid data'
      }
    }
  }
  return status >= 500 ? 'Server error. Try again in a moment.' : `Request failed (${status})`
}

export async function api<T = unknown>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = init.method ?? 'GET'
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (companySlug) headers['X-Company'] = companySlug
  if (method !== 'GET') {
    headers['Content-Type'] = 'application/json'
    headers['X-CSRFToken'] = csrfToken()
  }
  const res = await fetch(`/api${path}`, {
    method,
    headers,
    credentials: 'same-origin',
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  })
  const text = await res.text()
  const body = text ? JSON.parse(text) : null
  if (res.status === 401 && companySlug && !path.startsWith('/auth/')) {
    // Session ended (other device signed in, or ended from Kabinet): sign in again.
    window.location.href = `/${companySlug}/login`
  }
  if (!res.ok) throw new ApiError(res.status, messageOf(body, res.status), body)
  return body as T
}

export const get = <T,>(path: string) => api<T>(path)
export const post = <T,>(path: string, body?: unknown) => api<T>(path, { method: 'POST', body: body ?? {} })
export const put = <T,>(path: string, body: unknown) => api<T>(path, { method: 'PUT', body })

/** tiyin -> "1 500 000" (so'm, no decimals unless there are tiyin). */
export function soum(tiyin: number): string {
  const whole = Math.floor(tiyin / 100)
  const frac = tiyin % 100
  const s = whole.toLocaleString('ru-RU').replace(/ /g, ' ')
  return frac ? `${s}.${String(frac).padStart(2, '0')}` : s
}

export function when(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

async function raw(path: string, init: { method: string; json?: unknown; form?: FormData }): Promise<Response> {
  const headers: Record<string, string> = { 'X-CSRFToken': csrfToken() }
  if (companySlug) headers['X-Company'] = companySlug
  if (init.json !== undefined) headers['Content-Type'] = 'application/json'
  const res = await fetch(`/api${path}`, {
    method: init.method,
    headers,
    credentials: 'same-origin',
    body: init.form ?? (init.json === undefined ? undefined : JSON.stringify(init.json)),
  })
  if (!res.ok) {
    const text = await res.text()
    let body: unknown = null
    try {
      body = text ? JSON.parse(text) : null
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, messageOf(body, res.status), body)
  }
  return res
}

/** Multipart upload (e.g. a .docx template); returns the JSON answer. */
export async function upload<T>(path: string, form: FormData): Promise<T> {
  return (await raw(path, { method: 'POST', form })).json() as Promise<T>
}

/** POST that answers with a file: saves it in the browser under the server's filename. */
export async function downloadPost(path: string, body: unknown, fallbackName: string): Promise<void> {
  const res = await raw(path, { method: 'POST', json: body })
  const cd = res.headers.get('Content-Disposition') || ''
  const name = decodeURIComponent(cd.match(/filename\*=UTF-8''([^;]+)/)?.[1] ?? cd.match(/filename="([^"]+)"/)?.[1] ?? fallbackName)
  const url = URL.createObjectURL(await res.blob())
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 5000)
}

/** GET a file with the company header (for <img> of private images and downloads). */
export async function fetchBlob(path: string): Promise<Blob> {
  return (await raw(path, { method: 'GET' })).blob()
}

export async function downloadGet(path: string, name: string): Promise<void> {
  const url = URL.createObjectURL(await fetchBlob(path))
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 5000)
}
