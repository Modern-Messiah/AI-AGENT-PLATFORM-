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

watch([() => route.query.ask, () => settings.isConnected], async ([ask, connected]) => {
  if (!connected || typeof ask !== 'string' || !ask.trim() || consumedAsk.value === ask) return
  consumedAsk.value = ask
  await router.replace({ path: '/chat' })
  await handleSend(ask)
}, { immediate: true })

async function handleSend(query) {
  if (!settings.isConnected) {
    toast.value = { msg: 'Задайте X-API-Key в настройках', type: 'error' }
    return
  }
  try {
    await chat.sendMessage(query, model.value, requireApproval.value)
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
