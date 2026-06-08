<template>
  <div class="screen-body analytics-screen">
    <div class="analytics-toolbar">
      <span class="toolbar-label">Период:</span>
      <button
        v-for="d in [7, 14, 30]"
        :key="d"
        :class="['btn btn-ghost btn-sm', { 'btn-primary': days === d }]"
        @click="days = d"
      >
        {{ d }}д
      </button>
      <button class="btn btn-ghost btn-sm" :disabled="loading" @click="load">
        <div v-if="loading" class="spinner"></div>
        <AppIcon v-else name="refresh" :size="13" />
      </button>
      <span class="tenant-label">
        {{ data ? `tenant: ${data.tenant_id}` : 'нет данных' }}
      </span>
    </div>

    <div v-if="!settings.isConnected" class="empty">
      <div class="empty-icon">🔑</div>
      <div class="empty-title">Нет API-ключа</div>
      <div class="empty-sub">Настройте ключ в боковой панели чтобы загрузить аналитику</div>
    </div>

    <div v-if="error" class="analytics-error">
      Ошибка ClickHouse: {{ error }}
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
              <div class="card-title">Динамика расходов</div>
              <div class="card-sub">Стоимость и токены по дням</div>
            </div>
            <span class="badge badge-muted">last {{ days }}d</span>
          </div>
          <div v-if="!dashboard.dailyTrend.length" class="empty compact-empty">
            <div class="empty-title">Нет дневных событий</div>
            <div class="empty-sub">Новые события появятся после запросов к моделям</div>
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
            <span><i class="legend-dot cost"></i> стоимость</span>
            <span><i class="legend-dot tokens"></i> токены</span>
          </div>
        </div>

        <div class="card dashboard-card">
          <div class="card-header">
            <div>
              <div class="card-title">Микс провайдеров</div>
              <div class="card-sub">Кто реально отвечает на запросы</div>
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
                {{ provider.calls }} вызов(ов) · {{ fmtTokens(provider.tokens) }} · {{ fmtCost(provider.cost) }}
              </div>
            </div>
            <div v-if="!dashboard.providerMix.length" class="muted-line">Пока нет provider events</div>
          </div>
        </div>

        <div class="card dashboard-card">
          <div class="card-header">
            <div>
              <div class="card-title">Эффективность</div>
              <div class="card-sub">Сколько стоит контекст и насколько быстро отвечает</div>
            </div>
          </div>
          <div class="efficiency-grid">
            <div class="mini-metric">
              <span>Cost / 1K tokens</span>
              <strong>{{ fmtCost(dashboard.totals.costPer1kTokens, 5) }}</strong>
            </div>
            <div class="mini-metric">
              <span>Средняя latency</span>
              <strong>{{ fmtMs(dashboard.totals.avgLatencyMs) }}</strong>
            </div>
            <div class="mini-metric">
              <span>Статус скорости</span>
              <strong :class="['health', dashboard.latencyHealth.tone]">
                {{ dashboard.latencyHealth.label }}
              </strong>
            </div>
            <div class="mini-metric">
              <span>Вызовов / день</span>
              <strong>{{ callsPerDay }}</strong>
            </div>
          </div>
        </div>

        <div class="card dashboard-card">
          <div class="card-header">
            <div>
              <div class="card-title">Топ моделей</div>
              <div class="card-sub">По стоимости за период</div>
            </div>
          </div>
          <div class="model-rank">
            <div v-for="row in topModels" :key="`${row.provider}:${row.model}`" class="model-rank-row">
              <div>
                <span class="tag">{{ row.model }}</span>
                <div class="model-rank-meta">{{ row.provider }} · {{ row.call_count }} вызов(ов)</div>
              </div>
              <strong>{{ fmtCost(row.total_cost_usd) }}</strong>
            </div>
            <div v-if="!topModels.length" class="muted-line">Модели появятся после первых запросов</div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <div class="card-title">Разбивка по моделям</div>
          <span class="badge badge-muted">last {{ days }}d</span>
        </div>
        <div v-if="!data.breakdown.length" class="empty" style="padding: 32px">
          <div class="empty-icon">📊</div>
          <div class="empty-title">Нет данных</div>
          <div class="empty-sub">Сделайте запросы к агенту, чтобы увидеть аналитику</div>
        </div>
        <table v-else>
          <thead>
            <tr><th>Модель</th><th>Провайдер</th><th>Вызовов</th><th>Токены</th><th>Стоимость</th><th>Avg latency</th></tr>
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
import AppIcon from '@/components/AppIcon.vue'
import {
  buildAnalyticsDashboard,
  formatCost,
  formatMs,
  formatTokens,
} from '@/utils/analytics'

const { apiFetch } = useApi()
const settings = useSettingsStore()

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

const dashboard = computed(() => data.value ? buildAnalyticsDashboard(data.value) : null)
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
    { label: 'Общая стоимость', value: fmtCost(totals.totalCost), sub: `last ${days.value}d` },
    { label: 'Токены',          value: fmtTokens(totals.totalTokens), sub: 'prompt + completion' },
    { label: 'Avg latency',     value: fmtMs(totals.avgLatencyMs), sub: dashboard.value.latencyHealth.label },
    { label: 'Запросов',        value: String(totals.totalCalls), sub: `${callsPerDay.value} / день` },
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
