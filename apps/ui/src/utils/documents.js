export function formatFileSize(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)} KB`
  if (bytes < 1073741824) return `${(bytes / 1048576).toFixed(1)} MB`
  return `${(bytes / 1073741824).toFixed(1)} GB`
}

export function normalizeDocument(doc) {
  return {
    id: doc.id,
    name: doc.filename || doc.name || 'unnamed',
    status: doc.status || 'pending',
    error: doc.error || null,
    size: formatFileSize(doc.size_bytes || doc.sizeBytes || 0),
    time: doc.created_at ? new Date(doc.created_at).toLocaleDateString('ru') : '—',
    createdLabel: doc.created_at ? new Date(doc.created_at).toLocaleDateString('ru') : '—',
    summary: doc.summary || '',
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

export function buildQuestionRoute(question, documentId = null) {
  const query = { ask: question }
  if (documentId) query.document = documentId
  return { path: '/chat', query }
}

export function buildDocumentChatRoute(documentId) {
  return { path: '/chat', query: { document: documentId } }
}

export function buildDocumentRoute(documentId) {
  return { path: `/documents/${documentId}` }
}
