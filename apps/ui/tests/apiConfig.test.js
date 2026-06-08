import test from 'node:test'
import assert from 'node:assert/strict'

import { resolveApiConfig } from '../src/utils/apiConfig.js'


test('uses env API key before localStorage key', () => {
  const config = resolveApiConfig({
    stored: { apiKey: 'stored-key', base: '/stored-api' },
    env: { VITE_API_KEY: 'env-key', VITE_API_BASE_URL: '/env-api' },
  })

  assert.equal(config.apiKey, 'env-key')
  assert.equal(config.baseUrl, '/env-api')
  assert.equal(config.keySource, 'env')
  assert.equal(config.isKeyManagedByEnv, true)
})


test('falls back to localStorage key when env key is missing', () => {
  const config = resolveApiConfig({
    stored: { apiKey: 'stored-key', base: '/stored-api' },
    env: {},
  })

  assert.equal(config.apiKey, 'stored-key')
  assert.equal(config.baseUrl, '/stored-api')
  assert.equal(config.keySource, 'localStorage')
  assert.equal(config.isKeyManagedByEnv, false)
})
