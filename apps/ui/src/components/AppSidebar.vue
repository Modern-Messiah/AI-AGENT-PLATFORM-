<template>
  <div class="sidebar" :class="{ collapsed }">
    <div class="sidebar-logo">
      <div class="logo-mark">A</div>
      <div class="logo-copy">
        <div class="logo-text">AgentPlatform</div>
        <div class="logo-sub">v1.0.0 · local</div>
      </div>
      <button
        class="sidebar-toggle"
        type="button"
        :aria-label="collapsed ? 'Развернуть боковую панель' : 'Свернуть боковую панель'"
        :title="collapsed ? 'Развернуть панель' : 'Свернуть панель'"
        @click="$emit('toggle')"
      >
        <span class="sidebar-toggle-mark">{{ collapsed ? '›' : '‹' }}</span>
      </button>
    </div>

    <div class="sidebar-section">Навигация</div>
    <RouterLink v-for="item in nav" :key="item.path"
      :to="item.path"
      class="nav-item"
      :class="{ active: isNavActive(item.path) }"
      :title="item.label"
    >
      <AppIcon :name="item.icon" class="nav-icon" />
      <span class="nav-label">{{ item.label }}</span>
    </RouterLink>

    <div class="sidebar-section">Конфигурация</div>
    <div class="nav-item" title="Настройки" @click="$emit('openSettings')">
      <AppIcon name="settings" class="nav-icon" />
      <span class="nav-label">Настройки</span>
    </div>

    <div class="sidebar-bottom">
      <div
        class="tenant-pill"
        @click="$emit('openSettings')"
        :title="settings.isKeyManagedByEnv ? 'API-ключ задан через env' : 'Изменить API-ключ'"
      >
        <div :class="['tenant-dot', dotClass]"></div>
        <div class="tenant-info">
          <div class="tenant-name">{{ statusLabel }}</div>
          <div class="tenant-key">{{ settings.keyMasked }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, RouterLink } from 'vue-router'
import { useSettingsStore } from '@/stores/settings'
import AppIcon from './AppIcon.vue'

defineProps({
  collapsed: { type: Boolean, default: false },
})
defineEmits(['openSettings', 'toggle'])

const route = useRoute()
const settings = useSettingsStore()

const dotClass = computed(() => {
  if (!settings.isConnected)    return 'off'
  if (settings.isKeyInvalid)    return 'invalid'
  if (settings.keyStatus === 'valid') return ''
  return ''
})

const statusLabel = computed(() => {
  if (!settings.isConnected)  return 'No API Key'
  if (settings.isKeyInvalid)  return 'Неверный ключ'
  if (settings.isKeyManagedByEnv) return 'Env API Key'
  return 'Connected'
})

const nav = [
  { path: '/chat',       label: 'Агент',     icon: 'chat' },
  { path: '/documents',  label: 'База знаний', icon: 'docs' },
  { path: '/notebooks',  label: 'Ноутбуки', icon: 'docs' },
  { path: '/analytics',  label: 'Аналитика', icon: 'analytics' },
]

function isNavActive(path) {
  return route.path === path || route.path.startsWith(`${path}/`)
}
</script>
