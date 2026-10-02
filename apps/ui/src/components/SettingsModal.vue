<template>
  <div class="modal-overlay" @click.self="!validating && $emit('close')">
    <div class="modal settings-modal" role="dialog" aria-modal="true" :aria-label="t('settings.title')">
      <div class="settings-modal-header">
        <div class="settings-modal-copy">
          <div class="modal-title">{{ t('settings.title') }}</div>
          <div class="modal-sub">
            {{ isAdminUser
              ? (keyManagedByEnv ? t('settings.envDescription') : t('settings.localDescription'))
              : t('settings.interfaceOnly') }}
          </div>
        </div>
        <button
          type="button"
          class="modal-close-btn"
          :aria-label="t('common.close')"
          :title="t('common.close') + ' (Esc)'"
          :disabled="validating"
          @click="$emit('close')"
        >
          <AppIcon name="close" :size="14" />
        </button>
      </div>

      <div class="settings-modal-body">
        <div v-if="isAdminUser" class="settings-section">{{ t('settings.sectionConnection') }}</div>

        <div v-if="isAdminUser" class="form-group">
          <label class="form-label">{{ t('settings.baseUrl') }}</label>
          <input class="form-input" v-model="localBase" :placeholder="t('settings.basePlaceholder')"
                 :disabled="validating" />
        </div>

        <div v-if="isAdminUser && keyManagedByEnv" class="env-note">
          {{ t('settings.envNote') }}
        </div>

        <div v-else-if="isAdminUser" class="form-group">
          <label class="form-label">X-API-Key</label>
          <input class="form-input" type="password" v-model="localKey"
                 :placeholder="t('settings.keyPlaceholder')"
                 :disabled="validating" autofocus />
        </div>

        <div v-if="isAdminUser" class="settings-section">{{ t('settings.sectionAdmin') }}</div>

        <div v-if="isAdminUser" class="form-group">
          <label class="form-label">{{ t('settings.adminSecret') }}</label>
          <input class="form-input" type="password" v-model="localAdminSecret"
                 :placeholder="t('settings.adminSecretPlaceholder')"
                 :disabled="validating" />
          <div class="language-hint">{{ t('settings.adminSecretHint') }}</div>
        </div>

        <div v-if="session.isAuthenticated" class="settings-section">
          {{ t('settings.sectionSecurity') }}
        </div>

        <div v-if="session.isAuthenticated" class="form-group">
          <label class="form-label">{{ t('settings.newPassword') }}</label>
          <input
            v-model="localNewPassword"
            type="password"
            class="form-input"
            :placeholder="t('login.passwordPlaceholder')"
            :disabled="passwordSaving"
          />
          <div class="language-hint">{{ t('settings.newPasswordHint') }}</div>
          <button
            class="btn btn-ghost btn-sm"
            style="margin-top: 8px"
            :disabled="passwordSaving || localNewPassword.length < 8"
            @click="changePassword"
          >
            {{ passwordSaving ? t('settings.validating') : t('settings.changePassword') }}
          </button>
          <div v-if="passwordMessage" class="language-hint">{{ passwordMessage }}</div>
        </div>

        <div class="settings-section">{{ t('settings.sectionInterface') }}</div>

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

        <div class="form-group">
          <label class="form-label">{{ t('settings.theme') }}</label>
          <div class="theme-grid" role="group" :aria-label="t('settings.theme')">
            <button
              v-for="option in themeOptions"
              :key="option.id"
              type="button"
              :class="['theme-option', { active: settings.theme === option.id }]"
              :aria-label="t(option.labelKey)"
              :aria-pressed="settings.theme === option.id"
              @click="settings.setTheme(option.id)"
            >
              <span class="theme-swatches" aria-hidden="true">
                <span
                  v-for="swatch in option.swatches"
                  :key="swatch"
                  class="theme-swatch"
                  :style="{ background: swatch }"
                />
              </span>
              <span class="theme-name">{{ t(option.labelKey) }}</span>
            </button>
          </div>
          <div class="language-hint">{{ t('settings.themeHint') }}</div>
        </div>

        <div v-if="error" style="margin-bottom: 14px; padding: 9px 12px; background: color-mix(in oklch, var(--red) 10%, transparent); border: 1px solid color-mix(in oklch, var(--red) 30%, transparent); border-radius: 8px; font-size: 12px; color: var(--red)">
          {{ error }}
        </div>
      </div>

      <div class="settings-modal-footer">
        <template v-if="isAdminUser">
          <button class="btn btn-ghost" :disabled="validating" @click="$emit('close')">{{ t('common.cancel') }}</button>
          <button class="btn btn-primary" :disabled="validating || (!keyManagedByEnv && !localKey.trim())" @click="save">
            <div v-if="validating" class="spinner" style="width: 12px; height: 12px; border-width: 1.5px"></div>
            {{ validating ? t('settings.validating') : t('common.save') }}
          </button>
        </template>
        <template v-else>
          <button class="btn btn-primary" @click="$emit('close')">{{ t('common.close') }}</button>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import { useSettingsStore } from '@/stores/settings'
import { useSessionStore } from '@/stores/session'
import { useI18n } from '@/composables/useI18n'
import { THEMES } from '@/utils/theme'

const AUTO_THEME_OPTION = {
  id: 'auto',
  labelKey: 'settings.themeAuto',
  swatches: ['#0c0e12', '#f6f8fb', '#5067d9'],
}

const emit = defineEmits(['close'])
const settings = useSettingsStore()
const session = useSessionStore()
const { t } = useI18n()

function onKeydown(e) {
  if (e.key === 'Escape' && !validating.value) {
    emit('close')
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
})
const languageOptions = computed(() => [
  { value: 'ru', label: t('settings.russian') },
  { value: 'en', label: t('settings.english') },
])
const themeOptions = [AUTO_THEME_OPTION, ...THEMES]

const localKey  = ref(settings.apiKey)
const localBase = ref(settings.baseUrl)
const localAdminSecret = ref(settings.adminSecret)
const localNewPassword = ref('')
const passwordSaving = ref(false)
const passwordMessage = ref('')
const validating = ref(false)
const error = ref('')
const keyManagedByEnv = computed(() => settings.isKeyManagedByEnv)
const isAdminUser = computed(() => session.isAdmin || settings.hasAdminSecret)

async function changePassword() {
  const value = localNewPassword.value
  if (value.length < 8) return
  passwordSaving.value = true
  passwordMessage.value = ''
  try {
    const base = settings.baseUrl || '/api'
    const res = await fetch(`${base}/auth/password`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${session.token}`,
      },
      body: JSON.stringify({ new_password: value }),
    })
    if (!res.ok && res.status !== 204) {
      const detail = await res.json().catch(() => null)
      passwordMessage.value = detail?.detail?.[0]?.msg || t('settings.serverError', { status: res.status })
      return
    }
    localNewPassword.value = ''
    passwordMessage.value = t('settings.passwordChanged')
  } catch {
    passwordMessage.value = t('settings.connectionError')
  } finally {
    passwordSaving.value = false
  }
}

async function save() {
  if (!isAdminUser.value) {
    // Interface-only mode: locale/theme persist on change; nothing to validate.
    emit('close')
    return
  }
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
    settings.setAdminSecret(localAdminSecret.value)
    emit('close')
  } catch {
    error.value = t('settings.connectionError')
  } finally {
    validating.value = false
  }
}
</script>

<style scoped>
.settings-modal {
  width: 520px;
  max-height: min(760px, calc(100vh - 40px));
  padding: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.settings-modal-header {
  padding: 20px 24px 14px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid color-mix(in oklch, var(--border) 70%, transparent);
  flex-shrink: 0;
}
.settings-modal-copy {
  min-width: 0;
}
.settings-modal-copy .modal-title {
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.018em;
  margin-bottom: 4px;
}
.settings-modal-copy .modal-sub {
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 0;
}
.modal-close-btn {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  border: 1px solid var(--border);
  background: var(--s2);
  color: var(--muted2);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
  transition: background 0.15s var(--ease-spring), border-color 0.15s var(--ease-spring), color 0.15s var(--ease-spring), transform 0.08s var(--ease-spring-snappy);
}
.modal-close-btn:hover {
  background: var(--s3);
  border-color: var(--border2);
  color: var(--text);
}
.modal-close-btn:active {
  transform: scale(0.92);
}
.modal-close-btn:focus-visible {
  outline: 2px solid color-mix(in oklch, var(--accent) 55%, transparent);
  outline-offset: 2px;
}
.settings-modal-body {
  padding: 16px 24px;
  overflow-y: auto;
  flex: 1;
  min-height: 0;
}
.settings-modal-footer {
  padding: 14px 24px;
  border-top: 1px solid color-mix(in oklch, var(--border) 70%, transparent);
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  flex-shrink: 0;
  background: color-mix(in oklch, var(--s1) 90%, transparent);
  border-bottom-left-radius: 18px;
  border-bottom-right-radius: 18px;
}
.settings-section {
  margin: 10px 0 14px;
  padding-bottom: 7px;
  border-bottom: 1px solid var(--border);
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.09em;
}
.settings-section:first-of-type { margin-top: 4px; }
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
  gap: 3px;
  padding: 3px;
  border: 1px solid color-mix(in oklch, var(--border) 80%, transparent);
  border-radius: 10px;
  background: color-mix(in oklch, var(--s2) 65%, var(--s1));
}
.language-option {
  min-height: 34px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--muted2);
  cursor: pointer;
  font-family: var(--font);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: -0.01em;
  transition: all 0.15s cubic-bezier(0.16, 1, 0.3, 1);
  user-select: none;
}
.language-option.active {
  background: var(--s1);
  color: var(--text);
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.18), inset 0 1px 0 rgba(255, 255, 255, 0.06);
}
.language-option:active {
  transform: scale(0.97);
}
.language-hint {
  margin-top: 6px;
  color: var(--muted);
  font-size: 11px;
}
.theme-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: 8px;
}
.theme-option {
  min-width: 0;
  min-height: 64px;
  padding: 9px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--s2);
  color: var(--muted2);
  cursor: pointer;
  font-family: var(--font);
  text-align: left;
  transition: border-color 0.15s var(--ease-spring), background 0.15s var(--ease-spring), color 0.15s var(--ease-spring), transform 0.08s var(--ease-spring-snappy);
  user-select: none;
}
.theme-option:hover {
  border-color: var(--border2);
  background: var(--s3);
  color: var(--text);
}
.theme-option:active {
  transform: scale(0.97);
}
.theme-option:focus-visible {
  outline: 2px solid color-mix(in oklch, var(--accent) 55%, transparent);
  outline-offset: 2px;
}
.theme-option.active {
  border-color: var(--accent);
  color: var(--text);
  box-shadow: 0 0 0 1px var(--accent);
}
.theme-swatches {
  display: flex;
  height: 18px;
  margin-bottom: 8px;
  overflow: hidden;
  border: 1px solid color-mix(in oklch, var(--border2) 70%, transparent);
  border-radius: 5px;
}
.theme-swatch {
  flex: 1;
}
.theme-name {
  display: block;
  overflow: hidden;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}
@media (max-width: 520px) {
  .theme-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
