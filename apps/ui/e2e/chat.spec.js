import { readFileSync } from 'node:fs'
import { test, expect } from '@playwright/test'

// Black-box chat smoke: upload → index → scoped question → streamed
// markdown answer with at least one source citation chip.

const API_BASE = (process.env.E2E_API_BASE_URL || 'http://127.0.0.1:8001').replace(/\/$/, '')

function adminSecret() {
  if (process.env.ADMIN_SECRET) return process.env.ADMIN_SECRET
  for (const line of readFileSync(new URL('../../../.env', import.meta.url), 'utf8').split('\n')) {
    const match = line.match(/^ADMIN_SECRET=(.*)$/)
    if (match) return match[1].trim()
  }
  throw new Error('ADMIN_SECRET not found in env or .env')
}

async function api(path, init) {
  const response = await fetch(`${API_BASE}${path}`, init)
  if (!response.ok) throw new Error(`${path} -> ${response.status}: ${await response.text()}`)
  return response
}

test('chat answers a document question with citations', async ({ page, request }) => {
  test.setTimeout(240_000)

  // 1. throwaway tenant + key + document via the public API
  const tenant = `pw-${Date.now()}`
  const created = await (await api('/auth/keys', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Admin-Secret': adminSecret() },
    body: JSON.stringify({ tenant_id: tenant, name: 'playwright' }),
  })).json()
  const headers = { 'X-API-Key': created.raw_key, 'Content-Admin-Secret': '1' }

  const form = new FormData()
  form.append('file', new Blob(
    ['PLAYWRIGHT SENTINEL: the hybrid retrieval fusion constant K equals sixty. ' +
     'The maintenance window starts at 03:00 and lasts one hour.'],
    { type: 'text/plain' },
  ), 'playwright_sentinel.txt')
  const uploaded = await (await api('/documents', {
    method: 'POST',
    headers: { 'X-API-Key': created.raw_key },
    body: form,
  })).json()

  let status = 'pending'
  for (let i = 0; i < 40 && status !== 'done' && status !== 'failed'; i++) {
    await page.waitForTimeout(3_000)
    status = (await (await api(`/documents/${uploaded.id}`, {
      headers: { 'X-API-Key': created.raw_key },
    })).json()).status
  }
  expect(status).toBe('done')

  // 2. configure the SPA with the tenant key and open chat
  await page.goto('/')
  await page.evaluate((apiKey) => {
    localStorage.setItem('aap_config', JSON.stringify({ apiKey, base: '', locale: 'ru', theme: 'graphite' }))
  }, created.raw_key)
  await page.goto('/chat')
  await expect(page.locator('.topbar')).toBeVisible()

  // 3. ask the document question and wait for the streamed answer
  await page.fill('.chat-textarea', 'What is the value of the fusion constant K?')
  await page.press('.chat-textarea', 'Enter')

  const answer = page.locator('.msg.agent .md-content').last()
  await expect(answer).toBeVisible({ timeout: 90_000 })
  await expect(page.locator('.msg.agent .md-content, .msg.agent .msg-bubble').last())
    .toContainText(/sixty|60/i, { timeout: 30_000 })

  // 4. at least one citation chip for the uploaded document
  await expect(page.locator('.source-chip').first()).toBeVisible({ timeout: 15_000 })
  await expect(page.locator('.source-chip').first()).toContainText('playwright_sentinel.txt')
})
