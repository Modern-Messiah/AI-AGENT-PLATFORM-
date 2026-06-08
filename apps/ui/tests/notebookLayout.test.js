import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const viewSource = readFileSync(
  resolve(__dirname, '../src/views/NotebookDetailView.vue'),
  'utf8',
)

test('notebook source list has a dedicated scrollable layout region', () => {
  assert.match(viewSource, /class="card sources-card"/)
  assert.match(viewSource, /\.notebook-detail\s*\{[^}]*display:\s*grid/s)
  assert.match(viewSource, /\.sources-card\s*\{[^}]*display:\s*flex/s)
  assert.match(viewSource, /\.source-list\s*\{[^}]*overflow-y:\s*auto/s)
})
