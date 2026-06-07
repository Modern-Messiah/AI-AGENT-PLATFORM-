<template>
  <div class="screen-body">
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
              <div class="card-title">Спросить по коллекции</div>
              <div class="card-sub">RAG-поиск ограничен документами ниже</div>
            </div>
          </div>
          <div class="detail-card-body">
            <p v-if="normalized.description" class="summary-text">{{ normalized.description }}</p>
            <div v-if="suggestedQuestions.length" class="detail-questions">
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
            <button class="btn btn-primary ask-main" type="button" @click="askDefaultQuestion">
              Открыть чат по коллекции
            </button>
          </div>
        </div>

        <div class="card">
          <div class="card-header">
            <div>
              <div class="card-title">Состав ноутбука</div>
              <div class="card-sub">Можно менять подборку документов</div>
            </div>
            <button
              class="btn btn-ghost btn-sm"
              type="button"
              :disabled="saving"
              @click="saveDocuments"
            >
              {{ saving ? 'Сохраняю...' : 'Сохранить' }}
            </button>
          </div>
          <div class="doc-picker">
            <label v-for="doc in readyDocs" :key="doc.id" class="doc-option">
              <input v-model="selectedDocumentIds" type="checkbox" :value="doc.id" />
              <span>
                <strong>{{ doc.name }}</strong>
                <small>{{ doc.size }} · {{ doc.createdLabel }}</small>
              </span>
            </label>
            <div v-if="readyDocs.length === 0" class="muted-block">
              Нет готовых документов для добавления.
            </div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">Документы внутри</div>
            <div class="card-sub">{{ normalized.documentCount }} источник(ов)</div>
          </div>
          <button class="btn btn-ghost btn-sm" type="button" @click="loadNotebook">
            Обновить
          </button>
        </div>
        <div v-if="includedDocs.length === 0" class="empty">
          <div class="empty-title">Коллекция пустая</div>
          <div class="empty-sub">Добавьте хотя бы один готовый документ и сохраните состав</div>
        </div>
        <div v-else class="included-list">
          <article v-for="doc in includedDocs" :key="doc.id" class="included-card">
            <div>
              <strong>{{ doc.name }}</strong>
              <small>{{ doc.size }} · {{ doc.createdLabel }}</small>
            </div>
            <StatusBadge :status="doc.status" />
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
import { normalizeDocument } from '@/utils/documents'
import { buildNotebookQuestionRoute, normalizeNotebook } from '@/utils/notebooks'

const route = useRoute()
const router = useRouter()
const { apiFetch } = useApi()
const settings = useSettingsStore()

const notebook = ref(null)
const allDocs = ref([])
const selectedDocumentIds = ref([])
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const toast = ref(null)

const notebookId = computed(() => String(route.params.id || ''))
const normalized = computed(() => notebook.value ? normalizeNotebook(notebook.value) : null)
const readyDocs = computed(() => allDocs.value.filter(doc => doc.status === 'done'))
const includedDocs = computed(() => (normalized.value?.documents || []).map(normalizeDocument))
const suggestedQuestions = computed(() => {
  const questions = []
  for (const doc of includedDocs.value) {
    for (const question of doc.suggestedQuestions || []) {
      if (!questions.includes(question)) questions.push(question)
      if (questions.length >= 4) return questions
    }
  }
  return questions
})

watch([() => settings.apiKey, notebookId], loadNotebook, { immediate: true })

async function loadNotebook() {
  if (!settings.isConnected || !notebookId.value) {
    notebook.value = null
    allDocs.value = []
    selectedDocumentIds.value = []
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
    selectedDocumentIds.value = [...(notebookData.document_ids || [])]
  } catch (e) {
    notebook.value = null
    allDocs.value = []
    selectedDocumentIds.value = []
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function saveDocuments() {
  saving.value = true
  try {
    const data = await apiFetch(`/notebooks/${notebookId.value}/documents`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ document_ids: selectedDocumentIds.value }),
    })
    notebook.value = data
    selectedDocumentIds.value = [...(data.document_ids || [])]
    toast.value = { msg: 'Состав ноутбука сохранён', type: 'success' }
  } catch (e) {
    toast.value = { msg: `Ошибка сохранения: ${e.message}`, type: 'error' }
  } finally {
    saving.value = false
  }
}

function askQuestion(question) {
  router.push(buildNotebookQuestionRoute(question, notebookId.value))
}

function askDefaultQuestion() {
  askQuestion(`Сделай обзор коллекции ${normalized.value?.title || ''}`)
}
</script>

<style scoped>
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
.summary-text {
  margin: 0 0 14px;
  color: var(--muted2);
  font-size: 13px;
  line-height: 1.65;
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
.included-list {
  display: grid;
  gap: 10px;
  padding: 14px;
}
.included-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: color-mix(in oklch, var(--s2) 74%, transparent);
}
.included-card strong,
.included-card small {
  display: block;
}
.included-card strong {
  color: var(--text);
  font-size: 12px;
}
.included-card small {
  margin-top: 4px;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10px;
}

@media (max-width: 900px) {
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
}
</style>
