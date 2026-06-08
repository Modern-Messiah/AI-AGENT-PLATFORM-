<template>
  <div class="chat-toolbar">
    <select class="model-select" :value="model" @change="$emit('update:model', $event.target.value)">
      <option v-for="m in MODELS" :key="m" :value="m">{{ m }}</option>
    </select>
    <div style="width: 1px; height: 20px; background: var(--border); margin: 0 4px"></div>
    <label class="toggle-wrap" @click="$emit('update:requireApproval', !requireApproval)">
      <div :class="['toggle', { on: requireApproval }]"></div>
      <span>Human approval</span>
    </label>
    <span v-if="requireApproval" class="badge badge-yellow" style="margin-left: 4px">HITL on</span>
    <span style="margin-left: auto; font-size: 11px; color: var(--muted); font-family: var(--mono)">
      {{ settings.isConnected ? `${settings.isKeyManagedByEnv ? 'env key' : 'key'}: …${settings.apiKey.slice(-6)}` : 'no key' }}
    </span>
  </div>
</template>

<script setup>
import { useSettingsStore } from '@/stores/settings'

const MODELS = ['moonshot/kimi-k2.6', 'deepseek/deepseek-v4-pro', 'deepseek/deepseek-v4-flash']

defineProps({
  model: String,
  requireApproval: Boolean
})
defineEmits(['update:model', 'update:requireApproval'])

const settings = useSettingsStore()
</script>
