function cleanId(value) {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

export function normalizeChatScope(query = {}) {
  const documentId = cleanId(query.document)
  const notebookId = cleanId(query.notebook)

  if (notebookId) {
    return {
      type: 'notebook',
      documentId: null,
      notebookId,
      title: 'Чат по ноутбуку',
      description: 'Следующие вопросы ищут ответы и цитаты только внутри этой коллекции.',
      backLabel: 'Открыть ноутбук',
      backPath: `/notebooks/${notebookId}`,
    }
  }

  if (documentId) {
    return {
      type: 'document',
      documentId,
      notebookId: null,
      title: 'Чат по документу',
      description: 'Следующие вопросы ищут ответы и цитаты только внутри этого документа.',
      backLabel: 'Открыть документ',
      backPath: `/documents/${documentId}`,
    }
  }

  return {
    type: 'global',
    documentId: null,
    notebookId: null,
    title: '',
    description: '',
    backLabel: '',
    backPath: '',
  }
}

export function buildChatScopeQuery(scope) {
  if (scope?.type === 'notebook' && scope.notebookId) return { notebook: scope.notebookId }
  if (scope?.type === 'document' && scope.documentId) return { document: scope.documentId }
  return {}
}

export function scopeSendOptions(scope) {
  if (scope?.type === 'notebook' && scope.notebookId) return { notebookId: scope.notebookId }
  if (scope?.type === 'document' && scope.documentId) return { documentId: scope.documentId }
  return {}
}

export function scopeSessionTitle(scope, fallbackTitle = '') {
  const title = String(fallbackTitle || '').trim()
  if (title) return title
  if (scope?.type === 'notebook') return 'Ноутбук: новая сессия'
  if (scope?.type === 'document') return 'Документ: новая сессия'
  return 'New Chat'
}

export function sessionScopeMeta(title = '') {
  const match = String(title || '').trim().match(/^(Ноутбук|Документ):\s*(.+)$/)
  if (!match) return null

  const badge = match[1]
  const type = badge === 'Ноутбук' ? 'notebook' : 'document'
  const sourceTitle = match[2].trim()
  return {
    type,
    badge,
    title: sourceTitle,
    subtitle: type === 'notebook'
      ? `Чат по ноутбуку «${sourceTitle}»`
      : `Чат по документу «${sourceTitle}»`,
  }
}

export function scopeWelcomeMessage(scope) {
  if (scope?.type === 'notebook') {
    return 'Это отдельный чат по ноутбуку. Следующие ответы будут искать информацию только по документам внутри этого ноутбука.'
  }
  if (scope?.type === 'document') {
    return 'Это отдельный чат по документу. Следующие ответы будут искать информацию только внутри этого файла.'
  }
  return ''
}
