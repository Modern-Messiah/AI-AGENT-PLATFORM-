import { formatLocaleDate, translate } from '../i18n/index.js'

export function formatFileSize(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)} KB`
  if (bytes < 1073741824) return `${(bytes / 1048576).toFixed(1)} MB`
  return `${(bytes / 1073741824).toFixed(1)} GB`
}

export function normalizeDocument(doc, locale = 'ru') {
  const processedPages = Number.isInteger(doc.processed_pages) ? doc.processed_pages : 0
  const totalPages = Number.isInteger(doc.total_pages) ? doc.total_pages : 0
  return {
    id: doc.id,
    name: doc.filename || doc.name || translate(locale, 'documents.unnamed'),
    status: doc.status || 'pending',
    error: doc.error || null,
    size: formatFileSize(doc.size_bytes || doc.sizeBytes || 0),
    sourceType: doc.source_type || doc.sourceType || 'file',
    sourceUrl: doc.source_url || doc.sourceUrl || '',
    sourceTitle: doc.source_title || doc.sourceTitle || '',
    sourceCheckedAt: doc.source_checked_at || doc.sourceCheckedAt || null,
    sourceCheckedLabel: formatLocaleDate(doc.source_checked_at || doc.sourceCheckedAt, locale),
    time: formatLocaleDate(doc.created_at, locale),
    createdLabel: formatLocaleDate(doc.created_at, locale),
    summary: doc.summary || '',
    processingStage: doc.processing_stage || 'queued',
    processedPages,
    totalPages,
    progressPct: totalPages > 0
      ? Math.min(100, Math.round((processedPages / totalPages) * 100))
      : 0,
    warnings: Array.isArray(doc.warnings) ? doc.warnings : [],
    suggestedQuestions: Array.isArray(doc.suggested_questions)
      ? doc.suggested_questions
      : (doc.suggestedQuestions || []),
  }
}

export function knowledgeBaseStats(docs) {
  const total = docs.length
  const ready = docs.filter(doc => doc.status === 'done').length
  const processing = docs.filter(doc => doc.status === 'processing' || doc.status === 'pending').length
  const failed = docs.filter(doc => doc.status === 'failed').length

  return {
    total,
    ready,
    processing,
    failed,
    progressPct: total ? Math.round((ready / total) * 100) : 0,
  }
}

export function canReindexDocument(doc) {
  return Boolean(
    doc
    && !doc._pending
    && doc.status !== 'pending'
    && doc.status !== 'processing'
  )
}

export function canOpenDocumentChat(doc) {
  return Boolean(doc && !doc._pending && doc.status === 'done')
}

function documentChatTitle(title, locale = 'ru') {
  const label = translate(locale, 'chat.documentBadge')
  const fallback = translate(locale, 'documentDetail.fallbackTitle')
  return `${label}: ${String(title || fallback).trim() || fallback}`
}

export function buildQuestionRoute(question, documentId = null, title = '', locale = 'ru') {
  const query = { ask: question }
  if (documentId) {
    query.document = documentId
    if (title) {
      query.fresh = '1'
      query.title = documentChatTitle(title, locale)
    }
  }
  return { path: '/chat', query }
}

export function buildDocumentChatRoute(documentId, title = '', locale = 'ru') {
  const query = { document: documentId, fresh: '1' }
  if (title) query.title = documentChatTitle(title, locale)
  return { path: '/chat', query }
}

export function buildDocumentRoute(documentId) {
  return { path: `/documents/${documentId}` }
}
