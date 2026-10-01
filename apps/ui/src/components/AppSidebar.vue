<template>
  <div class="sidebar" :class="{ collapsed, 'mobile-open': mobileOpen }">
    <div class="sidebar-logo">
      <div class="logo-mark">A</div>
      <div class="logo-copy">
        <div class="logo-text">AgentPlatform</div>
        <div class="logo-sub">v1.0.0 · local</div>
      </div>
      <button
        class="sidebar-toggle"
        type="button"
        :aria-label="collapsed ? t('app.expandSidebar') : t('app.collapseSidebar')"
        :title="collapsed ? t('app.expandPanel') : t('app.collapsePanel')"
        @click="$emit('toggle')"
      >
        <span class="sidebar-toggle-mark">{{ collapsed ? '›' : '‹' }}</span>
      </button>
    </div>

    <div class="sidebar-section">{{ t('app.navigation') }}</div>
    <RouterLink v-for="item in nav" :key="item.path"
      :to="item.path"
      class="nav-item"
      :class="{ active: isNavActive(item.path) }"
      :title="item.label"
    >
      <AppIcon :name="item.icon" class="nav-icon" />
      <span class="nav-label">{{ item.label }}</span>
    </RouterLink>

    <div class="sidebar-section">{{ t('app.configuration') }}</div>
    <div class="nav-item" :title="t('app.settings')" @click="$emit('openSettings')">
      <AppIcon name="settings" class="nav-icon" />
      <span class="nav-label">{{ t('app.settings') }}</span>
    </div>

    <div class="sidebar-bottom">
      <div
        v-if="session.isAuthenticated"
        class="tenant-pill session-pill"
        :title="session.user?.email || session.displayName"
      >
        <div class="tenant-dot session"></div>
        <div class="tenant-info">
          <div class="tenant-name">{{ session.displayName }}</div>
          <div class="tenant-key">
            {{ session.isAdmin ? t('app.roleAdmin') : t('app.roleMember') }}
            · {{ session.user?.tenant_id }}
          </div>
        </div>
        <button
          class="logout-btn"
          type="button"
          :aria-label="t('login.logout')"
          :title="t('login.logout')"
          @click.stop="session.logout()"
        >
          <AppIcon name="stop" :size="12" />
        </button>
      </div>
      <div
        v-else
        class="tenant-pill"
        @click="$emit('openSettings')"
        :title="settings.isKeyManagedByEnv ? t('app.envKeyTitle') : t('app.changeKeyTitle')"
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
import { useSessionStore } from '@/stores/session'
import { useI18n } from '@/composables/useI18n'
import AppIcon from './AppIcon.vue'

defineProps({
  collapsed: { type: Boolean, default: false },
  mobileOpen: { type: Boolean, default: false },
})
defineEmits(['openSettings', 'toggle'])

const route = useRoute()
const settings = useSettingsStore()
const session = useSessionStore()
const { t } = useI18n()

const dotClass = computed(() => {
  if (!settings.isConnected)    return 'off'
  if (settings.isKeyInvalid)    return 'invalid'
  if (settings.keyStatus === 'valid') return ''
  return ''
})

const statusLabel = computed(() => {
  if (!settings.isConnected)  return t('app.noApiKey')
  if (settings.isKeyInvalid)  return t('app.invalidKey')
  if (settings.isKeyManagedByEnv) return t('app.envApiKey')
  return t('app.connected')
})

// The admin cabinet link appears only for admins (Google session role or
// the classic admin secret configured in settings).
const showAdmin = computed(() => session.isAdmin || settings.hasAdminSecret)

const nav = computed(() => {
  const items = [
    { path: '/chat', label: t('app.agent'), icon: 'chat' },
    { path: '/documents', label: t('app.knowledgeBase'), icon: 'docs' },
    { path: '/notebooks', label: t('app.notebooks'), icon: 'docs' },
    { path: '/analytics', label: t('app.analytics'), icon: 'analytics' },
  ]
  if (showAdmin.value) {
    items.push({ path: '/admin', label: t('app.adminPanel'), icon: 'shield' })
  }
  return items
})

function isNavActive(path) {
  return route.path === path || route.path.startsWith(`${path}/`)
}
</script>

<style scoped>
.session-pill {
  cursor: default;
}
.tenant-dot.session {
  background: var(--green);
}
.logout-btn {
  margin-left: auto;
  padding: 5px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  line-height: 0;
  transition: all 0.15s cubic-bezier(0.16, 1, 0.3, 1);
}
.logout-btn:hover {
  background: var(--s3);
  color: var(--red);
}
.logout-btn:active {
  transform: scale(0.92);
}
</style>
