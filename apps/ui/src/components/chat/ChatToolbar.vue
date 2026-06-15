<template>
  <div class="chat-toolbar">
    <select class="model-select" :value="model" @change="$emit('update:model', $event.target.value)">
      <option v-for="m in MODELS" :key="m" :value="m">{{ m }}</option>
    </select>
    <div style="width: 1px; height: 20px; background: var(--border); margin: 0 4px"></div>
    <label class="toggle-wrap" @click="$emit('update:requireApproval', !requireApproval)">
      <div :class="['toggle', { on: requireApproval }]"></div>
      <span>{{ t('chat.humanApproval') }}</span>
    </label>
    <span v-if="requireApproval" class="badge badge-yellow" style="margin-left: 4px">{{ t('chat.hitlOn') }}</span>
    <span style="margin-left: auto; font-size: 11px; color: var(--muted); font-family: var(--mono)">
      {{ settings.isConnected ? `${settings.isKeyManagedByEnv ? t('chat.envKey') : t('chat.key')}: …${settings.apiKey.slice(-6)}` : t('chat.noKey') }}
    </span>
  </div>
</template>

<script setup>
import { useSettingsStore } from '@/stores/settings'
import { useI18n } from '@/composables/useI18n'

const MODELS = ['moonshot/kimi-k2.6', 'deepseek/deepseek-v4-pro', 'deepseek/deepseek-v4-flash']

defineProps({
  model: String,
  requireApproval: Boolean
})
defineEmits(['update:model', 'update:requireApproval'])

const settings = useSettingsStore()
const { t } = useI18n()
</script>
