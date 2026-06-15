import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { resolveApiConfig } from '@/utils/apiConfig'
import { normalizeLocale, translate } from '@/i18n'
import { applyTheme, DEFAULT_THEME, normalizeTheme, persistTheme } from '@/utils/theme'

export const useSettingsStore = defineStore('settings', () => {
  const apiKey = ref('')
  const baseUrl = ref('/api')
  const locale = ref('ru')
  const theme = ref(DEFAULT_THEME)
  const keySource = ref('missing')
  const keyStatus = ref('unknown') // 'unknown' | 'valid' | 'invalid'

  function _load() {
    try {
      const cfg = JSON.parse(localStorage.getItem('aap_config') || '{}')
      const resolved = resolveApiConfig({ stored: cfg, env: import.meta.env })
      apiKey.value = resolved.apiKey
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
        locale: locale.value,
        theme: theme.value,
      }))
      return
    }

    apiKey.value = key.trim()
    keySource.value = apiKey.value ? 'localStorage' : 'missing'
    localStorage.setItem('aap_config', JSON.stringify({
      apiKey: apiKey.value,
      base: baseUrl.value,
      locale: locale.value,
      theme: theme.value,
    }))
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

  // Reset status when key changes so sidebar shows neutral state
  watch(apiKey, () => { keyStatus.value = 'unknown' })
  watch(locale, value => {
    if (globalThis.document?.documentElement) {
      globalThis.document.documentElement.lang = value
    }
  }, { immediate: true })
  watch(theme, value => {
    applyTheme(value)
  }, { immediate: true })

  const keyMasked    = computed(() => (
    apiKey.value ? `…${apiKey.value.slice(-6)}` : translate(locale.value, 'settings.notSet')
  ))
  const isConnected  = computed(() => !!apiKey.value)
  const isKeyInvalid = computed(() => keyStatus.value === 'invalid')
  const isKeyManagedByEnv = computed(() => keySource.value === 'env')

  _load()

  return {
    apiKey,
    baseUrl,
    locale,
    theme,
    keySource,
    keyStatus,
    save,
    setLocale,
    setTheme,
    markValid,
    markInvalid,
    keyMasked,
    isConnected,
    isKeyInvalid,
    isKeyManagedByEnv,
  }
})
