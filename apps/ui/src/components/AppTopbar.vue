<template>
  <div class="topbar">
    <span class="topbar-title">{{ title }}</span>
    <span class="topbar-sub">{{ sub }}</span>
    <div class="topbar-right">
      <span v-if="settings.isConnected" class="badge badge-green">
        <span class="dot-pulse"></span>{{ t('app.apiReady') }}
      </span>
      <span v-else class="badge badge-yellow">{{ t('app.noKey') }}</span>
    </div>
  </div>
</template>

<script setup>
import { useSettingsStore } from '@/stores/settings'
import { useI18n } from '@/composables/useI18n'

defineProps({
  title: String,
  sub: String
})

const settings = useSettingsStore()
const { t } = useI18n()
</script>
