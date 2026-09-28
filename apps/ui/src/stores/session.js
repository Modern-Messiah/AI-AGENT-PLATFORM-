import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'

const STORAGE_KEY = 'aap_session'

// Pure helpers (unit-tested) — the store wires them to localStorage.
export function parseSessionHash(hash) {
  const raw = String(hash || '')
  const tokenMatch = raw.match(/#token=(.+)$/)
  if (tokenMatch) return { token: tokenMatch[1], error: null }
  const errorMatch = raw.match(/#error=(.+)$/)
  if (errorMatch) return { token: null, error: decodeURIComponent(errorMatch[1]) }
  return { token: null, error: null }
}

export function decodeJwtPayload(token) {
  try {
    const part = String(token || '').split('.')[1]
    if (!part) return null
    const normalized = part.replace(/-/g, '+').replace(/_/g, '/')
    return JSON.parse(atob(normalized))
  } catch {
    return null
  }
}

export function sessionClaimsValid(claims, nowMs = Date.now()) {
  if (!claims || claims.type !== 'session') return false
  const exp = Number(claims.exp || 0)
  return Boolean(exp) && exp * 1000 > nowMs
}

export const useSessionStore = defineStore('session', () => {
  const token = ref('')
  const user = ref(null) // { tenant_id, user_id, user_name, email, role, is_admin }
  const status = ref('unknown') // 'unknown' | 'valid' | 'invalid'

  function _persist() {
    try {
      if (token.value) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ token: token.value, user: user.value }))
      } else {
        localStorage.removeItem(STORAGE_KEY)
      }
    } catch {}
  }

  function _load() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
      if (saved?.token) {
        const claims = decodeJwtPayload(saved.token)
        if (sessionClaimsValid(claims)) {
          token.value = saved.token
          user.value = saved.user || claimsToUser(claims)
        } else {
          localStorage.removeItem(STORAGE_KEY)
        }
      }
    } catch {}
  }

  function claimsToUser(claims) {
    if (!claims) return null
    return {
      tenant_id: claims.tid,
      user_id: claims.sub || null,
      user_name: claims.name || null,
      email: claims.email || null,
      role: claims.role || null,
      is_admin: claims.role === 'admin',
    }
  }

  function setToken(value) {
    const claims = decodeJwtPayload(value)
    if (!sessionClaimsValid(claims)) {
      status.value = 'invalid'
      return false
    }
    token.value = String(value)
    user.value = claimsToUser(claims)
    status.value = 'valid'
    _persist()
    return true
  }

  function setUser(info) {
    user.value = info || null
    _persist()
  }

  function markInvalid() {
    status.value = 'invalid'
    logout()
  }

  function logout() {
    token.value = ''
    user.value = null
    status.value = 'unknown'
    _persist()
  }

  // Expired tokens become unusable on tab activation, not just on load.
  watch(token, (value) => {
    if (!value) return
    const claims = decodeJwtPayload(value)
    if (!sessionClaimsValid(claims)) logout()
  })

  const isAuthenticated = computed(() => Boolean(token.value && user.value))
  const isAdmin = computed(() => Boolean(user.value?.is_admin))
  const displayName = computed(() => (
    user.value?.user_name || user.value?.email || ''
  ))

  _load()

  return {
    token,
    user,
    status,
    setToken,
    setUser,
    markInvalid,
    logout,
    isAuthenticated,
    isAdmin,
    displayName,
  }
})
