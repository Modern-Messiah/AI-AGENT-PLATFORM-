import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useApi } from '@/composables/useApi'

const WELCOME = 'Привет! Я готов отвечать на вопросы о вашей кодовой базе и документах. Что хотите узнать?'
const LS_HITL_KEY = 'chatPendingHitl'

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
  const loadedKey = ref(null)
  const streamTick = ref(0)  // incremented on each streaming token to trigger scroll
  let activeStreamController = null

  // sessId → [{ workflowId, time }, ...]  (array to support multiple pending workflows per session)
  // Persisted to localStorage so pending HITL cards survive page refresh.
  // HITL state is not stored server-side, so this map is the only source of truth.
  const pendingHitl = ref(_loadPendingHitl())

  function _loadPendingHitl() {
    try {
      const raw = localStorage.getItem(LS_HITL_KEY)
      if (!raw) return new Map()
      // Migrate old single-entry format { workflowId, time } → array format [{ workflowId, time }]
      return new Map(JSON.parse(raw).map(([sid, val]) => [sid, Array.isArray(val) ? val : [val]]))
    } catch { return new Map() }
  }

  function _savePendingHitl() {
    try { localStorage.setItem(LS_HITL_KEY, JSON.stringify([...pendingHitl.value])) } catch {}
  }

  function _clearPendingByWorkflow(workflowId) {
    for (const [sid, entries] of pendingHitl.value) {
      const next = entries.filter(e => e.workflowId !== workflowId)
      if (next.length !== entries.length) {
        if (next.length === 0) pendingHitl.value.delete(sid)
        else pendingHitl.value.set(sid, next)
        break
      }
    }
    _savePendingHitl()
  }

  function reset() {
    if (activeStreamController) {
      activeStreamController.abort()
      activeStreamController = null
    }
    sessions.value = []
    activeId.value = null
    messages.value = []
    loading.value = false
    sessLoading.value = false
    loadedKey.value = null
  }

  async function loadSessions(apiKey = null) {
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
      loadedKey.value = apiKey
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
      // Re-inject a pending HITL card if one exists for this session and the session is
      // still active (guard against rapid session switches causing cross-session injection).
      if (activeId.value === id) {
        for (const hitl of (pendingHitl.value.get(id) || [])) {
          if (!messages.value.some(m => m.role === 'hitl' && m.workflowId === hitl.workflowId)) {
            messages.value.push({ id: 'h' + Date.now(), role: 'hitl', time: hitl.time, workflowId: hitl.workflowId, sessId: id })
          }
        }
      }
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
    if (pendingHitl.value.has(id)) {
      pendingHitl.value.delete(id)
      _savePendingHitl()
    }
    if (activeId.value === id) {
      if (remaining.length > 0) await selectSession(remaining[0].id)
      else { activeId.value = null; messages.value = [] }
    }
  }

  async function sendMessage(query, model, requireApproval = false) {
    const { apiFetch, apiStreamFetch } = useApi()
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
    }).catch(e => console.error('Failed to persist user message:', e))

    const curSess = sessions.value.find(s => s.id === sessId)
    if (curSess?.title === 'New Chat') {
      const title = query.slice(0, 40) + (query.length > 40 ? '…' : '')
      apiFetch(`/sessions/${sessId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title })
      }).then(() => {
        sessions.value = sessions.value.map(x => x.id === sessId ? { ...x, title } : x)
      }).catch(e => console.error('Failed to update session title:', e))
    }

    // ── HITL path — uses Temporal workflow ──────────────────────────────────
    if (requireApproval) {
      try {
        const data = await apiFetch('/agent/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_query: query, model, require_approval: true })
        })
        loading.value = false
        if (data.pending_approval) {
          const pending = pendingHitl.value.get(sessId) || []
          pending.push({ workflowId: data.workflow_id, time: nowTime() })
          pendingHitl.value.set(sessId, pending)
          _savePendingHitl()
          if (activeId.value === sessId) {
            messages.value.push({ id: 'h' + Date.now(), role: 'hitl', time: nowTime(), workflowId: data.workflow_id, sessId })
          }
        }
        return null
      } catch (e) {
        loading.value = false
        if (activeId.value === sessId) {
          messages.value.push({ id: 'e' + Date.now(), role: 'agent', text: `Ошибка: ${e.message}`, time: nowTime(), sources: [], error: true })
        }
        throw e
      }
    }

    // ── Streaming path ───────────────────────────────────────────────────────
    let streamMsg = null
    const streamController = new AbortController()
    activeStreamController = streamController
    try {
      const response = await apiStreamFetch('/agent/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_query: query, model }),
        signal: streamController.signal,
      })

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() ?? ''

        for (const part of parts) {
          if (!part.startsWith('data: ')) continue
          let event
          try { event = JSON.parse(part.slice(6)) } catch { continue }

          if (event.type === 'token') {
            if (!streamMsg) {
              // First token: create message, hide typing indicator
              streamMsg = { id: 'a' + Date.now(), role: 'agent', text: '', time: nowTime(), sources: [], cached: false, streaming: true }
              if (activeId.value === sessId) messages.value.push(streamMsg)
              loading.value = false
            }
            if (activeId.value === sessId) {
              let idx = messages.value.findIndex(m => m.id === streamMsg.id)
              if (idx === -1) {
                messages.value.push(streamMsg)
                idx = messages.value.length - 1
              }
              if (idx !== -1) {
                messages.value[idx].text += event.content
                streamTick.value++
              }
            }

          } else if (event.type === 'done') {
            if (activeStreamController === streamController) activeStreamController = null
            loading.value = false
            if (activeId.value === sessId) {
              if (streamMsg) {
                const idx = messages.value.findIndex(m => m.id === streamMsg.id)
                if (idx !== -1) {
                  messages.value[idx] = { ...messages.value[idx], text: event.answer, sources: event.sources || [], cached: event.cached || false, streaming: false }
                } else {
                  messages.value.push({
                    ...streamMsg,
                    text: event.answer,
                    sources: event.sources || [],
                    cached: event.cached || false,
                    streaming: false
                  })
                }
              } else {
                // Cache hit — full answer in one shot
                streamMsg = { id: 'a' + Date.now(), role: 'agent', text: event.answer, time: nowTime(), sources: event.sources || [], cached: event.cached || false, streaming: false }
                messages.value.push(streamMsg)
              }
            }
            apiFetch(`/sessions/${sessId}/messages`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ role: 'agent', content: event.answer, sources: event.sources || [], cached: event.cached || false })
            }).catch(e => console.error('Failed to persist agent message:', e))
            return streamMsg

          } else if (event.type === 'error') {
            if (activeStreamController === streamController) activeStreamController = null
            loading.value = false
            const errMsg = { id: 'e' + Date.now(), role: 'agent', text: `Ошибка: ${event.message}`, time: nowTime(), sources: [], error: true }
            if (activeId.value === sessId) {
              if (streamMsg) {
                const idx = messages.value.findIndex(m => m.id === streamMsg.id)
                if (idx !== -1) messages.value[idx] = errMsg
                else messages.value.push(errMsg)
              } else {
                messages.value.push(errMsg)
              }
            }
            return null
          }
        }
      }
    } catch (e) {
      if (activeStreamController === streamController) activeStreamController = null
      loading.value = false
      if (e?.name === 'AbortError') return null
      const errMsg = { id: 'e' + Date.now(), role: 'agent', text: `Ошибка: ${e.message}`, time: nowTime(), sources: [], error: true }
      if (activeId.value === sessId) {
        if (streamMsg) {
          const idx = messages.value.findIndex(m => m.id === streamMsg.id)
          if (idx !== -1) messages.value[idx] = errMsg
          else messages.value.push(errMsg)
        } else {
          messages.value.push(errMsg)
        }
      }
      throw e
    }
    return streamMsg
  }

  function cancelStreaming(options = {}) {
    const { removePartial = false } = options
    if (activeStreamController) {
      activeStreamController.abort()
      activeStreamController = null
    }
    loading.value = false
    if (removePartial) {
      messages.value = messages.value.filter(m => !m.streaming)
      return
    }
    messages.value = messages.value.map(m => m.streaming ? { ...m, streaming: false } : m)
  }

  async function approveHitl(workflowId) {
    const { apiFetch } = useApi()
    const isThis = m => m.role === 'hitl' && m.workflowId === workflowId
    // Capture sessId synchronously before any awaits: messages.value may point to a
    // different session if the user switches chats while the workflow is pending.
    const origSessId = messages.value.find(m => isThis(m))?.sessId ?? activeId.value
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
          messages.value = messages.value.map(m => isThis(m) ? { ...agentMsg, id: m.id } : m)
          if (origSessId) {
            _clearPendingByWorkflow(workflowId)
            apiFetch(`/sessions/${origSessId}/messages`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ role: 'agent', content: data.answer, sources: data.sources || [], cached: data.cached || false })
            }).catch(() => {})
          }
          return
        }
      }
      // 5-min deadline exceeded — mark card as timed out and remove from pendingHitl so
      // navigating back doesn't re-inject a fresh "waiting" card for a dead workflow.
      messages.value = messages.value.map(m => isThis(m) ? { ...m, status: 'timeout' } : m)
      _clearPendingByWorkflow(workflowId)
    } catch (e) {
      if (activeId.value === origSessId) {
        messages.value = messages.value.filter(m => !isThis(m))
        messages.value.push({ id: 'e' + Date.now(), role: 'agent', text: `HITL error: ${e.message}`, time: nowTime(), sources: [], error: true })
      }
      _clearPendingByWorkflow(workflowId)
    }
  }

  async function rejectHitl(workflowId) {
    const { apiFetch } = useApi()
    if (workflowId) {
      try {
        await apiFetch(`/workflows/${workflowId}/reject`, { method: 'POST' })
      } catch (e) {
        // API call failed — the Temporal workflow is still waiting for a signal.
        // Keep the card visible and mark it as errored so the user can retry.
        messages.value = messages.value.map(m =>
          m.role === 'hitl' && m.workflowId === workflowId
            ? { ...m, status: 'reject_error', error: e.message }
            : m
        )
        return
      }
    }
    _clearPendingByWorkflow(workflowId)
    messages.value = messages.value.filter(m => !(m.role === 'hitl' && m.workflowId === workflowId))
  }

  return {
    sessions, activeId, messages, loading, sessLoading, loadedKey, streamTick,
    reset, loadSessions, selectSession, newChat, deleteSession,
    sendMessage, cancelStreaming, approveHitl, rejectHitl
  }
})
