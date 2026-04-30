<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal">
      <div class="modal-title">Настройки подключения</div>
      <div class="modal-sub">API-ключ хранится в localStorage браузера</div>

      <div class="form-group">
        <label class="form-label">API Base URL</label>
        <input class="form-input" v-model="localBase" placeholder="http://localhost:8000 или /api" />
      </div>

      <div class="form-group">
        <label class="form-label">X-API-Key</label>
        <input class="form-input" type="password" v-model="localKey"
               placeholder="Вставьте raw_key из POST /auth/keys" autofocus />
      </div>

      <div class="form-actions">
        <button class="btn btn-ghost" @click="$emit('close')">Отмена</button>
        <button class="btn btn-primary" @click="save">Сохранить</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useSettingsStore } from '@/stores/settings'

const emit = defineEmits(['close'])
const settings = useSettingsStore()

const localKey = ref(settings.apiKey)
const localBase = ref(settings.baseUrl)

function save() {
  settings.save(localKey.value, localBase.value)
  emit('close')
}
</script>
