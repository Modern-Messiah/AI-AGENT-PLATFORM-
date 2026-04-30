<template>
  <div class="chat-messages" ref="containerRef">
    <template v-for="msg in chat.messages" :key="msg.id">
      <!-- HITL approval card -->
      <div v-if="msg.role === 'hitl'" class="hitl-card">
        <!-- waiting for human decision -->
        <template v-if="!msg.status">
          <div class="hitl-icon">⏳</div>
          <div>
            <div class="hitl-title">Ожидает подтверждения</div>
            <div class="hitl-desc">Агент сформировал ответ. Подтвердите или отклоните перед показом.</div>
            <div class="hitl-actions">
              <button class="btn btn-success btn-sm" @click="$emit('approve', msg.workflowId)">✓ Approve</button>
              <button class="btn btn-danger btn-sm" @click="$emit('reject', msg.workflowId)">✕ Reject</button>
            </div>
          </div>
        </template>
        <!-- approved — waiting for workflow to return the answer -->
        <template v-else-if="msg.status === 'polling'">
          <div class="hitl-icon">
            <div class="typing-bubble" style="background:transparent;padding:0">
              <div class="typing-dot"></div>
              <div class="typing-dot"></div>
              <div class="typing-dot"></div>
            </div>
          </div>
          <div>
            <div class="hitl-title">Подтверждено — ждём ответа агента…</div>
          </div>
        </template>
        <!-- took longer than 5 minutes -->
        <template v-else-if="msg.status === 'timeout'">
          <div class="hitl-icon">⚠️</div>
          <div>
            <div class="hitl-title" style="color:var(--yellow)">Workflow не завершился за 5 минут</div>
            <div class="hitl-desc">Проверьте Temporal UI или попробуйте ещё раз.</div>
          </div>
        </template>
      </div>

      <!-- Regular message -->
      <div v-else :class="['msg', msg.role]">
        <div class="msg-avatar"><AppIcon :name="msg.role" /></div>
        <div class="msg-body">
          <div class="msg-bubble" :style="msg.error ? { borderColor: 'var(--red)' } : {}">
            {{ msg.text }}
          </div>
          <div class="msg-meta">
            <span class="msg-time">{{ msg.time }}</span>
            <span v-if="msg.cached" class="badge badge-purple" style="font-size: 10px; padding: 1px 6px">cache hit</span>
          </div>
          <div v-if="msg.sources && msg.sources.length" class="sources-list">
            <span v-for="s in msg.sources" :key="s" class="source-chip">📄 {{ s.slice(0, 12) }}…</span>
          </div>
        </div>
      </div>
    </template>

    <!-- Typing indicator -->
    <div v-if="chat.loading" class="msg agent">
      <div class="msg-avatar"><AppIcon name="agent" /></div>
      <div class="msg-body">
        <div class="typing-bubble">
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import { useChatStore } from '@/stores/chat'
import AppIcon from '@/components/AppIcon.vue'

defineEmits(['approve', 'reject'])

const chat = useChatStore()
const containerRef = ref(null)

async function scrollToBottom() {
  await nextTick()
  if (containerRef.value) {
    containerRef.value.scrollTop = containerRef.value.scrollHeight
  }
}

watch([() => chat.messages.length, () => chat.loading], scrollToBottom)
</script>
