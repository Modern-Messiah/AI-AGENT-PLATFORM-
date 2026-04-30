import { useSettingsStore } from '@/stores/settings'

export function useApi() {
  const settings = useSettingsStore()

  async function apiFetch(path, opts = {}) {
    const base = settings.baseUrl || '/api'
    const res = await fetch(`${base}${path}`, {
      ...opts,
      headers: {
        'X-API-Key': settings.apiKey,
        ...(opts.headers || {}),
      },
    })
    if (!res.ok) {
      if (res.status === 401) settings.markInvalid()
      const text = await res.text().catch(() => res.statusText)
      throw new Error(`${res.status}: ${text}`)
    }
    if (settings.keyStatus !== 'valid') settings.markValid()
    if (res.status === 204 || res.headers.get('content-length') === '0') return null
    return res.json()
  }

  return { apiFetch }
}
