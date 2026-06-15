import { formatLocaleDate, translate } from '../i18n/index.js'

export function normalizeNotebook(notebook, locale = 'ru') {
  return {
    id: notebook.id,
    title: notebook.title || translate(locale, 'notebooks.untitled'),
    description: notebook.description || '',
    documentCount: notebook.document_count ?? notebook.documentCount ?? 0,
    documentIds: Array.isArray(notebook.document_ids)
      ? notebook.document_ids
      : (notebook.documentIds || []),
    documents: notebook.documents || [],
    summary: notebook.summary || '',
    suggestedQuestions: Array.isArray(notebook.suggested_questions)
      ? notebook.suggested_questions
      : (notebook.suggestedQuestions || []),
    keyTopics: Array.isArray(notebook.key_topics)
      ? notebook.key_topics
      : (notebook.keyTopics || []),
    insightsUpdatedLabel: notebook.insights_updated_at
      ? formatLocaleDate(notebook.insights_updated_at, locale)
      : '—',
    createdLabel: formatLocaleDate(notebook.created_at, locale),
    updatedLabel: formatLocaleDate(notebook.updated_at, locale),
  }
}

export function normalizeNotebookSources(documents = [], locale = 'ru') {
  return documents.map(doc => {
    const status = doc.status || 'pending'
    const isReady = status === 'done'
    const isFailed = status === 'failed'
    const isProcessing = status === 'processing' || status === 'pending'

    return {
      id: doc.id,
      name: doc.filename || doc.name || translate(locale, 'documents.unnamed'),
      status,
      isReady,
      isFailed,
      isProcessing,
      readinessLabel: isReady
        ? translate(locale, 'notebookDetail.ready')
        : isFailed
          ? translate(locale, 'notebookDetail.indexingError')
          : translate(locale, 'notebookDetail.indexing'),
      error: doc.error || null,
      sizeBytes: doc.size_bytes || doc.sizeBytes || 0,
      createdAt: doc.created_at || doc.createdAt || null,
      createdLabel: formatLocaleDate(doc.created_at || doc.createdAt, locale),
    }
  })
}

export function notebookOverviewQuestions(notebook) {
  return Array.isArray(notebook?.suggestedQuestions) ? notebook.suggestedQuestions : []
}

export function buildNotebookDocumentSelection(currentIds = [], addIds = []) {
  const seen = new Set()
  const merged = []
  for (const id of [...currentIds, ...addIds]) {
    if (!id || seen.has(id)) continue
    seen.add(id)
    merged.push(id)
  }
  return merged
}

export function filterAvailableNotebookDocuments(documents = [], currentIds = []) {
  const current = new Set(currentIds)
  return documents.filter(doc => doc.status === 'done' && !current.has(doc.id))
}

export function buildNotebookRoute(notebookId) {
  return { path: `/notebooks/${notebookId}` }
}

export function buildNotebookUploadPath(notebookId) {
  return `/notebooks/${notebookId}/documents/upload`
}

function notebookChatTitle(title, locale = 'ru') {
  const label = translate(locale, 'chat.notebookBadge')
  const fallback = translate(locale, 'notebookDetail.fallbackTitle')
  return `${label}: ${String(title || fallback).trim() || fallback}`
}

export function buildNotebookChatRoute(notebookId, title = '', locale = 'ru') {
  return {
    path: '/chat',
    query: {
      notebook: notebookId,
      fresh: '1',
      title: notebookChatTitle(title, locale),
    },
  }
}

export function buildNotebookQuestionRoute(question, notebookId, title = '', locale = 'ru') {
  return {
    path: '/chat',
    query: {
      ask: question,
      notebook: notebookId,
      fresh: '1',
      title: notebookChatTitle(title, locale),
    },
  }
}
