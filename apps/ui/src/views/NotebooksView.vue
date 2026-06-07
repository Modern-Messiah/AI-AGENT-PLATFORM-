<template>
  <div class="screen-body">
    <div class="notebook-hero">
      <div>
        <div class="notebook-eyebrow">Коллекции источников</div>
        <h1>Ноутбуки</h1>
        <p>
          Соберите несколько документов в отдельное пространство, чтобы чат
          отвечал только по выбранной подборке источников.
        </p>
      </div>
      <div class="notebook-stat">
        <span>{{ notebooks.length }}</span>
        <label>коллекций</label>
      </div>
    </div>

    <div class="notebook-grid">
      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">Новый ноутбук</div>
            <div class="card-sub">Выберите документы из общей базы знаний</div>
          </div>
        </div>
        <div class="form-panel">
          <div class="form-group">
            <label class="form-label">Название</label>
            <input v-model="title" class="form-input" placeholder="Например: Product research" />
          </div>
          <div class="form-group">
            <label class="form-label">Описание</label>
            <textarea
              v-model="description"
              class="form-input textarea"
              placeholder="Для чего эта подборка"
            ></textarea>
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
              Сначала загрузите и дождитесь индексации документов в базе знаний.
            </div>
          </div>

          <button
            class="btn btn-primary create-btn"
            type="button"
            :disabled="creating || !title.trim()"
            @click="createNotebook"
          >
            {{ creating ? 'Создаю...' : 'Создать ноутбук' }}
          </button>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">Мои ноутбуки</div>
            <div class="card-sub">Подборки документов для scoped chat</div>
          </div>
          <button class="btn btn-ghost btn-sm" type="button" @click="loadData">
            Обновить
          </button>
        </div>

        <div v-if="loading" class="empty">
          <div class="spinner"></div>
          <div class="empty-title">Загружаю ноутбуки</div>
        </div>

        <div v-else-if="notebooks.length === 0" class="empty">
          <div class="empty-title">Ноутбуков пока нет</div>
          <div class="empty-sub">Создайте первую подборку из готовых документов</div>
        </div>

        <div v-else class="notebook-list">
          <article v-for="notebook in notebooks" :key="notebook.id" class="notebook-card">
            <button class="notebook-open" type="button" @click="openNotebook(notebook.id)">
              <span>{{ notebook.title }}</span>
              <small>
                {{ notebook.documentCount }} документ(ов) · создан {{ notebook.createdLabel }}
              </small>
            </button>
            <button class="btn btn-ghost btn-sm" title="Удалить" @click="deleteNotebook(notebook.id)">
              <AppIcon name="trash" />
            </button>
          </article>
        </div>
      </div>
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
import { normalizeDocument } from '@/utils/documents'
import { buildNotebookRoute, normalizeNotebook } from '@/utils/notebooks'

const { apiFetch } = useApi()
const router = useRouter()
const settings = useSettingsStore()

const docs = ref([])
const notebooks = ref([])
const selectedDocumentIds = ref([])
const title = ref('')
const description = ref('')
const loading = ref(false)
const creating = ref(false)
const toast = ref(null)

const readyDocs = computed(() => docs.value.filter(doc => doc.status === 'done'))

watch(() => settings.apiKey, loadData, { immediate: true })

async function loadData() {
  if (!settings.isConnected) {
    docs.value = []
    notebooks.value = []
    return
  }
  loading.value = true
  try {
    const [docRows, notebookRows] = await Promise.all([
      apiFetch('/documents'),
      apiFetch('/notebooks'),
    ])
    docs.value = docRows.map(normalizeDocument)
    notebooks.value = notebookRows.map(normalizeNotebook)
  } catch (e) {
    toast.value = { msg: `Ошибка загрузки: ${e.message}`, type: 'error' }
  } finally {
    loading.value = false
  }
}

async function createNotebook() {
  if (!settings.isConnected) {
    toast.value = { msg: 'Задайте X-API-Key в настройках', type: 'error' }
    return
  }
  creating.value = true
  try {
    const data = await apiFetch('/notebooks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: title.value,
        description: description.value || null,
        document_ids: selectedDocumentIds.value,
      }),
    })
    notebooks.value = [normalizeNotebook(data), ...notebooks.value]
    title.value = ''
    description.value = ''
    selectedDocumentIds.value = []
    toast.value = { msg: 'Ноутбук создан', type: 'success' }
  } catch (e) {
    toast.value = { msg: `Ошибка создания: ${e.message}`, type: 'error' }
  } finally {
    creating.value = false
  }
}

async function deleteNotebook(id) {
  try {
    await apiFetch(`/notebooks/${id}`, { method: 'DELETE' })
    notebooks.value = notebooks.value.filter(notebook => notebook.id !== id)
  } catch (e) {
    toast.value = { msg: `Ошибка удаления: ${e.message}`, type: 'error' }
  }
}

function openNotebook(id) {
  router.push(buildNotebookRoute(id))
}
</script>

<style scoped>
.notebook-hero {
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
.notebook-eyebrow {
  margin-bottom: 6px;
  color: var(--accent);
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.notebook-hero h1 {
  margin: 0 0 8px;
  font-size: 24px;
  letter-spacing: -0.04em;
}
.notebook-hero p {
  max-width: 620px;
  color: var(--muted2);
  font-size: 13px;
  line-height: 1.6;
}
.notebook-stat {
  min-width: 120px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: color-mix(in oklch, var(--s2) 86%, transparent);
}
.notebook-stat span {
  display: block;
  color: var(--text);
  font-family: var(--mono);
  font-size: 20px;
  font-weight: 700;
}
.notebook-stat label {
  color: var(--muted);
  font-size: 11px;
}
.notebook-grid {
  display: grid;
  grid-template-columns: minmax(320px, 0.8fr) minmax(0, 1.2fr);
  gap: 14px;
}
.form-panel {
  padding: 16px 18px;
}
.textarea {
  min-height: 76px;
  resize: vertical;
}
.doc-picker {
  display: grid;
  gap: 8px;
  margin: 14px 0;
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
.create-btn {
  width: 100%;
  justify-content: center;
}
.notebook-list {
  display: grid;
  gap: 10px;
  padding: 14px;
}
.notebook-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: color-mix(in oklch, var(--s2) 74%, transparent);
}
.notebook-open {
  flex: 1;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text);
  cursor: pointer;
  font-family: var(--font);
  text-align: left;
}
.notebook-open span,
.notebook-open small {
  display: block;
}
.notebook-open small {
  margin-top: 4px;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10px;
}

@media (max-width: 900px) {
  .notebook-hero {
    flex-direction: column;
  }
  .notebook-grid {
    grid-template-columns: 1fr;
  }
}
</style>
