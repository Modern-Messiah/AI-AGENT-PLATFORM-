import test from 'node:test'
import assert from 'node:assert/strict'

import {
  clearSettingsQuery,
  settingsRedirect,
  shouldOpenSettingsModal,
} from '../src/utils/settingsRoute.js'


test('redirects direct settings URL to chat with modal query flag', () => {
  assert.deepEqual(settingsRedirect(), {
    path: '/chat',
    query: { settings: '1' },
  })
})


test('detects settings modal route query flag', () => {
  assert.equal(shouldOpenSettingsModal({ settings: '1' }), true)
  assert.equal(shouldOpenSettingsModal({ settings: 'true' }), true)
  assert.equal(shouldOpenSettingsModal({ settings: '0' }), false)
  assert.equal(shouldOpenSettingsModal({}), false)
})


test('removes only settings flag when modal closes', () => {
  assert.deepEqual(clearSettingsQuery({ settings: '1', ask: 'hello', model: 'kimi' }), {
    ask: 'hello',
    model: 'kimi',
  })
})
