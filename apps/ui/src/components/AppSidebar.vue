<template>
  <div class="sidebar" :class="{ collapsed, 'mobile-open': mobileOpen }">
    <div class="sidebar-logo">
      <div
        class="logo-mark"
        :class="{ clickable: collapsed }"
        :title="collapsed ? t('app.expandPanel') : undefined"
        @click="collapsed && $emit('toggle')"
      >
        A
      </div>
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
        <span class="sidebar-toggle-mark">
          <AppIcon :name="collapsed ? 'chevron-right' : 'chevron-left'" :size="12" />
        </span>
      </button>
    </div>

    <div class="sidebar-section nav-section">{{ t('app.navigation') }}</div>
    <RouterLink v-for="item in nav" :key="item.path"
      :to="item.path"
      class="nav-item"
      :class="{ active: isNavActive(item.path) }"
      :title="item.label"
    >
      <AppIcon :name="item.icon" class="nav-icon" />
      <span class="nav-label">{{ item.label }}</span>
    </RouterLink>

    <div class="sidebar-section config-section">{{ t('app.configuration') }}</div>
    <div class="nav-item" :title="t('app.settings')" @click="$emit('openSettings')">
      <AppIcon name="settings" class="nav-icon" />
      <span class="nav-label">{{ t('app.settings') }}</span>
    </div>

    <div class="sidebar-bottom">
      <div
        v-if="session.isAuthenticated"
        :class="['tenant-pill', 'session-pill', { clickable: collapsed }]"
        :title="sessionTooltip"
        @click="collapsed && $emit('toggle')"
      >
        <div class="user-avatar-wrap">
          <div class="user-avatar">{{ userInitial }}</div>
          <div class="tenant-dot session"></div>
        </div>
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
        :class="{ clickable: collapsed }"
        @click="$emit('openSettings')"
        :title="settings.isKeyManagedByEnv ? t('app.envKeyTitle') : t('app.changeKeyTitle')"
      >
        <div class="user-avatar-wrap key-mode">
          <AppIcon name="settings" :size="14" class="key-mode-icon" />
          <div :class="['tenant-dot', dotClass]"></div>
        </div>
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

const props = defineProps({
  collapsed: { type: Boolean, default: false },
  mobileOpen: { type: Boolean, default: false },
})
defineEmits(['openSettings', 'toggle'])

const route = useRoute()
const settings = useSettingsStore()
const session = useSessionStore()
const { t } = useI18n()

const userInitial = computed(() => {
  const name = session.displayName || session.user?.email || 'A'
  return name.trim().charAt(0).toUpperCase()
})

const sessionTooltip = computed(() => {
  const role = session.isAdmin ? t('app.roleAdmin') : t('app.roleMember')
  const tenant = session.user?.tenant_id ? ` · ${session.user.tenant_id}` : ''
  const base = `${session.displayName || ''} (${role}${tenant})`
  return props.collapsed ? `${base} — ${t('app.expandPanel')}` : (session.user?.email || session.displayName)
})

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
    { path: '/notebooks', label: t('app.notebooks'), icon: 'book' },
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
.tenant-pill.clickable {
  cursor: pointer;
}
.user-avatar-wrap {
  position: relative;
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.user-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: linear-gradient(135deg, color-mix(in oklch, var(--accent) 35%, var(--s3)), var(--s2));
  border: 1px solid color-mix(in oklch, var(--border2) 80%, transparent);
  color: var(--text);
  font-weight: 600;
  font-size: 12px;
  line-height: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  user-select: none;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.15);
  transition: transform 0.12s var(--ease-spring), border-color 0.12s var(--ease-spring);
}
.clickable:hover .user-avatar {
  transform: scale(1.05);
  border-color: var(--border2);
}
.user-avatar-wrap .tenant-dot.session {
  position: absolute;
  bottom: -1px;
  right: -1px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--green);
  box-shadow: 0 0 0 2px var(--s2), 0 0 6px var(--green);
}
.user-avatar-wrap.key-mode {
  position: relative;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted2);
}
.user-avatar-wrap.key-mode .tenant-dot {
  position: absolute;
  bottom: -1px;
  right: -1px;
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
