import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { resolveApiConfig } from '@/utils/apiConfig'

export const useSettingsStore = defineStore('settings', () => {
  const apiKey = ref('')
  const baseUrl = ref('/api')
  const keySource = ref('missing')
  const keyStatus = ref('unknown') // 'unknown' | 'valid' | 'invalid'

  function _load() {
    try {
      const cfg = JSON.parse(localStorage.getItem('aap_config') || '{}')
      const resolved = resolveApiConfig({ stored: cfg, env: import.meta.env })
      apiKey.value = resolved.apiKey
      baseUrl.value = resolved.baseUrl
      keySource.value = resolved.keySource
    } catch {}
  }

  function save(key, url) {
    const resolved = resolveApiConfig({ env: import.meta.env })
    baseUrl.value = (url || resolved.baseUrl || '/api').trim()
    if (resolved.isKeyManagedByEnv) {
      apiKey.value = resolved.apiKey
      keySource.value = 'env'
      localStorage.setItem('aap_config', JSON.stringify({ base: baseUrl.value }))
      return
    }

    apiKey.value = key.trim()
    keySource.value = apiKey.value ? 'localStorage' : 'missing'
    localStorage.setItem('aap_config', JSON.stringify({ apiKey: apiKey.value, base: baseUrl.value }))
  }

  function markValid()   { keyStatus.value = 'valid' }
  function markInvalid() { keyStatus.value = 'invalid' }

  // Reset status when key changes so sidebar shows neutral state
  watch(apiKey, () => { keyStatus.value = 'unknown' })

  const keyMasked    = computed(() => apiKey.value ? `…${apiKey.value.slice(-6)}` : 'не задан')
  const isConnected  = computed(() => !!apiKey.value)
  const isKeyInvalid = computed(() => keyStatus.value === 'invalid')
  const isKeyManagedByEnv = computed(() => keySource.value === 'env')

  _load()

  return {
    apiKey,
    baseUrl,
    keySource,
    keyStatus,
    save,
    markValid,
    markInvalid,
    keyMasked,
    isConnected,
    isKeyInvalid,
    isKeyManagedByEnv,
  }
})
