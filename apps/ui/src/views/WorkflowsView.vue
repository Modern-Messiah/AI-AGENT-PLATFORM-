<template>
  <div class="screen-body">
    <div class="card">
      <div class="card-header">
        <div class="card-title">HITL управление</div>
        <div class="card-sub">Approve / Reject Temporal workflow по ID</div>
      </div>
      <div style="padding: 14px 18px; display: flex; gap: 8px">
        <input class="form-input"
               style="flex: 1; font-family: var(--mono); font-size: 12px; background: var(--s2); border: 1px solid var(--border); color: var(--text); padding: 8px 12px; border-radius: 8px; outline: none"
               placeholder="agent-run-tenant-uuid"
               v-model="wfId"
               @keydown.enter="addManual" />
        <button class="btn btn-ghost" @click="addManual">Добавить</button>
      </div>
    </div>

    <div style="display: flex; gap: 8px; align-items: center">
      <button v-for="f in filters" :key="f.key"
              :class="['btn btn-ghost btn-sm', { 'btn-primary': filter === f.key }]"
              @click="filter = f.key">
        {{ f.label }}
        <span v-if="f.count > 0" style="font-family: var(--mono); font-size: 10px; opacity: 0.8">{{ f.count }}</span>
      </button>
      <span style="margin-left: auto; font-size: 12px; color: var(--muted); font-family: var(--mono)">
        Temporal UI:
        <a href="http://localhost:8233" target="_blank" style="color: var(--accent); text-decoration: none">localhost:8233</a>
      </span>
    </div>

    <div class="wf-list">
      <div v-if="!filtered.length" class="empty" style="padding: 40px">
        <div class="empty-icon">⚡</div>
        <div class="empty-title">Нет workflows</div>
        <div class="empty-sub">Добавьте workflow_id выше чтобы управлять HITL, или откройте Temporal UI</div>
      </div>

      <div v-for="wf in filtered" :key="wf.id"
           :class="['wf-card', { 'hitl-pending': wf.status === 'hitl' }]">
        <div class="wf-status-col">
          <div class="wf-status-dot" :style="dotStyle(wf.status)"></div>
        </div>
        <div class="wf-main">
          <div class="wf-title">
            <span class="badge badge-blue">{{ wf.type }}</span>
            <StatusBadge :status="wf.status" />
            <span style="font-family: var(--mono); font-size: 11px; color: var(--muted); font-weight: 400">{{ wf.id }}</span>
          </div>
          <div class="wf-query">"{{ wf.query }}"</div>
          <div class="wf-meta">
            <span class="wf-meta-item">⟢ {{ wf.model }}</span>
            <span class="wf-meta-item">🕐 {{ wf.started }}</span>
          </div>
        </div>
        <div v-if="wf.status === 'hitl'" class="wf-actions">
          <button class="btn btn-success btn-sm"
                  :disabled="acting === wf.id + 'approve'"
                  @click="signal(wf.id, 'approve')">
            <div v-if="acting === wf.id + 'approve'" class="spinner"></div>
            <template v-else>✓</template>
            Approve
          </button>
          <button class="btn btn-danger btn-sm"
                  :disabled="acting === wf.id + 'reject'"
                  @click="signal(wf.id, 'reject')">
            <div v-if="acting === wf.id + 'reject'" class="spinner"></div>
            <template v-else>✕</template>
            Reject
          </button>
        </div>
      </div>
    </div>

    <AppToast v-if="toast" v-bind="toast" @done="toast = null" />
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useApi } from '@/composables/useApi'
import { useSettingsStore } from '@/stores/settings'
import AppToast from '@/components/AppToast.vue'
import StatusBadge from '@/components/StatusBadge.vue'

const { apiFetch } = useApi()
const settings = useSettingsStore()

const workflows = ref([])
const filter = ref('all')
const wfId = ref('')
const acting = ref(null)
const toast = ref(null)

watch(() => settings.apiKey, () => {
  workflows.value = []
  filter.value = 'all'
})

const STATUS_COLOR = { running: 'var(--accent)', completed: 'var(--green)', failed: 'var(--red)', hitl: 'var(--yellow)', pending: 'var(--muted)' }
const dotStyle = status => ({
  background: STATUS_COLOR[status] || 'var(--muted)',
  boxShadow: status === 'hitl' ? `0 0 8px ${STATUS_COLOR[status]}` : 'none'
})

const filters = computed(() => [
  { key: 'all',       label: 'Все',       count: workflows.value.length },
  { key: 'hitl',      label: 'HITL',      count: workflows.value.filter(w => w.status === 'hitl').length },
  { key: 'completed', label: 'Completed', count: workflows.value.filter(w => w.status === 'completed').length },
  { key: 'failed',    label: 'Failed',    count: workflows.value.filter(w => w.status === 'failed').length },
])
const filtered = computed(() => filter.value === 'all' ? workflows.value : workflows.value.filter(w => w.status === filter.value))

function addManual() {
  const id = wfId.value.trim()
  if (!id) return
  if (workflows.value.find(w => w.id === id)) { toast.value = { msg: 'Уже добавлен', type: 'info' }; return }
  workflows.value = [{ id, type: 'AgentRun', status: 'hitl', query: '(manually added)', model: '—', started: 'сейчас', steps: [] }, ...workflows.value]
  wfId.value = ''
  toast.value = { msg: `Добавлен workflow: ${id}`, type: 'success' }
}

async function signal(id, action) {
  if (!settings.isConnected) { toast.value = { msg: 'Задайте X-API-Key', type: 'error' }; return }
  acting.value = id + action
  try {
    await apiFetch(`/workflows/${id}/${action}`, { method: 'POST' })
    toast.value = { msg: `Workflow ${action === 'approve' ? 'одобрен' : 'отклонён'}`, type: action === 'approve' ? 'success' : 'error' }
    workflows.value = workflows.value.map(w => w.id === id ? { ...w, status: action === 'approve' ? 'completed' : 'failed' } : w)
  } catch (e) {
    toast.value = { msg: `Ошибка: ${e.message}`, type: 'error' }
  } finally {
    acting.value = null
  }
}
</script>
