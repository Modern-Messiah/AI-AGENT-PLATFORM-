<template>
  <div class="sidebar">
    <div class="sidebar-logo">
      <div class="logo-mark">A</div>
      <div>
        <div class="logo-text">AgentPlatform</div>
        <div class="logo-sub">v1.0.0 · local</div>
      </div>
    </div>

    <div class="sidebar-section">Навигация</div>
    <RouterLink v-for="item in nav" :key="item.path"
      :to="item.path"
      class="nav-item"
      :class="{ active: route.path === item.path }"
    >
      <AppIcon :name="item.icon" class="nav-icon" />
      {{ item.label }}
    </RouterLink>

    <div class="sidebar-section">Конфигурация</div>
    <div class="nav-item" @click="$emit('openSettings')">
      <AppIcon name="settings" class="nav-icon" />
      Настройки
    </div>

    <div class="sidebar-bottom">
      <div class="tenant-pill" @click="$emit('openSettings')" title="Изменить API-ключ">
        <div :class="['tenant-dot', { off: !settings.isConnected }]"></div>
        <div class="tenant-info">
          <div class="tenant-name">{{ settings.isConnected ? 'Connected' : 'No API Key' }}</div>
          <div class="tenant-key">{{ settings.keyMasked }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useRoute, RouterLink } from 'vue-router'
import { useSettingsStore } from '@/stores/settings'
import AppIcon from './AppIcon.vue'

defineEmits(['openSettings'])

const route = useRoute()
const settings = useSettingsStore()

const nav = [
  { path: '/chat',       label: 'Агент',     icon: 'chat' },
  { path: '/documents',  label: 'Документы', icon: 'docs' },
  { path: '/analytics',  label: 'Аналитика', icon: 'analytics' },
  { path: '/workflows',  label: 'Workflows', icon: 'workflows' },
]
</script>
