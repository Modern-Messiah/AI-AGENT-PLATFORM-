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

export function buildNotebookRoute(notebookId) {
  return { path: `/notebooks/${notebookId}` }
}

export function buildNotebookUploadPath(notebookId) {
  return `/notebooks/${notebookId}/documents/upload`
}

export function buildNotebookQuestionRoute(question, notebookId) {
  return { path: '/chat', query: { ask: question, notebook: notebookId } }
}
