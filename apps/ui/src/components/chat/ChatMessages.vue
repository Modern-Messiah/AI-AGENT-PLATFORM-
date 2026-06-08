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
            {{ msg.text }}<span v-if="msg.streaming" class="streaming-cursor">▋</span>
          </div>
          <div class="msg-meta">
            <span class="msg-time">{{ msg.time }}</span>
            <span v-if="msg.cached" class="badge badge-purple" style="font-size: 10px; padding: 1px 6px">cache hit</span>
          </div>
          <div v-if="msg.sources && msg.sources.length" class="sources-list">
            <template v-for="(source, index) in msg.sources" :key="sourceKey(msg, source, index)">
              <button
                v-if="isStructuredCitation(source)"
                :class="[
                  'source-chip',
                  'source-chip-button',
                  {
                    active: openCitationKey === sourceKey(msg, source, index),
                    referenced: citationIsReferenced(msg.text, source),
                  },
                ]"
                type="button"
                @click="toggleCitation(msg, source, index)"
              >
                {{ sourceLabel(source) }}
              </button>
              <span v-else class="source-chip">📄 {{ source }}</span>
            </template>
          </div>
          <div v-if="expandedCitation(msg)" class="citation-panel">
            <div class="citation-panel-header">
              <div>
                <div class="citation-title">
                  [{{ expandedCitation(msg).id }}] {{ expandedCitation(msg).filename }}
                </div>
                <div class="citation-location">{{ sourceLocation(expandedCitation(msg)) }}</div>
              </div>
              <span class="citation-score">
                score {{ Number(expandedCitation(msg).score || 0).toFixed(3) }}
              </span>
            </div>
            <div class="citation-excerpt">{{ expandedCitation(msg).excerpt }}</div>
            <RouterLink
              class="btn btn-ghost btn-sm citation-open"
              :to="buildCitationRoute(expandedCitation(msg))"
            >
              Открыть источник
            </RouterLink>
          </div>
        </div>
      </div>
    </template>

    <!-- Typing indicator -->
    <div v-if="chat.isActiveSessionLoading()" class="msg agent">
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
import {
  buildCitationRoute,
  citationIsReferenced,
  isStructuredCitation,
  sourceLabel,
  sourceLocation,
} from '@/utils/citations'

defineEmits(['approve', 'reject'])

const chat = useChatStore()
const containerRef = ref(null)
const openCitationKey = ref(null)

function sourceKey(msg, source, index) {
  if (isStructuredCitation(source)) return `${msg.id}:${source.id}:${source.chunk_id}`
  return `${msg.id}:legacy:${index}:${source}`
}

function toggleCitation(msg, source, index) {
  const key = sourceKey(msg, source, index)
  openCitationKey.value = openCitationKey.value === key ? null : key
}

function expandedCitation(msg) {
  if (!openCitationKey.value) return null
  return (msg.sources || []).find((source, index) => (
    isStructuredCitation(source)
    && sourceKey(msg, source, index) === openCitationKey.value
  )) || null
}

async function scrollToBottom() {
  await nextTick()
  if (containerRef.value) {
    containerRef.value.scrollTop = containerRef.value.scrollHeight
  }
}

watch([() => chat.messages.length, () => chat.isActiveSessionLoading(), () => chat.streamTick], scrollToBottom)
</script>

<style scoped>
.streaming-cursor {
  display: inline-block;
  margin-left: 1px;
  animation: blink 0.8s step-end infinite;
}
.source-chip-button {
  border: 1px solid var(--border);
  cursor: pointer;
  font: inherit;
  text-align: left;
}
.source-chip-button:hover,
.source-chip-button.active {
  border-color: var(--purple);
  color: var(--text);
}
.source-chip-button.referenced {
  background: color-mix(in srgb, var(--purple) 12%, transparent);
}
.citation-panel {
  margin-top: 8px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--s2);
}
.citation-panel-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}
.citation-title {
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
  word-break: break-word;
}
.citation-location,
.citation-score {
  margin-top: 3px;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10px;
}
.citation-score {
  white-space: nowrap;
}
.citation-excerpt {
  margin-top: 10px;
  color: var(--text);
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
}
.citation-open {
  margin-top: 10px;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0; }
}
</style>
