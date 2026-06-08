<template>
  <div class="modal-overlay" @click.self="!validating && $emit('close')">
    <div class="modal">
      <div class="modal-title">Настройки подключения</div>
      <div class="modal-sub">
        {{ keyManagedByEnv
          ? 'X-API-Key берётся из env и не хранится в localStorage'
          : 'API-ключ хранится в localStorage браузера' }}
      </div>

      <div class="form-group">
        <label class="form-label">API Base URL</label>
        <input class="form-input" v-model="localBase" placeholder="http://localhost:8000 или /api"
               :disabled="validating" />
      </div>

      <div v-if="keyManagedByEnv" class="env-note">
        Ключ задан через <span>VITE_API_KEY</span>. В интерфейсе можно менять только Base URL.
      </div>

      <div v-else class="form-group">
        <label class="form-label">X-API-Key</label>
        <input class="form-input" type="password" v-model="localKey"
               placeholder="Вставьте raw_key из POST /auth/keys"
               :disabled="validating" autofocus />
      </div>

      <div v-if="error" style="margin-bottom: 14px; padding: 9px 12px; background: color-mix(in oklch, var(--red) 10%, transparent); border: 1px solid color-mix(in oklch, var(--red) 30%, transparent); border-radius: 8px; font-size: 12px; color: var(--red)">
        {{ error }}
      </div>

      <div class="form-actions">
        <button class="btn btn-ghost" :disabled="validating" @click="$emit('close')">Отмена</button>
        <button class="btn btn-primary" :disabled="validating || (!keyManagedByEnv && !localKey.trim())" @click="save">
          <div v-if="validating" class="spinner" style="width: 12px; height: 12px; border-width: 1.5px"></div>
          {{ validating ? 'Проверка…' : 'Сохранить' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useSettingsStore } from '@/stores/settings'

const emit = defineEmits(['close'])
const settings = useSettingsStore()

const localKey  = ref(settings.apiKey)
const localBase = ref(settings.baseUrl)
const validating = ref(false)
const error = ref('')
const keyManagedByEnv = computed(() => settings.isKeyManagedByEnv)

async function save() {
  const key  = keyManagedByEnv.value ? settings.apiKey : localKey.value.trim()
  const base = localBase.value.trim() || '/api'
  if (!key) return

  validating.value = true
  error.value = ''

  try {
    const res = await fetch(`${base}/sessions`, {
      headers: { 'X-API-Key': key }
    })
    if (res.status === 401) {
      error.value = 'Неверный API-ключ — проверьте raw_key'
      return
    }
    if (!res.ok && res.status !== 404) {
      error.value = `Ошибка сервера: ${res.status}`
      return
    }
    settings.save(key, base)
    emit('close')
  } catch {
    error.value = 'Не удалось подключиться к серверу — проверьте Base URL'
  } finally {
    validating.value = false
  }
}
</script>

<style scoped>
.env-note {
  margin-bottom: 16px;
  padding: 10px 12px;
  border: 1px solid color-mix(in oklch, var(--accent) 28%, transparent);
  border-radius: 10px;
  background: color-mix(in oklch, var(--accent) 8%, transparent);
  color: var(--muted2);
  font-size: 12px;
  line-height: 1.5;
}
.env-note span {
  color: var(--text);
  font-family: var(--mono);
}
</style>
