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
    <SettingsModal v-if="showSettings" @close="closeSettings" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter, RouterView } from 'vue-router'
import AppSidebar from './components/AppSidebar.vue'
import AppTopbar from './components/AppTopbar.vue'
import SettingsModal from './components/SettingsModal.vue'
import { useSettingsStore } from './stores/settings'
import { useI18n } from './composables/useI18n'
import { readStoredSidebarCollapsed, toggleSidebarCollapsed } from './utils/sidebarCollapse'
import { clearSettingsQuery, shouldOpenSettingsModal } from './utils/settingsRoute'

const route = useRoute()
const router = useRouter()
const settings = useSettingsStore()
const { t } = useI18n()
const showSettings = ref(!settings.isConnected || shouldOpenSettingsModal(route.query))
const sidebarCollapsed = ref(false)

const meta = computed(() => {
  if (route.path.startsWith('/documents/')) {
    return { title: t('app.documentTitle'), sub: t('app.documentSub') }
  }
  if (route.path.startsWith('/notebooks/')) {
    return { title: t('app.notebookTitle'), sub: t('app.notebookSub') }
  }
  const pageMeta = {
    '/chat': { title: t('app.chatTitle'), sub: t('app.chatSub') },
    '/documents': { title: t('app.documentsTitle'), sub: t('app.documentsSub') },
    '/notebooks': { title: t('app.notebooksTitle'), sub: t('app.notebooksSub') },
    '/analytics': { title: t('app.analyticsTitle'), sub: t('app.analyticsSub') },
  }
  return pageMeta[route.path] || { title: 'AI Agent Platform', sub: '' }
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

function closeSettings() {
  showSettings.value = false
  if (shouldOpenSettingsModal(route.query)) {
    router.replace({ path: route.path, query: clearSettingsQuery(route.query) })
  }
}

onMounted(() => {
  sidebarCollapsed.value = readStoredSidebarCollapsed(sidebarStorage())
})

watch(
  () => route.query.settings,
  () => {
    if (shouldOpenSettingsModal(route.query)) {
      showSettings.value = true
    }
  },
  { immediate: true },
)
</script>
