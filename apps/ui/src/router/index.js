import { createRouter, createWebHistory } from 'vue-router'
import ChatView from '@/views/ChatView.vue'
import DocumentsView from '@/views/DocumentsView.vue'
import DocumentDetailView from '@/views/DocumentDetailView.vue'
import NotebooksView from '@/views/NotebooksView.vue'
import NotebookDetailView from '@/views/NotebookDetailView.vue'
import AnalyticsView from '@/views/AnalyticsView.vue'
import { settingsRedirect } from '@/utils/settingsRoute'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/chat', component: ChatView },
    { path: '/documents', component: DocumentsView },
    { path: '/documents/:id', component: DocumentDetailView },
    { path: '/notebooks', component: NotebooksView },
    { path: '/notebooks/:id', component: NotebookDetailView },
    { path: '/analytics', component: AnalyticsView },
    { path: '/settings', redirect: settingsRedirect },
    { path: '/workflows', redirect: '/chat' },
  ]
})
