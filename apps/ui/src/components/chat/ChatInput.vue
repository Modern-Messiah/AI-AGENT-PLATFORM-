<template>
  <div class="chat-input-area">
    <div class="input-box">
      <textarea
        class="chat-textarea"
        ref="textareaRef"
        :placeholder="settings.isConnected ? 'Задайте вопрос агенту…' : 'Настройте API-ключ в боковой панели…'"
        :disabled="!settings.isConnected"
        v-model="input"
        rows="1"
        @input="resize"
        @keydown.enter.exact.prevent="send"
      ></textarea>
      <button class="send-btn"
              :disabled="!input.trim() || tooLong || chat.loading || !settings.isConnected"
              @click="send">
        <AppIcon name="send" />
      </button>
    </div>
    <div style="display: flex; gap: 12px; margin-top: 8px; font-size: 11px; color: var(--muted)">
      <span>Enter — отправить · Shift+Enter — новая строка</span>
      <span v-if="tooLong" style="color: var(--red)">{{ input.length }} / {{ MAX_QUERY_CHARS }}</span>
      <span v-if="requireApproval" style="color: var(--yellow)">⚠ HITL on — ответы требуют подтверждения</span>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useSettingsStore } from '@/stores/settings'
import AppIcon from '@/components/AppIcon.vue'

const props = defineProps({
  model: String,
  requireApproval: Boolean
})
const emit = defineEmits(['send'])

const chat = useChatStore()
const settings = useSettingsStore()
const input = ref('')
const textareaRef = ref(null)
const MAX_QUERY_CHARS = 12000
const tooLong = computed(() => input.value.length > MAX_QUERY_CHARS)

function resize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

function send() {
  const q = input.value.trim()
  if (!q || tooLong.value || chat.loading || !settings.isConnected) return
  input.value = ''
  if (textareaRef.value) textareaRef.value.style.height = 'auto'
  emit('send', q)
}
</script>
