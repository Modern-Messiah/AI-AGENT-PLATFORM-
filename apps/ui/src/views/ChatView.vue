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
import { useChatStore } from '@/stores/chat'
import { useSettingsStore } from '@/stores/settings'
import ChatHistory from '@/components/chat/ChatHistory.vue'
import ChatToolbar from '@/components/chat/ChatToolbar.vue'
import ChatMessages from '@/components/chat/ChatMessages.vue'
import ChatInput from '@/components/chat/ChatInput.vue'
import AppToast from '@/components/AppToast.vue'

const chat = useChatStore()
const settings = useSettingsStore()

const model = ref('moonshot/kimi-k2.6')
const requireApproval = ref(false)
const toast = ref(null)
const pendingHitl = ref(null)

function setToast(t) { toast.value = t }

watch(() => settings.apiKey, async (key) => {
  if (!key) { chat.sessions = []; chat.activeId = null; chat.messages = []; return }
  try { await chat.loadSessions() } catch {}
}, { immediate: true })

async function handleSend(query) {
  if (!settings.isConnected) {
    toast.value = { msg: 'Задайте X-API-Key в настройках', type: 'error' }
    return
  }
  try {
    const agentMsg = await chat.sendMessage(query, model.value, requireApproval.value)
    if (requireApproval.value && agentMsg) {
      pendingHitl.value = agentMsg
    }
  } catch {}
}

function approveHitl() {
  if (!pendingHitl.value) return
  chat.approveHitl(pendingHitl.value)
  pendingHitl.value = null
  toast.value = { msg: 'Ответ подтверждён', type: 'success' }
}

function rejectHitl() {
  chat.rejectHitl()
  pendingHitl.value = null
  toast.value = { msg: 'Ответ отклонён', type: 'error' }
}
</script>
