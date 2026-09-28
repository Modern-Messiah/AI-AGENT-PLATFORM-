import test from 'node:test'
import assert from 'node:assert/strict'

import {
  PROMPT_MODES,
  PROMPT_STATUSES,
  buildCreateKeyPayload,
  buildPromptQueryParams,
  buildQueryTrend,
  buildUsageTrend,
  documentTone,
  formatBytes,
  formatCost,
  formatDateTime,
  healthTone,
  keyDisplayName,
  keyStatusTone,
  keyUserLabel,
  promptActor,
  promptStatusTone,
} from '../src/utils/admin.js'


test('buildQueryTrend maps days, labels and bar heights', () => {
  const trend = buildQueryTrend([
    { day: '2026-09-27', count: 10, errors: 1 },
    { day: '2026-09-28', count: 0, errors: 0 },
  ], 'ru')

  assert.equal(trend.length, 2)
  assert.equal(trend[0].dayLabel, '27.09')
  assert.equal(trend[0].countHeight, 100)
  assert.equal(trend[0].errorsHeight, 100)
  // zero rows still get the 4% minimum bar so the column stays visible
  assert.equal(trend[1].countHeight, 4)
  assert.equal(trend[1].errorsHeight, 4)
})


test('buildQueryTrend uses en day labels and tolerates junk input', () => {
  assert.equal(buildQueryTrend([{ day: '2026-01-05', count: 3, errors: 0 }], 'en')[0].dayLabel, '01/05')
  assert.deepEqual(buildQueryTrend(null), [])
  assert.deepEqual(buildQueryTrend(undefined, 'ru'), [])
})


test('buildUsageTrend maps admin usage rows onto TrendChart fields', () => {
  const trend = buildUsageTrend([
    { day: '2026-09-27', cost_usd: 1.25, total_tokens: 900, calls: 9 },
  ], 'ru')

  assert.equal(trend[0].total_cost_usd, 1.25)
  assert.equal(trend[0].total_tokens, 900)
  assert.equal(trend[0].calls, 9)
  assert.equal(trend[0].avg_latency_ms, 0)
  assert.equal(trend[0].dayLabel, '27.09')
})


test('status tones map statuses onto badge colours', () => {
  assert.equal(promptStatusTone('ok'), 'good')
  assert.equal(promptStatusTone('pending'), 'warn')
  assert.equal(promptStatusTone('error'), 'bad')
  assert.equal(documentTone('done'), 'good')
  assert.equal(documentTone('processing'), 'warn')
  assert.equal(documentTone('failed'), 'bad')
  assert.equal(healthTone('ok'), 'good')
  assert.equal(healthTone('error: TimeoutError'), 'bad')
})


test('buildPromptQueryParams only includes set filters', () => {
  const params = buildPromptQueryParams(
    { tenantId: 'tenant-a', q: 'схема', mode: 'stream', status: '', days: 30 },
    { limit: 50, offset: 100 },
  )
  assert.equal(
    params,
    'tenant_id=tenant-a&mode=stream&q=%D1%81%D1%85%D0%B5%D0%BC%D0%B0&days=30&limit=50&offset=100',
  )

  const empty = buildPromptQueryParams({}, {})
  assert.equal(empty, 'days=30&limit=50&offset=0')
})


test('prompt modes and statuses feed the filter selects', () => {
  assert.deepEqual(PROMPT_MODES, ['stream', 'run', 'research'])
  assert.deepEqual(PROMPT_STATUSES, ['ok', 'error', 'pending'])
})


test('promptActor prefers the name, then the id prefix, then the fallback', () => {
  assert.equal(promptActor({ user_name: 'alice' }), 'alice')
  assert.equal(promptActor({ user_id: '12345678-1111-2222-3333-444444444444' }), '12345678')
  assert.equal(promptActor({ tenant_id: 't' }, 'ru'), 'ключ без пользователя')
  assert.equal(promptActor({ tenant_id: 't' }, 'en'), 'unbound key')
})


test('formatters render costs, bytes and datetimes', () => {
  assert.equal(formatCost(0), '$0.0000')
  assert.equal(formatCost(1.5, 2), '$1.50')
  assert.equal(formatBytes(512), '512 B')
  assert.equal(formatBytes(2048), '2 KB')
  assert.equal(formatBytes(5 * 1024 * 1024), '5.0 MB')
  assert.equal(formatDateTime('', 'ru'), '—')
  assert.equal(formatDateTime('not-a-date', 'ru'), '—')
})


test('formatDateTime renders date and time for a valid timestamp', () => {
  const value = formatDateTime('2026-09-28T12:00:00Z', 'ru')
  assert.match(value, /\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}/)
})


test('key helpers render labels, tones and create payloads', () => {
  const key = {
    id: '12345678-1111-2222-3333-444444444444',
    name: 'laptop',
    user_name: 'alice',
    is_active: true,
  }
  assert.equal(keyDisplayName(key), 'laptop')
  assert.equal(keyDisplayName({ id: key.id }), '12345678')
  assert.equal(keyDisplayName(null), '—')
  assert.equal(keyUserLabel(key, 'ru'), 'alice')
  assert.equal(keyUserLabel({ user_id: key.id }, 'ru'), '12345678')
  assert.equal(keyUserLabel({}, 'ru'), 'ключ без пользователя')
  assert.equal(keyUserLabel({}, 'en'), 'unbound key')
  assert.equal(keyStatusTone(true), 'good')
  assert.equal(keyStatusTone(false), 'bad')
})


test('buildCreateKeyPayload trims fields and omits empty user binding', () => {
  assert.deepEqual(
    buildCreateKeyPayload({ tenantId: ' tenant-a ', name: ' laptop ', userId: '' }),
    { tenant_id: 'tenant-a', name: 'laptop' },
  )
  assert.deepEqual(
    buildCreateKeyPayload({ tenantId: 't', name: 'k', userId: 'u-1' }),
    { tenant_id: 't', name: 'k', user_id: 'u-1' },
  )
})
