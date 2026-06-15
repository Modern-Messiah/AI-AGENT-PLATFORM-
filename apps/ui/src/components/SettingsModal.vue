<template>
  <div class="modal-overlay" @click.self="!validating && $emit('close')">
    <div class="modal">
      <div class="modal-title">{{ t('settings.title') }}</div>
      <div class="modal-sub">
        {{ keyManagedByEnv
          ? t('settings.envDescription')
          : t('settings.localDescription') }}
      </div>

      <div class="form-group">
        <label class="form-label">{{ t('settings.baseUrl') }}</label>
        <input class="form-input" v-model="localBase" :placeholder="t('settings.basePlaceholder')"
               :disabled="validating" />
      </div>

      <div v-if="keyManagedByEnv" class="env-note">
        {{ t('settings.envNote').split('VITE_API_KEY')[0] }}<span>VITE_API_KEY</span>{{ t('settings.envNote').split('VITE_API_KEY')[1] }}
      </div>

      <div v-else class="form-group">
        <label class="form-label">X-API-Key</label>
        <input class="form-input" type="password" v-model="localKey"
               :placeholder="t('settings.keyPlaceholder')"
               :disabled="validating" autofocus />
      </div>

      <div class="form-group">
        <label class="form-label">{{ t('settings.language') }}</label>
        <div class="language-control" role="group" :aria-label="t('settings.language')">
          <button
            v-for="option in languageOptions"
            :key="option.value"
            type="button"
            :class="['language-option', { active: settings.locale === option.value }]"
            :aria-pressed="settings.locale === option.value"
            @click="settings.setLocale(option.value)"
          >
            {{ option.label }}
          </button>
        </div>
        <div class="language-hint">{{ t('settings.languageHint') }}</div>
      </div>

      <div v-if="error" style="margin-bottom: 14px; padding: 9px 12px; background: color-mix(in oklch, var(--red) 10%, transparent); border: 1px solid color-mix(in oklch, var(--red) 30%, transparent); border-radius: 8px; font-size: 12px; color: var(--red)">
        {{ error }}
      </div>

      <div class="form-actions">
        <button class="btn btn-ghost" :disabled="validating" @click="$emit('close')">{{ t('common.cancel') }}</button>
        <button class="btn btn-primary" :disabled="validating || (!keyManagedByEnv && !localKey.trim())" @click="save">
          <div v-if="validating" class="spinner" style="width: 12px; height: 12px; border-width: 1.5px"></div>
          {{ validating ? t('settings.validating') : t('common.save') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { useI18n } from '@/composables/useI18n'

const emit = defineEmits(['close'])
const settings = useSettingsStore()
const { t } = useI18n()
const languageOptions = computed(() => [
  { value: 'ru', label: t('settings.russian') },
  { value: 'en', label: t('settings.english') },
])

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
      error.value = t('settings.invalidApiKey')
      return
    }
    if (!res.ok && res.status !== 404) {
      error.value = t('settings.serverError', { status: res.status })
      return
    }
    settings.save(key, base)
    emit('close')
  } catch {
    error.value = t('settings.connectionError')
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
.language-control {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  padding: 4px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--s1);
}
.language-option {
  min-height: 34px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--muted2);
  cursor: pointer;
  font-family: var(--font);
  font-size: 12px;
  font-weight: 600;
}
.language-option.active {
  background: var(--s3);
  color: var(--text);
  box-shadow: inset 0 0 0 1px var(--border2);
}
.language-hint {
  margin-top: 6px;
  color: var(--muted);
  font-size: 11px;
}
</style>
