import { useSettingsStore } from '@/stores/settings'
import { useSessionStore } from '@/stores/session'

export function useApi() {
  const settings = useSettingsStore()
  const session = useSessionStore()

  // Session (Google login) takes precedence; API key stays as the fallback.
  function _tenantHeaders() {
    if (session.isAuthenticated) return { Authorization: `Bearer ${session.token}` }
    // No credentials yet — send no header rather than an empty X-API-Key.
    return settings.apiKey ? { 'X-API-Key': settings.apiKey } : {}
  }

  async function apiRawFetch(path, opts = {}) {
    const base = settings.baseUrl || '/api'
    const res = await fetch(`${base}${path}`, {
      ...opts,
      headers: {
        ..._tenantHeaders(),
        ...(opts.headers || {}),
      },
    })
    if (!res.ok) {
      if (res.status === 401) {
        if (session.isAuthenticated) session.markInvalid()
        else settings.markInvalid()
      }
      const text = await res.text().catch(() => res.statusText)
      throw new Error(`${res.status}: ${text}`)
    }
    if (session.isAuthenticated) {
      // keep it; /auth/me refresh handled where needed
    } else if (settings.keyStatus !== 'valid') settings.markValid()
    return res
  }

  async function apiFetch(path, opts = {}) {
    const res = await apiRawFetch(path, opts)
    if (res.status === 204 || res.headers.get('content-length') === '0') return null
    return res.json()
  }

  async function apiStreamFetch(path, opts = {}) {
    return apiRawFetch(path, opts)
  }

  // Upload with progress events: fetch() cannot report request-body progress,
  // so file uploads go through XHR. Same auth and 401 handling as apiFetch.
  function apiUpload(path, opts = {}) {
    const { method = 'POST', body, onProgress } = opts
    return new Promise((resolve, reject) => {
      const base = settings.baseUrl || '/api'
      const xhr = new XMLHttpRequest()
      xhr.open(method, `${base}${path}`)
      const headers = _tenantHeaders()
      for (const [name, value] of Object.entries(headers)) xhr.setRequestHeader(name, value)
      if (onProgress) {
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) onProgress(e.loaded / e.total)
        }
      }
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          if (settings.keyStatus !== 'valid') settings.markValid()
          try {
            resolve(xhr.responseText ? JSON.parse(xhr.responseText) : null)
          } catch {
            resolve(null)
          }
        } else {
          if (xhr.status === 401) {
            if (session.isAuthenticated) session.markInvalid()
            else settings.markInvalid()
          }
          reject(new Error(`${xhr.status}: ${xhr.responseText || xhr.statusText}`))
        }
      }
      xhr.onerror = () => reject(new Error('network error'))
      xhr.send(body)
    })
  }

  // Admin panel calls: an admin session (Bearer) when logged in via Google,
  // otherwise the deployment-wide admin secret.
  async function apiAdminFetch(path, opts = {}) {
    const base = settings.baseUrl || '/api'
    const headers = session.isAdmin
      ? { Authorization: `Bearer ${session.token}` }
      : { 'X-Admin-Secret': settings.adminSecret }
    const res = await fetch(`${base}${path}`, {
      ...opts,
      headers: {
        ...headers,
        ...(opts.headers || {}),
      },
    })
    if (!res.ok) {
      if (res.status === 403 && !session.isAdmin) settings.markAdminInvalid()
      const text = await res.text().catch(() => res.statusText)
      throw new Error(`${res.status}: ${text}`)
    }
    if (!session.isAdmin && settings.adminStatus !== 'valid') settings.markAdminValid()
    if (res.status === 204 || res.headers.get('content-length') === '0') return null
    return res.json()
  }

  return { apiFetch, apiRawFetch, apiStreamFetch, apiUpload, apiAdminFetch }
}
