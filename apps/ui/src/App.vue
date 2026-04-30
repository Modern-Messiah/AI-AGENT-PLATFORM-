<template>
  <div class="layout">
    <AppSidebar @open-settings="showSettings = true" />
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
import { ref, computed } from 'vue'
import { useRoute, RouterView } from 'vue-router'
import AppSidebar from './components/AppSidebar.vue'
import AppTopbar from './components/AppTopbar.vue'
import SettingsModal from './components/SettingsModal.vue'
import { useSettingsStore } from './stores/settings'

const route = useRoute()
const settings = useSettingsStore()
const showSettings = ref(!settings.isConnected)

const PAGE_META = {
  '/chat':       { title: 'AI Agent Chat',  sub: 'PydanticAI · Temporal · Kimi K2' },
  '/documents':  { title: 'Документы',      sub: 'RAG · pgvector · MinIO' },
  '/analytics':  { title: 'Аналитика',      sub: 'ClickHouse · Cost Tracking' },
  '/workflows':  { title: 'Workflows',      sub: 'Temporal · HITL · Durable Execution' },
}

const meta = computed(() => PAGE_META[route.path] || { title: 'AI Agent Platform', sub: '' })
</script>
