import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useApi } from '@/composables/useApi'

const WELCOME = 'Привет! Я готов отвечать на вопросы о вашей кодовой базе и документах. Что хотите узнать?'

function fmtTime(iso) {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' }) } catch { return '—' }
}
function nowTime() {
  return new Date().toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' })
}

export const useChatStore = defineStore('chat', () => {
  const sessions = ref([])
  const activeId = ref(null)
  const messages = ref([])
  const loading = ref(false)
  const sessLoading = ref(false)

  async function loadSessions() {
    const { apiFetch } = useApi()
    sessions.value = []
    activeId.value = null
    messages.value = []
    sessLoading.value = true
    try {
      const data = await apiFetch('/sessions')
      sessions.value = data
      if (data.length > 0) await selectSession(data[0].id)
    } finally {
      sessLoading.value = false
    }
  }

  async function selectSession(id) {
    const { apiFetch } = useApi()
    activeId.value = id
    messages.value = []
    sessLoading.value = true
    try {
      const msgs = await apiFetch(`/sessions/${id}/messages`)
      if (msgs.length > 0) {
        messages.value = msgs.map(m => ({
          id: m.id, role: m.role, text: m.content,
          time: fmtTime(m.created_at), sources: m.sources || [], cached: m.cached
        }))
      } else {
        messages.value = [{ id: 'w', role: 'agent', text: WELCOME, time: '—', sources: [] }]
      }
    } catch {
      messages.value = [{ id: 'w', role: 'agent', text: WELCOME, time: '—', sources: [] }]
    } finally {
      sessLoading.value = false
    }
  }

  async function newChat(model) {
    const { apiFetch } = useApi()
    const sess = await apiFetch('/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'New Chat', model })
    })
    sessions.value = [sess, ...sessions.value]
    activeId.value = sess.id
    messages.value = [{ id: 'w', role: 'agent', text: WELCOME, time: nowTime(), sources: [] }]
    return sess
  }

  async function deleteSession(id) {
    const { apiFetch } = useApi()
    await apiFetch(`/sessions/${id}`, { method: 'DELETE' })
    const remaining = sessions.value.filter(s => s.id !== id)
    sessions.value = remaining
    if (activeId.value === id) {
      if (remaining.length > 0) await selectSession(remaining[0].id)
      else { activeId.value = null; messages.value = [] }
    }
  }

  async function sendMessage(query, model, requireApproval = false) {
    const { apiFetch } = useApi()
    if (!query.trim() || loading.value) return null

    let sessId = activeId.value
    if (!sessId) {
      const sess = await apiFetch('/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: query.slice(0, 40), model })
      })
      sessId = sess.id
      sessions.value = [sess, ...sessions.value]
      activeId.value = sessId
    }

    const userMsg = { id: 'u' + Date.now(), role: 'user', text: query, time: nowTime(), sources: [] }
    messages.value = messages.value.filter(x => x.id !== 'w').concat(userMsg)
    loading.value = true

    apiFetch(`/sessions/${sessId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role: 'user', content: query })
    }).catch(() => {})

    const curSess = sessions.value.find(s => s.id === sessId)
    if (curSess?.title === 'New Chat') {
      const title = query.slice(0, 40) + (query.length > 40 ? '…' : '')
      apiFetch(`/sessions/${sessId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title })
      }).then(() => {
        sessions.value = sessions.value.map(x => x.id === sessId ? { ...x, title } : x)
      }).catch(() => {})
    }

    try {
      const data = await apiFetch('/agent/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_query: query, model, require_approval: requireApproval })
      })
      loading.value = false

      if (data.pending_approval) {
        // Store sessId so approveHitl saves to the originating session even if the user
        // switches chats while the workflow is pending.
        messages.value.push({ id: 'h' + Date.now(), role: 'hitl', time: nowTime(), workflowId: data.workflow_id, sessId })
        return null
      }

      const agentMsg = {
        id: 'a' + Date.now(), role: 'agent', text: data.answer,
        time: nowTime(), sources: data.sources || [], cached: data.cached || false
      }
      apiFetch(`/sessions/${sessId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: 'agent', content: data.answer, sources: data.sources || [], cached: data.cached || false })
      }).catch(() => {})
      messages.value.push(agentMsg)
      return agentMsg
    } catch (e) {
      loading.value = false
      messages.value.push({ id: 'e' + Date.now(), role: 'agent', text: `Ошибка: ${e.message}`, time: nowTime(), sources: [], error: true })
      throw e
    }
  }

  async function approveHitl(workflowId) {
    const { apiFetch } = useApi()
    const isThis = m => m.role === 'hitl' && m.workflowId === workflowId
    // Show spinner on this specific card immediately
    messages.value = messages.value.map(m => isThis(m) ? { ...m, status: 'polling' } : m)
    try {
      await apiFetch(`/workflows/${workflowId}/approve`, { method: 'POST' })
      // Poll with exponential backoff for up to 5 minutes
      const deadline = Date.now() + 5 * 60 * 1000
      let delay = 800
      while (Date.now() < deadline) {
        await new Promise(r => setTimeout(r, delay))
        delay = Math.min(Math.round(delay * 1.5), 8000)
        const data = await apiFetch(`/workflows/${workflowId}/result`)
        if (!data.pending_approval) {
          const agentMsg = {
            id: 'a' + Date.now(), role: 'agent', text: data.answer,
            time: nowTime(), sources: data.sources || [], cached: data.cached || false
          }
          // Capture sessId from the hitl message BEFORE replacing it.
          const origSessId = messages.value.find(m => isThis(m))?.sessId
          messages.value = messages.value.map(m => isThis(m) ? { ...agentMsg, id: m.id } : m)
          const targetSess = origSessId || activeId.value
          if (targetSess) {
            apiFetch(`/sessions/${targetSess}/messages`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ role: 'agent', content: data.answer, sources: data.sources || [], cached: data.cached || false })
            }).catch(() => {})
          }
          return
        }
      }
      // 5-min deadline exceeded — mark this card as timed out, don't remove it
      messages.value = messages.value.map(m => isThis(m) ? { ...m, status: 'timeout' } : m)
    } catch (e) {
      messages.value = messages.value.filter(m => !isThis(m))
      messages.value.push({ id: 'e' + Date.now(), role: 'agent', text: `HITL error: ${e.message}`, time: nowTime(), sources: [], error: true })
    }
  }

  async function rejectHitl(workflowId) {
    const { apiFetch } = useApi()
    try {
      if (workflowId) await apiFetch(`/workflows/${workflowId}/reject`, { method: 'POST' })
    } catch {}
    messages.value = messages.value.filter(m => !(m.role === 'hitl' && m.workflowId === workflowId))
  }

  return {
    sessions, activeId, messages, loading, sessLoading,
    loadSessions, selectSession, newChat, deleteSession,
    sendMessage, approveHitl, rejectHitl
  }
})
