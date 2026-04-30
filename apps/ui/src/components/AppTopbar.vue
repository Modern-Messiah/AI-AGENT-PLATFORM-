<template>
  <div class="topbar">
    <span class="topbar-title">{{ title }}</span>
    <span class="topbar-sub">{{ sub }}</span>
    <div class="topbar-right">
      <span v-if="settings.isConnected" class="badge badge-green">
        <span class="dot-pulse"></span>API ready
      </span>
      <span v-else class="badge badge-yellow">⚠ Нет ключа</span>
    </div>
  </div>
</template>

<script setup>
import { useSettingsStore } from '@/stores/settings'

defineProps({
  title: String,
  sub: String
})

const settings = useSettingsStore()
</script>
