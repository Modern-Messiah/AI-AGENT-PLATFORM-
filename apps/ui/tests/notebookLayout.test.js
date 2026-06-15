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
const listViewSource = readFileSync(
  resolve(__dirname, '../src/views/NotebooksView.vue'),
  'utf8',
)
const desktopLayoutRule = viewSource.match(/\.notebook-detail\s*\{([^}]*)\}/)?.[1] || ''

test('notebook source list has a dedicated scrollable layout region', () => {
  assert.match(viewSource, /class="card sources-card"/)
  assert.match(viewSource, /\.notebook-detail\s*\{[^}]*display:\s*grid/s)
  assert.match(viewSource, /\.sources-card\s*\{[^}]*display:\s*flex/s)
  assert.match(viewSource, /\.source-list\s*\{[^}]*overflow-y:\s*auto/s)
  assert.match(viewSource, /\.source-list\s*\{[^}]*align-content:\s*start/s)
  assert.match(viewSource, /\.source-list\s*\{[^}]*grid-auto-rows:\s*max-content/s)
})

test('desktop notebook detail remains vertically scrollable', () => {
  assert.match(desktopLayoutRule, /overflow-y:\s*auto/)
  assert.doesNotMatch(desktopLayoutRule, /overflow:\s*hidden/)
})

test('notebook sources card has a spacious adaptive height', () => {
  assert.match(
    viewSource,
    /@media \(min-width:\s*901px\)\s*\{\s*\.sources-card\s*\{\s*min-height:\s*clamp\(520px,\s*55vh,\s*720px\)/,
  )
})

test('notebook source cards stay compact', () => {
  assert.doesNotMatch(viewSource, /class="source-summary/)
  assert.doesNotMatch(viewSource, /class="source-questions"/)
  assert.doesNotMatch(viewSource, /Summary появится после индексации источника/)
})

test('notebook overview explains generated sections and chat questions', () => {
  assert.match(viewSource, /t\('notebookDetail\.summary'\)/)
  assert.match(viewSource, /t\('notebookDetail\.topics'\)/)
  assert.match(viewSource, /t\('notebookDetail\.questions'\)/)
  assert.match(viewSource, /t\('notebookDetail\.questionsHint'\)/)
})


test('notebook topic preview has airy spacing around wrapped tags', () => {
  assert.match(
    listViewSource,
    /\.notebook-open \.topic-preview\s*\{[^}]*display:\s*flex[^}]*gap:\s*9px 10px[^}]*margin-top:\s*24px/s,
  )
})


test('desktop notebook collection keeps its header fixed and scrolls the list', () => {
  assert.match(listViewSource, /class="card notebook-collection"/)
  assert.match(
    listViewSource,
    /@media \(min-width:\s*901px\)\s*\{[^}]*\.notebook-collection\s*\{[^}]*height:\s*clamp\(560px,\s*65vh,\s*760px\)/s,
  )
  assert.match(
    listViewSource,
    /\.notebook-collection\s*\{[^}]*display:\s*flex[^}]*flex-direction:\s*column/s,
  )
  assert.match(
    listViewSource,
    /\.notebook-collection \.notebook-list\s*\{[^}]*overflow-y:\s*auto/s,
  )
})
