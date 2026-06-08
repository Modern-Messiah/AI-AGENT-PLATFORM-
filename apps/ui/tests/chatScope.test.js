import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildChatScopeQuery,
  normalizeChatScope,
  sessionScopeMeta,
  scopeSessionTitle,
  scopeSendOptions,
  scopeWelcomeMessage,
} from '../src/utils/chatScope.js'


test('normalizes notebook chat scope from route query', () => {
  const scope = normalizeChatScope({ notebook: 'notebook-1' })

  assert.equal(scope.type, 'notebook')
  assert.equal(scope.notebookId, 'notebook-1')
  assert.equal(scope.documentId, null)
  assert.equal(scope.title, 'Чат по ноутбуку')
  assert.equal(scopeSessionTitle(scope, 'Ноутбук: Product research'), 'Ноутбук: Product research')
  assert.match(scopeWelcomeMessage(scope), /только по документам внутри этого ноутбука/)
  assert.equal(scope.backPath, '/notebooks/notebook-1')
})


test('keeps scope query when removing one-shot ask param', () => {
  const scope = normalizeChatScope({ ask: 'Что общего?', notebook: 'notebook-1' })

  assert.deepEqual(buildChatScopeQuery(scope), { notebook: 'notebook-1' })
  assert.deepEqual(scopeSendOptions(scope), { notebookId: 'notebook-1' })
})


test('normalizes document chat scope from route query', () => {
  const scope = normalizeChatScope({ document: 'doc-1' })

  assert.equal(scope.type, 'document')
  assert.equal(scope.documentId, 'doc-1')
  assert.equal(scope.notebookId, null)
  assert.deepEqual(buildChatScopeQuery(scope), { document: 'doc-1' })
  assert.deepEqual(scopeSendOptions(scope), { documentId: 'doc-1' })
  assert.equal(scope.backPath, '/documents/doc-1')
})


test('normalizes global chat when route has no scope', () => {
  const scope = normalizeChatScope({})

  assert.equal(scope.type, 'global')
  assert.deepEqual(buildChatScopeQuery(scope), {})
  assert.deepEqual(scopeSendOptions(scope), {})
})


test('extracts visible session scope metadata from scoped titles', () => {
  assert.deepEqual(sessionScopeMeta('Ноутбук: Это команды линукс'), {
    type: 'notebook',
    badge: 'Ноутбук',
    title: 'Это команды линукс',
    subtitle: 'Чат по ноутбуку «Это команды линукс»',
  })

  assert.deepEqual(sessionScopeMeta('Документ: Vim_Cheat_Sheet.pdf'), {
    type: 'document',
    badge: 'Документ',
    title: 'Vim_Cheat_Sheet.pdf',
    subtitle: 'Чат по документу «Vim_Cheat_Sheet.pdf»',
  })

  assert.equal(sessionScopeMeta('New Chat'), null)
})
