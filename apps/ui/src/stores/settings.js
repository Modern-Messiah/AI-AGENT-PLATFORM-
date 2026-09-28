import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { resolveApiConfig } from '@/utils/apiConfig'
import { normalizeLocale, translate } from '@/i18n'
import { applyTheme, AUTO_THEME, DEFAULT_THEME, normalizeTheme, persistTheme } from '@/utils/theme'

export const useSettingsStore = defineStore('settings', () => {
  const apiKey = ref('')
  const adminSecret = ref('')
  const baseUrl = ref('/api')
  const locale = ref('ru')
  const theme = ref(DEFAULT_THEME)
  const keySource = ref('missing')
  const keyStatus = ref('unknown') // 'unknown' | 'valid' | 'invalid'
  const adminStatus = ref('unknown') // 'unknown' | 'valid' | 'invalid'

  function _load() {
    try {
      const cfg = JSON.parse(localStorage.getItem('aap_config') || '{}')
      const resolved = resolveApiConfig({ stored: cfg, env: import.meta.env })
      apiKey.value = resolved.apiKey
      adminSecret.value = typeof cfg.adminSecret === 'string' ? cfg.adminSecret : ''
      baseUrl.value = resolved.baseUrl
      locale.value = normalizeLocale(cfg.locale)
      theme.value = normalizeTheme(cfg.theme)
      keySource.value = resolved.keySource
    } catch {}
  }

  function save(key, url) {
    const resolved = resolveApiConfig({ env: import.meta.env })
    baseUrl.value = (url || resolved.baseUrl || '/api').trim()
    if (resolved.isKeyManagedByEnv) {
      apiKey.value = resolved.apiKey
      keySource.value = 'env'
      localStorage.setItem('aap_config', JSON.stringify({
        base: baseUrl.value,
        adminSecret: adminSecret.value,
        locale: locale.value,
        theme: theme.value,
      }))
      return
    }

    apiKey.value = key.trim()
    keySource.value = apiKey.value ? 'localStorage' : 'missing'
    localStorage.setItem('aap_config', JSON.stringify({
      apiKey: apiKey.value,
      adminSecret: adminSecret.value,
      base: baseUrl.value,
      locale: locale.value,
      theme: theme.value,
    }))
  }

  function setAdminSecret(value) {
    adminSecret.value = String(value || '').trim()
    adminStatus.value = 'unknown'
    try {
      const cfg = JSON.parse(localStorage.getItem('aap_config') || '{}')
      localStorage.setItem('aap_config', JSON.stringify({ ...cfg, adminSecret: adminSecret.value }))
    } catch {}
  }

  function setLocale(value) {
    locale.value = normalizeLocale(value)
    try {
      const cfg = JSON.parse(localStorage.getItem('aap_config') || '{}')
      localStorage.setItem('aap_config', JSON.stringify({ ...cfg, locale: locale.value }))
    } catch {}
  }

  function setTheme(value) {
    theme.value = normalizeTheme(value)
    try {
      persistTheme(localStorage, theme.value)
    } catch {}
  }

  function markValid()   { keyStatus.value = 'valid' }
  function markInvalid() { keyStatus.value = 'invalid' }
  function markAdminValid()   { adminStatus.value = 'valid' }
  function markAdminInvalid() { adminStatus.value = 'invalid' }

  // Reset status when key changes so sidebar shows neutral state
  watch(apiKey, () => { keyStatus.value = 'unknown' })
  watch(adminSecret, () => { adminStatus.value = 'unknown' })
  watch(locale, value => {
    if (globalThis.document?.documentElement) {
      globalThis.document.documentElement.lang = value
    }
  }, { immediate: true })
  watch(theme, value => {
    applyTheme(value)
  }, { immediate: true })

  // Re-resolve the 'auto' pseudo-theme live when the OS colour scheme flips.
  if (typeof globalThis.matchMedia === 'function') {
    globalThis.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      if (theme.value === AUTO_THEME) applyTheme(AUTO_THEME)
    })
  }

  const keyMasked    = computed(() => (
    apiKey.value ? `…${apiKey.value.slice(-6)}` : translate(locale.value, 'settings.notSet')
  ))
  const adminMasked  = computed(() => (
    adminSecret.value ? `…${adminSecret.value.slice(-4)}` : translate(locale.value, 'settings.notSet')
  ))
  const isConnected  = computed(() => !!apiKey.value)
  const hasAdminSecret = computed(() => !!adminSecret.value)
  const isAdminInvalid = computed(() => adminStatus.value === 'invalid')
  const isKeyInvalid = computed(() => keyStatus.value === 'invalid')
  const isKeyManagedByEnv = computed(() => keySource.value === 'env')

  _load()

  return {
    apiKey,
    adminSecret,
    baseUrl,
    locale,
    theme,
    keySource,
    keyStatus,
    adminStatus,
    save,
    setAdminSecret,
    setLocale,
    setTheme,
    markValid,
    markInvalid,
    markAdminValid,
    markAdminInvalid,
    keyMasked,
    adminMasked,
    isConnected,
    hasAdminSecret,
    isAdminInvalid,
    isKeyInvalid,
    isKeyManagedByEnv,
  }
})
