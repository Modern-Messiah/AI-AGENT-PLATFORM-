<template>
  <div ref="chatLayoutRef" class="chat-layout" :class="{ 'is-resizing-history': isResizingHistory }">
    <ChatHistory
      :model="model"
      :width="historyWidth"
      :mobile-open="mobileHistoryOpen"
      :is-mobile="isMobile"
      @toast="setToast"
    />
    <div
      v-if="isMobile && mobileHistoryOpen"
      class="mobile-backdrop"
      @click="mobileHistoryOpen = false"
    ></div>

    <button
      class="chat-history-resizer"
      type="button"
      role="separator"
      aria-orientation="vertical"
      :aria-label="t('chat.resizeSessions')"
      :aria-valuemin="CHAT_HISTORY_MIN_WIDTH"
      :aria-valuemax="maxHistoryWidth()"
      :aria-valuenow="historyWidth"
      :title="t('chat.resizeSessionsHint')"
      @pointerdown="startHistoryResize"
      @mousedown="startHistoryResize"
      @touchstart.prevent="startHistoryResize"
      @keydown="handleHistoryResizeKeydown"
    ></button>

    <div class="chat-main">
      <ChatToolbar
        v-model:model="model"
        v-model:requireApproval="requireApproval"
        :show-history-toggle="isMobile"
        :scope="displayScope"
        :scope-locked="isScopeLocked"
        @toggle-history="mobileHistoryOpen = !mobileHistoryOpen"
        @open-scope="!isScopeLocked && (isScopeModalOpen = true)"
      />
      <ChatMessages @approve="approveHitl" @reject="rejectHitl" @regenerate="handleRegenerate" />
      <ChatInput :model="model" :require-approval="requireApproval" @send="handleSend" />
    </div>

    <ChatScopeModal
      v-if="isScopeModalOpen"
      :current-scope="displayScope"
      @select="handleScopeSelect"
      @cancel="isScopeModalOpen = false"
    />

    <AppToast v-if="toast" v-bind="toast" @done="toast = null" />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChatStore } from '@/stores/chat'
import { useSettingsStore } from '@/stores/settings'
import { useI18n } from '@/composables/useI18n'
import {
  buildChatScopeQuery,
  normalizeChatScope,
  normalizeStoredChatScope,
  sessionScopeMetaFromSession,
  scopeSessionTitle,
  scopeSendOptions,
  scopeWelcomeMessage,
  isChatScopeLocked,
} from '@/utils/chatScope'
import {
  CHAT_HISTORY_DEFAULT_WIDTH,
  CHAT_HISTORY_MAX_WIDTH,
  CHAT_HISTORY_MIN_WIDTH,
  clampPaneWidth,
  readStoredPaneWidth,
  storePaneWidth,
} from '@/utils/paneResize'
import ChatHistory from '@/components/chat/ChatHistory.vue'
import { useMaxWidthMediaQuery } from '@/utils/mediaQuery'
import ChatToolbar from '@/components/chat/ChatToolbar.vue'
import ChatMessages from '@/components/chat/ChatMessages.vue'
import ChatInput from '@/components/chat/ChatInput.vue'
import AppToast from '@/components/AppToast.vue'
import AppIcon from '@/components/AppIcon.vue'
import ChatScopeModal from '@/components/chat/ChatScopeModal.vue'
import { buildDocumentChatRoute } from '@/utils/documents'
import { buildNotebookChatRoute } from '@/utils/notebooks'

const chat = useChatStore()
const settings = useSettingsStore()
const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const isScopeModalOpen = ref(false)

const model = ref('moonshot/kimi-k2.6')
const requireApproval = ref(false)
const toast = ref(null)
const consumedAsk = ref('')
const chatLayoutRef = ref(null)
const isMobile = useMaxWidthMediaQuery(900)
const mobileHistoryOpen = ref(false)
const historyWidth = ref(CHAT_HISTORY_DEFAULT_WIDTH)
const isResizingHistory = ref(false)
let previousBodyCursor = ''
let previousBodyUserSelect = ''
const currentScope = computed(() => normalizeChatScope(route.query, settings.locale))
const activeSession = computed(() => chat.sessions.find(session => session.id === chat.activeId) || null)
const activeSessionScope = computed(() => normalizeStoredChatScope(activeSession.value, settings.locale))
const activeSessionMeta = computed(() => {
  return sessionScopeMetaFromSession(activeSession.value, settings.locale)
})
const displayScope = computed(() => {
  const scope = currentScope.value.type !== 'global'
    ? currentScope.value
    : activeSessionScope.value
  const meta = activeSessionMeta.value
  if (scope.type !== 'global' && meta?.type === scope.type) {
    return { ...scope, title: meta.subtitle }
  }
  return scope
})

const isScopeLocked = computed(() => {
  return isChatScopeLocked({
    session: activeSession.value,
    messages: chat.messages,
    isDraft: activeSession.value?.id ? chat.freshDraftIds.has(activeSession.value.id) : true,
  })
})

async function handleScopeSelect(selected) {
  isScopeModalOpen.value = false
  if (isScopeLocked.value) return

  const prevSessionId = activeSession.value?.id
  const prevIsEmpty = prevSessionId && chat.messages.every(m => m.role !== 'user')

  if (selected.type === 'global') {
    if (prevSessionId) {
      chat.lockSessionScope(prevSessionId)
    }
    await clearScope()
    return
  }
  if (selected.type === 'document') {
    if (prevIsEmpty && prevSessionId) {
      try { await chat.deleteSession(prevSessionId) } catch {}
    }
    const r = buildDocumentChatRoute(selected.documentId, selected.title, settings.locale)
    await router.replace(r)
    return
  }
  if (selected.type === 'notebook') {
    if (prevIsEmpty && prevSessionId) {
      try { await chat.deleteSession(prevSessionId) } catch {}
    }
    const r = buildNotebookChatRoute(selected.notebookId, selected.title, settings.locale)
    await router.replace(r)
  }
}

function setToast(t) { toast.value = t }

function paneStorage() {
  try {
    return globalThis.localStorage
  } catch {
    return null
  }
}

function applyHistoryWidth(clientX) {
  const rect = chatLayoutRef.value?.getBoundingClientRect()
  if (!rect) return

  updateHistoryWidth(clientX - rect.left)
}

function historyResizeClientX(event) {
  return event.touches?.[0]?.clientX ?? event.changedTouches?.[0]?.clientX ?? event.clientX
}

function maxHistoryWidth() {
  const rect = chatLayoutRef.value?.getBoundingClientRect()
  if (!rect) return CHAT_HISTORY_MAX_WIDTH

  return Math.max(
    CHAT_HISTORY_MIN_WIDTH,
    Math.min(CHAT_HISTORY_MAX_WIDTH, rect.width - 360),
  )
}

function updateHistoryWidth(width) {
  historyWidth.value = clampPaneWidth(width, CHAT_HISTORY_MIN_WIDTH, maxHistoryWidth())
}

function persistHistoryWidth() {
  storePaneWidth(paneStorage(), historyWidth.value)
}

function setResizeCursor() {
  previousBodyCursor = document.body.style.cursor
  previousBodyUserSelect = document.body.style.userSelect
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

function restoreResizeCursor() {
  document.body.style.cursor = previousBodyCursor
  document.body.style.userSelect = previousBodyUserSelect
  previousBodyCursor = ''
  previousBodyUserSelect = ''
}

function startHistoryResize(event) {
  if (isResizingHistory.value) return
  if (event.button !== undefined && event.button !== 0) return

  const clientX = historyResizeClientX(event)
  if (!Number.isFinite(clientX)) return

  event.preventDefault()
  applyHistoryWidth(clientX)
  isResizingHistory.value = true
  setResizeCursor()
  window.addEventListener('pointermove', handleHistoryResize)
  window.addEventListener('pointerup', stopHistoryResize)
  window.addEventListener('pointercancel', stopHistoryResize)
  window.addEventListener('mousemove', handleHistoryResize)
  window.addEventListener('mouseup', stopHistoryResize)
  window.addEventListener('touchmove', handleHistoryResize, { passive: false })
  window.addEventListener('touchend', stopHistoryResize)
  window.addEventListener('touchcancel', stopHistoryResize)
}

function handleHistoryResize(event) {
  const clientX = historyResizeClientX(event)
  if (!Number.isFinite(clientX)) return

  if (event.cancelable) {
    event.preventDefault()
  }
  applyHistoryWidth(clientX)
}

function stopHistoryResize() {
  if (!isResizingHistory.value) return

  restoreResizeCursor()
  isResizingHistory.value = false
  removeHistoryResizeListeners()
  persistHistoryWidth()
}

function handleWindowResize() {
  updateHistoryWidth(historyWidth.value)
}

function handleHistoryResizeKeydown(event) {
  const step = event.shiftKey ? 40 : 16
  const keyDelta = {
    ArrowLeft: -step,
    ArrowRight: step,
  }[event.key]

  if (keyDelta !== undefined) {
    event.preventDefault()
    updateHistoryWidth(historyWidth.value + keyDelta)
    persistHistoryWidth()
    return
  }

  if (event.key === 'Home') {
    event.preventDefault()
    updateHistoryWidth(CHAT_HISTORY_MIN_WIDTH)
    persistHistoryWidth()
    return
  }

  if (event.key === 'End') {
    event.preventDefault()
    updateHistoryWidth(maxHistoryWidth())
    persistHistoryWidth()
  }
}

function removeHistoryResizeListeners() {
  window.removeEventListener('pointermove', handleHistoryResize)
  window.removeEventListener('pointerup', stopHistoryResize)
  window.removeEventListener('pointercancel', stopHistoryResize)
  window.removeEventListener('mousemove', handleHistoryResize)
  window.removeEventListener('mouseup', stopHistoryResize)
  window.removeEventListener('touchmove', handleHistoryResize)
  window.removeEventListener('touchend', stopHistoryResize)
  window.removeEventListener('touchcancel', stopHistoryResize)
}

onMounted(() => {
  updateHistoryWidth(readStoredPaneWidth(paneStorage()))
  window.addEventListener('resize', handleWindowResize)
})

onBeforeUnmount(() => {
  removeHistoryResizeListeners()
  window.removeEventListener('resize', handleWindowResize)
  if (isResizingHistory.value) {
    restoreResizeCursor()
  }
})

watch(() => settings.credentialKey, async (key) => {
  if (!key) { chat.reset(); return }
  if (chat.loadedKey === key && (chat.sessions.length || chat.activeId)) return
  try { await chat.loadSessions(key) } catch {}
}, { immediate: true })

watch(
  [
    () => route.query.ask,
    () => route.query.document,
    () => route.query.notebook,
    () => route.query.fresh,
    () => route.query.title,
    () => settings.isConnected,
  ],
  async ([ask, document, notebook, fresh, title, connected]) => {
    if (!connected) return
    const documentId = typeof document === 'string' ? document : null
    const notebookId = typeof notebook === 'string' ? notebook : null
    const wantsFreshSession = fresh === '1' && (documentId || notebookId)
    const askKey = `${ask}:${documentId || ''}:${notebookId || ''}`
    const scope = normalizeChatScope({ document: documentId, notebook: notebookId }, settings.locale)

    if (wantsFreshSession) {
      await waitForSessionLoad()
      await chat.newChat(model.value, {
        title: scopeSessionTitle(scope, typeof title === 'string' ? title : '', settings.locale),
        welcome: scopeWelcomeMessage(scope, settings.locale),
        ...scopeSendOptions(scope),
      })
      await router.replace({ path: '/chat', query: buildChatScopeQuery(scope) })
      if (typeof ask !== 'string' || !ask.trim()) return
    }

    if (typeof ask !== 'string' || !ask.trim()) return
    if (consumedAsk.value === askKey) return
    consumedAsk.value = askKey
    if (!wantsFreshSession) {
      await router.replace({ path: '/chat', query: buildChatScopeQuery(scope) })
    }
    await handleSend(ask, { documentId, notebookId })
  },
  { immediate: true },
)

async function waitForSessionLoad() {
  for (let i = 0; i < 100 && chat.sessLoading; i++) {
    await new Promise(resolve => setTimeout(resolve, 25))
  }
}

async function clearScope() {
  const wasPersistedScope = activeSessionScope.value.type !== 'global'
  await router.replace({ path: '/chat' })
  if (wasPersistedScope) {
    await chat.newChat(model.value)
  }
}

async function handleRegenerate() {
  // Re-ask the last user question: a fresh answer (new retrieval, new docs).
  // The superseded answer is dropped from the local view (server history
  // keeps it — regenerate is a client-side view operation).
  chat.dropLastAgentMessage()
  for (let i = chat.messages.length - 1; i >= 0; i--) {
    if (chat.messages[i].role === 'user' && chat.messages[i].text?.trim()) {
      await handleSend(chat.messages[i].text.trim())
      return
    }
  }
}

async function handleSend(query, options = {}) {
  if (!settings.isConnected) {
    toast.value = { msg: t('documents.apiKeyRequired'), type: 'error' }
    return
  }
  try {
    const scopeOptions = scopeSendOptions(displayScope.value)
    const sendOptions = {
      documentId: options.documentId || scopeOptions.documentId,
      notebookId: options.notebookId || scopeOptions.notebookId,
    }
    const approval = sendOptions.documentId || sendOptions.notebookId ? false : requireApproval.value
    await chat.sendMessage(query, model.value, approval, sendOptions)
  } catch {}
}

// workflowId is carried by the hitl message itself and emitted from the card
async function approveHitl(workflowId) {
  await chat.approveHitl(workflowId)
  toast.value = { msg: t('chat.answerApproved'), type: 'success' }
}

async function rejectHitl(workflowId) {
  await chat.rejectHitl(workflowId)
  toast.value = { msg: t('chat.answerRejected'), type: 'error' }
}
</script>

<style scoped>
.chat-history-resizer {
  position: relative;
  z-index: 3;
  flex: 0 0 10px;
  margin-right: -5px;
  margin-left: -5px;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: col-resize;
  outline: none;
  touch-action: none;
}
.chat-history-resizer::before {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 50%;
  width: 1px;
  background: var(--border);
  content: '';
  transform: translateX(-50%);
  transition: background 0.12s, box-shadow 0.12s;
}
.chat-history-resizer:hover::before,
.chat-history-resizer:focus-visible::before,
.chat-layout.is-resizing-history .chat-history-resizer::before {
  background: var(--accent);
  box-shadow: 0 0 0 1px color-mix(in oklch, var(--accent) 35%, transparent);
}
.chat-layout.is-resizing-history {
  user-select: none;
}
</style>
