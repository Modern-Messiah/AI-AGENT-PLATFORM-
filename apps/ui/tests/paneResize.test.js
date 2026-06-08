import test from 'node:test'
import assert from 'node:assert/strict'

import {
  CHAT_HISTORY_DEFAULT_WIDTH,
  CHAT_HISTORY_MAX_WIDTH,
  CHAT_HISTORY_MIN_WIDTH,
  clampPaneWidth,
  readStoredPaneWidth,
  storePaneWidth,
} from '../src/utils/paneResize.js'

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

test('clamps chat history width into the usable range', () => {
  assert.equal(clampPaneWidth(CHAT_HISTORY_MIN_WIDTH - 30), CHAT_HISTORY_MIN_WIDTH)
  assert.equal(clampPaneWidth(CHAT_HISTORY_MAX_WIDTH + 30), CHAT_HISTORY_MAX_WIDTH)
  assert.equal(clampPaneWidth(280), 280)
})

test('reads only valid stored chat history widths', () => {
  assert.equal(readStoredPaneWidth(memoryStorage({ chatHistoryWidth: '320' })), 320)
  assert.equal(readStoredPaneWidth(memoryStorage({ chatHistoryWidth: 'bad' })), CHAT_HISTORY_DEFAULT_WIDTH)
  assert.equal(readStoredPaneWidth(memoryStorage({ chatHistoryWidth: '9999' })), CHAT_HISTORY_DEFAULT_WIDTH)
  assert.equal(readStoredPaneWidth(null), CHAT_HISTORY_DEFAULT_WIDTH)
})

test('stores a clamped chat history width', () => {
  const storage = memoryStorage()

  storePaneWidth(storage, CHAT_HISTORY_MAX_WIDTH + 80)

  assert.equal(storage.getItem('chatHistoryWidth'), String(CHAT_HISTORY_MAX_WIDTH))
})
