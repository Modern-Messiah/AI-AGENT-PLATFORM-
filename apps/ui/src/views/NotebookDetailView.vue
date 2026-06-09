<template>
  <div class="screen-body notebook-detail">
    <div class="notebook-detail-hero">
      <div>
        <button class="back-link" type="button" @click="router.push('/notebooks')">
          Назад к ноутбукам
        </button>
        <div class="detail-eyebrow">Коллекция источников</div>
        <h1>{{ normalized?.title || 'Ноутбук' }}</h1>
        <p>
          Вопросы из этого экрана идут только по документам внутри коллекции,
          без смешивания со всей базой знаний.
        </p>
      </div>
      <div v-if="normalized" class="detail-status">
        <span>{{ normalized.documentCount }} документ(ов)</span>
        <span>создан {{ normalized.createdLabel }}</span>
      </div>
    </div>

    <div v-if="loading" class="card">
      <div class="empty">
        <div class="spinner"></div>
        <div class="empty-title">Загружаю ноутбук</div>
      </div>
    </div>

    <div v-else-if="error" class="card">
      <div class="empty">
        <div class="empty-title">Не удалось открыть ноутбук</div>
        <div class="empty-sub">{{ error }}</div>
      </div>
    </div>

    <template v-else-if="normalized">
      <div class="detail-grid">
        <div class="card">
          <div class="card-header">
            <div>
              <div class="card-title">Обзор коллекции</div>
              <div class="card-sub">
                {{ normalized.insightsUpdatedLabel === '—' ? 'Ещё не собран' : `обновлён ${normalized.insightsUpdatedLabel}` }}
              </div>
            </div>
            <button
              class="btn btn-ghost btn-sm"
              type="button"
              :disabled="refreshingInsights || includedSources.length === 0"
              @click="refreshInsights"
            >
              {{ refreshingInsights ? 'Обновляю...' : 'Обновить обзор' }}
            </button>
          </div>
          <div class="detail-card-body">
            <template v-if="normalized.summary">
              <div class="overview-label">Краткий обзор</div>
              <p class="summary-text">{{ normalized.summary }}</p>
            </template>
            <div v-else class="muted-block">
              Нажмите «Обновить обзор», чтобы собрать краткое описание, темы и вопросы по этой коллекции.
            </div>
            <div v-if="normalized.keyTopics.length" class="overview-section">
              <div class="overview-label">Ключевые темы</div>
              <div class="topic-row">
                <span v-for="topic in normalized.keyTopics" :key="topic" class="topic-chip">
                  {{ topic }}
                </span>
              </div>
            </div>
            <div v-if="suggestedQuestions.length" class="overview-section">
              <div class="overview-label">Вопросы для чата</div>
              <div class="overview-hint">Нажмите на вопрос, чтобы открыть чат по этой коллекции.</div>
              <div class="detail-questions">
                <button
                  v-for="question in suggestedQuestions"
                  :key="question"
                  class="question-chip"
                  type="button"
                  @click="askQuestion(question)"
                >
                  {{ question }}
                </button>
              </div>
            </div>
            <div v-else-if="normalized.description" class="summary-note">
              {{ normalized.description }}
            </div>
            <button class="btn btn-primary ask-main" type="button" @click="askDefaultQuestion">
              Открыть чат по коллекции
            </button>
          </div>
        </div>

        <div class="card">
          <div class="card-header">
            <div>
              <div class="card-title">Состав ноутбука</div>
              <div class="card-sub">Добавьте документы, которых ещё нет в коллекции</div>
            </div>
            <button
              class="btn btn-ghost btn-sm"
              type="button"
              :disabled="saving || pendingAddDocumentIds.length === 0"
              @click="saveDocuments"
            >
              {{ saving ? 'Сохраняю...' : addButtonLabel }}
            </button>
          </div>
          <div
            :class="['inline-upload', { 'drag-over': draggingUpload }]"
            @dragover.prevent="draggingUpload = true"
            @dragleave="draggingUpload = false"
            @drop="handleUploadDrop"
            @click="fileInput?.click()"
          >
            <div>
              <strong>{{ uploading ? 'Загружаю файл...' : 'Загрузить файл в этот ноутбук' }}</strong>
              <span>Файл сразу попадёт в коллекцию и начнёт индексироваться</span>
            </div>
            <button class="btn btn-ghost btn-sm" type="button" :disabled="uploading">
              Выбрать
            </button>
            <input
              ref="fileInput"
              type="file"
              multiple
              style="display: none"
              @change="handleUploadInput"
            />
          </div>
          <div class="picker-heading">
            <span>Доступно для добавления</span>
            <small>{{ availableDocs.length }} документ(ов)</small>
          </div>
          <div class="doc-picker">
            <label v-for="doc in availableDocs" :key="doc.id" class="doc-option">
              <input v-model="pendingAddDocumentIds" type="checkbox" :value="doc.id" />
              <span>
                <strong>{{ doc.name }}</strong>
                <small>{{ doc.size }} · {{ doc.createdLabel }}</small>
              </span>
            </label>
            <div v-if="availableDocs.length === 0" class="muted-block">
              Все готовые документы уже в ноутбуке. Новые файлы можно загрузить прямо сюда.
            </div>
          </div>
        </div>
      </div>

      <div class="card sources-card">
        <div class="card-header">
          <div>
            <div class="card-title">Источники ноутбука</div>
            <div class="card-sub">
              {{ includedSources.length }} источник(ов), {{ readySourceCount }} готово для вопросов
            </div>
          </div>
          <button class="btn btn-ghost btn-sm" type="button" @click="loadNotebook">
            Обновить
          </button>
        </div>
        <div v-if="includedSources.length === 0" class="empty">
          <div class="empty-title">Коллекция пустая</div>
          <div class="empty-sub">Добавьте хотя бы один готовый документ и сохраните состав</div>
        </div>
        <div v-else class="source-list">
          <article v-for="source in includedSources" :key="source.id" class="source-card">
            <div class="source-main">
              <div class="source-title-row">
                <RouterLink class="source-title" :to="buildDocumentRoute(source.id)">
                  {{ source.name }}
                </RouterLink>
                <StatusBadge :status="source.status" />
              </div>
              <div class="source-meta">
                <span>{{ source.readinessLabel }}</span>
                <span>{{ formatFileSize(source.sizeBytes) }}</span>
                <span>{{ source.createdLabel }}</span>
              </div>
              <p v-if="source.error" class="source-error">
                {{ source.error }}
              </p>
            </div>
            <div class="source-actions">
              <RouterLink class="btn btn-ghost btn-sm" :to="buildDocumentRoute(source.id)">
                Открыть
              </RouterLink>
              <button
                class="btn btn-ghost btn-sm"
                type="button"
                :disabled="!source.isReady"
                @click="askSource(source)"
              >
                Спросить
              </button>
              <button
                class="btn btn-ghost btn-sm"
                type="button"
                :disabled="saving"
                @click="excludeSource(source.id)"
              >
                Исключить
              </button>
            </div>
          </article>
        </div>
      </div>
    </template>

    <AppToast v-if="toast" v-bind="toast" @done="toast = null" />
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useApi } from '@/composables/useApi'
import { useSettingsStore } from '@/stores/settings'
import AppToast from '@/components/AppToast.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { buildDocumentRoute, formatFileSize, normalizeDocument } from '@/utils/documents'
import {
  buildNotebookDocumentSelection,
  buildNotebookChatRoute,
  buildNotebookQuestionRoute,
  buildNotebookUploadPath,
  filterAvailableNotebookDocuments,
  notebookOverviewQuestions,
  normalizeNotebookSources,
  normalizeNotebook,
} from '@/utils/notebooks'

const route = useRoute()
const router = useRouter()
const { apiFetch } = useApi()
const settings = useSettingsStore()

const notebook = ref(null)
const allDocs = ref([])
const pendingAddDocumentIds = ref([])
const loading = ref(false)
const saving = ref(false)
const refreshingInsights = ref(false)
const uploading = ref(false)
const draggingUpload = ref(false)
const error = ref('')
const toast = ref(null)
const fileInput = ref(null)

const notebookId = computed(() => String(route.params.id || ''))
const normalized = computed(() => notebook.value ? normalizeNotebook(notebook.value) : null)
const currentDocumentIds = computed(() => normalized.value?.documentIds || [])
const availableDocs = computed(() => (
  filterAvailableNotebookDocuments(allDocs.value, currentDocumentIds.value)
))
const includedSources = computed(() => normalizeNotebookSources(normalized.value?.documents || []))
const readySourceCount = computed(() => includedSources.value.filter(source => source.isReady).length)
const addButtonLabel = computed(() => (
  pendingAddDocumentIds.value.length
    ? `Добавить (${pendingAddDocumentIds.value.length})`
    : 'Добавить'
))
const suggestedQuestions = computed(() => notebookOverviewQuestions(normalized.value))

watch([() => settings.apiKey, notebookId], loadNotebook, { immediate: true })

async function loadNotebook() {
  if (!settings.isConnected || !notebookId.value) {
    notebook.value = null
    allDocs.value = []
    pendingAddDocumentIds.value = []
    error.value = settings.isConnected ? 'Ноутбук не выбран' : 'Задайте X-API-Key в настройках'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const [notebookData, documentRows] = await Promise.all([
      apiFetch(`/notebooks/${notebookId.value}`),
      apiFetch('/documents'),
    ])
    notebook.value = notebookData
    allDocs.value = documentRows.map(normalizeDocument)
    pendingAddDocumentIds.value = []
  } catch (e) {
    notebook.value = null
    allDocs.value = []
    pendingAddDocumentIds.value = []
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function saveDocuments(options = {}) {
  saving.value = true
  const documentIds = options.documentIds || buildNotebookDocumentSelection(
    currentDocumentIds.value,
    pendingAddDocumentIds.value,
  )
  try {
    const data = await apiFetch(`/notebooks/${notebookId.value}/documents`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ document_ids: documentIds }),
    })
    notebook.value = data
    pendingAddDocumentIds.value = []
    toast.value = { msg: options.successMessage || 'Состав ноутбука сохранён', type: 'success' }
    return true
  } catch (e) {
    toast.value = { msg: `Ошибка сохранения: ${e.message}`, type: 'error' }
    return false
  } finally {
    saving.value = false
  }
}

async function uploadFiles(files) {
  if (!settings.isConnected) {
    toast.value = { msg: 'Задайте X-API-Key в настройках', type: 'error' }
    return
  }
  const uploadList = Array.from(files || []).filter(file => file.size > 0)
  if (!uploadList.length) return

  uploading.value = true
  const uploadedDocumentIds = []
  try {
    for (const file of uploadList) {
      const form = new FormData()
      form.append('file', file)
      const doc = await apiFetch(buildNotebookUploadPath(notebookId.value), {
        method: 'POST',
        body: form,
      })
      uploadedDocumentIds.push(doc.id)
    }
    await loadNotebook()
    uploadedDocumentIds.forEach(pollUploadedDocument)
    toast.value = { msg: `Загружено: ${uploadList.length}`, type: 'success' }
  } catch (e) {
    toast.value = { msg: `Ошибка загрузки: ${e.message}`, type: 'error' }
  } finally {
    uploading.value = false
  }
}

async function pollUploadedDocument(documentId) {
  for (let i = 0; i < 120; i++) {
    await new Promise(resolve => setTimeout(resolve, 5000))
    try {
      const doc = await apiFetch(`/documents/${documentId}`)
      if (doc.status === 'done' || doc.status === 'failed') {
        await loadNotebook()
        return
      }
    } catch {}
  }
  await loadNotebook()
}

function handleUploadDrop(event) {
  event.preventDefault()
  draggingUpload.value = false
  uploadFiles(event.dataTransfer.files)
}

function handleUploadInput(event) {
  uploadFiles(event.target.files)
  event.target.value = ''
}

async function refreshInsights() {
  refreshingInsights.value = true
  try {
    const data = await apiFetch(`/notebooks/${notebookId.value}/insights`, { method: 'POST' })
    notebook.value = data
    toast.value = { msg: 'Обзор коллекции обновлён', type: 'success' }
  } catch (e) {
    toast.value = { msg: `Ошибка обзора: ${e.message}`, type: 'error' }
  } finally {
    refreshingInsights.value = false
  }
}

function askQuestion(question) {
  router.push(buildNotebookQuestionRoute(question, notebookId.value, normalized.value?.title || ''))
}

function askSource(source) {
  askQuestion(`Что важно в ${source.name}?`)
}

async function excludeSource(documentId) {
  const documentIds = currentDocumentIds.value.filter(id => id !== documentId)
  await saveDocuments({ documentIds, successMessage: 'Источник исключён из ноутбука' })
}

function askDefaultQuestion() {
  router.push(buildNotebookChatRoute(notebookId.value, normalized.value?.title || ''))
}
</script>

<style scoped>
.notebook-detail {
  display: grid;
  grid-template-rows: auto auto minmax(220px, 1fr);
  gap: 20px;
  height: 100%;
  min-height: 0;
  min-width: 0;
  overflow-y: auto;
  padding-bottom: 24px;
}
.notebook-detail-hero {
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
.notebook-detail-hero h1 {
  margin: 0 0 8px;
  font-size: 24px;
  letter-spacing: -0.04em;
  overflow-wrap: anywhere;
}
.notebook-detail-hero p {
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
.detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 0.9fr);
  gap: 14px;
}
.detail-card-body {
  padding: 16px 18px;
}
.overview-section {
  margin-top: 14px;
}
.overview-label {
  margin-bottom: 7px;
  color: var(--text);
  font-size: 11px;
  font-weight: 700;
}
.overview-hint {
  margin: -2px 0 8px;
  color: var(--muted);
  font-size: 10px;
  line-height: 1.45;
}
.summary-text {
  margin: 0 0 14px;
  color: var(--muted2);
  font-size: 13px;
  line-height: 1.65;
}
.summary-note {
  margin-bottom: 14px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.5;
}
.topic-row {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-bottom: 14px;
}
.topic-chip {
  padding: 5px 8px;
  border: 1px solid color-mix(in oklch, var(--accent) 35%, transparent);
  border-radius: 999px;
  background: color-mix(in oklch, var(--accent) 10%, transparent);
  color: var(--accent);
  font-family: var(--mono);
  font-size: 10px;
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
.question-chip:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
.ask-main {
  width: 100%;
  justify-content: center;
}
.inline-upload {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 14px 14px 0;
  padding: 12px;
  border: 1px dashed var(--border2);
  border-radius: 12px;
  background: color-mix(in oklch, var(--accent) 4%, var(--s2));
  cursor: pointer;
}
.inline-upload.drag-over {
  border-color: var(--accent);
  background: color-mix(in oklch, var(--accent) 8%, var(--s2));
}
.inline-upload strong,
.inline-upload span {
  display: block;
}
.inline-upload strong {
  color: var(--text);
  font-size: 12px;
}
.inline-upload span {
  margin-top: 3px;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.4;
}
.picker-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 14px 14px 0;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.picker-heading small {
  color: var(--muted2);
  font-size: 10px;
}
.doc-picker {
  display: grid;
  gap: 8px;
  padding: 14px;
}
.doc-option {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--s2);
  cursor: pointer;
}
.doc-option strong {
  display: block;
  color: var(--text);
  font-size: 12px;
  overflow-wrap: anywhere;
}
.doc-option small {
  display: block;
  margin-top: 2px;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10px;
}
.muted-block {
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.5;
}
.sources-card {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.sources-card > .card-header {
  flex-shrink: 0;
}
.source-list {
  display: grid;
  flex: 1;
  align-content: start;
  gap: 12px;
  grid-auto-rows: max-content;
  min-height: 0;
  overflow-y: auto;
  padding: 14px;
}
.source-card {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: color-mix(in oklch, var(--s2) 74%, transparent);
}
.source-main {
  min-width: 0;
}
.source-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.source-title {
  display: block;
  color: var(--text);
  font-size: 13px;
  font-weight: 650;
  overflow-wrap: anywhere;
  text-decoration: none;
}
.source-title:hover {
  color: var(--accent);
}
.source-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 4px;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10px;
}
.source-error {
  margin: 10px 0 0;
  color: var(--red);
  font-size: 12px;
  line-height: 1.55;
}
.source-actions {
  display: flex;
  align-items: flex-start;
  flex-shrink: 0;
  gap: 8px;
}

@media (min-width: 901px) {
  .sources-card {
    min-height: clamp(520px, 55vh, 720px);
  }
}

@media (max-width: 900px) {
  .notebook-detail {
    display: flex;
    overflow-y: auto;
    padding-bottom: 56px;
  }
  .notebook-detail-hero,
  .detail-status {
    align-items: flex-start;
  }
  .notebook-detail-hero {
    flex-direction: column;
  }
  .detail-grid {
    grid-template-columns: 1fr;
  }
  .source-card,
  .source-title-row,
  .source-actions {
    align-items: stretch;
    flex-direction: column;
  }
  .source-actions {
    flex-wrap: wrap;
  }
}
</style>
