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
          <div class="session-title">{{ s.title }}</div>
          <div class="session-meta">{{ s.updated_at ? new Date(s.updated_at).toLocaleDateString('ru') : '' }}</div>
        </div>
        <button class="btn btn-ghost btn-sm del-btn" style="padding: 2px 5px; flex-shrink: 0"
                @click.stop="handleDelete(s.id)" title="Удалить">✕</button>
      </div>

      <div v-if="settings.isConnected && chat.sessions.length === 0 && !chat.sessLoading"
           style="padding: 12px 16px; font-size: 12px; color: var(--muted)">
        Нет сессий — нажми New
      </div>
    </div>
  </div>
</template>

<script setup>
import { useChatStore } from '@/stores/chat'
import { useSettingsStore } from '@/stores/settings'
import AppIcon from '@/components/AppIcon.vue'

const props = defineProps({ model: String })
const emit = defineEmits(['toast'])

const chat = useChatStore()
const settings = useSettingsStore()

async function handleNew() {
  if (!settings.isConnected) return
  try {
    await chat.newChat(props.model)
  } catch (e) {
    emit('toast', { msg: `Ошибка: ${e.message}`, type: 'error' })
  }
}

async function handleDelete(id) {
  const sess = chat.sessions.find(s => s.id === id)
  if (!confirm(`Удалить сессию "${sess?.title || id}"?\nВсе сообщения будут удалены.`)) return
  try {
    await chat.deleteSession(id)
  } catch (e) {
    emit('toast', { msg: `Ошибка: ${e.message}`, type: 'error' })
  }
}
</script>
