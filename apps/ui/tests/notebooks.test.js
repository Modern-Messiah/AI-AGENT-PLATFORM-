import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildNotebookChatRoute,
  buildNotebookDocumentSelection,
  buildNotebookRoute,
  buildNotebookUploadPath,
  buildNotebookQuestionRoute,
  filterAvailableNotebookDocuments,
  normalizeNotebookSources,
  normalizeNotebook,
} from '../src/utils/notebooks.js'


test('normalizes API notebooks for the notebook table', () => {
  const notebook = normalizeNotebook({
    id: 'notebook-1',
    title: 'Product research',
    description: 'Source set for one project.',
    document_count: 2,
    document_ids: ['doc-1', 'doc-2'],
    summary: 'Combined source overview.',
    suggested_questions: ['Что общее в источниках?'],
    key_topics: ['Revenue', 'Expansion'],
    insights_updated_at: '2026-06-07T10:00:00Z',
    created_at: '2026-06-07T09:00:00Z',
  })

  assert.equal(notebook.id, 'notebook-1')
  assert.equal(notebook.title, 'Product research')
  assert.equal(notebook.description, 'Source set for one project.')
  assert.equal(notebook.documentCount, 2)
  assert.deepEqual(notebook.documentIds, ['doc-1', 'doc-2'])
  assert.equal(notebook.summary, 'Combined source overview.')
  assert.deepEqual(notebook.suggestedQuestions, ['Что общее в источниках?'])
  assert.deepEqual(notebook.keyTopics, ['Revenue', 'Expansion'])
  assert.equal(notebook.insightsUpdatedLabel, '07.06.2026')
  assert.equal(notebook.createdLabel, '07.06.2026')
})


test('builds notebook routes', () => {
  assert.deepEqual(buildNotebookRoute('notebook-1'), { path: '/notebooks/notebook-1' })
  assert.equal(buildNotebookUploadPath('notebook-1'), '/notebooks/notebook-1/documents/upload')
  assert.deepEqual(
    buildNotebookChatRoute('notebook-1', 'Product research'),
    {
      path: '/chat',
      query: { notebook: 'notebook-1', fresh: '1', title: 'Ноутбук: Product research' },
    },
  )
  assert.deepEqual(
    buildNotebookQuestionRoute('Что общее в источниках?', 'notebook-1', 'Product research'),
    {
      path: '/chat',
      query: {
        ask: 'Что общее в источниках?',
        notebook: 'notebook-1',
        fresh: '1',
        title: 'Ноутбук: Product research',
      },
    },
  )
})


test('normalizes notebook source cards', () => {
  const sources = normalizeNotebookSources([
    {
      id: 'doc-1',
      filename: 'manual.pdf',
      status: 'done',
      size_bytes: 2048,
      created_at: '2026-06-07T09:00:00Z',
      summary: 'Manual overview.',
      suggested_questions: ['Что важно в manual.pdf?'],
    },
    {
      id: 'doc-2',
      filename: 'draft.md',
      status: 'processing',
      size_bytes: 0,
      created_at: '2026-06-07T10:00:00Z',
    },
  ])

  assert.equal(sources[0].name, 'manual.pdf')
  assert.equal(sources[0].isReady, true)
  assert.equal(sources[0].readinessLabel, 'Готов для вопросов')
  assert.equal(sources[0].summary, 'Manual overview.')
  assert.deepEqual(sources[0].suggestedQuestions, ['Что важно в manual.pdf?'])
  assert.equal(sources[0].createdLabel, '07.06.2026')
  assert.equal(sources[1].isReady, false)
  assert.equal(sources[1].readinessLabel, 'Индексируется')
})


test('builds append-only notebook document selection', () => {
  assert.deepEqual(
    buildNotebookDocumentSelection(['doc-1'], ['doc-2', 'doc-1', 'doc-2']),
    ['doc-1', 'doc-2'],
  )
})


test('filters addable notebook documents', () => {
  const docs = [
    { id: 'doc-1', status: 'done', name: 'Already inside.pdf' },
    { id: 'doc-2', status: 'done', name: 'Can add.pdf' },
    { id: 'doc-3', status: 'processing', name: 'Still indexing.pdf' },
  ]

  assert.deepEqual(
    filterAvailableNotebookDocuments(docs, ['doc-1']).map(doc => doc.id),
    ['doc-2'],
  )
})
