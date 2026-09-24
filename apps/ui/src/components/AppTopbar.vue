<template>
  <div class="topbar">
    <button
      v-if="showBurger"
      class="topbar-burger"
      type="button"
      :aria-label="t('app.openNavigation')"
      :title="t('app.openNavigation')"
      @click="$emit('toggle-sidebar')"
    >
      <AppIcon name="chat" :size="16" />
    </button>
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
import AppIcon from '@/components/AppIcon.vue'

defineProps({
  title: String,
  sub: String,
  showBurger: Boolean
})

const settings = useSettingsStore()
const { t } = useI18n()

defineEmits(['toggle-sidebar'])
</script>
