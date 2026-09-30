<template>
  <div class="chat-toolbar">
    <button
      v-if="showHistoryToggle"
      class="btn btn-ghost btn-sm history-toggle"
      type="button"
      :aria-label="t('chat.sessions')"
      :title="t('chat.sessions')"
      @click="$emit('toggle-history')"
    >
      <AppIcon name="docs" :size="14" />
    </button>
    <button
      class="scope-pill-btn"
      :class="`is-${scope?.type || 'global'}`"
      type="button"
      :title="t('chat.scopeTooltip')"
      @click="$emit('open-scope')"
    >
      <AppIcon :name="scope?.type === 'document' ? 'docs' : (scope?.type === 'notebook' ? 'book' : 'globe')" :size="12" />
      <span class="scope-pill-text">{{ scope?.title || t('chat.scopeGlobalTitle') }}</span>
      <AppIcon name="chevron-down" :size="10" />
    </button>
    <select
      v-if="session.isAdmin"
      class="model-select"
      :value="model"
      @change="$emit('update:model', $event.target.value)"
    >
      <option v-for="m in MODELS" :key="m" :value="m">{{ m }}</option>
    </select>
    <div style="width: 1px; height: 20px; background: var(--border); margin: 0 4px"></div>
    <label class="toggle-wrap" @click="$emit('update:requireApproval', !requireApproval)">
      <div :class="['toggle', { on: requireApproval }]"></div>
      <span>{{ t('chat.humanApproval') }}</span>
    </label>
    <span v-if="requireApproval" class="badge badge-yellow" style="margin-left: 4px">{{ t('chat.hitlOn') }}</span>
    <span style="margin-left: auto; font-size: 11px; color: var(--muted); font-family: var(--mono)">
      {{ session.isAuthenticated ? (session.displayName || t('app.connected')) : (settings.isConnected ? `${settings.isKeyManagedByEnv ? t('chat.envKey') : t('chat.key')}: …${settings.apiKey.slice(-6)}` : t('chat.noKey')) }}
    </span>
  </div>
</template>

<script setup>
import { useSettingsStore } from '@/stores/settings'
import { useSessionStore } from '@/stores/session'
import { useI18n } from '@/composables/useI18n'
import AppIcon from '@/components/AppIcon.vue'

const MODELS = ['moonshot/kimi-k2.6', 'deepseek/deepseek-v4-pro', 'deepseek/deepseek-v4-flash']

defineProps({
  model: String,
  requireApproval: Boolean,
  showHistoryToggle: Boolean,
  scope: {
    type: Object,
    default: () => ({ type: 'global', title: '' }),
  },
})
defineEmits(['update:model', 'update:requireApproval', 'toggle-history', 'open-scope'])

const settings = useSettingsStore()
const session = useSessionStore()
const { t } = useI18n()
</script>

<style scoped>
.scope-pill-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 9px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--s2);
  color: var(--text);
  font-size: 11.5px;
  cursor: pointer;
  transition: all 0.15s ease;
  max-width: 220px;
}

.scope-pill-btn:hover {
  background: var(--s3);
  border-color: color-mix(in oklch, var(--accent) 50%, var(--border));
}

.scope-pill-btn.is-global {
  border-color: color-mix(in oklch, var(--teal, var(--accent)) 30%, var(--border));
  color: var(--text);
}

.scope-pill-btn.is-document {
  border-color: color-mix(in oklch, var(--purple) 35%, var(--border));
  color: var(--purple);
}

.scope-pill-btn.is-notebook {
  border-color: color-mix(in oklch, var(--accent) 35%, var(--border));
  color: var(--accent);
}

.scope-pill-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
