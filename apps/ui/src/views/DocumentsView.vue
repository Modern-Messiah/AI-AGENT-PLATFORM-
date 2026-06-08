<template>
  <div class="screen-body">
    <div class="kb-hero">
      <div>
        <div class="kb-eyebrow">Общая память для всех чатов</div>
        <h1>База знаний</h1>
        <p>
          Загруженные файлы индексируются один раз, а потом агент использует их
          в любом новом чате с точными ссылками на источники.
        </p>
      </div>
      <div class="kb-stats">
        <div class="kb-stat">
          <span>{{ stats.ready }}</span>
          <label>готово</label>
        </div>
        <div class="kb-stat">
          <span>{{ stats.processing }}</span>
          <label>в работе</label>
        </div>
        <div class="kb-stat" :class="{ warn: stats.failed }">
          <span>{{ stats.failed }}</span>
          <label>ошибки</label>
        </div>
      </div>
    </div>

    <div
      :class="['drop-zone', { 'drag-over': dragging }]"
      @dragover.prevent="dragging = true"
      @dragleave="dragging = false"
      @drop="handleDrop"
      @click="fileInput.click()"
    >
      <div class="drop-icon">
        <AppIcon name="upload" :size="32" />
      </div>
      <div class="drop-title">Добавьте документы в базу знаний</div>
      <div class="drop-sub">PDF сохраняют страницы для цитат, остальные файлы индексируются фрагментами</div>
      <div class="drop-types">
        <span v-for="t in ['PDF','DOCX','TXT','MD','CSV','HTML']" :key="t" class="type-chip">.{{ t.toLowerCase() }}</span>
      </div>
      <input ref="fileInput" type="file" multiple style="display: none" @change="handleFileInput" />
    </div>

    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">Файлы памяти</div>
          <div class="card-sub">{{ stats.ready }} из {{ stats.total }} готово для ответов во всех чатах</div>
        </div>
        <div style="display: flex; gap: 8px; align-items: center">
          <div v-if="docs.length" class="progress" style="width: 100px">
            <div class="progress-fill" :style="{ width: stats.progressPct + '%' }"></div>
          </div>
          <button class="btn btn-ghost btn-sm" title="Обновить" @click="loadDocs">
            <AppIcon name="refresh" :size="11" />
          </button>
          <button class="btn btn-ghost btn-sm" title="Очистить список" @click="clearAll">
            <AppIcon name="trash" :size="11" />
          </button>
        </div>
      </div>

      <div v-if="docs.length === 0" class="empty" style="padding: 40px">
        <div class="empty-icon">📂</div>
        <div class="empty-title">База знаний пока пустая</div>
        <div class="empty-sub">Загрузите документы, и агент сможет опираться на них в любом чате</div>
      </div>
      <table v-else>
        <thead>
          <tr>
            <th>Файл</th><th>Статус</th><th>Размер</th><th>Загружен</th><th></th>
          </tr>
        </thead>
        <tbody>
          <template v-for="doc in docs" :key="doc.id">
            <tr>
              <td>
                <div class="file-name">
                  <div class="file-icon">{{ mimeIcon(doc.name) }}</div>
                  <div>
                    <button
                      class="file-title-button"
                      type="button"
                      :disabled="doc._pending"
                      @click="openDocument(doc)"
                    >
                      {{ doc.name }}
                    </button>
                    <div v-if="doc.error" style="font-size: 11px; color: var(--red); margin-top: 2px">{{ doc.error }}</div>
                    <div style="font-size: 10px; color: var(--muted); font-family: var(--mono); margin-top: 1px">{{ doc.id }}</div>
                  </div>
                </div>
              </td>
              <td>
                <div style="display: flex; align-items: center; gap: 8px">
                  <StatusBadge :status="doc.status" />
                  <div v-if="doc.status === 'processing' || doc.status === 'pending'" class="spinner"></div>
                </div>
              </td>
              <td class="td-mono">{{ doc.size }}</td>
              <td class="td-mono">{{ doc.time }}</td>
              <td>
                <div style="display: flex; gap: 6px; justify-content: flex-end">
                  <button
                    class="btn btn-ghost btn-sm"
                    title="Открыть документ"
                    :disabled="doc._pending"
                    @click="openDocument(doc)"
                  >
                    <AppIcon name="docs" />
                  </button>
                  <button class="btn btn-ghost btn-sm" title="Копировать ID" @click="copyId(doc.id)">
                    <AppIcon name="copy" />
                  </button>
                  <button
                    class="btn btn-ghost btn-sm"
                    title="Переиндексировать"
                    :disabled="!canReindexDocument(doc)"
                    @click="reindexDoc(doc)"
                  >
                    <AppIcon name="refresh" />
                  </button>
                  <button class="btn btn-ghost btn-sm" title="Удалить" @click="removeDoc(doc.id)">
                    <AppIcon name="trash" />
                  </button>
                </div>
              </td>
            </tr>
            <tr v-if="hasInsights(doc)" class="doc-insights-row">
              <td colspan="5">
                <div class="doc-insights">
                  <div v-if="doc.summary" class="doc-summary">
                    <span>Что внутри</span>
                    {{ doc.summary }}
                  </div>
                  <div v-if="doc.suggestedQuestions.length" class="doc-questions">
                    <button
                      v-for="question in doc.suggestedQuestions"
                      :key="question"
                      class="question-chip"
                      type="button"
                      @click="askQuestion(question, doc)"
                    >
                      {{ question }}
                    </button>
                  </div>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <div style="font-size: 12px; color: var(--muted); display: flex; align-items: center; gap: 8px">
      <span style="font-family: var(--mono)">pgvector</span> · multi-document citations · page-aware PDF parsing · semantic cache invalidation
    </div>

    <AppToast v-if="toast" v-bind="toast" @done="toast = null" />
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useApi } from '@/composables/useApi'
import { useSettingsStore } from '@/stores/settings'
import AppIcon from '@/components/AppIcon.vue'
import AppToast from '@/components/AppToast.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import {
  buildDocumentRoute,
  buildQuestionRoute,
  canReindexDocument,
  formatFileSize,
  knowledgeBaseStats,
  normalizeDocument,
} from '@/utils/documents'

const { apiFetch } = useApi()
const settings = useSettingsStore()
const router = useRouter()

const docs = ref([])
const dragging = ref(false)
const toast = ref(null)
const fileInput = ref(null)

async function loadDocs() {
  if (!settings.isConnected) { docs.value = []; return }
  try {
    const data = await apiFetch('/documents')
    // merge: keep in-progress uploads that aren't in the API list yet
    const apiIds = new Set(data.map(d => d.id))
    const pending = docs.value.filter(d => d._pending && !apiIds.has(d.id))
    docs.value = [...pending, ...data.map(normalizeDocument)]
  } catch { docs.value = [] }
}

watch(() => settings.apiKey, loadDocs, { immediate: true })

const stats = computed(() => knowledgeBaseStats(docs.value))

function mimeIcon(name) {
  const ext = (name || '').split('.').pop().toLowerCase()
  return ({ pdf: '📄', md: '📝', txt: '📃', csv: '📊', html: '🌐', docx: '📘' })[ext] || '📁'
}

function hasInsights(doc) {
  return Boolean(doc.summary || doc.suggestedQuestions?.length)
}

function askQuestion(question, doc) {
  router.push(buildQuestionRoute(question, doc.id, doc.name))
}

function openDocument(doc) {
  if (doc?._pending) return
  router.push(buildDocumentRoute(doc.id))
}

async function removeDoc(id) {
  const doc = docs.value.find(d => d.id === id)
  if (doc?._pending) { docs.value = docs.value.filter(d => d.id !== id); return }
  try {
    await apiFetch(`/documents/${id}`, { method: 'DELETE' })
    docs.value = docs.value.filter(d => d.id !== id)
  } catch (e) {
    toast.value = { msg: `Ошибка удаления: ${e.message}`, type: 'error' }
  }
}

async function reindexDoc(doc) {
  if (!canReindexDocument(doc)) return
  updateDoc(doc.id, { status: 'pending', error: null, _pending: true })
  toast.value = { msg: `Переиндексация: ${doc.name}`, type: 'info' }
  try {
    await apiFetch(`/documents/${doc.id}/reindex`, { method: 'POST' })
    pollStatus(doc.id)
  } catch (e) {
    updateDoc(doc.id, { status: 'failed', error: e.message, _pending: false })
    toast.value = { msg: `Ошибка переиндексации: ${e.message}`, type: 'error' }
  }
}

async function clearAll() {
  const toDelete = docs.value.filter(d => !d._pending)
  if (!toDelete.length) { docs.value = docs.value.filter(d => d._pending); return }
  const failed = []
  await Promise.all(toDelete.map(async doc => {
    try { await apiFetch(`/documents/${doc.id}`, { method: 'DELETE' }) }
    catch { failed.push(doc.id) }
  }))
  docs.value = docs.value.filter(d => d._pending || failed.includes(d.id))
  if (failed.length) toast.value = { msg: `Не удалось удалить ${failed.length} документ(а)`, type: 'error' }
}
function copyId(id) { navigator.clipboard.writeText(id).catch(() => {}); toast.value = { msg: `ID скопирован: ${id}`, type: 'info' } }

function updateDoc(id, patch) {
  docs.value = docs.value.map(d => d.id === id ? { ...d, ...patch } : d)
}

async function pollStatus(docId) {
  // Poll for up to 10 minutes (120 × 5s). Large PDFs + embedding can take several minutes.
  for (let i = 0; i < 120; i++) {
    await new Promise(r => setTimeout(r, 5000))
    try {
      const data = await apiFetch(`/documents/${docId}`)
      if (data.status === 'done') {
        updateDoc(docId, { ...normalizeDocument(data), _pending: false })
        return
      }
      if (data.status === 'failed') { updateDoc(docId, { status: 'failed', error: data.error || 'Failed', _pending: false }); return }
    } catch {}
  }
  // After 10 min show 'processing' (not 'failed') — Temporal may still be running
  updateDoc(docId, { status: 'processing', error: null, _pending: false })
}

async function uploadFile(file) {
  if (!settings.isConnected) { toast.value = { msg: 'Задайте X-API-Key в настройках', type: 'error' }; return }
  const tempId = 'upload-' + Date.now()
  const size = formatFileSize(file.size)
  docs.value = [{ id: tempId, name: file.name, status: 'processing', time: 'сейчас', error: null, size, _pending: true }, ...docs.value]
  toast.value = { msg: `Загрузка: ${file.name}`, type: 'info' }
  try {
    const form = new FormData(); form.append('file', file)
    const data = await apiFetch('/documents', { method: 'POST', body: form })
    docs.value = docs.value.map(d => d.id === tempId ? { ...d, id: data.id, _pending: true } : d)
    pollStatus(data.id)
  } catch (e) {
    updateDoc(tempId, { status: 'failed', error: e.message })
    toast.value = { msg: `Ошибка: ${e.message}`, type: 'error' }
  }
}

function handleDrop(e) {
  e.preventDefault(); dragging.value = false
  Array.from(e.dataTransfer.files).forEach(uploadFile)
}
function handleFileInput(e) {
  Array.from(e.target.files).forEach(uploadFile)
  e.target.value = ''
}
</script>

<style scoped>
.kb-hero {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  padding: 18px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background:
    radial-gradient(circle at 10% 0%, color-mix(in oklch, var(--purple) 18%, transparent), transparent 28%),
    var(--s1);
}
.kb-eyebrow {
  margin-bottom: 6px;
  color: var(--accent);
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.kb-hero h1 {
  margin: 0 0 8px;
  font-size: 24px;
  letter-spacing: -0.04em;
}
.kb-hero p {
  max-width: 620px;
  color: var(--muted2);
  font-size: 13px;
  line-height: 1.6;
}
.kb-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(84px, 1fr));
  gap: 8px;
  min-width: 280px;
}
.kb-stat {
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: color-mix(in oklch, var(--s2) 86%, transparent);
}
.kb-stat span {
  display: block;
  color: var(--text);
  font-family: var(--mono);
  font-size: 20px;
  font-weight: 700;
}
.kb-stat label {
  color: var(--muted);
  font-size: 11px;
}
.kb-stat.warn span {
  color: var(--red);
}
.file-title-button {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text);
  cursor: pointer;
  font-family: var(--font);
  font-size: 13px;
  text-align: left;
}
.file-title-button:hover {
  color: var(--accent);
}
.file-title-button:disabled {
  color: var(--muted2);
  cursor: not-allowed;
}
.doc-insights-row td {
  padding-top: 0;
}
.doc-insights {
  margin: 0 8px 12px 42px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: color-mix(in oklch, var(--s2) 74%, transparent);
}
.doc-summary {
  color: var(--muted2);
  font-size: 12px;
  line-height: 1.55;
}
.doc-summary span {
  display: block;
  margin-bottom: 4px;
  color: var(--text);
  font-size: 11px;
  font-weight: 600;
}
.doc-questions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}
.question-chip {
  padding: 5px 9px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--s1);
  color: var(--muted2);
  cursor: pointer;
  font-family: var(--font);
  font-size: 11px;
}
.question-chip:hover {
  border-color: var(--accent);
  color: var(--text);
}

@media (max-width: 900px) {
  .kb-hero {
    flex-direction: column;
  }
  .kb-stats {
    min-width: 0;
  }
}
</style>
