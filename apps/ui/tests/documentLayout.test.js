import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const viewSource = readFileSync(
  resolve(__dirname, '../src/views/DocumentDetailView.vue'),
  'utf8',
)
const documentsViewSource = readFileSync(
  resolve(__dirname, '../src/views/DocumentsView.vue'),
  'utf8',
)
const protectedAssetSource = readFileSync(
  resolve(__dirname, '../src/components/ProtectedAssetImage.vue'),
  'utf8',
)
const chatMessagesSource = readFileSync(
  resolve(__dirname, '../src/components/chat/ChatMessages.vue'),
  'utf8',
)
const i18nSource = readFileSync(
  resolve(__dirname, '../src/i18n/index.js'),
  'utf8',
)
const desktopDetailRule = viewSource.match(/\.document-detail\s*\{([^}]*)\}/)?.[1] || ''

test('document chunks list has a dedicated scrollable layout region', () => {
  assert.match(viewSource, /class="card chunks-card"/)
  assert.match(viewSource, /\.document-detail\s*\{[^}]*display:\s*grid/s)
  assert.match(viewSource, /\.chunks-card\s*\{[^}]*display:\s*flex/s)
  assert.match(viewSource, /\.chunks-list\s*\{[^}]*overflow-y:\s*auto/s)
})

test('desktop document detail remains vertically scrollable', () => {
  assert.match(desktopDetailRule, /overflow-y:\s*auto/)
  assert.doesNotMatch(desktopDetailRule, /overflow:\s*hidden/)
})

test('document chunks card matches the notebook sources height', () => {
  assert.match(
    viewSource,
    /@media \(min-width:\s*901px\)\s*\{\s*\.chunks-card\s*\{\s*min-height:\s*clamp\(520px,\s*55vh,\s*720px\)/,
  )
})

test('knowledge base file table does not render document insights inline', () => {
  assert.doesNotMatch(documentsViewSource, /doc-insights-row/)
  assert.doesNotMatch(documentsViewSource, /class="doc-summary"/)
  assert.doesNotMatch(documentsViewSource, /class="doc-questions"/)
})

test('knowledge base file table surfaces document warnings', () => {
  assert.match(documentsViewSource, /doc\.warnings\?\.length/)
  assert.match(documentsViewSource, /v-for="warning in doc\.warnings"/)
  assert.match(documentsViewSource, /class="document-warning"/)
})

test('knowledge base document deletion requires confirmation modal', () => {
  assert.match(documentsViewSource, /import ConfirmModal from ['"]@\/components\/ConfirmModal\.vue['"]/)
  assert.match(documentsViewSource, /const deleteConfirmDoc = ref\(null\)/)
  assert.match(documentsViewSource, /function askDeleteDoc\(doc\)/)
  assert.match(documentsViewSource, /async function confirmDeleteDoc\(\)/)
  assert.match(documentsViewSource, /<ConfirmModal\s+v-if="deleteConfirmDoc"/)
  assert.match(documentsViewSource, /@confirm="confirmDeleteDoc"/)
  assert.match(documentsViewSource, /@cancel="cancelDeleteDoc"/)
  assert.match(documentsViewSource, /@click="askDeleteDoc\(doc\)"/)
  assert.doesNotMatch(documentsViewSource, /@click="removeDoc\(doc\.id\)"/)
})

test('knowledge base file table scrolls inside its card', () => {
  assert.match(documentsViewSource, /class="card documents-memory-card"/)
  assert.match(documentsViewSource, /class="documents-table-scroll"/)
  assert.match(documentsViewSource, /class="documents-table"/)
  assert.match(documentsViewSource, /\.documents-memory-card\s*\{[^}]*display:\s*flex/s)
  assert.match(documentsViewSource, /\.documents-memory-card\s*\{[^}]*flex:\s*0 0 clamp\(460px,\s*48vh,\s*620px\)/s)
  assert.match(documentsViewSource, /\.documents-memory-card\s*\{[^}]*min-height:\s*460px/s)
  assert.match(documentsViewSource, /\.documents-memory-card\s*\{[^}]*max-height:\s*620px/s)
  assert.doesNotMatch(documentsViewSource, /\.documents-memory-card\s*\{[^}]*flex:\s*0 0 clamp\(340px,\s*35vh,\s*420px\)/s)
  assert.doesNotMatch(documentsViewSource, /\.documents-memory-card\s*\{[^}]*flex:\s*0 0 clamp\(230px,\s*25vh,\s*280px\)/s)
  assert.doesNotMatch(documentsViewSource, /\.documents-memory-card\s*\{[^}]*max-height:\s*420px/s)
  assert.doesNotMatch(documentsViewSource, /\.documents-memory-card\s*\{[^}]*max-height:\s*280px/s)
  assert.doesNotMatch(documentsViewSource, /\.documents-memory-card\s*\{[^}]*flex:\s*1 1 0/s)
  assert.doesNotMatch(documentsViewSource, /\.documents-memory-card\s*\{[^}]*min-height:\s*500px/s)
  assert.doesNotMatch(documentsViewSource, /\.documents-memory-card\s*\{[^}]*height:\s*clamp/s)
  assert.match(documentsViewSource, /\.documents-table-scroll\s*\{[^}]*flex:\s*1 1 auto/s)
  assert.match(documentsViewSource, /\.documents-table-scroll\s*\{[^}]*overflow-y:\s*auto/s)
  assert.match(documentsViewSource, /\.documents-table-scroll\s*\{[^}]*overflow-x:\s*hidden/s)
  assert.match(documentsViewSource, /\.documents-table-scroll table\s*\{[^}]*table-layout:\s*fixed/s)
  assert.match(documentsViewSource, /\.documents-table-scroll table\s*\{[^}]*min-width:\s*0/s)
  assert.match(documentsViewSource, /\.documents-col-status\s*\{[^}]*width:\s*148px/s)
  assert.match(documentsViewSource, /\.documents-col-size\s*\{[^}]*width:\s*82px/s)
  assert.match(documentsViewSource, /class="documents-actions-cell"/)
  assert.match(documentsViewSource, /\.documents-col-actions\s*\{[^}]*width:\s*154px/s)
  assert.match(documentsViewSource, /\.documents-actions-cell\s*\{[^}]*padding-left:\s*6px/s)
  assert.match(documentsViewSource, /\.document-row-actions \.btn-sm\s*\{[^}]*width:\s*36px/s)
  assert.match(documentsViewSource, /\.document-row-actions \.btn-sm\s*\{[^}]*padding:\s*0/s)
  assert.match(documentsViewSource, /\.document-status-line\s*\{[^}]*min-width:\s*0/s)
  assert.doesNotMatch(documentsViewSource, /\.documents-col-actions\s*\{[^}]*width:\s*132px/s)
  assert.doesNotMatch(documentsViewSource, /\.documents-col-status\s*\{[^}]*width:\s*118px/s)
  assert.doesNotMatch(documentsViewSource, /documents\.copyId/)
  assert.doesNotMatch(documentsViewSource, /@click="copyId\(doc\.id\)"/)
  assert.doesNotMatch(documentsViewSource, /function copyId\(/)
  assert.match(documentsViewSource, /\.documents-table-scroll \.file-name\s*\{[^}]*min-width:\s*0/s)
  assert.match(documentsViewSource, /\.source-url-text\s*\{[^}]*text-overflow:\s*ellipsis/s)
  assert.doesNotMatch(documentsViewSource, /\.documents-table-scroll\s*\{[^}]*overflow-x:\s*auto/s)
  assert.doesNotMatch(documentsViewSource, /\.documents-table-scroll table\s*\{[^}]*min-width:\s*860px/s)
  assert.match(documentsViewSource, /\.documents-table-scroll thead\s*\{[^}]*position:\s*sticky/s)
})

test('knowledge base hides implementation footer text', () => {
  assert.doesNotMatch(documentsViewSource, /pgvector/)
  assert.doesNotMatch(documentsViewSource, /multi-document citations/)
  assert.doesNotMatch(documentsViewSource, /page-aware PDF parsing/)
  assert.doesNotMatch(documentsViewSource, /semantic cache invalidation/)
})

test('knowledge base file table scrollbar uses subdued theme colors', () => {
  const thumbRule = documentsViewSource.match(
    /\.documents-table-scroll::-webkit-scrollbar-thumb\s*\{([^}]*)\}/s,
  )?.[1] || ''

  assert.match(thumbRule, /var\(--muted2\)/)
  assert.doesNotMatch(thumbRule, /var\(--accent\)/)
})

test('URL source input uses themed field styling', () => {
  assert.match(documentsViewSource, /class="url-source-input"/)
  assert.match(documentsViewSource, /\.url-source-input\s*\{[^}]*background:\s*[\s\S]*var\(--s2\)/)
  assert.match(documentsViewSource, /\.url-source-input\s*\{[^}]*border:\s*1px solid var\(--border\)/s)
  assert.match(documentsViewSource, /\.url-source-input:focus\s*\{[^}]*var\(--accent\)/s)
})

test('URL source add button keeps a themed disabled state', () => {
  assert.match(documentsViewSource, /class="btn btn-ghost url-add-btn"/)
  assert.match(documentsViewSource, /\.url-add-btn:disabled\s*\{[^}]*border-color:\s*var\(--border\)/s)
  assert.match(documentsViewSource, /\.url-add-btn:disabled\s*\{[^}]*background:\s*transparent/s)
  assert.match(documentsViewSource, /\.url-add-btn:disabled\s*\{[^}]*color:\s*var\(--muted2\)/s)
  assert.doesNotMatch(documentsViewSource, /class="btn url-add-btn"/)
  assert.doesNotMatch(documentsViewSource, /\.url-add-btn:disabled\s*\{[^}]*background:\s*color-mix\(in oklch,\s*var\(--s1\)/s)
  assert.doesNotMatch(documentsViewSource, /\.url-add-btn:disabled\s*\{[^}]*background:\s*#[0-9a-fA-F]{3,6}/s)
})

test('GitHub URL sources reuse the URL panel and source badge', () => {
  assert.match(documentsViewSource, /urlCheck\.source_type === "github"/)
  assert.match(documentsViewSource, /documents\.githubReady/)
  assert.match(documentsViewSource, /documents\.githubBadge/)
  assert.match(documentsViewSource, /function isExternalSource\(doc\)/)
  assert.match(documentsViewSource, /files:\s*urlCheck\.file_count/)
  assert.match(documentsViewSource, /images:\s*urlCheck\.image_count/)
  assert.match(i18nSource, /GitHub source detected: found \{files\} useful files, \{images\} images/)
})

test('external documents show last checked and reindex result states', () => {
  assert.match(documentsViewSource, /doc\.sourceCheckedLabel/)
  assert.match(documentsViewSource, /documents\.sourceCheckedAt/)
  assert.match(documentsViewSource, /doc\._reindexing/)
  assert.match(documentsViewSource, /documents\.reindexUpdating/)
  assert.match(documentsViewSource, /documents\.reindexUpdated/)
  assert.match(documentsViewSource, /documents\.reindexNoChanges/)
  assert.match(documentsViewSource, /workflow_started/)
  assert.match(documentsViewSource, /changed/)
  assert.match(i18nSource, /Изменений не найдено/)
  assert.match(i18nSource, /No changes found/)
})

test('knowledge base document list can load additional pages', () => {
  assert.match(documentsViewSource, /const DOCUMENT_PAGE_SIZE = 100/)
  assert.match(documentsViewSource, /documentsLoadedCount/)
  assert.match(documentsViewSource, /documentsHasMore/)
  assert.match(documentsViewSource, /function documentListPath\(offset\)/)
  assert.match(documentsViewSource, /`\/documents\?limit=\$\{DOCUMENT_PAGE_SIZE \+ 1\}&offset=\$\{offset\}`/)
  assert.match(documentsViewSource, /async function loadMoreDocuments\(\)/)
  assert.match(documentsViewSource, /class="load-more-row"/)
  assert.match(documentsViewSource, /documents\.loadMore/)
  assert.match(i18nSource, /Показать ещё/)
  assert.match(i18nSource, /Load more/)
})

test('document status polling refreshes immediately and clears pending final states', () => {
  assert.match(
    documentsViewSource,
    /for\s*\(let i = 0; i < 120; i\+\+\)\s*\{\s*if\s*\(i > 0\)\s*await new Promise\(\(?r\)?\s*=> setTimeout\(r,\s*5000\)\)/s,
  )
  assert.doesNotMatch(
    documentsViewSource,
    /for\s*\(let i = 0; i < 120; i\+\+\)\s*\{\s*await new Promise\(\(?r\)?\s*=> setTimeout\(r,\s*5000\)\)/s,
  )

  const doneIndex = documentsViewSource.search(/if\s*\(\s*data\.status\s*===\s*['"]done['"]\s*\)/)
  const failedIndex = documentsViewSource.search(/if\s*\(\s*data\.status\s*===\s*['"]failed['"]\s*\)/)
  const pendingIndex = documentsViewSource.search(
    /updateDoc\s*\(\s*docId\s*,\s*\{\s*\.\.\.normalized,\s*_pending:\s*true,\s*_reindexing:\s*Boolean\(options\.reindex\),\s*\}\s*\)/,
  )

  assert.notEqual(doneIndex, -1)
  assert.notEqual(failedIndex, -1)
  assert.notEqual(pendingIndex, -1)
  assert.ok(doneIndex < pendingIndex)
  assert.ok(failedIndex < pendingIndex)
})

test('knowledge base accepts image sources and shows page progress', () => {
  assert.match(documentsViewSource, /accept="[^"]*image\/png[^"]*image\/jpeg[^"]*image\/webp/)
  assert.match(documentsViewSource, /doc\.processedPages/)
  assert.match(documentsViewSource, /doc\.totalPages/)
})

test('document detail does not show a visual asset gallery', () => {
  assert.doesNotMatch(viewSource, /apiFetch\(`\/documents\/\$\{documentId\.value\}\/assets`\)/)
  assert.doesNotMatch(viewSource, /<ProtectedAssetImage/)
  assert.doesNotMatch(viewSource, /class="asset-gallery"/)
  assert.doesNotMatch(i18nSource, /Распознанные страницы и изображения/)
  assert.doesNotMatch(i18nSource, /Recognized pages and images/)
})

test('chat citation details do not show image previews', () => {
  assert.doesNotMatch(chatMessagesSource, /<ProtectedAssetImage/)
  assert.doesNotMatch(chatMessagesSource, /class="citation-preview"/)
  assert.doesNotMatch(chatMessagesSource, /\.citation-preview/)
})

test('protected asset preview aborts stale authenticated image requests', () => {
  assert.match(protectedAssetSource, /new AbortController\(\)/)
  assert.match(protectedAssetSource, /signal:\s*controller\.signal/)
  assert.match(protectedAssetSource, /requestController\s*===\s*controller/)
  assert.match(protectedAssetSource, /requestController\?\.abort\(\)/)
})

test('protected asset previews load lazily for documents with many pages', () => {
  assert.match(protectedAssetSource, /new globalThis\.IntersectionObserver/)
  assert.match(protectedAssetSource, /rootMargin:\s*'200px'/)
  assert.match(protectedAssetSource, /if \(!visible\.value\)/)
})
