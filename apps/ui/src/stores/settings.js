import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useSettingsStore = defineStore('settings', () => {
  const apiKey = ref('')
  const baseUrl = ref('/api')

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

  const keyMasked = computed(() => apiKey.value ? `…${apiKey.value.slice(-6)}` : 'не задан')
  const isConnected = computed(() => !!apiKey.value)

  _load()

  return { apiKey, baseUrl, save, keyMasked, isConnected }
})
