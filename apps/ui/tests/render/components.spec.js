import { test, expect } from 'vitest'
import { mount, config } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import ConfirmModal from '../../src/components/ConfirmModal.vue'
import StatusBadge from '../../src/components/StatusBadge.vue'
import AppIcon from '../../src/components/AppIcon.vue'
import ChatMessages from '../../src/components/chat/ChatMessages.vue'
import ChatToolbar from '../../src/components/chat/ChatToolbar.vue'
import ChatScopeModal from '../../src/components/chat/ChatScopeModal.vue'
import { translate } from '../../src/i18n/index.js'
import { useChatStore } from '../../src/stores/chat.js'

config.global.stubs = { RouterLink: true, Teleport: true }
config.global.mocks = { $t: (key, params) => translate('ru', key, params) }


function withSetup(component, props = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  return mount(component, { props, global: { plugins: [pinia] } })
}


test('ConfirmModal renders and emits confirm on button click', async () => {
  const wrapper = withSetup(ConfirmModal, {
    heading: 'Удалить документ?',
    title: 'report.pdf',
    warning: 'Действие необратимо',
  })
  expect(wrapper.text()).toContain('report.pdf')
  await wrapper.find('button.btn-danger').trigger('click')
  expect(wrapper.emitted('confirm')).toHaveLength(1)
})


test('StatusBadge maps statuses to semantic classes', () => {
  expect(withSetup(StatusBadge, { status: 'done' }).classes().join(' ')).toContain('badge-green')
  expect(withSetup(StatusBadge, { status: 'failed' }).classes().join(' ')).toContain('badge-red')
})


test('AppIcon renders known icons and falls back gracefully', () => {
  expect(withSetup(AppIcon, { name: 'chat' }).find('svg').exists()).toBe(true)
  // unknown names render the trailing v-else branch without crashing
  const unknown = withSetup(AppIcon, { name: 'agent' })
  expect(unknown.text()).toBe('A')
})


test('ChatMessages renders markdown, confidence badge and citation chips', async () => {
  const wrapper = withSetup(ChatMessages)
  const chat = useChatStore()
  chat.messages = [
    {
      id: 'a1',
      role: 'agent',
      text: 'The constant is **sixty** [1].',
      time: '12:00',
      sources: [{
        id: 1,
        document_id: 'd1',
        chunk_id: 'c1',
        filename: 'runbook.pdf',
        chunk_index: 0,
        page: 3,
        excerpt: 'fusion constant K equals sixty',
        score: 0.8,
        preview_available: true,
        asset_id: 'asset-1',
        asset_kind: 'page',
      }],
      confidence: 0.82,
      cached: false,
      streaming: false,
    },
  ]
  await new Promise(resolve => setTimeout(resolve, 30))

  const md = wrapper.find('.md-content')
  expect(md.exists()).toBe(true)
  expect(md.html()).toContain('<strong>sixty</strong>')

  expect(wrapper.find('.badge-green').exists()).toBe(true)

  const chip = wrapper.find('.source-chip')
  expect(chip.exists()).toBe(true)
  expect(chip.text()).toContain('runbook.pdf')
})


test('ChatMessages keeps streaming answers on the plain-text path', async () => {
  const wrapper = withSetup(ChatMessages)
  const chat = useChatStore()
  chat.messages = [
    {
      id: 's1',
      role: 'agent',
      text: 'частичный **ответ',
      time: '12:01',
      sources: [],
      confidence: undefined,
      streaming: true,
    },
  ]
  await new Promise(resolve => setTimeout(resolve, 30))

  // streaming messages must NOT go through the markdown v-html branch
  expect(wrapper.find('.md-content').exists()).toBe(false)
  expect(wrapper.text()).toContain('частичный **ответ')
})


test('ChatToolbar renders scope pill and emits open-scope', async () => {
  const wrapper = withSetup(ChatToolbar, {
    scope: { type: 'global', title: 'По всей базе знаний' },
  })
  const pill = wrapper.find('.scope-pill-btn')
  expect(pill.exists()).toBe(true)
  expect(pill.text()).toContain('По всей базе знаний')
  await pill.trigger('click')
  expect(wrapper.emitted('open-scope')).toHaveLength(1)
})


test('ChatScopeModal renders options and emits select with global scope', async () => {
  const origFetch = globalThis.fetch
  globalThis.fetch = async () => ({
    ok: true,
    status: 200,
    json: async () => [],
    text: async () => '[]',
  })
  try {
    const wrapper = withSetup(ChatScopeModal, {
      currentScope: { type: 'global', documentId: null, notebookId: null },
    })
    expect(wrapper.text()).toContain('Вся база знаний')
    expect(wrapper.text()).toContain('По документу')
    expect(wrapper.text()).toContain('По блокноту')

    const applyBtn = wrapper.find('button.btn-primary')
    await applyBtn.trigger('click')
    expect(wrapper.emitted('select')).toHaveLength(1)
    expect(wrapper.emitted('select')[0][0]).toEqual({
      type: 'global',
      documentId: null,
      notebookId: null,
      title: '',
    })
  } finally {
    globalThis.fetch = origFetch
  }
})

