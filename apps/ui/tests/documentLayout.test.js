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

test('knowledge base accepts image sources and shows page progress', () => {
  assert.match(documentsViewSource, /accept="[^"]*image\/png[^"]*image\/jpeg[^"]*image\/webp/)
  assert.match(documentsViewSource, /doc\.processedPages/)
  assert.match(documentsViewSource, /doc\.totalPages/)
})

test('document detail loads visual assets through the protected preview component', () => {
  assert.match(viewSource, /apiFetch\(`\/documents\/\$\{documentId\.value\}\/assets`\)/)
  assert.match(viewSource, /<ProtectedAssetImage/)
  assert.match(viewSource, /class="asset-gallery"/)
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
