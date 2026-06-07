import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildDocumentRoute,
  buildQuestionRoute,
  canReindexDocument,
  knowledgeBaseStats,
  normalizeDocument,
} from '../src/utils/documents.js'


test('normalizes API documents for the knowledge-base table', () => {
  const doc = normalizeDocument({
    id: 'doc-1',
    filename: 'manual.pdf',
    status: 'done',
    size_bytes: 1536,
    created_at: '2026-06-07T09:00:00Z',
    summary: 'Short summary.',
    suggested_questions: ['Что внутри manual.pdf?'],
  })

  assert.equal(doc.id, 'doc-1')
  assert.equal(doc.name, 'manual.pdf')
  assert.equal(doc.size, '1.5 KB')
  assert.equal(doc.status, 'done')
  assert.equal(doc.error, null)
  assert.equal(doc.createdLabel, '07.06.2026')
  assert.equal(doc.summary, 'Short summary.')
  assert.deepEqual(doc.suggestedQuestions, ['Что внутри manual.pdf?'])
})


test('summarizes knowledge-base readiness', () => {
  const stats = knowledgeBaseStats([
    { status: 'done' },
    { status: 'done' },
    { status: 'processing' },
    { status: 'failed' },
  ])

  assert.deepEqual(stats, {
    total: 4,
    ready: 2,
    processing: 1,
    failed: 1,
    progressPct: 50,
  })
})


test('allows reindexing only stable server-side documents', () => {
  assert.equal(canReindexDocument({ status: 'done' }), true)
  assert.equal(canReindexDocument({ status: 'failed' }), true)
  assert.equal(canReindexDocument({ status: 'processing' }), false)
  assert.equal(canReindexDocument({ status: 'pending' }), false)
  assert.equal(canReindexDocument({ status: 'done', _pending: true }), false)
})


test('builds chat route for suggested questions', () => {
  assert.deepEqual(
    buildQuestionRoute('Что внутри manual.pdf?'),
    { path: '/chat', query: { ask: 'Что внутри manual.pdf?' } },
  )

  assert.deepEqual(
    buildQuestionRoute('Что внутри manual.pdf?', 'doc-1'),
    { path: '/chat', query: { ask: 'Что внутри manual.pdf?', document: 'doc-1' } },
  )
})


test('builds document detail route', () => {
  assert.deepEqual(buildDocumentRoute('doc-1'), { path: '/documents/doc-1' })
})
