import { createRouter, createWebHistory } from 'vue-router'
import ChatView from '@/views/ChatView.vue'
import DocumentsView from '@/views/DocumentsView.vue'
import DocumentDetailView from '@/views/DocumentDetailView.vue'
import NotebooksView from '@/views/NotebooksView.vue'
import NotebookDetailView from '@/views/NotebookDetailView.vue'
import AnalyticsView from '@/views/AnalyticsView.vue'
import AdminView from '@/views/AdminView.vue'
import LoginView from '@/views/LoginView.vue'
import { settingsRedirect } from '@/utils/settingsRoute'
import { useSessionStore } from '@/stores/session'
import { useSettingsStore } from '@/stores/settings'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/login', component: LoginView, meta: { public: true } },
    { path: '/chat', component: ChatView },
    { path: '/documents', component: DocumentsView },
    { path: '/documents/:id', component: DocumentDetailView },
    { path: '/notebooks', component: NotebooksView },
    { path: '/notebooks/:id', component: NotebookDetailView },
    { path: '/analytics', component: AnalyticsView },
    { path: '/admin', component: AdminView, meta: { admin: true } },
    { path: '/settings', redirect: settingsRedirect },
    { path: '/workflows', redirect: '/chat' },
  ]
})

// Cabinet separation: the admin panel needs either an admin session
// (Google login with ADMIN_EMAILS) or the classic admin secret; every
// other page needs any credential (session token or API key).
router.beforeEach((to) => {
  const session = useSessionStore()
  const settings = useSettingsStore()
  const hasAnyCredential = session.isAuthenticated || settings.isConnected

  if (to.meta.public) return true
  if (!hasAnyCredential) return '/login'
  if (to.meta.admin && !session.isAdmin && !settings.hasAdminSecret) {
    return session.isAuthenticated ? '/chat' : '/login'
  }
  return true
})

export default router
