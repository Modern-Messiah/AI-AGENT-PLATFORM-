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

test('document chunks list has a dedicated scrollable layout region', () => {
  assert.match(viewSource, /class="card chunks-card"/)
  assert.match(viewSource, /\.document-detail\s*\{[^}]*display:\s*grid/s)
  assert.match(viewSource, /\.chunks-card\s*\{[^}]*display:\s*flex/s)
  assert.match(viewSource, /\.chunks-list\s*\{[^}]*overflow-y:\s*auto/s)
})

test('knowledge base file table does not render document insights inline', () => {
  assert.doesNotMatch(documentsViewSource, /doc-insights-row/)
  assert.doesNotMatch(documentsViewSource, /class="doc-summary"/)
  assert.doesNotMatch(documentsViewSource, /class="doc-questions"/)
})
