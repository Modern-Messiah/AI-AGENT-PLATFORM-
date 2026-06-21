<template>
  <div class="screen-body document-detail">
    <div class="detail-hero">
      <div>
        <button class="back-link" type="button" @click="router.push('/documents')">
          {{ t('documentDetail.back') }}
        </button>
        <div class="detail-eyebrow">{{ t('documentDetail.eyebrow') }}</div>
        <h1>{{ normalized?.name || t('documentDetail.fallbackTitle') }}</h1>
        <p>{{ t('documentDetail.description') }}</p>
      </div>
      <div v-if="normalized" class="detail-status">
        <StatusBadge :status="normalized.status" />
        <span>{{ normalized.size }}</span>
        <span>{{ normalized.createdLabel }}</span>
        <div v-if="normalized.totalPages > 0" class="detail-progress">
          <span>
            {{ t('documents.pageProgress', {
              processed: normalized.processedPages,
              total: normalized.totalPages,
            }) }}
          </span>
          <div class="progress">
            <div class="progress-fill" :style="{ width: normalized.progressPct + '%' }"></div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="loading" class="card">
      <div class="empty">
        <div class="spinner"></div>
        <div class="empty-title">{{ t('documentDetail.loading') }}</div>
      </div>
    </div>

    <div v-else-if="error" class="card">
      <div class="empty">
        <div class="empty-title">{{ t('documentDetail.openError') }}</div>
        <div class="empty-sub">{{ error }}</div>
      </div>
    </div>

    <template v-else-if="normalized">
      <div class="detail-grid">
        <div class="card">
          <div class="card-header">
            <div>
              <div class="card-title">{{ t('documentDetail.inside') }}</div>
              <div class="card-sub">{{ t('documentDetail.summarySub') }}</div>
            </div>
          </div>
          <div class="detail-card-body">
            <p v-if="normalized.summary" class="summary-text">{{ normalized.summary }}</p>
            <div v-else class="muted-block">
              {{ t('documentDetail.summaryEmpty') }}
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-header">
            <div>
              <div class="card-title">{{ t('documentDetail.askTitle') }}</div>
              <div class="card-sub">{{ t('documentDetail.askSub') }}</div>
            </div>
          </div>
          <div class="detail-card-body">
            <div v-if="normalized.suggestedQuestions.length" class="detail-questions">
              <button
                v-for="question in normalized.suggestedQuestions"
                :key="question"
                class="question-chip"
                type="button"
                @click="askQuestion(question)"
              >
                {{ question }}
              </button>
            </div>
            <button
              class="btn btn-primary ask-main"
              type="button"
              :disabled="!canOpenDocumentChat"
              @click="openDocumentChat"
            >
              {{ t('documentDetail.openChat') }}
            </button>
            <div v-if="normalized && !canOpenDocumentChat" class="ask-disabled-note">
              {{ t('documentDetail.chatPending') }}
            </div>
          </div>
        </div>
      </div>

      <div v-if="normalized.warnings.length" class="card warnings-card">
        <div class="card-header">
          <div class="card-title">{{ t('documentDetail.warningsTitle') }}</div>
        </div>
        <ul>
          <li v-for="warning in normalized.warnings" :key="warning">{{ warning }}</li>
        </ul>
      </div>

      <div v-if="normalized.sourceType === 'url' && normalized.sourceUrl" class="card source-card">
        <div class="card-header">
          <div>
            <div class="card-title">{{ t('documentDetail.sourceUrlTitle') }}</div>
            <div class="card-sub">
              {{ normalized.sourceCheckedLabel
                ? t('documentDetail.sourceCheckedAt', { date: normalized.sourceCheckedLabel })
                : t('documentDetail.sourceUrlSub') }}
            </div>
          </div>
          <a
            class="btn btn-ghost btn-sm"
            :href="normalized.sourceUrl"
            target="_blank"
            rel="noopener noreferrer"
          >
            {{ t('documentDetail.openOriginal') }}
          </a>
        </div>
        <div class="detail-card-body">
          <a
            class="source-url-link"
            :href="normalized.sourceUrl"
            target="_blank"
            rel="noopener noreferrer"
          >
            {{ normalized.sourceTitle || normalized.sourceUrl }}
          </a>
          <div v-if="normalized.sourceTitle" class="source-url-text">{{ normalized.sourceUrl }}</div>
        </div>
      </div>

      <div class="card chunks-card">
        <div class="card-header">
          <div>
            <div class="card-title">{{ t('documentDetail.chunksTitle') }}</div>
            <div class="card-sub">{{ t('documentDetail.chunksCount', { count: chunks.length }) }}</div>
          </div>
          <button class="btn btn-ghost btn-sm" type="button" @click="loadDocument">
            {{ t('common.refresh') }}
          </button>
        </div>

        <div v-if="chunks.length === 0" class="empty">
          <div class="empty-title">{{ t('documentDetail.noChunks') }}</div>
          <div class="empty-sub">{{ t('documentDetail.noChunksHint') }}</div>
        </div>

        <div v-else class="chunks-list">
          <article
            v-for="chunk in chunks"
            :id="chunkDomId(chunk)"
            :key="chunk.chunk_id"
            :class="['chunk-card', { 'chunk-card-target': isTargetChunk(chunk) }]"
          >
            <div class="chunk-meta">
              <span>#{{ chunk.chunk_index + 1 }}</span>
              <span v-if="chunk.page">{{ t('documentDetail.page', { page: chunk.page }) }}</span>
              <span v-if="isTargetChunk(chunk)">{{ t('documentDetail.selectedSource') }}</span>
            </div>
            <p>{{ chunk.excerpt }}</p>
          </article>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useApi } from '@/composables/useApi'
import { useSettingsStore } from '@/stores/settings'
import { useI18n } from '@/composables/useI18n'
import StatusBadge from '@/components/StatusBadge.vue'
import { buildDocumentChatRoute, buildQuestionRoute, normalizeDocument } from '@/utils/documents'

const route = useRoute()
const router = useRouter()
const { apiFetch } = useApi()
const settings = useSettingsStore()
const { t } = useI18n()

const document = ref(null)
const chunks = ref([])
const loading = ref(false)
const error = ref('')

const documentId = computed(() => String(route.params.id || ''))
const normalized = computed(() => (
  document.value ? normalizeDocument(document.value, settings.locale) : null
))
const canOpenDocumentChat = computed(() => normalized.value?.status === 'done')
const targetChunkId = computed(() => (
  typeof route.query.chunk === 'string' ? route.query.chunk : ''
))

watch([() => settings.apiKey, documentId], loadDocument, { immediate: true })
watch(targetChunkId, () => scrollToTargetChunk())

async function loadDocument() {
  if (!settings.isConnected || !documentId.value) {
    document.value = null
    chunks.value = []
    error.value = settings.isConnected
      ? t('documentDetail.notSelected')
      : t('documents.apiKeyRequired')
    return
  }

  loading.value = true
  error.value = ''
  try {
    const [doc, chunkRows] = await Promise.all([
      apiFetch(`/documents/${documentId.value}`),
      apiFetch(`/documents/${documentId.value}/chunks`).catch(() => []),
    ])
    document.value = doc
    chunks.value = chunkRows
    await nextTick()
    scrollToTargetChunk()
  } catch (e) {
    document.value = null
    chunks.value = []
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function chunkDomId(chunk) {
  return `chunk-${chunk.chunk_id}`
}

function isTargetChunk(chunk) {
  return Boolean(targetChunkId.value && chunk.chunk_id === targetChunkId.value)
}

function scrollToTargetChunk() {
  if (!targetChunkId.value) return
  const el = globalThis.document?.getElementById(chunkDomId({ chunk_id: targetChunkId.value }))
  el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

function askQuestion(question) {
  router.push(buildQuestionRoute(
    question,
    documentId.value,
    normalized.value?.name || '',
    settings.locale,
  ))
}

function openDocumentChat() {
  if (!canOpenDocumentChat.value) return
  router.push(buildDocumentChatRoute(
    documentId.value,
    normalized.value?.name || '',
    settings.locale,
  ))
}
</script>

<style scoped>
.document-detail {
  display: grid;
  grid-template-rows: auto auto minmax(220px, 1fr);
  gap: 20px;
  height: 100%;
  min-height: 0;
  min-width: 0;
  overflow-y: auto;
  padding-bottom: 24px;
}
.detail-hero {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  padding: 18px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background:
    radial-gradient(circle at 0% 0%, color-mix(in oklch, var(--accent) 18%, transparent), transparent 30%),
    var(--s1);
}
.back-link {
  margin: 0 0 12px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--muted2);
  cursor: pointer;
  font-family: var(--font);
  font-size: 12px;
}
.back-link:hover {
  color: var(--text);
}
.detail-eyebrow {
  margin-bottom: 6px;
  color: var(--accent);
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.detail-hero h1 {
  margin: 0 0 8px;
  font-size: 24px;
  letter-spacing: -0.04em;
  overflow-wrap: anywhere;
}
.detail-hero p {
  max-width: 640px;
  color: var(--muted2);
  font-size: 13px;
  line-height: 1.6;
}
.detail-status {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
  min-width: 140px;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 11px;
}
.detail-progress {
  display: grid;
  gap: 5px;
  width: 150px;
  text-align: right;
}
.detail-progress .progress {
  width: 100%;
}
.detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.8fr);
  gap: 14px;
}
.detail-card-body {
  padding: 16px 18px;
}
.summary-text {
  margin: 0;
  color: var(--muted2);
  font-size: 13px;
  line-height: 1.65;
}
.muted-block {
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.5;
}
.detail-questions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}
.question-chip {
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--s1);
  color: var(--muted2);
  cursor: pointer;
  font-family: var(--font);
  font-size: 12px;
  text-align: left;
}
.question-chip:hover {
  border-color: var(--accent);
  color: var(--text);
}
.ask-main {
  width: 100%;
  justify-content: center;
}
.ask-disabled-note {
  margin-top: 8px;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.45;
  text-align: center;
}
.warnings-card ul {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 14px 28px 16px 34px;
  color: var(--yellow);
  font-size: 11px;
  line-height: 1.5;
}
.source-url-link {
  color: var(--text);
  font-size: 13px;
  font-weight: 700;
  overflow-wrap: anywhere;
  text-decoration: none;
}
.source-url-link:hover {
  color: var(--accent);
}
.source-url-text {
  margin-top: 6px;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 11px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}
.chunks-card {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.chunks-card > .card-header {
  flex-shrink: 0;
}
.chunks-list {
  display: grid;
  flex: 1;
  gap: 10px;
  min-height: 0;
  overflow-y: auto;
  padding: 14px;
}
.chunk-card {
  padding: 13px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: color-mix(in oklch, var(--s2) 74%, transparent);
  scroll-margin: 100px;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.chunk-card-target {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px color-mix(in oklch, var(--accent) 40%, transparent);
}
.chunk-meta {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
  color: var(--accent);
  font-family: var(--mono);
  font-size: 10px;
  text-transform: uppercase;
}
.chunk-card p {
  margin: 0;
  color: var(--muted2);
  font-size: 12px;
  line-height: 1.6;
}

@media (min-width: 901px) {
  .chunks-card {
    min-height: clamp(520px, 55vh, 720px);
  }
}

@media (max-width: 900px) {
  .document-detail {
    display: flex;
    overflow-y: auto;
    padding-bottom: 56px;
  }
  .detail-hero,
  .detail-status {
    align-items: flex-start;
  }
  .detail-hero {
    flex-direction: column;
  }
  .detail-grid {
    grid-template-columns: 1fr;
  }
}
</style>
