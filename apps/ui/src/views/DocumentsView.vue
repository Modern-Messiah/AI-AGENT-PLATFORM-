<template>
  <div class="screen-body">
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
      <div class="drop-title">Перетащите файлы или нажмите для выбора</div>
      <div class="drop-sub">Файлы загружаются в MinIO и обрабатываются через IngestionWorkflow</div>
      <div class="drop-types">
        <span v-for="t in ['PDF','DOCX','TXT','MD','CSV','HTML']" :key="t" class="type-chip">.{{ t.toLowerCase() }}</span>
      </div>
      <input ref="fileInput" type="file" multiple style="display: none" @change="handleFileInput" />
    </div>

    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">Документы</div>
          <div class="card-sub">{{ doneCount }} из {{ docs.length }} проиндексировано</div>
        </div>
        <div style="display: flex; gap: 8px; align-items: center">
          <div v-if="docs.length" class="progress" style="width: 100px">
            <div class="progress-fill" :style="{ width: progressPct + '%' }"></div>
          </div>
          <button class="btn btn-ghost btn-sm" title="Очистить список" @click="clearAll">
            <AppIcon name="trash" :size="11" />
          </button>
        </div>
      </div>

      <div v-if="docs.length === 0" class="empty" style="padding: 40px">
        <div class="empty-icon">📂</div>
        <div class="empty-title">Нет документов</div>
        <div class="empty-sub">Загрузите файл выше для начала RAG-индексации</div>
      </div>
      <table v-else>
        <thead>
          <tr>
            <th>Файл</th><th>Статус</th><th>Размер</th><th>Загружен</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="doc in docs" :key="doc.id">
            <td>
              <div class="file-name">
                <div class="file-icon">{{ mimeIcon(doc.name) }}</div>
                <div>
                  <div>{{ doc.name }}</div>
                  <div v-if="doc.error" style="font-size: 11px; color: var(--red); margin-top: 2px">{{ doc.error }}</div>
                  <div style="font-size: 10px; color: var(--muted); font-family: var(--mono); margin-top: 1px">{{ doc.id }}</div>
                </div>
              </div>
            </td>
            <td>
              <div style="display: flex; align-items: center; gap: 8px">
                <StatusBadge :status="doc.status" />
                <div v-if="doc.status === 'processing'" class="spinner"></div>
              </div>
            </td>
            <td class="td-mono">{{ doc.size }}</td>
            <td class="td-mono">{{ doc.time }}</td>
            <td>
              <div style="display: flex; gap: 6px; justify-content: flex-end">
                <button class="btn btn-ghost btn-sm" title="Копировать ID" @click="copyId(doc.id)">
                  <AppIcon name="copy" />
                </button>
                <button class="btn btn-ghost btn-sm" title="Удалить" @click="removeDoc(doc.id)">
                  <AppIcon name="trash" />
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div style="font-size: 12px; color: var(--muted); display: flex; align-items: center; gap: 8px">
      <span style="font-family: var(--mono)">pgvector</span> · bge-small-en-v1.5 (384-dim) · HNSW index · cosine similarity
    </div>

    <AppToast v-if="toast" v-bind="toast" @done="toast = null" />
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useApi } from '@/composables/useApi'
import { useSettingsStore } from '@/stores/settings'
import AppIcon from '@/components/AppIcon.vue'
import AppToast from '@/components/AppToast.vue'
import StatusBadge from '@/components/StatusBadge.vue'

const { apiFetch } = useApi()
const settings = useSettingsStore()

const docs = ref([])
const dragging = ref(false)
const toast = ref(null)
const fileInput = ref(null)

function storageKey() {
  return settings.apiKey ? `aap_docs_${settings.apiKey}` : 'aap_docs'
}
function loadDocs() {
  try { docs.value = JSON.parse(localStorage.getItem(storageKey()) || '[]') } catch { docs.value = [] }
}
function persist() { localStorage.setItem(storageKey(), JSON.stringify(docs.value)) }

watch(() => settings.apiKey, loadDocs, { immediate: true })

const doneCount = computed(() => docs.value.filter(d => d.status === 'done').length)
const progressPct = computed(() => docs.value.length ? doneCount.value / docs.value.length * 100 : 0)
function mimeIcon(name) {
  const ext = (name || '').split('.').pop().toLowerCase()
  return ({ pdf: '📄', md: '📝', txt: '📃', csv: '📊', html: '🌐', docx: '📘' })[ext] || '📁'
}
function removeDoc(id) { docs.value = docs.value.filter(d => d.id !== id); persist() }
function clearAll() { docs.value = []; persist() }
function copyId(id) { navigator.clipboard.writeText(id).catch(() => {}); toast.value = { msg: `ID скопирован: ${id}`, type: 'info' } }

async function pollStatus(docId) {
  for (let i = 0; i < 30; i++) {
    await new Promise(r => setTimeout(r, 3000))
    try {
      const data = await apiFetch(`/documents/${docId}`)
      if (data.status === 'done') { updateDoc(docId, { status: 'done' }); return }
      if (data.status === 'failed') { updateDoc(docId, { status: 'failed', error: data.error || 'Failed' }); return }
    } catch {}
  }
  updateDoc(docId, { status: 'failed', error: 'Timeout' })
}

function updateDoc(id, patch) {
  docs.value = docs.value.map(d => d.id === id ? { ...d, ...patch } : d)
  persist()
}

async function uploadFile(file) {
  if (!settings.isConnected) { toast.value = { msg: 'Задайте X-API-Key в настройках', type: 'error' }; return }
  const tempId = 'upload-' + Date.now()
  const entry = {
    id: tempId, name: file.name, status: 'processing', time: 'сейчас', error: null,
    size: file.size < 1048576 ? (file.size / 1024).toFixed(0) + ' KB' : (file.size / 1048576).toFixed(1) + ' MB'
  }
  docs.value = [entry, ...docs.value]; persist()
  toast.value = { msg: `Загрузка: ${file.name}`, type: 'info' }
  try {
    const form = new FormData(); form.append('file', file)
    const data = await apiFetch('/documents', { method: 'POST', body: form })
    docs.value = docs.value.map(d => d.id === tempId ? { ...d, id: data.id } : d); persist()
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
