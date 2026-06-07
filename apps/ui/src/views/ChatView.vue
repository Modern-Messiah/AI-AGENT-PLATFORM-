<template>
  <div class="chat-layout">
    <ChatHistory :model="model" @toast="setToast" />

    <div class="chat-main">
      <ChatToolbar v-model:model="model" v-model:requireApproval="requireApproval" />
      <ChatMessages @approve="approveHitl" @reject="rejectHitl" />
      <ChatInput :model="model" :require-approval="requireApproval" @send="handleSend" />
    </div>

    <AppToast v-if="toast" v-bind="toast" @done="toast = null" />
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChatStore } from '@/stores/chat'
import { useSettingsStore } from '@/stores/settings'
import ChatHistory from '@/components/chat/ChatHistory.vue'
import ChatToolbar from '@/components/chat/ChatToolbar.vue'
import ChatMessages from '@/components/chat/ChatMessages.vue'
import ChatInput from '@/components/chat/ChatInput.vue'
import AppToast from '@/components/AppToast.vue'

const chat = useChatStore()
const settings = useSettingsStore()
const route = useRoute()
const router = useRouter()

const model = ref('moonshot/kimi-k2.6')
const requireApproval = ref(false)
const toast = ref(null)
const consumedAsk = ref('')

function setToast(t) { toast.value = t }

watch(() => settings.apiKey, async (key) => {
  if (!key) { chat.reset(); return }
  if (chat.loadedKey === key && (chat.sessions.length || chat.activeId)) return
  try { await chat.loadSessions(key) } catch {}
}, { immediate: true })

watch(
  [
    () => route.query.ask,
    () => route.query.document,
    () => route.query.notebook,
    () => settings.isConnected,
  ],
  async ([ask, document, notebook, connected]) => {
    if (!connected || typeof ask !== 'string' || !ask.trim()) return
    const documentId = typeof document === 'string' ? document : null
    const notebookId = typeof notebook === 'string' ? notebook : null
    const askKey = `${ask}:${documentId || ''}:${notebookId || ''}`
    if (consumedAsk.value === askKey) return
    consumedAsk.value = askKey
    await router.replace({ path: '/chat' })
    await handleSend(ask, { documentId, notebookId })
  },
  { immediate: true },
)

async function handleSend(query, options = {}) {
  if (!settings.isConnected) {
    toast.value = { msg: 'Задайте X-API-Key в настройках', type: 'error' }
    return
  }
  try {
    const approval = options.documentId || options.notebookId ? false : requireApproval.value
    await chat.sendMessage(query, model.value, approval, options)
  } catch {}
}

// workflowId is carried by the hitl message itself and emitted from the card
async function approveHitl(workflowId) {
  await chat.approveHitl(workflowId)
  toast.value = { msg: 'Ответ подтверждён', type: 'success' }
}

async function rejectHitl(workflowId) {
  await chat.rejectHitl(workflowId)
  toast.value = { msg: 'Ответ отклонён', type: 'error' }
}
</script>
