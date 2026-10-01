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
            <button
              v-if="documentsHasMore"
              class="btn btn-ghost load-more-inline"
              type="button"
              :disabled="documentsLoadingMore"
              @click="loadMoreDocuments"
            >
              {{ documentsLoadingMore ? t('notebooks.loadingMoreDocuments') : t('notebooks.loadMoreDocuments') }}
            </button>
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
            <div class="card-title">
              {{ notebookScope === 'mine' ? t('notebooks.mine') : t('notebooks.sharedTitle') }}
            </div>
            <div class="card-sub">{{ t('notebooks.mineSub') }}</div>
          </div>
          <div style="display: flex; gap: 8px; align-items: center">
            <div v-if="session.isAuthenticated" class="scope-control">
              <button
                type="button"
                class="scope-btn"
                :class="{ active: notebookScope === 'mine' }"
                @click="notebookScope = 'mine'"
              >
                <AppIcon name="user" :size="12" />
                {{ t('documents.scopeMine') }}
              </button>
              <button
                type="button"
                class="scope-btn"
                :class="{ active: notebookScope === 'shared' }"
                @click="notebookScope = 'shared'"
              >
                <AppIcon name="users" :size="12" />
                {{ t('documents.scopeShared') }}
              </button>
            </div>
            <button class="btn btn-ghost btn-sm" type="button" @click="loadData">
              {{ t('common.refresh') }}
            </button>
          </div>
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
          <div v-if="notebooksHasMore" class="load-more-row">
            <button
              class="btn btn-ghost"
              type="button"
              :disabled="notebooksLoadingMore"
              @click="loadMoreNotebooks"
            >
              {{ notebooksLoadingMore ? t('notebooks.loadingMoreNotebooks') : t('notebooks.loadMoreNotebooks') }}
            </button>
          </div>
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
import { useSessionStore } from '@/stores/session'
import { useI18n } from '@/composables/useI18n'
import AppIcon from '@/components/AppIcon.vue'
import AppToast from '@/components/AppToast.vue'
import { normalizeDocument } from '@/utils/documents'
import { buildNotebookRoute, normalizeNotebook } from '@/utils/notebooks'

const { apiFetch } = useApi()
const router = useRouter()
const settings = useSettingsStore()
const session = useSessionStore()
const { t } = useI18n()

const DOCUMENT_PICKER_PAGE_SIZE = 100
const NOTEBOOK_PAGE_SIZE = 50
const docs = ref([])
const notebooks = ref([])
const selectedDocumentIds = ref([])
const title = ref('')
const description = ref('')
const loading = ref(false)
const creating = ref(false)
const toast = ref(null)
const documentsLoadedCount = ref(0)
const documentsHasMore = ref(false)
const documentsLoadingMore = ref(false)
const notebooksLoadedCount = ref(0)
const notebooksHasMore = ref(false)
const notebooksLoadingMore = ref(false)

// Personal knowledge base: notebooks default to the user's own; the
// document picker always shows everything the user may attach.
const notebookScope = ref(
  localStorage.getItem('aap_notebooks_scope')
    || (session.isAuthenticated ? 'mine' : 'shared'),
)
watch(notebookScope, value => localStorage.setItem('aap_notebooks_scope', value))
const currentUserId = computed(() => session.user?.user_id || null)

const readyDocs = computed(() => docs.value.filter(doc => doc.status === 'done'))

watch(
  [() => settings.credentialKey, () => settings.locale, notebookScope],
  loadData,
  { immediate: true },
)

function documentListPath(offset) {
  return `/documents?limit=${DOCUMENT_PICKER_PAGE_SIZE + 1}&offset=${offset}`
}

function notebookListPath(offset) {
  return `/notebooks?limit=${NOTEBOOK_PAGE_SIZE + 1}&offset=${offset}&scope=${notebookScope.value}`
}

function appendUniqueById(existing, incoming) {
  const seen = new Set(existing.map(item => item.id))
  return [
    ...existing,
    ...incoming.filter(item => {
      if (seen.has(item.id)) return false
      seen.add(item.id)
      return true
    }),
  ]
}

async function loadData() {
  if (!settings.isConnected) {
    docs.value = []
    notebooks.value = []
    documentsLoadedCount.value = 0
    documentsHasMore.value = false
    notebooksLoadedCount.value = 0
    notebooksHasMore.value = false
    return
  }
  loading.value = true
  try {
    const [docRows, notebookRows] = await Promise.all([
      apiFetch(documentListPath(0)),
      apiFetch(notebookListPath(0)),
    ])
    const documentPage = docRows.slice(0, DOCUMENT_PICKER_PAGE_SIZE)
    const notebookPage = notebookRows.slice(0, NOTEBOOK_PAGE_SIZE)
    docs.value = documentPage.map(doc => normalizeDocument(doc, settings.locale, currentUserId.value))
    notebooks.value = notebookPage.map(notebook => normalizeNotebook(notebook, settings.locale, currentUserId.value))
    documentsLoadedCount.value = documentPage.length
    documentsHasMore.value = docRows.length > DOCUMENT_PICKER_PAGE_SIZE
    notebooksLoadedCount.value = notebookPage.length
    notebooksHasMore.value = notebookRows.length > NOTEBOOK_PAGE_SIZE
  } catch (e) {
    toast.value = { msg: t('notebooks.loadError', { message: e.message }), type: 'error' }
  } finally {
    loading.value = false
  }
}

async function loadMoreDocuments() {
  if (documentsLoadingMore.value || !documentsHasMore.value) return
  documentsLoadingMore.value = true
  try {
    const docRows = await apiFetch(documentListPath(documentsLoadedCount.value))
    const documentPage = docRows.slice(0, DOCUMENT_PICKER_PAGE_SIZE)
    docs.value = appendUniqueById(
      docs.value,
      documentPage.map(doc => normalizeDocument(doc, settings.locale)),
    )
    documentsLoadedCount.value += documentPage.length
    documentsHasMore.value = docRows.length > DOCUMENT_PICKER_PAGE_SIZE
  } catch (e) {
    toast.value = { msg: t('notebooks.loadMoreDocumentsError', { message: e.message }), type: 'error' }
  } finally {
    documentsLoadingMore.value = false
  }
}

async function loadMoreNotebooks() {
  if (notebooksLoadingMore.value || !notebooksHasMore.value) return
  notebooksLoadingMore.value = true
  try {
    const notebookRows = await apiFetch(notebookListPath(notebooksLoadedCount.value))
    const notebookPage = notebookRows.slice(0, NOTEBOOK_PAGE_SIZE)
    notebooks.value = appendUniqueById(
      notebooks.value,
      notebookPage.map(notebook => normalizeNotebook(notebook, settings.locale, currentUserId.value)),
    )
    notebooksLoadedCount.value += notebookPage.length
    notebooksHasMore.value = notebookRows.length > NOTEBOOK_PAGE_SIZE
  } catch (e) {
    toast.value = { msg: t('notebooks.loadMoreNotebooksError', { message: e.message }), type: 'error' }
  } finally {
    notebooksLoadingMore.value = false
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
    notebooks.value = [normalizeNotebook(data, settings.locale, currentUserId.value), ...notebooks.value]
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
.scope-control {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  border: 1px solid color-mix(in oklch, var(--border) 80%, transparent);
  border-radius: 8px;
  background: color-mix(in oklch, var(--s2) 65%, var(--s1));
}
.scope-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--muted2);
  font-family: var(--font);
  font-size: 11.5px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s cubic-bezier(0.16, 1, 0.3, 1);
  user-select: none;
}
.scope-btn:hover {
  color: var(--text);
}
.scope-btn.active {
  background: var(--s1);
  color: var(--text);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.15), inset 0 1px 0 rgba(255, 255, 255, 0.05);
}
.scope-btn:active {
  transform: scale(0.96);
}
.notebook-hero {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  padding: 20px 22px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background:
    radial-gradient(circle at 10% 0%, color-mix(in oklch, var(--purple) 18%, transparent), transparent 28%),
    var(--s1);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.05);
}
.notebook-eyebrow {
  margin-bottom: 6px;
  color: var(--accent);
  font-family: var(--mono);
  font-size: 10.5px;
  letter-spacing: 0.06em;
  font-weight: 600;
  text-transform: uppercase;
}
.notebook-hero h1 {
  margin: 0 0 8px;
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.025em;
}
.notebook-hero p {
  max-width: 620px;
  color: var(--muted2);
  font-size: 13px;
  line-height: 1.6;
}
.notebook-stat {
  min-width: 120px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: color-mix(in oklch, var(--s2) 86%, transparent);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
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
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--s2);
  cursor: pointer;
  transition: all 0.15s cubic-bezier(0.16, 1, 0.3, 1);
  user-select: none;
}
.doc-option:hover {
  background: color-mix(in oklch, var(--s2) 70%, var(--s3));
  border-color: color-mix(in oklch, var(--accent) 30%, var(--border));
}
.doc-option:active {
  transform: scale(0.98);
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
.load-more-inline {
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
.load-more-row {
  display: flex;
  justify-content: center;
  padding: 4px 0 2px;
}
.load-more-row .btn {
  min-width: 160px;
  justify-content: center;
}
.notebook-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: color-mix(in oklch, var(--s2) 74%, transparent);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  transition: all 0.15s cubic-bezier(0.16, 1, 0.3, 1);
}
.notebook-card:hover {
  border-color: color-mix(in oklch, var(--accent) 32%, var(--border));
  background: color-mix(in oklch, var(--s2) 90%, transparent);
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.08);
}
.notebook-card .btn-ghost.btn-sm:active {
  transform: scale(0.93);
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
