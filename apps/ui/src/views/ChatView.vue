<template>
  <div class="chat-layout">
    <ChatHistory :model="model" @toast="setToast" />

    <div class="chat-main">
      <ChatToolbar v-model:model="model" v-model:requireApproval="requireApproval" />
      <div v-if="currentScope.type !== 'global'" class="scope-banner">
        <div>
          <strong>{{ currentScope.title }}</strong>
          <span>{{ currentScope.description }}</span>
        </div>
        <div class="scope-actions">
          <RouterLink class="btn btn-ghost btn-sm" :to="currentScope.backPath">
            {{ currentScope.backLabel }}
          </RouterLink>
          <button class="btn btn-ghost btn-sm" type="button" @click="clearScope">
            Обычный чат
          </button>
        </div>
      </div>
      <ChatMessages @approve="approveHitl" @reject="rejectHitl" />
      <ChatInput :model="model" :require-approval="requireApproval" @send="handleSend" />
    </div>

    <AppToast v-if="toast" v-bind="toast" @done="toast = null" />
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChatStore } from '@/stores/chat'
import { useSettingsStore } from '@/stores/settings'
import {
  buildChatScopeQuery,
  normalizeChatScope,
  scopeSessionTitle,
  scopeSendOptions,
  scopeWelcomeMessage,
} from '@/utils/chatScope'
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
const currentScope = computed(() => normalizeChatScope(route.query))

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
    const scope = normalizeChatScope({ document: documentId, notebook: notebookId })

    if (wantsFreshSession) {
      await waitForSessionLoad()
      await chat.newChat(model.value, {
        title: scopeSessionTitle(scope, typeof title === 'string' ? title : ''),
        welcome: scopeWelcomeMessage(scope),
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
  await router.replace({ path: '/chat' })
}

async function handleSend(query, options = {}) {
  if (!settings.isConnected) {
    toast.value = { msg: 'Задайте X-API-Key в настройках', type: 'error' }
    return
  }
  try {
    const scopeOptions = scopeSendOptions(currentScope.value)
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
  toast.value = { msg: 'Ответ подтверждён', type: 'success' }
}

async function rejectHitl(workflowId) {
  await chat.rejectHitl(workflowId)
  toast.value = { msg: 'Ответ отклонён', type: 'error' }
}
</script>

<style scoped>
.scope-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin: 12px 16px 0;
  padding: 12px 14px;
  border: 1px solid color-mix(in oklch, var(--purple) 42%, var(--border));
  border-radius: 14px;
  background: color-mix(in oklch, var(--purple) 9%, var(--s1));
}
.scope-banner strong,
.scope-banner span {
  display: block;
}
.scope-banner strong {
  color: var(--text);
  font-size: 13px;
}
.scope-banner span {
  margin-top: 3px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.4;
}
.scope-actions {
  display: flex;
  flex-shrink: 0;
  gap: 8px;
}
@media (max-width: 760px) {
  .scope-banner {
    align-items: stretch;
    flex-direction: column;
  }
  .scope-actions {
    flex-wrap: wrap;
  }
}
</style>
