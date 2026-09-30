<template>
  <Teleport to="body">
    <div class="modal-overlay" @click.self="$emit('cancel')">
      <div class="modal scope-modal" role="dialog" aria-modal="true">
        <div class="scope-modal-header">
          <div class="scope-modal-icon">
            <AppIcon name="filter" :size="20" />
          </div>
          <div>
            <h2 class="scope-modal-title">{{ t('chat.scopeSelectTitle') }}</h2>
            <p class="scope-modal-sub">{{ t('chat.scopeSelectSub') }}</p>
          </div>
        </div>

        <div class="scope-tabs">
          <button
            type="button"
            class="scope-tab"
            :class="{ active: selectedType === 'global' }"
            @click="selectType('global')"
          >
            <span class="scope-tab-icon is-global"><AppIcon name="globe" :size="16" /></span>
            <div class="scope-tab-text">
              <strong>{{ t('chat.scopeOptionGlobal') }}</strong>
              <small>{{ t('chat.scopeOptionGlobalDesc') }}</small>
            </div>
          </button>

          <button
            type="button"
            class="scope-tab"
            :class="{ active: selectedType === 'document' }"
            @click="selectType('document')"
          >
            <span class="scope-tab-icon is-document"><AppIcon name="docs" :size="16" /></span>
            <div class="scope-tab-text">
              <strong>{{ t('chat.scopeOptionDocument') }}</strong>
              <small>{{ t('chat.scopeOptionDocumentDesc') }}</small>
            </div>
          </button>

          <button
            type="button"
            class="scope-tab"
            :class="{ active: selectedType === 'notebook' }"
            @click="selectType('notebook')"
          >
            <span class="scope-tab-icon is-notebook"><AppIcon name="book" :size="16" /></span>
            <div class="scope-tab-text">
              <strong>{{ t('chat.scopeOptionNotebook') }}</strong>
              <small>{{ t('chat.scopeOptionNotebookDesc') }}</small>
            </div>
          </button>
        </div>

        <!-- Document Picker Panel -->
        <div v-if="selectedType === 'document'" class="scope-subpanel">
          <div v-if="loading" class="scope-loading">{{ t('common.loading') }}</div>
          <div v-else-if="documents.length === 0" class="scope-empty">
            {{ t('chat.noDocumentsReady') }}
          </div>
          <div v-else class="scope-picker-wrap">
            <input
              v-model="searchQuery"
              type="text"
              class="form-input scope-search-input"
              :placeholder="t('chat.searchPlaceholder')"
              autofocus
            />
            <div class="scope-list">
              <div
                v-for="doc in filteredDocuments"
                :key="doc.id"
                class="scope-list-item"
                :class="{ selected: selectedDocId === doc.id }"
                @click="selectedDocId = doc.id"
              >
                <AppIcon name="docs" :size="14" />
                <span class="item-name" :title="doc.name">{{ doc.name }}</span>
                <span class="item-badge">{{ doc.size }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Notebook Picker Panel -->
        <div v-if="selectedType === 'notebook'" class="scope-subpanel">
          <div v-if="loading" class="scope-loading">{{ t('common.loading') }}</div>
          <div v-else-if="notebooks.length === 0" class="scope-empty">
            {{ t('chat.noNotebooksReady') }}
          </div>
          <div v-else class="scope-picker-wrap">
            <input
              v-model="searchQuery"
              type="text"
              class="form-input scope-search-input"
              :placeholder="t('chat.searchPlaceholder')"
              autofocus
            />
            <div class="scope-list">
              <div
                v-for="nb in filteredNotebooks"
                :key="nb.id"
                class="scope-list-item"
                :class="{ selected: selectedNotebookId === nb.id }"
                @click="selectedNotebookId = nb.id"
              >
                <AppIcon name="book" :size="14" />
                <span class="item-name" :title="nb.title">{{ nb.title }}</span>
                <span class="item-badge">{{ nb.documentCount }}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="scope-modal-actions">
          <button class="btn btn-ghost" type="button" @click="$emit('cancel')">
            {{ t('common.cancel') }}
          </button>
          <button
            class="btn btn-primary"
            type="button"
            :disabled="!canSubmit"
            @click="handleSubmit"
          >
            {{ t('chat.applyScope') }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import { useI18n } from '@/composables/useI18n'
import { useApi } from '@/composables/useApi'
import { normalizeDocument } from '@/utils/documents'
import { normalizeNotebook } from '@/utils/notebooks'

const props = defineProps({
  currentScope: {
    type: Object,
    default: () => ({ type: 'global', documentId: null, notebookId: null }),
  },
})

const emit = defineEmits(['select', 'cancel'])

const { t, locale } = useI18n()
const { apiFetch } = useApi()

const selectedType = ref(props.currentScope?.type || 'global')
const selectedDocId = ref(props.currentScope?.documentId || null)
const selectedNotebookId = ref(props.currentScope?.notebookId || null)
const searchQuery = ref('')
const loading = ref(false)
const documents = ref([])
const notebooks = ref([])

function selectType(type) {
  selectedType.value = type
  searchQuery.value = ''
  if (type === 'document' && !selectedDocId.value && documents.value.length > 0) {
    selectedDocId.value = documents.value[0].id
  }
  if (type === 'notebook' && !selectedNotebookId.value && notebooks.value.length > 0) {
    selectedNotebookId.value = notebooks.value[0].id
  }
}

const filteredDocuments = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return documents.value
  return documents.value.filter(doc => doc.name.toLowerCase().includes(q))
})

const filteredNotebooks = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return notebooks.value
  return notebooks.value.filter(nb => nb.title.toLowerCase().includes(q))
})

const canSubmit = computed(() => {
  if (selectedType.value === 'global') return true
  if (selectedType.value === 'document') return Boolean(selectedDocId.value)
  if (selectedType.value === 'notebook') return Boolean(selectedNotebookId.value)
  return false
})

async function loadData() {
  loading.value = true
  try {
    const [docsData, nbsData] = await Promise.all([
      apiFetch('/documents').catch(() => []),
      apiFetch('/notebooks').catch(() => []),
    ])
    documents.value = (Array.isArray(docsData) ? docsData : [])
      .filter(d => d.status === 'done')
      .map(d => normalizeDocument(d, locale.value))
    notebooks.value = (Array.isArray(nbsData) ? nbsData : [])
      .map(nb => normalizeNotebook(nb, locale.value))

    if (selectedType.value === 'document' && !selectedDocId.value && documents.value.length > 0) {
      selectedDocId.value = documents.value[0].id
    }
    if (selectedType.value === 'notebook' && !selectedNotebookId.value && notebooks.value.length > 0) {
      selectedNotebookId.value = notebooks.value[0].id
    }
  } finally {
    loading.value = false
  }
}

function handleSubmit() {
  if (!canSubmit.value) return
  if (selectedType.value === 'global') {
    emit('select', { type: 'global', documentId: null, notebookId: null, title: '' })
    return
  }
  if (selectedType.value === 'document') {
    const doc = documents.value.find(d => d.id === selectedDocId.value)
    emit('select', {
      type: 'document',
      documentId: selectedDocId.value,
      notebookId: null,
      title: doc?.name || '',
    })
    return
  }
  if (selectedType.value === 'notebook') {
    const nb = notebooks.value.find(n => n.id === selectedNotebookId.value)
    emit('select', {
      type: 'notebook',
      documentId: null,
      notebookId: selectedNotebookId.value,
      title: nb?.title || '',
    })
  }
}

function onKeydown(e) {
  if (e.key === 'Escape') emit('cancel')
}

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
  loadData()
})

onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
})
</script>

<style scoped>
.scope-modal {
  width: min(540px, 94vw);
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  padding: 22px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 18px;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.35);
  color: var(--text);
}

.scope-modal-header {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 18px;
}

.scope-modal-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: color-mix(in oklch, var(--accent) 15%, transparent);
  color: var(--accent);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.scope-modal-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
}

.scope-modal-sub {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--muted);
}

.scope-tabs {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}

.scope-tab {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border-radius: 12px;
  border: 1px solid var(--border);
  background: var(--s1);
  color: var(--text);
  cursor: pointer;
  text-align: left;
  transition: all 0.15s ease;
}

.scope-tab:hover {
  border-color: color-mix(in oklch, var(--accent) 45%, var(--border));
  background: color-mix(in oklch, var(--accent) 6%, var(--s1));
}

.scope-tab.active {
  border-color: var(--accent);
  background: color-mix(in oklch, var(--accent) 12%, var(--s1));
}

.scope-tab-icon {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: var(--s2);
}

.scope-tab-icon.is-global {
  color: var(--teal, var(--accent));
}

.scope-tab-icon.is-document {
  color: var(--purple, var(--accent));
}

.scope-tab-icon.is-notebook {
  color: var(--accent);
}

.scope-tab-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.scope-tab-text strong {
  font-size: 13px;
  color: var(--text);
}

.scope-tab-text small {
  font-size: 11px;
  color: var(--muted);
  line-height: 1.3;
}

.scope-subpanel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 150px;
  max-height: 220px;
  margin-bottom: 16px;
}

.scope-loading,
.scope-empty {
  padding: 24px;
  text-align: center;
  font-size: 12px;
  color: var(--muted);
  background: var(--s1);
  border-radius: 10px;
}

.scope-picker-wrap {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  flex: 1;
}

.scope-search-input {
  padding: 7px 10px;
  font-size: 12px;
  border-radius: 8px;
}

.scope-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  overflow-y: auto;
  max-height: 160px;
  padding-right: 4px;
}

.scope-list-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 8px;
  border: 1px solid transparent;
  background: var(--s1);
  color: var(--text);
  cursor: pointer;
  font-size: 12px;
  transition: all 0.12s;
}

.scope-list-item:hover {
  background: color-mix(in oklch, var(--accent) 8%, var(--s1));
  border-color: color-mix(in oklch, var(--accent) 30%, transparent);
}

.scope-list-item.selected {
  background: color-mix(in oklch, var(--accent) 15%, var(--s1));
  border-color: var(--accent);
  font-weight: 500;
}

.scope-list-item .item-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.scope-list-item .item-badge {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);
}

.scope-modal-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}
</style>
