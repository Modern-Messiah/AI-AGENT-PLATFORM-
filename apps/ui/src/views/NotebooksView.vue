<template>
  <div class="screen-body">
    <div class="notebook-hero">
      <div>
        <div class="notebook-eyebrow">{{ t('notebooks.eyebrow') }}</div>
        <h1>{{ t('notebooks.title') }}</h1>
        <p>{{ t('notebooks.description') }}</p>
      </div>
      <div class="notebook-stat">
        <span>{{ notebooks.length }}</span>
        <label>{{ t('notebooks.collections') }}</label>
      </div>
    </div>

    <div class="notebook-grid">
      <div class="card notebook-create">
        <div class="card-header">
          <div>
            <div class="card-title">{{ t('notebooks.newTitle') }}</div>
            <div class="card-sub">{{ t('notebooks.newSub') }}</div>
          </div>
        </div>
        <div class="form-panel">
          <div class="form-group">
            <label class="form-label">{{ t('notebooks.name') }}</label>
            <input v-model="title" class="form-input" :placeholder="t('notebooks.namePlaceholder')" />
          </div>
          <div class="form-group">
            <label class="form-label">{{ t('notebooks.descriptionLabel') }}</label>
            <textarea
              v-model="description"
              class="form-input textarea"
              :placeholder="t('notebooks.descriptionPlaceholder')"
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
              {{ t('notebooks.noReadyDocs') }}
            </div>
          </div>

          <button
            class="btn btn-primary create-btn"
            type="button"
            :disabled="creating || !title.trim()"
            @click="createNotebook"
          >
            {{ creating ? t('notebooks.creating') : t('notebooks.create') }}
          </button>
        </div>
      </div>

      <div class="card notebook-collection">
        <div class="card-header">
          <div>
            <div class="card-title">{{ t('notebooks.mine') }}</div>
            <div class="card-sub">{{ t('notebooks.mineSub') }}</div>
          </div>
          <button class="btn btn-ghost btn-sm" type="button" @click="loadData">
            {{ t('common.refresh') }}
          </button>
        </div>

        <div v-if="loading" class="empty">
          <div class="spinner"></div>
          <div class="empty-title">{{ t('notebooks.loading') }}</div>
        </div>

        <div v-else-if="notebooks.length === 0" class="empty">
          <div class="empty-title">{{ t('notebooks.empty') }}</div>
          <div class="empty-sub">{{ t('notebooks.emptySub') }}</div>
        </div>

        <div v-else class="notebook-list">
          <article v-for="notebook in notebooks" :key="notebook.id" class="notebook-card">
            <button class="notebook-open" type="button" @click="openNotebook(notebook.id)">
              <span>{{ notebook.title }}</span>
              <small>
                {{ t('notebooks.documentCount', { count: notebook.documentCount, date: notebook.createdLabel }) }}
              </small>
              <em v-if="notebook.summary">{{ notebook.summary }}</em>
              <span v-if="notebook.keyTopics.length" class="topic-preview">
                <strong v-for="topic in notebook.keyTopics.slice(0, 4)" :key="topic">
                  {{ topic }}
                </strong>
              </span>
            </button>
            <button class="btn btn-ghost btn-sm" :title="t('common.delete')" @click="deleteNotebook(notebook.id)">
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
import { useI18n } from '@/composables/useI18n'
import AppIcon from '@/components/AppIcon.vue'
import AppToast from '@/components/AppToast.vue'
import { normalizeDocument } from '@/utils/documents'
import { buildNotebookRoute, normalizeNotebook } from '@/utils/notebooks'

const { apiFetch } = useApi()
const router = useRouter()
const settings = useSettingsStore()
const { t } = useI18n()

const docs = ref([])
const notebooks = ref([])
const selectedDocumentIds = ref([])
const title = ref('')
const description = ref('')
const loading = ref(false)
const creating = ref(false)
const toast = ref(null)

const readyDocs = computed(() => docs.value.filter(doc => doc.status === 'done'))

watch([() => settings.apiKey, () => settings.locale], loadData, { immediate: true })

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
    docs.value = docRows.map(doc => normalizeDocument(doc, settings.locale))
    notebooks.value = notebookRows.map(notebook => normalizeNotebook(notebook, settings.locale))
  } catch (e) {
    toast.value = { msg: t('notebooks.loadError', { message: e.message }), type: 'error' }
  } finally {
    loading.value = false
  }
}

async function createNotebook() {
  if (!settings.isConnected) {
    toast.value = { msg: t('documents.apiKeyRequired'), type: 'error' }
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
    notebooks.value = [normalizeNotebook(data, settings.locale), ...notebooks.value]
    title.value = ''
    description.value = ''
    selectedDocumentIds.value = []
    toast.value = { msg: t('notebooks.created'), type: 'success' }
  } catch (e) {
    toast.value = { msg: t('notebooks.createError', { message: e.message }), type: 'error' }
  } finally {
    creating.value = false
  }
}

async function deleteNotebook(id) {
  try {
    await apiFetch(`/notebooks/${id}`, { method: 'DELETE' })
    notebooks.value = notebooks.value.filter(notebook => notebook.id !== id)
  } catch (e) {
    toast.value = { msg: t('notebooks.deleteError', { message: e.message }), type: 'error' }
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
.notebook-create {
  display: flex;
  min-height: 0;
  flex-direction: column;
}
.notebook-create .form-panel {
  display: flex;
  min-height: 0;
  flex-direction: column;
  flex: 1;
}
.textarea {
  min-height: 76px;
  resize: vertical;
}
.doc-picker {
  display: grid;
  align-content: start;
  flex: 1 1 auto;
  gap: 8px;
  max-height: clamp(260px, 32vh, 420px);
  margin: 14px 0;
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
  scrollbar-color: color-mix(in oklch, var(--muted2) 42%, var(--border2)) transparent;
  scrollbar-width: thin;
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
  align-content: start;
  gap: 10px;
  min-height: 0;
  padding: 14px;
}
.notebook-collection {
  display: flex;
  min-height: 0;
  flex-direction: column;
}
.notebook-collection .notebook-list {
  overflow-y: auto;
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
.notebook-open small,
.notebook-open em {
  display: block;
}
.notebook-open small {
  margin-top: 4px;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10px;
}
.notebook-open em {
  margin-top: 8px;
  color: var(--muted2);
  font-size: 12px;
  font-style: normal;
  line-height: 1.45;
}
.notebook-open .topic-preview {
  display: flex;
  flex-wrap: wrap;
  gap: 9px 10px;
  margin-top: 24px;
}
.topic-preview strong {
  padding: 3px 6px;
  border-radius: 999px;
  background: color-mix(in oklch, var(--accent) 10%, transparent);
  color: var(--accent);
  font-family: var(--mono);
  font-size: 9px;
  font-weight: 500;
}

@media (min-width: 901px) {
  .notebook-create,
  .notebook-collection {
    height: clamp(560px, 65vh, 760px);
  }
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
