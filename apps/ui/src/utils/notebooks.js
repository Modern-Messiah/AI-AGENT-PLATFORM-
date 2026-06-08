export function normalizeNotebook(notebook) {
  return {
    id: notebook.id,
    title: notebook.title || 'Untitled notebook',
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
      ? new Date(notebook.insights_updated_at).toLocaleDateString('ru')
      : '—',
    createdLabel: notebook.created_at ? new Date(notebook.created_at).toLocaleDateString('ru') : '—',
    updatedLabel: notebook.updated_at ? new Date(notebook.updated_at).toLocaleDateString('ru') : '—',
  }
}

export function normalizeNotebookSources(documents = []) {
  return documents.map(doc => {
    const status = doc.status || 'pending'
    const isReady = status === 'done'
    const isFailed = status === 'failed'
    const isProcessing = status === 'processing' || status === 'pending'

    return {
      id: doc.id,
      name: doc.filename || doc.name || 'unnamed',
      status,
      isReady,
      isFailed,
      isProcessing,
      readinessLabel: isReady
        ? 'Готов для вопросов'
        : isFailed
          ? 'Ошибка индексации'
          : 'Индексируется',
      error: doc.error || null,
      sizeBytes: doc.size_bytes || doc.sizeBytes || 0,
      summary: doc.summary || '',
      suggestedQuestions: Array.isArray(doc.suggested_questions)
        ? doc.suggested_questions
        : (doc.suggestedQuestions || []),
      createdAt: doc.created_at || doc.createdAt || null,
      createdLabel: doc.created_at ? new Date(doc.created_at).toLocaleDateString('ru') : '—',
    }
  })
}

export function buildNotebookRoute(notebookId) {
  return { path: `/notebooks/${notebookId}` }
}

export function buildNotebookUploadPath(notebookId) {
  return `/notebooks/${notebookId}/documents/upload`
}

export function buildNotebookQuestionRoute(question, notebookId) {
  return { path: '/chat', query: { ask: question, notebook: notebookId } }
}
