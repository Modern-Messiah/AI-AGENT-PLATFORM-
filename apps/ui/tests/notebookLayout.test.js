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
const desktopLayoutRule = viewSource.match(/\.notebook-detail\s*\{([^}]*)\}/)?.[1] || ''

test('notebook source list has a dedicated scrollable layout region', () => {
  assert.match(viewSource, /class="card sources-card"/)
  assert.match(viewSource, /\.notebook-detail\s*\{[^}]*display:\s*grid/s)
  assert.match(viewSource, /\.sources-card\s*\{[^}]*display:\s*flex/s)
  assert.match(viewSource, /\.source-list\s*\{[^}]*overflow-y:\s*auto/s)
})

test('desktop notebook detail remains vertically scrollable', () => {
  assert.match(desktopLayoutRule, /overflow-y:\s*auto/)
  assert.doesNotMatch(desktopLayoutRule, /overflow:\s*hidden/)
})

test('notebook sources card has a spacious adaptive height', () => {
  assert.match(
    viewSource,
    /@media \(min-width:\s*901px\)\s*\{\s*\.sources-card\s*\{\s*min-height:\s*clamp\(360px,\s*45vh,\s*560px\)/,
  )
})
