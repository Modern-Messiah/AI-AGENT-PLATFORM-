import { createRouter, createWebHistory } from 'vue-router'
import ChatView from '@/views/ChatView.vue'
import DocumentsView from '@/views/DocumentsView.vue'
import DocumentDetailView from '@/views/DocumentDetailView.vue'
import AnalyticsView from '@/views/AnalyticsView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/chat', component: ChatView },
    { path: '/documents', component: DocumentsView },
    { path: '/documents/:id', component: DocumentDetailView },
    { path: '/analytics', component: AnalyticsView },
    { path: '/workflows', redirect: '/chat' },
  ]
})
