import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'

export const useSettingsStore = defineStore('settings', () => {
  const apiKey = ref('')
  const baseUrl = ref('/api')
  const keyStatus = ref('unknown') // 'unknown' | 'valid' | 'invalid'

  function _load() {
    try {
      const cfg = JSON.parse(localStorage.getItem('aap_config') || '{}')
      apiKey.value = cfg.apiKey || ''
      baseUrl.value = cfg.base || '/api'
    } catch {}
  }

  function save(key, url) {
    apiKey.value = key.trim()
    baseUrl.value = (url || '/api').trim()
    localStorage.setItem('aap_config', JSON.stringify({ apiKey: apiKey.value, base: baseUrl.value }))
  }

  function markValid()   { keyStatus.value = 'valid' }
  function markInvalid() { keyStatus.value = 'invalid' }

  // Reset status when key changes so sidebar shows neutral state
  watch(apiKey, () => { keyStatus.value = 'unknown' })

  const keyMasked    = computed(() => apiKey.value ? `…${apiKey.value.slice(-6)}` : 'не задан')
  const isConnected  = computed(() => !!apiKey.value)
  const isKeyInvalid = computed(() => keyStatus.value === 'invalid')

  _load()

  return { apiKey, baseUrl, keyStatus, save, markValid, markInvalid, keyMasked, isConnected, isKeyInvalid }
})
