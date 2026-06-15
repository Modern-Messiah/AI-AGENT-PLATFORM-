import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildAnalyticsDashboard,
  formatCost,
  formatMs,
  formatTokens,
} from '../src/utils/analytics.js'


const usage = {
  total_cost_usd: 0.012345,
  breakdown: [
    {
      model: 'kimi-k2.6',
      provider: 'moonshot',
      call_count: 3,
      total_tokens: 7000,
      total_cost_usd: 0.0096,
      avg_latency_ms: 34874,
    },
    {
      model: 'deepseek-v4-flash',
      provider: 'deepseek',
      call_count: 5,
      total_tokens: 12000,
      total_cost_usd: 0.002745,
      avg_latency_ms: 1200,
    },
  ],
  daily: [
    { day: '2026-06-07', total_cost_usd: 0.004, total_tokens: 8000, call_count: 4 },
    { day: '2026-06-08', total_cost_usd: 0.008345, total_tokens: 11000, call_count: 4 },
  ],
}


test('formats analytics values for dashboard cards', () => {
  assert.equal(formatTokens(19000), '19K')
  assert.equal(formatCost(0.012345), '$0.0123')
  assert.equal(formatMs(34874), '34.9s')
})


test('builds dashboard summary, provider mix and trend from usage data', () => {
  const dashboard = buildAnalyticsDashboard(usage)

  assert.equal(dashboard.totals.totalCalls, 8)
  assert.equal(dashboard.totals.totalTokens, 19000)
  assert.equal(dashboard.totals.avgLatencyMs, 18037)
  assert.equal(dashboard.totals.costPer1kTokens, 0.00065)
  assert.equal(dashboard.latencyHealth.label, 'медленно')
  assert.deepEqual(
    dashboard.providerMix.map(item => [item.provider, item.percent]),
    [['deepseek', 63], ['moonshot', 38]],
  )
  assert.deepEqual(
    dashboard.dailyTrend.map(item => [item.dayLabel, item.costHeight, item.tokensHeight]),
    [['07.06', 48, 73], ['08.06', 100, 100]],
  )

  const englishDashboard = buildAnalyticsDashboard(usage, 'en')
  assert.equal(englishDashboard.latencyHealth.label, 'slow')
  assert.deepEqual(
    englishDashboard.dailyTrend.map(item => item.dayLabel),
    ['06/07', '06/08'],
  )
})
