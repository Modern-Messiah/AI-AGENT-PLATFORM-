function cleanId(value) {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

export function normalizeChatScope(query = {}, locale = 'ru') {
  const documentId = cleanId(query.document)
  const notebookId = cleanId(query.notebook)

  if (notebookId) {
    return {
      type: 'notebook',
      documentId: null,
      notebookId,
      title: translate(locale, 'chat.scopeNotebookTitle'),
      description: translate(locale, 'chat.scopeNotebookDescription'),
      backLabel: translate(locale, 'chat.scopeNotebookBack'),
      backPath: `/notebooks/${notebookId}`,
    }
  }

  if (documentId) {
    return {
      type: 'document',
      documentId,
      notebookId: null,
      title: translate(locale, 'chat.scopeDocumentTitle'),
      description: translate(locale, 'chat.scopeDocumentDescription'),
      backLabel: translate(locale, 'chat.scopeDocumentBack'),
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

export function normalizeStoredChatScope(session = {}, locale = 'ru') {
  if (session?.scope_type === 'notebook' && cleanId(session.notebook_id)) {
    return normalizeChatScope({ notebook: session.notebook_id }, locale)
  }
  if (session?.scope_type === 'document' && cleanId(session.document_id)) {
    return normalizeChatScope({ document: session.document_id }, locale)
  }
  return normalizeChatScope({}, locale)
}

export function scopeSessionTitle(scope, fallbackTitle = '', locale = 'ru') {
  const title = String(fallbackTitle || '').trim()
  if (title) return title
  if (scope?.type === 'notebook') return translate(locale, 'chat.notebookSession')
  if (scope?.type === 'document') return translate(locale, 'chat.documentSession')
  return translate(locale, 'chat.newChat')
}

export function sessionScopeMeta(title = '', locale = 'ru') {
  const match = String(title || '').trim().match(/^(Ноутбук|Документ|Notebook|Document):\s*(.+)$/)
  if (!match) return null

  const type = match[1] === 'Ноутбук' || match[1] === 'Notebook' ? 'notebook' : 'document'
  const badge = translate(locale, type === 'notebook' ? 'chat.notebookBadge' : 'chat.documentBadge')
  const sourceTitle = match[2].trim()
  return {
    type,
    badge,
    title: sourceTitle,
    subtitle: translate(
      locale,
      type === 'notebook' ? 'chat.notebookSubtitle' : 'chat.documentSubtitle',
      { title: sourceTitle },
    ),
  }
}

export function sessionScopeMetaFromSession(session = {}, locale = 'ru') {
  const meta = sessionScopeMeta(session?.title, locale)
  if (meta) return meta

  const scope = normalizeStoredChatScope(session, locale)
  if (scope.type === 'global') return null

  const badge = translate(locale, scope.type === 'notebook' ? 'chat.notebookBadge' : 'chat.documentBadge')
  const title = String(session?.title || '').trim() || scope.title
  return {
    type: scope.type,
    badge,
    title,
    subtitle: scope.title,
  }
}

export function scopeWelcomeMessage(scope, locale = 'ru') {
  if (scope?.type === 'notebook') {
    return translate(locale, 'chat.notebookWelcome')
  }
  if (scope?.type === 'document') {
    return translate(locale, 'chat.documentWelcome')
  }
  return ''
}
import { translate } from '../i18n/index.js'
