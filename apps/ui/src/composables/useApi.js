import { useSettingsStore } from '@/stores/settings'

export function useApi() {
  const settings = useSettingsStore()

  async function apiRawFetch(path, opts = {}) {
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
      xhr.setRequestHeader('X-API-Key', settings.apiKey)
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
          if (xhr.status === 401) settings.markInvalid()
          reject(new Error(`${xhr.status}: ${xhr.responseText || xhr.statusText}`))
        }
      }
      xhr.onerror = () => reject(new Error('network error'))
      xhr.send(body)
    })
  }

  return { apiFetch, apiRawFetch, apiStreamFetch, apiUpload }
}
