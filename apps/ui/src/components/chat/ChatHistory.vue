<template>
  <div class="chat-history">
    <div class="chat-history-header">
      <span>Сессии</span>
      <button class="btn btn-ghost btn-sm" style="padding: 3px 7px; gap: 4px" @click="handleNew">
        <AppIcon name="plus" :size="11" /> New
      </button>
    </div>
    <div class="chat-sessions">
      <div v-if="chat.sessLoading && chat.sessions.length === 0"
           style="padding: 12px 16px; font-size: 12px; color: var(--muted)">Загрузка…</div>
      <div v-else-if="!settings.isConnected"
           style="padding: 12px 16px; font-size: 12px; color: var(--muted)">Нет API-ключа</div>

      <div v-for="s in chat.sessions" :key="s.id"
           class="chat-session-item"
           :class="{ active: chat.activeId === s.id }"
           @click="chat.selectSession(s.id)">
        <div style="flex: 1; min-width: 0">
          <div class="session-title">{{ sessionTitle(s) }}</div>
          <div v-if="sessionMeta(s)" class="session-scope">
            <span :class="['session-scope-badge', `is-${sessionMeta(s).type}`]">
              {{ sessionMeta(s).badge }}
            </span>
            <span class="session-scope-copy">{{ sessionMeta(s).subtitle }}</span>
          </div>
          <div class="session-meta">{{ s.updated_at ? new Date(s.updated_at).toLocaleDateString('ru') : '' }}</div>
        </div>
        <button class="btn btn-ghost btn-sm del-btn" style="padding: 2px 5px; flex-shrink: 0"
                @click.stop="askDelete(s)" title="Удалить">
          <AppIcon name="trash" :size="11" />
        </button>
      </div>

      <div v-if="settings.isConnected && chat.sessions.length === 0 && !chat.sessLoading"
           style="padding: 12px 16px; font-size: 12px; color: var(--muted)">
        Нет сессий — нажми New
      </div>
    </div>
  </div>

  <ConfirmModal
    v-if="confirmId"
    :title="confirmTitle"
    @confirm="doDelete"
    @cancel="cancelDelete"
  />
</template>

<script setup>
import { ref } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useSettingsStore } from '@/stores/settings'
import AppIcon from '@/components/AppIcon.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'
import { sessionScopeMeta } from '@/utils/chatScope'

const props = defineProps({ model: String })
const emit = defineEmits(['toast'])

const chat = useChatStore()
const settings = useSettingsStore()

const confirmId    = ref(null)
const confirmTitle = ref('')

function sessionMeta(sess) {
  return sessionScopeMeta(sess?.title)
}

function sessionTitle(sess) {
  return sessionMeta(sess)?.title || sess?.title || 'New Chat'
}

function askDelete(sess) {
  confirmTitle.value = sess.title || sess.id
  confirmId.value    = sess.id
}

function cancelDelete() {
  confirmId.value    = null
  confirmTitle.value = ''
}

async function doDelete() {
  const id = confirmId.value
  confirmId.value = null
  try {
    await chat.deleteSession(id)
  } catch (e) {
    emit('toast', { msg: `Ошибка: ${e.message}`, type: 'error' })
  }
}

async function handleNew() {
  if (!settings.isConnected) return
  try {
    await chat.newChat(props.model)
  } catch (e) {
    emit('toast', { msg: `Ошибка: ${e.message}`, type: 'error' })
  }
}
</script>

<style scoped>
.session-scope {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
  min-width: 0;
}
.session-scope-badge {
  flex-shrink: 0;
  padding: 2px 6px;
  border: 1px solid color-mix(in oklch, var(--accent) 35%, transparent);
  border-radius: 999px;
  color: var(--accent);
  font-family: var(--mono);
  font-size: 9px;
  line-height: 1.2;
}
.session-scope-badge.is-document {
  border-color: color-mix(in oklch, var(--purple) 38%, transparent);
  color: var(--purple);
}
.session-scope-copy {
  min-width: 0;
  overflow: hidden;
  color: var(--muted);
  font-size: 10.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
