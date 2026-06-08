import test from 'node:test'
import assert from 'node:assert/strict'

import {
  SIDEBAR_COLLAPSED_STORAGE_KEY,
  readStoredSidebarCollapsed,
  storeSidebarCollapsed,
  toggleSidebarCollapsed,
} from '../src/utils/sidebarCollapse.js'

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial))

  return {
    getItem(key) {
      return values.has(key) ? values.get(key) : null
    },
    setItem(key, value) {
      values.set(key, String(value))
    },
  }
}

test('sidebar starts expanded when no stored preference exists', () => {
  assert.equal(readStoredSidebarCollapsed(memoryStorage()), false)
  assert.equal(readStoredSidebarCollapsed(null), false)
})

test('reads stored collapsed sidebar preference', () => {
  assert.equal(readStoredSidebarCollapsed(memoryStorage({ [SIDEBAR_COLLAPSED_STORAGE_KEY]: '1' })), true)
  assert.equal(readStoredSidebarCollapsed(memoryStorage({ [SIDEBAR_COLLAPSED_STORAGE_KEY]: '0' })), false)
})

test('toggles and stores sidebar collapse preference', () => {
  const storage = memoryStorage()

  const collapsed = toggleSidebarCollapsed(false, storage)

  assert.equal(collapsed, true)
  assert.equal(storage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY), '1')

  const expanded = toggleSidebarCollapsed(collapsed, storage)

  assert.equal(expanded, false)
  assert.equal(storage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY), '0')
})
