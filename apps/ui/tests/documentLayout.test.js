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

test('knowledge base file table scrolls inside its card', () => {
  assert.match(documentsViewSource, /class="card documents-memory-card"/)
  assert.match(documentsViewSource, /class="documents-table-scroll"/)
  assert.match(documentsViewSource, /\.documents-memory-card\s*\{[^}]*display:\s*flex/s)
  assert.match(documentsViewSource, /\.documents-memory-card\s*\{[^}]*height:\s*clamp\(440px,\s*62vh,\s*760px\)/s)
  assert.match(documentsViewSource, /\.documents-table-scroll\s*\{[^}]*flex:\s*1 1 auto/s)
  assert.match(documentsViewSource, /\.documents-table-scroll\s*\{[^}]*overflow-y:\s*auto/s)
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
