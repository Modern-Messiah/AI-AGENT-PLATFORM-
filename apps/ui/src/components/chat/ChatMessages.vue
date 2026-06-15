<template>
  <div class="chat-messages" ref="containerRef">
    <template v-for="msg in chat.messages" :key="msg.id">
      <!-- HITL approval card -->
      <div v-if="msg.role === 'hitl'" class="hitl-card">
        <!-- waiting for human decision -->
        <template v-if="!msg.status">
          <div class="hitl-icon">⏳</div>
          <div>
            <div class="hitl-title">{{ t('chat.waitingApproval') }}</div>
            <div class="hitl-desc">{{ t('chat.approvalDescription') }}</div>
            <div class="hitl-actions">
              <button class="btn btn-success btn-sm" @click="$emit('approve', msg.workflowId)">{{ t('chat.approve') }}</button>
              <button class="btn btn-danger btn-sm" @click="$emit('reject', msg.workflowId)">{{ t('chat.reject') }}</button>
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
            <div class="hitl-title">{{ t('chat.approvedWaiting') }}</div>
          </div>
        </template>
        <!-- took longer than 5 minutes -->
        <template v-else-if="msg.status === 'timeout'">
          <div class="hitl-icon">⚠️</div>
          <div>
            <div class="hitl-title" style="color:var(--yellow)">{{ t('chat.workflowTimeout') }}</div>
            <div class="hitl-desc">{{ t('chat.workflowTimeoutHint') }}</div>
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
            <span v-if="msg.cached" class="badge badge-purple" style="font-size: 10px; padding: 1px 6px">{{ t('chat.cacheHit') }}</span>
          </div>
          <div v-if="msg.sources && msg.sources.length" class="sources-list">
            <template v-for="(group, index) in citationGroups(msg)" :key="citationGroupKey(msg, group, index)">
              <button
                v-if="group.type === 'document'"
                :class="[
                  'source-chip',
                  'source-chip-button',
                  {
                    active: openCitationKey === citationGroupKey(msg, group, index),
                    referenced: citationGroupIsReferenced(msg.text, group),
                  },
                ]"
                type="button"
                @click="toggleCitationGroup(msg, group, index)"
              >
                <span class="source-chip-index">{{ citationGroupMarker(group) }}</span>
                <span class="source-chip-name">{{ group.filename }}</span>
                <span class="source-chip-separator">·</span>
                <span class="source-chip-location">{{ citationLabel(group) }}</span>
              </button>
              <span v-else class="source-chip">📄 {{ group.label }}</span>
            </template>
          </div>
          <div v-if="expandedCitationGroup(msg)" class="citation-panel">
            <div class="citation-panel-header">
              <div class="citation-heading">
                <div class="citation-kicker">{{ t('chat.source', { marker: citationGroupMarker(expandedCitationGroup(msg)) }) }}</div>
                <div class="citation-title">
                  {{ expandedCitationGroup(msg).filename }}
                </div>
                <div class="citation-location">{{ citationLabel(expandedCitationGroup(msg)) }}</div>
              </div>
              <span class="citation-score">
                {{ scoreLabel(expandedCitationGroup(msg).citations[0]) }}
              </span>
            </div>
            <div class="citation-excerpt-wrap">
              <div class="citation-excerpt-label">{{ t('chat.foundFragments') }}</div>
              <div class="citation-fragments">
                <article
                  v-for="citation in expandedCitationGroup(msg).citations"
                  :key="citation.chunk_id || citation.id"
                  class="citation-fragment"
                >
                  <div class="citation-fragment-header">
                    <div>
                      <div class="citation-fragment-title">
                        [{{ citation.id }}] {{ locationLabel(citation) }}
                      </div>
                    </div>
                    <span class="citation-score citation-score-inline">
                      {{ scoreLabel(citation) }}
                    </span>
                  </div>
                  <ProtectedAssetImage
                    v-if="hasAssetPreview(citation) && isFirstAssetCitation(expandedCitationGroup(msg), citation)"
                    class="citation-preview"
                    :document-id="citation.document_id"
                    :asset-id="citation.asset_id"
                    :page-number="citation.page"
                    :alt="`${citation.filename} · ${locationLabel(citation)}`"
                    compact
                  />
                  <div class="citation-excerpt">{{ citation.excerpt }}</div>
                  <RouterLink
                    class="btn btn-ghost btn-sm citation-open"
                    :to="buildCitationRoute(citation)"
                  >
                    {{ t('chat.openFragment') }}
                  </RouterLink>
                </article>
              </div>
            </div>
            <div class="citation-actions">
              <RouterLink
                class="btn btn-ghost btn-sm citation-open"
                :to="buildCitationDocumentRoute(expandedCitationGroup(msg))"
              >
                {{ t('chat.openDocument') }}
              </RouterLink>
            </div>
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
import { useI18n } from '@/composables/useI18n'
import AppIcon from '@/components/AppIcon.vue'
import ProtectedAssetImage from '@/components/ProtectedAssetImage.vue'
import {
  buildCitationDocumentRoute,
  buildCitationRoute,
  citationGroupIsReferenced,
  citationGroupLabel,
  citationGroupMarker,
  groupCitationsByDocument,
  hasAssetPreview,
  sourceLocation,
  sourceScoreLabel,
} from '@/utils/citations'

defineEmits(['approve', 'reject'])

const chat = useChatStore()
const { locale, t } = useI18n()
const containerRef = ref(null)
const openCitationKey = ref(null)

function citationGroups(msg) {
  return groupCitationsByDocument(msg.sources || [])
}

function citationLabel(group) {
  return citationGroupLabel(group, locale.value)
}

function locationLabel(citation) {
  return sourceLocation(citation, locale.value)
}

function scoreLabel(citation) {
  return sourceScoreLabel(citation, locale.value)
}

function citationGroupKey(msg, group, index) {
  return `${msg.id}:${group.key || index}`
}

function toggleCitationGroup(msg, group, index) {
  const key = citationGroupKey(msg, group, index)
  openCitationKey.value = openCitationKey.value === key ? null : key
}

function expandedCitationGroup(msg) {
  if (!openCitationKey.value) return null
  return citationGroups(msg).find((group, index) => (
    group.type === 'document'
    && citationGroupKey(msg, group, index) === openCitationKey.value
  )) || null
}

function isFirstAssetCitation(group, citation) {
  if (!group || !citation?.asset_id) return false
  return group.citations.find(item => item.asset_id === citation.asset_id) === citation
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
  display: inline-flex;
  align-items: center;
  gap: 5px;
  max-width: min(100%, 360px);
  padding: 5px 10px;
  border: 1px solid color-mix(in oklch, var(--border2) 82%, transparent);
  border-radius: 999px;
  background: color-mix(in oklch, var(--s2) 88%, transparent);
  color: var(--muted2);
  cursor: pointer;
  font-family: var(--font);
  font-size: 11.5px;
  line-height: 1.2;
  text-align: left;
  transition: border-color 0.12s, background 0.12s, color 0.12s, box-shadow 0.12s;
}
.source-chip-button:hover,
.source-chip-button.active {
  border-color: color-mix(in oklch, var(--accent) 72%, var(--border));
  background: color-mix(in oklch, var(--accent) 13%, var(--s2));
  color: var(--text);
  box-shadow: 0 0 0 1px color-mix(in oklch, var(--accent) 10%, transparent);
}
.source-chip-button.referenced {
  border-color: color-mix(in oklch, var(--accent) 48%, var(--border));
  background: color-mix(in oklch, var(--accent) 9%, var(--s2));
}
.source-chip-index {
  color: var(--accent);
  flex-shrink: 0;
  font-family: var(--mono);
  font-weight: 700;
}
.source-chip-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.source-chip-separator,
.source-chip-location {
  color: var(--muted);
  flex-shrink: 0;
}
.source-chip-location {
  font-family: var(--mono);
  font-size: 10.5px;
}
.citation-panel {
  margin-top: 10px;
  width: min(100%, 760px);
  overflow: hidden;
  border: 1px solid color-mix(in oklch, var(--border2) 88%, transparent);
  border-radius: 14px;
  background:
    linear-gradient(135deg, color-mix(in oklch, var(--accent) 7%, transparent), transparent 42%),
    var(--s2);
  box-shadow: 0 14px 36px var(--shadow-soft);
}
.citation-panel-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
  background: color-mix(in oklch, var(--s3) 58%, transparent);
}
.citation-heading {
  min-width: 0;
}
.citation-kicker {
  margin-bottom: 4px;
  color: var(--accent);
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.citation-title {
  color: var(--text);
  font-size: 13.5px;
  font-weight: 700;
  line-height: 1.35;
  word-break: break-word;
}
.citation-location {
  margin-top: 4px;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 11px;
}
.citation-score {
  margin-top: 1px;
  padding: 4px 9px;
  border: 1px solid color-mix(in oklch, var(--green) 25%, transparent);
  border-radius: 999px;
  background: color-mix(in oklch, var(--green) 10%, transparent);
  color: var(--green);
  flex-shrink: 0;
  font-family: var(--mono);
  font-size: 10.5px;
  white-space: nowrap;
}
.citation-excerpt-wrap {
  padding: 14px 16px 12px;
}
.citation-excerpt-label {
  margin-bottom: 8px;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.07em;
  text-transform: uppercase;
}
.citation-fragments {
  display: grid;
  gap: 10px;
  max-height: 430px;
  overflow-y: auto;
  padding-right: 4px;
  overscroll-behavior: contain;
}
.citation-fragment {
  padding: 12px;
  border: 1px solid color-mix(in oklch, var(--border2) 82%, transparent);
  border-radius: 12px;
  background: color-mix(in oklch, var(--s1) 70%, transparent);
}
.citation-fragment-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 9px;
}
.citation-fragment-title {
  color: var(--text);
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 700;
}
.citation-score-inline {
  margin-top: 0;
  font-size: 10px;
}
.citation-excerpt {
  color: var(--text);
  padding-left: 12px;
  border-left: 2px solid color-mix(in oklch, var(--accent) 45%, var(--border));
  font-size: 13px;
  line-height: 1.65;
  white-space: pre-wrap;
}
.citation-preview {
  margin-bottom: 10px;
}
.citation-fragment .citation-open {
  margin-top: 10px;
}
.citation-actions {
  display: flex;
  justify-content: flex-end;
  padding: 0 16px 14px;
}
.citation-open {
  margin-top: 0;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0; }
}
</style>
