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

  async function sendMessage(query, model) {
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
        body: JSON.stringify({ user_query: query, model })
      })
      loading.value = false
      const agentMsg = {
        id: 'a' + Date.now(), role: 'agent', text: data.answer,
        time: nowTime(), sources: data.sources || [], cached: data.cached || false
      }
      apiFetch(`/sessions/${sessId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: 'agent', content: data.answer, sources: data.sources || [], cached: data.cached || false })
      }).catch(() => {})
      return agentMsg
    } catch (e) {
      loading.value = false
      messages.value.push({ id: 'e' + Date.now(), role: 'agent', text: `Ошибка: ${e.message}`, time: nowTime(), sources: [], error: true })
      throw e
    }
  }

  function approveHitl(pending) {
    messages.value = messages.value.map(m => m.role === 'hitl' ? { ...pending, id: m.id, role: 'agent' } : m)
  }

  function rejectHitl() {
    messages.value = messages.value.filter(m => m.role !== 'hitl')
  }

  return {
    sessions, activeId, messages, loading, sessLoading,
    loadSessions, selectSession, newChat, deleteSession,
    sendMessage, approveHitl, rejectHitl
  }
})
