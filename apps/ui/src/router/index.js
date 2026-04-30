import { createRouter, createWebHistory } from 'vue-router'
import ChatView from '@/views/ChatView.vue'
import DocumentsView from '@/views/DocumentsView.vue'
import AnalyticsView from '@/views/AnalyticsView.vue'
import WorkflowsView from '@/views/WorkflowsView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/chat', component: ChatView },
    { path: '/documents', component: DocumentsView },
    { path: '/analytics', component: AnalyticsView },
    { path: '/workflows', component: WorkflowsView },
  ]
})
