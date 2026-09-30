import { test } from 'vitest'
import assert from 'node:assert/strict'

import { createPinia, setActivePinia } from 'pinia'

import { useChatStore } from '../../src/stores/chat.js'

// The chat store drives SSE streaming, HITL cards and session switching —
// the raciest code in the UI. These tests fake fetch (the composable calls
// the global) and exercise the store through its public API.

function deferred() {
  let resolve
  const promise = new Promise((res) => { resolve = res })
  return { promise, resolve }
}

function jsonResponse(data) {
  return {
    ok: true,
    status: 200,
    headers: new Map(),
    json: async () => data,
    text: async () => JSON.stringify(data),
  }
}

function sseResponse(events, { hangAfter = null } = {}) {
  const chunks = events.map((e) => `data: ${JSON.stringify(e)}\n\n`)
  let i = 0
  const reader = {
    read: async () => {
      if (i < chunks.length) return { done: false, value: new TextEncoder().encode(chunks[i++]) }
      if (hangAfter) return hangAfter.promise
      return { done: true, value: undefined }
    },
  }
  return {
    ok: true,
    status: 200,
    headers: new Map(),
    json: async () => ({}),
    body: { getReader: () => reader },
  }
}

const ISO = '2026-09-30T10:00:00Z'

function withStore(handler) {
  const calls = []
  const originalFetch = globalThis.fetch
  globalThis.fetch = (url, opts) => handler(String(url), opts, calls)
  globalThis.localStorage?.clear()
  globalThis.sessionStorage?.clear()
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useChatStore()
  return { store, calls, restore() { globalThis.fetch = originalFetch } }
}

function defaultHandler(extra = {}) {
  return (url, opts, calls) => {
    calls.push({ url, method: opts.method || 'GET', body: opts.body || null })
    const route = extra[`${(opts && opts.method) || 'GET'} ${url}`]
    if (route) return route(url, opts)
    return jsonResponse([])
  }
}

const ticks = async (n = 3) => {
  for (let i = 0; i < n; i++) await new Promise((r) => setImmediate(r))
}

test('a second sendMessage is rejected while a stream is active', async () => {
  const gate = deferred()
  const { store, calls, restore } = withStore(defaultHandler({
    'GET /api/sessions': () => jsonResponse([{ id: 's1', title: 'Chat' }]),
    'GET /api/sessions/s1/messages': () => jsonResponse([]),
    'POST /api/agent/stream': async () => {
      await gate.promise
      return sseResponse([{ type: 'done', answer: 'first answer', sources: [] }])
    },
  }))
  try {
    await store.loadSessions()

    const first = store.sendMessage('question one', 'model')
    await ticks()
    assert.equal(store.isStreaming, true)
    // loading already cleared by the first token — the guard must use the
    // stream controller, not loading (the bug this pins down).
    assert.equal(store.loading, true)

    const second = await store.sendMessage('question two', 'model')
    assert.equal(second, null)
    const streamCalls = calls.filter((c) => c.url === '/api/agent/stream')
    assert.equal(streamCalls.length, 1)

    gate.resolve(null)
    const result = await first
    assert.equal(result.text, 'first answer')
    assert.equal(store.isStreaming, false)
  } finally {
    restore()
  }
})

test('token events build the message, done finalizes and persists it', async () => {
  const { store, calls, restore } = withStore(defaultHandler({
    'GET /api/sessions': () => jsonResponse([{ id: 's1', title: 'Chat' }]),
    'GET /api/sessions/s1/messages': () => jsonResponse([]),
    'POST /api/agent/stream': () => sseResponse([
      { type: 'stage', stage: 'retrieve' },
      { type: 'token', content: 'Hel' },
      { type: 'token', content: 'lo' },
      { type: 'done', answer: 'Hello', sources: [{ url: 'https://x' }], cached: false, confidence: 0.9 },
    ]),
  }))
  try {
    await store.loadSessions()
    const message = await store.sendMessage('q', 'model')

    assert.equal(message.text, 'Hello')
    const stored = store.messages.find((m) => m.role === 'agent' && m.text === 'Hello')
    assert.ok(stored)
    assert.equal(stored.streaming, false)
    assert.deepEqual(stored.sources, [{ url: 'https://x' }])
    assert.equal(store.isStreaming, false)

    const persist = calls.filter(
      (c) => c.url === '/api/sessions/s1/messages' && String(c.body).includes('"role":"agent"'),
    )
    assert.equal(persist.length, 1)
  } finally {
    restore()
  }
})

test('a late session response cannot overwrite the newer session view', async () => {
  const slow = deferred()
  const fast = deferred()
  const { store, restore } = withStore((url) => {
    if (url === '/api/sessions/s1/messages') return slow.promise.then(() => jsonResponse([
      { id: 'm1', role: 'user', content: 'from-one', created_at: ISO, sources: [] },
    ]))
    if (url === '/api/sessions/s2/messages') return fast.promise.then(() => jsonResponse([
      { id: 'm2', role: 'user', content: 'from-two', created_at: ISO, sources: [] },
    ]))
    return jsonResponse([])
  })
  try {
    store.sessions = [
      { id: 's1', title: 'One' },
      { id: 's2', title: 'Two' },
    ]

    const first = store.selectSession('s1')
    await ticks()
    const second = store.selectSession('s2')
    await ticks()

    fast.resolve(null)
    await second
    slow.resolve(null)
    await first

    assert.equal(store.activeId, 's2')
    assert.equal(store.messages.some((m) => m.text === 'from-two'), true)
    assert.equal(store.messages.some((m) => m.text === 'from-one'), false)
  } finally {
    restore()
  }
})

test('cancelStreaming stops the stream and keeps or drops the partial answer', async () => {
  const hang = () => deferred()
  const { store, restore } = withStore(defaultHandler({
    'GET /api/sessions': () => jsonResponse([{ id: 's1', title: 'Chat' }]),
    'GET /api/sessions/s1/messages': () => jsonResponse([]),
    'POST /api/agent/stream': () => {
      const gate = hang()
      return sseResponse([{ type: 'token', content: 'Par' }], { hangAfter: gate })
    },
  }))
  try {
    await store.loadSessions()

    const first = store.sendMessage('q', 'model')
    await ticks()
    assert.equal(store.isStreaming, true)

    store.cancelStreaming()
    assert.equal(store.isStreaming, false)
    const partial = store.messages.find((m) => m.text === 'Par')
    assert.ok(partial)
    assert.equal(partial.streaming, false)

    // After cancellation a new stream is allowed again; dropping the partial
    // removes it from the transcript.
    const second = store.sendMessage('q2', 'model')
    await ticks()
    assert.equal(store.isStreaming, true)
    store.cancelStreaming({ removePartial: true })
    assert.equal(store.messages.some((m) => m.streaming), false)

    first.catch(() => {})
    second.catch(() => {})
  } finally {
    restore()
  }
})

test('HITL card is created, re-injected on session switch, and removed on reject', async () => {
  const { store, restore } = withStore(defaultHandler({
    'GET /api/sessions': () => jsonResponse([{ id: 's1', title: 'Chat' }]),
    'GET /api/sessions/s1/messages': () => jsonResponse([]),
    'GET /api/sessions/s2/messages': () => jsonResponse([]),
    'POST /api/agent/run': () => jsonResponse({ pending_approval: true, workflow_id: 'wf-1' }),
    'POST /api/workflows/wf-1/reject': () => jsonResponse({ ok: true }),
  }))
  try {
    await store.loadSessions()

    await store.sendMessage('needs approval', 'model', true)
    assert.equal(store.messages.some((m) => m.role === 'hitl' && m.workflowId === 'wf-1'), true)

    // Switch away and back: the pending card must be re-injected from the
    // persisted HITL state.
    store.sessions = [{ id: 's1', title: 'Chat' }, { id: 's2', title: 'Two' }]
    await store.selectSession('s2')
    assert.equal(store.messages.some((m) => m.role === 'hitl'), false)
    await store.selectSession('s1')
    assert.equal(store.messages.some((m) => m.role === 'hitl' && m.workflowId === 'wf-1'), true)

    await store.rejectHitl('wf-1')
    assert.equal(store.messages.some((m) => m.role === 'hitl'), false)
    // Rejected once — switching again must not resurrect the card.
    await store.selectSession('s2')
    await store.selectSession('s1')
    assert.equal(store.messages.some((m) => m.role === 'hitl'), false)
  } finally {
    restore()
  }
})

test('manages fresh draft session IDs and locks scope on message or explicit lock', async () => {
  const { store, restore } = withStore(defaultHandler({
    'POST /api/sessions': (url, opts) => {
      const parsed = JSON.parse(opts.body || '{}')
      return jsonResponse({
        id: parsed.document_id ? 'sess-doc' : 'sess-global',
        title: parsed.title,
        document_id: parsed.document_id || null,
        notebook_id: parsed.notebook_id || null,
      })
    },
    'POST /api/agent/stream': () => sseResponse([{ type: 'done', answer: 'ok', sources: [] }]),
    'DELETE /api/sessions/sess-doc': () => jsonResponse({ ok: true }),
  }))
  try {
    // 1. newChat without documentId adds to freshDraftIds
    const s1 = await store.newChat('model')
    assert.equal(store.freshDraftIds.has(s1.id), true)

    // 2. lockSessionScope removes it
    store.lockSessionScope(s1.id)
    assert.equal(store.freshDraftIds.has(s1.id), false)

    // 3. newChat with documentId is not added to freshDraftIds
    const s2 = await store.newChat('model', { documentId: 'doc-1' })
    assert.equal(store.freshDraftIds.has(s2.id), false)

    // 4. sending a message locks draft scope
    const s3 = await store.newChat('model')
    assert.equal(store.freshDraftIds.has(s3.id), true)
    await store.sendMessage('testing query', 'model')
    assert.equal(store.freshDraftIds.has(s3.id), false)
  } finally {
    restore()
  }
})

