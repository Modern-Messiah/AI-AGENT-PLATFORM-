import test from 'node:test'
import assert from 'node:assert/strict'

import {
  DEFAULT_THEME,
  THEMES,
  applyTheme,
  normalizeTheme,
  persistTheme,
} from '../src/utils/theme.js'


test('supports five themes and uses graphite by default', () => {
  assert.equal(DEFAULT_THEME, 'graphite')
  assert.deepEqual(
    THEMES.map(theme => theme.id),
    ['graphite', 'pine', 'plum', 'porcelain', 'daylight'],
  )
  assert.equal(normalizeTheme('pine'), 'pine')
  assert.equal(normalizeTheme('unknown'), 'graphite')
  assert.equal(normalizeTheme(), 'graphite')
})


test('applies the normalized theme and browser color scheme', () => {
  const root = { dataset: {}, style: {} }

  assert.equal(applyTheme('porcelain', root), 'porcelain')
  assert.equal(root.dataset.theme, 'porcelain')
  assert.equal(root.style.colorScheme, 'light')

  assert.equal(applyTheme('not-a-theme', root), 'graphite')
  assert.equal(root.dataset.theme, 'graphite')
  assert.equal(root.style.colorScheme, 'dark')
})


test('persists a normalized theme without replacing other settings', () => {
  let stored = JSON.stringify({ apiKey: 'secret', base: '/api', locale: 'en' })
  const storage = {
    getItem: () => stored,
    setItem: (_key, value) => { stored = value },
  }

  assert.equal(persistTheme(storage, 'pine'), 'pine')
  assert.deepEqual(JSON.parse(stored), {
    apiKey: 'secret',
    base: '/api',
    locale: 'en',
    theme: 'pine',
  })

  assert.equal(persistTheme(storage, 'invalid'), 'graphite')
  assert.equal(JSON.parse(stored).theme, 'graphite')
})
