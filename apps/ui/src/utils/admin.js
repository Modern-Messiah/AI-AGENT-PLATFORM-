import { formatLocaleDate, translate } from '../i18n/index.js'

// Day labels match the TrendChart contract (dd.mm for ru, mm/dd for en).
function dayLabel(day, locale = 'ru') {
  const match = String(day || '').match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (match) {
    return locale === 'en' ? `${match[2]}/${match[3]}` : `${match[3]}.${match[2]}`
  }
  return String(day || '—')
}

function barHeight(value, max) {
  if (!max) return 0
  return Math.max(4, Math.round((Number(value || 0) / max) * 100))
}

// ── Overview: daily query activity ──────────────────────────────────────────

export function buildQueryTrend(dailyQueries = [], locale = 'ru') {
  const rows = Array.isArray(dailyQueries) ? dailyQueries : []
  const maxCount = Math.max(...rows.map(row => Number(row.count || 0)), 0)
  const maxErrors = Math.max(...rows.map(row => Number(row.errors || 0)), 0)
  return rows.map(row => ({
    day: row.day,
    dayLabel: dayLabel(row.day, locale),
    count: Number(row.count || 0),
    errors: Number(row.errors || 0),
    countHeight: barHeight(row.count, maxCount),
    errorsHeight: barHeight(row.errors, maxErrors),
  }))
}

// ── Usage: map /admin/usage daily rows onto the TrendChart fields ───────────

export function buildUsageTrend(daily = [], locale = 'ru') {
  const rows = Array.isArray(daily) ? daily : []
  return rows.map(row => ({
    day: row.day,
    dayLabel: dayLabel(row.day, locale),
    total_cost_usd: Number(row.cost_usd || 0),
    total_tokens: Number(row.total_tokens || 0),
    avg_latency_ms: 0,
    calls: Number(row.calls || 0),
  }))
}

// ── Status tones ────────────────────────────────────────────────────────────

export function promptStatusTone(status) {
  if (status === 'error') return 'bad'
  if (status === 'pending') return 'warn'
  return 'good'
}

export function healthTone(status) {
  return status === 'ok' ? 'good' : 'bad'
}

export function documentTone(status) {
  if (status === 'done') return 'good'
  if (status === 'failed') return 'bad'
  return 'warn'
}

// ── Formatters ──────────────────────────────────────────────────────────────

export function formatCost(value, digits = 4) {
  return `$${Number(value || 0).toFixed(digits)}`
}

export function formatDateTime(value, locale = 'ru') {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const time = date.toLocaleTimeString(
    locale === 'en' ? 'en-US' : 'ru-RU',
    { hour: '2-digit', minute: '2-digit' },
  )
  return `${formatLocaleDate(date, locale)} ${time}`
}

export function formatBytes(bytes) {
  const n = Number(bytes || 0)
  if (n >= 1024 * 1024 * 1024) return `${(n / 1024 / 1024 / 1024).toFixed(1)} GB`
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`
  if (n >= 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${n} B`
}

// ── Prompt feed helpers ─────────────────────────────────────────────────────

export const PROMPT_MODES = ['stream', 'run', 'research']
export const PROMPT_STATUSES = ['ok', 'error', 'pending']

export function buildPromptQueryParams(filters = {}, pagination = {}) {
  const params = new URLSearchParams()
  if (filters.tenantId) params.set('tenant_id', filters.tenantId)
  if (filters.userId) params.set('user_id', filters.userId)
  if (filters.mode) params.set('mode', filters.mode)
  if (filters.status) params.set('status', filters.status)
  if (filters.q) params.set('q', filters.q)
  params.set('days', String(filters.days || 30))
  params.set('limit', String(pagination.limit || 50))
  params.set('offset', String(pagination.offset || 0))
  return params.toString()
}

export function promptActor(item, locale = 'ru') {
  if (!item) return '—'
  if (item.user_name) return item.user_name
  if (item.user_id) return String(item.user_id).slice(0, 8)
  return translate(locale, 'admin.unboundKey')
}
