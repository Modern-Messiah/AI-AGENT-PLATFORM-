<template>
  <div class="layout">
    <AppSidebar
      :collapsed="sidebarCollapsed"
      @toggle="toggleSidebar"
      @open-settings="showSettings = true"
    />
    <div class="main">
      <AppTopbar :title="meta.title" :sub="meta.sub" />
      <div class="content">
        <RouterView />
      </div>
    </div>
    <SettingsModal v-if="showSettings" @close="showSettings = false" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, RouterView } from 'vue-router'
import AppSidebar from './components/AppSidebar.vue'
import AppTopbar from './components/AppTopbar.vue'
import SettingsModal from './components/SettingsModal.vue'
import { useSettingsStore } from './stores/settings'
import { readStoredSidebarCollapsed, toggleSidebarCollapsed } from './utils/sidebarCollapse'

const route = useRoute()
const settings = useSettingsStore()
const showSettings = ref(!settings.isConnected)
const sidebarCollapsed = ref(false)

const PAGE_META = {
  '/chat':       { title: 'AI Agent Chat',  sub: 'PydanticAI · Temporal · Kimi K2' },
  '/documents':  { title: 'База знаний',    sub: 'Общая память для всех чатов' },
  '/notebooks':  { title: 'Ноутбуки',       sub: 'Коллекции источников' },
  '/analytics':  { title: 'Аналитика',      sub: 'ClickHouse · Cost Tracking' },
}

const meta = computed(() => {
  if (route.path.startsWith('/documents/')) {
    return { title: 'Документ', sub: 'Фокусный режим базы знаний' }
  }
  if (route.path.startsWith('/notebooks/')) {
    return { title: 'Ноутбук', sub: 'Чат по выбранной коллекции' }
  }
  return PAGE_META[route.path] || { title: 'AI Agent Platform', sub: '' }
})

function sidebarStorage() {
  try {
    return globalThis.localStorage
  } catch {
    return null
  }
}

function toggleSidebar() {
  sidebarCollapsed.value = toggleSidebarCollapsed(sidebarCollapsed.value, sidebarStorage())
}

onMounted(() => {
  sidebarCollapsed.value = readStoredSidebarCollapsed(sidebarStorage())
})
</script>
