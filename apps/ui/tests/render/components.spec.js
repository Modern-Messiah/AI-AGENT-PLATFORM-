import { test, expect } from 'vitest'
import { mount, config } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import ConfirmModal from '../../src/components/ConfirmModal.vue'
import StatusBadge from '../../src/components/StatusBadge.vue'
import AppIcon from '../../src/components/AppIcon.vue'
import AppSidebar from '../../src/components/AppSidebar.vue'
import ChatMessages from '../../src/components/chat/ChatMessages.vue'
import ChatToolbar from '../../src/components/chat/ChatToolbar.vue'
import ChatScopeModal from '../../src/components/chat/ChatScopeModal.vue'
import SettingsModal from '../../src/components/SettingsModal.vue'
import { translate } from '../../src/i18n/index.js'
import { useChatStore } from '../../src/stores/chat.js'
import { useSessionStore } from '../../src/stores/session.js'
import { createRouter, createMemoryHistory } from 'vue-router'

config.global.stubs = { RouterLink: true, Teleport: true }
config.global.mocks = { $t: (key, params) => translate('ru', key, params) }

const testRouter = createRouter({
  history: createMemoryHistory(),
  routes: [{ path: '/chat', component: { template: '<div />' } }],
})

function withSetup(component, props = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  return mount(component, { props, global: { plugins: [pinia, testRouter] } })
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

  await wrapper.find('button.confirm-close-btn').trigger('click')
  expect(wrapper.emitted('cancel')).toHaveLength(1)
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


test('ChatMessages renders animated generation loader and prevents duplicate pending bubble', async () => {
  const wrapper = withSetup(ChatMessages)
  const chat = useChatStore()

  // Scenario 1: pipeline stage active before any streaming message exists
  chat.pipelineStage = { name: 'generation', startedAt: Date.now(), elapsedMs: 1200 }
  chat.messages = []
  await new Promise(resolve => setTimeout(resolve, 30))

  expect(wrapper.find('.gen-pending-bubble').exists()).toBe(true)
  expect(wrapper.find('.generation-loader').exists()).toBe(true)
  expect(wrapper.find('.gen-wave').exists()).toBe(true)
  expect(wrapper.text()).toContain('Генерирую ответ...')

  // Scenario 2: token arrives and message streams — no duplicate pending bubble below
  chat.messages = [
    {
      id: 's2',
      role: 'agent',
      text: 'Начало ответа...',
      time: '12:02',
      sources: [],
      streaming: true,
    },
  ]
  await new Promise(resolve => setTimeout(resolve, 30))

  // The bottom pending bubble must NOT be rendered when a streaming message is active
  expect(wrapper.find('.gen-pending-bubble').exists()).toBe(false)
  expect(wrapper.text()).toContain('Начало ответа...')
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


test('ChatToolbar disables scope button and does not emit open-scope when scope is locked', async () => {
  const wrapper = withSetup(ChatToolbar, {
    scope: { type: 'document', title: 'Doc 1' },
    scopeLocked: true,
  })
  const pill = wrapper.find('.scope-pill-btn')
  expect(pill.classes()).toContain('is-locked')
  expect(pill.attributes('disabled')).toBeDefined()
  await pill.trigger('click')
  expect(wrapper.emitted('open-scope')).toBeUndefined()
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
    expect(wrapper.text()).toContain('Моя база знаний')
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

    const closeBtn = wrapper.find('button.modal-close-btn')
    expect(closeBtn.exists()).toBe(true)
    await closeBtn.trigger('click')
    expect(wrapper.emitted('cancel')).toHaveLength(1)
  } finally {
    globalThis.fetch = origFetch
  }
})
 
 
test('SettingsModal renders close button in header and emits close on click or Escape', async () => {
  const wrapper = withSetup(SettingsModal)
  expect(wrapper.text()).toContain('Настройки')

  // Close button in header exists
  const closeBtn = wrapper.find('button.modal-close-btn')
  expect(closeBtn.exists()).toBe(true)

  await closeBtn.trigger('click')
  expect(wrapper.emitted('close')).toHaveLength(1)

  // Pressing Escape emits close
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  expect(wrapper.emitted('close')).toHaveLength(2)

  wrapper.unmount()
})


test('AppIcon renders chevron-left and chevron-right icons', () => {
  expect(withSetup(AppIcon, { name: 'chevron-left' }).find('svg').exists()).toBe(true)
  expect(withSetup(AppIcon, { name: 'chevron-right' }).find('svg').exists()).toBe(true)
})


test('AppSidebar renders expanded state and emits toggle on button click', async () => {
  const wrapper = withSetup(AppSidebar, { collapsed: false })
  expect(wrapper.classes()).not.toContain('collapsed')
  expect(wrapper.text()).toContain('AgentPlatform')

  const toggleBtn = wrapper.find('.sidebar-toggle')
  expect(toggleBtn.exists()).toBe(true)
  await toggleBtn.trigger('click')
  expect(wrapper.emitted('toggle')).toHaveLength(1)
})


test('AppSidebar renders collapsed state with centered toggle and avatar', async () => {
  const wrapper = withSetup(AppSidebar, { collapsed: true })
  const session = useSessionStore()
  const exp = Math.floor(Date.now() / 1000) + 3600
  const payload = btoa(JSON.stringify({
    type: 'session',
    exp,
    name: 'denivops',
    email: 'denivops@example.com',
    tid: 'main',
    role: 'admin',
  }))
  session.setToken(`eyJhbGciOiJIUzI1NiJ9.${payload}.signature`)
  await wrapper.vm.$nextTick()

  expect(wrapper.classes()).toContain('collapsed')
  const logoMark = wrapper.find('.logo-mark')
  expect(logoMark.classes()).toContain('clickable')
  await logoMark.trigger('click')
  expect(wrapper.emitted('toggle')).toHaveLength(1)

  const avatar = wrapper.find('.user-avatar')
  expect(avatar.exists()).toBe(true)
  expect(avatar.text()).toBe('D')

  const toggleBtn = wrapper.find('.sidebar-toggle')
  await toggleBtn.trigger('click')
  expect(wrapper.emitted('toggle')).toHaveLength(2)
})



