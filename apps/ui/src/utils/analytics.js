export function formatTokens(value) {
  const n = Number(value || 0)
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`
  return String(Math.round(n))
}

export function formatCost(value, digits = 4) {
  return `$${Number(value || 0).toFixed(digits)}`
}

export function formatMs(value) {
  const n = Number(value || 0)
  if (n >= 1000) return `${(n / 1000).toFixed(1)}s`
  return `${Math.round(n)}ms`
}

function roundTo(value, digits) {
  const multiplier = 10 ** digits
  return Math.round(value * multiplier) / multiplier
}

function dayLabel(day, locale = 'ru') {
  if (typeof day === 'string') {
    const match = day.match(/^(\d{4})-(\d{2})-(\d{2})/)
    if (match) {
      return locale === 'en' ? `${match[2]}/${match[3]}` : `${match[3]}.${match[2]}`
    }
  }
  const date = new Date(day)
  if (Number.isNaN(date.getTime())) return String(day || '—')
  return formatLocaleDate(date, locale, { day: '2-digit', month: '2-digit' })
}

function barHeight(value, max) {
  if (!max) return 0
  return Math.max(4, Math.round((Number(value || 0) / max) * 100))
}

export function buildAnalyticsDashboard(data, locale = 'ru') {
  const breakdown = data?.breakdown || []
  const daily = data?.daily || []
  const totalTokens = breakdown.reduce((sum, row) => sum + Number(row.total_tokens || 0), 0)
  const totalCalls = breakdown.reduce((sum, row) => sum + Number(row.call_count || 0), 0)
  const avgLatencyMs = breakdown.length
    ? Math.round(
      breakdown.reduce((sum, row) => sum + Number(row.avg_latency_ms || 0), 0) / breakdown.length,
    )
    : 0
  const totalCost = Number(data?.total_cost_usd || 0)
  const costPer1kTokens = totalTokens ? roundTo((totalCost / totalTokens) * 1000, 5) : 0

  const providerTotals = new Map()
  breakdown.forEach((row) => {
    const provider = row.provider || 'unknown'
    const current = providerTotals.get(provider) || { provider, calls: 0, cost: 0, tokens: 0 }
    current.calls += Number(row.call_count || 0)
    current.cost += Number(row.total_cost_usd || 0)
    current.tokens += Number(row.total_tokens || 0)
    providerTotals.set(provider, current)
  })

  const providerMix = [...providerTotals.values()]
    .map(item => ({
      ...item,
      percent: totalCalls ? Math.round((item.calls / totalCalls) * 100) : 0,
    }))
    .sort((a, b) => b.calls - a.calls)

  const maxDailyCost = Math.max(...daily.map(row => Number(row.total_cost_usd || 0)), 0)
  const maxDailyTokens = Math.max(...daily.map(row => Number(row.total_tokens || 0)), 0)
  const dailyTrend = daily.map(row => ({
    ...row,
    dayLabel: dayLabel(row.day, locale),
    costHeight: barHeight(row.total_cost_usd, maxDailyCost),
    tokensHeight: barHeight(row.total_tokens, maxDailyTokens),
  }))

  let latencyHealth = { label: translate(locale, 'analytics.fast'), tone: 'good' }
  if (avgLatencyMs >= 10_000) latencyHealth = { label: translate(locale, 'analytics.slow'), tone: 'bad' }
  else if (avgLatencyMs >= 3_000) latencyHealth = { label: translate(locale, 'analytics.normal'), tone: 'warn' }

  return {
    totals: {
      totalCost,
      totalTokens,
      totalCalls,
      avgLatencyMs,
      costPer1kTokens,
    },
    providerMix,
    dailyTrend,
    latencyHealth,
  }
}
import { formatLocaleDate, translate } from '../i18n/index.js'
