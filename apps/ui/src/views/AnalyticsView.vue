<template>
  <div class="screen-body analytics-screen">
    <div class="analytics-toolbar">
      <span class="toolbar-label">{{ t('analytics.period') }}</span>
      <button
        v-for="d in [7, 14, 30]"
        :key="d"
        :class="['btn btn-ghost btn-sm', { 'btn-primary': days === d }]"
        @click="days = d"
      >
        {{ t('analytics.daysShort', { days: d }) }}
      </button>
      <button class="btn btn-ghost btn-sm" :disabled="loading" @click="load">
        <div v-if="loading" class="spinner"></div>
        <AppIcon v-else name="refresh" :size="13" />
      </button>
      <span class="tenant-label">
        {{ data ? `tenant: ${data.tenant_id}` : t('analytics.noData') }}
      </span>
    </div>

    <div v-if="!settings.isConnected" class="empty">
      <div class="empty-icon">🔑</div>
      <div class="empty-title">{{ t('analytics.noKeyTitle') }}</div>
      <div class="empty-sub">{{ t('analytics.noKeySub') }}</div>
    </div>

    <div v-if="error" class="analytics-error">
      {{ t('analytics.clickhouseError', { message: error }) }}
    </div>

    <template v-if="settings.isConnected && data && dashboard">
      <div class="stats-grid">
        <div v-for="s in stats" :key="s.label" class="stat-card">
          <div class="stat-label">{{ s.label }}</div>
          <div class="stat-value">{{ s.value }}</div>
          <div v-if="s.sub" class="stat-sub">{{ s.sub }}</div>
        </div>
      </div>

      <div class="analytics-dashboard">
        <div class="card dashboard-card trend-card">
          <div class="card-header">
            <div>
              <div class="card-title">{{ t('analytics.trend') }}</div>
              <div class="card-sub">{{ t('analytics.trendSub') }}</div>
            </div>
            <span class="badge badge-muted">{{ t('analytics.lastDays', { days }) }}</span>
          </div>
          <div v-if="!dashboard.dailyTrend.length" class="empty compact-empty">
            <div class="empty-title">{{ t('analytics.noDaily') }}</div>
            <div class="empty-sub">{{ t('analytics.noDailySub') }}</div>
          </div>
          <div v-else class="trend-chart">
            <div
              v-for="day in dashboard.dailyTrend"
              :key="day.day"
              class="trend-day"
            >
              <div class="trend-bars">
                <span class="trend-bar cost" :style="{ height: day.costHeight + '%' }"></span>
                <span class="trend-bar tokens" :style="{ height: day.tokensHeight + '%' }"></span>
              </div>
              <div class="trend-label">{{ day.dayLabel }}</div>
            </div>
          </div>
          <div class="legend-row">
            <span><i class="legend-dot cost"></i> {{ t('analytics.cost') }}</span>
            <span><i class="legend-dot tokens"></i> {{ t('analytics.tokens') }}</span>
          </div>
        </div>

        <div class="card dashboard-card">
          <div class="card-header">
            <div>
              <div class="card-title">{{ t('analytics.providerMix') }}</div>
              <div class="card-sub">{{ t('analytics.providerMixSub') }}</div>
            </div>
          </div>
          <div class="provider-list">
            <div v-for="provider in dashboard.providerMix" :key="provider.provider" class="provider-row">
              <div class="provider-head">
                <span class="provider-name">{{ provider.provider }}</span>
                <span class="td-mono">{{ provider.percent }}%</span>
              </div>
              <div class="provider-track">
                <span class="provider-fill" :style="{ width: provider.percent + '%' }"></span>
              </div>
              <div class="provider-meta">
                {{ t('analytics.calls', { count: provider.calls }) }} · {{ fmtTokens(provider.tokens) }} · {{ fmtCost(provider.cost) }}
              </div>
            </div>
            <div v-if="!dashboard.providerMix.length" class="muted-line">{{ t('analytics.noProviderEvents') }}</div>
          </div>
        </div>

        <div class="card dashboard-card">
          <div class="card-header">
            <div>
              <div class="card-title">{{ t('analytics.efficiency') }}</div>
              <div class="card-sub">{{ t('analytics.efficiencySub') }}</div>
            </div>
          </div>
          <div class="efficiency-grid">
            <div class="mini-metric">
              <span>{{ t('analytics.costPerTokens') }}</span>
              <strong>{{ fmtCost(dashboard.totals.costPer1kTokens, 5) }}</strong>
            </div>
            <div class="mini-metric">
              <span>{{ t('analytics.averageLatency') }}</span>
              <strong>{{ fmtMs(dashboard.totals.avgLatencyMs) }}</strong>
            </div>
            <div class="mini-metric">
              <span>{{ t('analytics.speedStatus') }}</span>
              <strong :class="['health', dashboard.latencyHealth.tone]">
                {{ dashboard.latencyHealth.label }}
              </strong>
            </div>
            <div class="mini-metric">
              <span>{{ t('analytics.callsPerDay') }}</span>
              <strong>{{ callsPerDay }}</strong>
            </div>
          </div>
        </div>

        <div class="card dashboard-card">
          <div class="card-header">
            <div>
              <div class="card-title">{{ t('analytics.topModels') }}</div>
              <div class="card-sub">{{ t('analytics.topModelsSub') }}</div>
            </div>
          </div>
          <div class="model-rank">
            <div v-for="row in topModels" :key="`${row.provider}:${row.model}`" class="model-rank-row">
              <div>
                <span class="tag">{{ row.model }}</span>
                <div class="model-rank-meta">{{ row.provider }} · {{ t('analytics.calls', { count: row.call_count }) }}</div>
              </div>
              <strong>{{ fmtCost(row.total_cost_usd) }}</strong>
            </div>
            <div v-if="!topModels.length" class="muted-line">{{ t('analytics.modelsEmpty') }}</div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <div class="card-title">{{ t('analytics.breakdown') }}</div>
          <span class="badge badge-muted">{{ t('analytics.lastDays', { days }) }}</span>
        </div>
        <div v-if="!data.breakdown.length" class="empty" style="padding: 32px">
          <div class="empty-icon">📊</div>
          <div class="empty-title">{{ t('analytics.noBreakdown') }}</div>
          <div class="empty-sub">{{ t('analytics.noBreakdownSub') }}</div>
        </div>
        <table v-else>
          <thead>
            <tr>
              <th>{{ t('analytics.model') }}</th>
              <th>{{ t('analytics.provider') }}</th>
              <th>{{ t('analytics.callCount') }}</th>
              <th>{{ t('analytics.tokens') }}</th>
              <th>{{ t('analytics.costColumn') }}</th>
              <th>{{ t('analytics.averageLatency') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in data.breakdown" :key="i">
              <td><span class="tag">{{ row.model }}</span></td>
              <td class="td-mono">{{ row.provider }}</td>
              <td class="td-mono">{{ row.call_count }}</td>
              <td class="td-mono">{{ fmtTokens(row.total_tokens) }}</td>
              <td><span style="font-family: var(--mono); font-weight: 600">{{ fmtCost(row.total_cost_usd) }}</span></td>
              <td class="td-mono">{{ fmtMs(row.avg_latency_ms) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <div style="display: flex; gap: 16px; font-size: 12px; color: var(--muted)">
      <span>ClickHouse · analytics.llm_usage_events · TTL 90d</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useApi } from '@/composables/useApi'
import { useSettingsStore } from '@/stores/settings'
import { useI18n } from '@/composables/useI18n'
import AppIcon from '@/components/AppIcon.vue'
import {
  buildAnalyticsDashboard,
  formatCost,
  formatMs,
  formatTokens,
} from '@/utils/analytics'

const { apiFetch } = useApi()
const settings = useSettingsStore()
const { t } = useI18n()

const days = ref(7)
const data = ref(null)
const loading = ref(false)
const error = ref(null)

async function load() {
  if (!settings.isConnected) return
  loading.value = true; error.value = null
  try {
    data.value = await apiFetch(`/analytics/usage?days=${days.value}`)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

watch([days, () => settings.apiKey], load, { immediate: true })

const fmtTokens = formatTokens
const fmtCost = formatCost
const fmtMs = formatMs

const dashboard = computed(() => (
  data.value ? buildAnalyticsDashboard(data.value, settings.locale) : null
))
const topModels = computed(() => (
  [...(data.value?.breakdown || [])]
    .sort((a, b) => Number(b.total_cost_usd || 0) - Number(a.total_cost_usd || 0))
    .slice(0, 4)
))
const callsPerDay = computed(() => {
  if (!dashboard.value || !days.value) return '0'
  return (dashboard.value.totals.totalCalls / days.value).toFixed(1)
})

const stats = computed(() => {
  if (!data.value || !dashboard.value) return []
  const totals = dashboard.value.totals
  return [
    { label: t('analytics.totalCost'), value: fmtCost(totals.totalCost), sub: t('analytics.lastDays', { days: days.value }) },
    { label: t('analytics.tokens'), value: fmtTokens(totals.totalTokens), sub: 'prompt + completion' },
    { label: t('analytics.averageLatency'), value: fmtMs(totals.avgLatencyMs), sub: dashboard.value.latencyHealth.label },
    { label: t('analytics.requests'), value: String(totals.totalCalls), sub: t('analytics.perDay', { count: callsPerDay.value }) },
  ]
})
</script>

<style scoped>
.analytics-screen {
  gap: 24px;
}
.analytics-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
}
.toolbar-label {
  color: var(--muted);
  font-size: 13px;
}
.tenant-label {
  margin-left: auto;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 12px;
}
.analytics-error {
  padding: 12px 16px;
  border: 1px solid color-mix(in oklch, var(--red) 30%, transparent);
  border-radius: 10px;
  background: color-mix(in oklch, var(--red) 10%, transparent);
  color: var(--red);
  font-size: 12px;
}
.stat-sub {
  margin-top: 6px;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10.5px;
}
.analytics-dashboard {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(280px, 0.75fr);
  gap: 14px;
}
.dashboard-card {
  min-height: 220px;
}
.trend-card {
  grid-row: span 2;
}
.trend-chart {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  min-height: 260px;
  padding: 18px 22px 8px;
}
.trend-day {
  display: flex;
  flex: 1;
  min-width: 28px;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}
.trend-bars {
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 4px;
  width: 100%;
  height: 220px;
  padding: 0 2px;
  border-bottom: 1px solid var(--border);
}
.trend-bar {
  width: 10px;
  min-height: 4px;
  border-radius: 999px 999px 0 0;
}
.trend-bar.cost,
.legend-dot.cost {
  background: var(--accent);
}
.trend-bar.tokens,
.legend-dot.tokens {
  background: var(--purple);
}
.trend-label {
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10px;
}
.legend-row {
  display: flex;
  gap: 14px;
  padding: 0 22px 18px;
  color: var(--muted);
  font-size: 11px;
}
.legend-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  margin-right: 5px;
  border-radius: 50%;
}
.provider-list,
.model-rank {
  display: grid;
  gap: 12px;
  padding: 16px 18px;
}
.provider-head,
.model-rank-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.provider-name {
  color: var(--text);
  font-weight: 700;
}
.provider-track {
  height: 7px;
  margin: 8px 0 6px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--s3);
}
.provider-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--accent), var(--purple));
}
.provider-meta,
.model-rank-meta,
.muted-line {
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10.5px;
}
.efficiency-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  padding: 16px 18px;
}
.mini-metric {
  min-height: 74px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: color-mix(in oklch, var(--s2) 74%, transparent);
}
.mini-metric span {
  display: block;
  margin-bottom: 8px;
  color: var(--muted);
  font-size: 11px;
}
.mini-metric strong,
.model-rank-row strong {
  color: var(--text);
  font-family: var(--mono);
  font-size: 15px;
}
.health.good {
  color: var(--green);
}
.health.warn {
  color: var(--yellow);
}
.health.bad {
  color: var(--red);
}
.compact-empty {
  padding: 36px 20px;
}

@media (max-width: 1000px) {
  .analytics-dashboard {
    grid-template-columns: 1fr;
  }
  .trend-card {
    grid-row: auto;
  }
}

@media (max-width: 680px) {
  .analytics-toolbar {
    align-items: flex-start;
    flex-wrap: wrap;
  }
  .tenant-label {
    width: 100%;
    margin-left: 0;
  }
  .efficiency-grid {
    grid-template-columns: 1fr;
  }
}
</style>
