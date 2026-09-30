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
    <div class="scope-group">
      <button
        class="scope-pill-btn"
        :class="[`is-${scope?.type || 'global'}`, { 'is-locked': scopeLocked }]"
        type="button"
        :disabled="scopeLocked"
        :title="scopeLocked ? t('chat.scopeLockedHint') : t('chat.scopeTooltip')"
        @click="!scopeLocked && $emit('open-scope')"
      >
        <AppIcon :name="scope?.type === 'document' ? 'docs' : (scope?.type === 'notebook' ? 'book' : 'globe')" :size="12" />
        <span class="scope-pill-text">{{ scope?.title || t('chat.scopeGlobalTitle') }}</span>
        <AppIcon v-if="!scopeLocked" name="chevron-down" :size="10" />
        <AppIcon v-else name="lock" :size="10" class="scope-pill-lock" />
      </button>

      <button
        v-if="!scopeLocked"
        class="btn btn-ghost btn-xs scope-select-btn"
        type="button"
        :title="t('chat.scopeSelectSub')"
        @click="$emit('open-scope')"
      >
        <AppIcon name="filter" :size="11" />
        <span>{{ t('chat.changeScope') }}</span>
      </button>

      <RouterLink
        v-if="scope?.backPath"
        class="btn btn-ghost btn-xs scope-back-btn"
        :to="scope.backPath"
      >
        {{ scope.backLabel }}
      </RouterLink>
    </div>
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
import { RouterLink } from 'vue-router'
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
  scopeLocked: {
    type: Boolean,
    default: false,
  },
})
defineEmits(['update:model', 'update:requireApproval', 'toggle-history', 'open-scope'])

const settings = useSettingsStore()
const session = useSessionStore()
const { t } = useI18n()
</script>

<style scoped>
.scope-group {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.scope-select-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 6px;
  color: var(--accent);
  border: 1px solid color-mix(in oklch, var(--accent) 30%, var(--border));
  background: color-mix(in oklch, var(--accent) 6%, transparent);
  cursor: pointer;
  transition: all 0.15s ease;
}

.scope-select-btn:hover {
  background: color-mix(in oklch, var(--accent) 14%, transparent);
  border-color: var(--accent);
}

.scope-back-btn {
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 6px;
  color: var(--muted);
  text-decoration: none;
}

.scope-back-btn:hover {
  color: var(--text);
}

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

.scope-pill-btn.is-locked {
  cursor: default;
}

.scope-pill-btn.is-locked:hover {
  background: var(--s2);
  border-color: var(--border);
}

.scope-pill-lock {
  opacity: 0.65;
  flex-shrink: 0;
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
