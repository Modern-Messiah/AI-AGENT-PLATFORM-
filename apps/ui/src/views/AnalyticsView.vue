<template>
  <div class="screen-body">
    <div style="display: flex; align-items: center; gap: 10px">
      <span style="font-size: 13px; color: var(--muted)">Период:</span>
      <button v-for="d in [7, 14, 30]" :key="d"
              :class="['btn btn-ghost btn-sm', { 'btn-primary': days === d }]"
              @click="days = d">{{ d }}д</button>
      <button class="btn btn-ghost btn-sm" :disabled="loading" style="margin-left: 4px" @click="load">
        <div v-if="loading" class="spinner"></div>
        <AppIcon v-else name="refresh" :size="13" />
      </button>
      <span style="margin-left: auto; font-family: var(--mono); font-size: 12px; color: var(--muted)">
        {{ data ? `tenant: ${data.tenant_id}` : 'нет данных' }}
      </span>
    </div>

    <div v-if="!settings.isConnected" class="empty">
      <div class="empty-icon">🔑</div>
      <div class="empty-title">Нет API-ключа</div>
      <div class="empty-sub">Настройте ключ в боковой панели чтобы загрузить аналитику</div>
    </div>

    <div v-if="error" style="padding: 12px 16px; background: color-mix(in oklch, var(--red) 10%, transparent); border: 1px solid color-mix(in oklch, var(--red) 30%, transparent); border-radius: 10px; font-size: 12px; color: var(--red)">
      Ошибка ClickHouse: {{ error }}
    </div>

    <template v-if="settings.isConnected && data">
      <div class="stats-grid">
        <div v-for="s in stats" :key="s.label" class="stat-card">
          <div class="stat-label">{{ s.label }}</div>
          <div class="stat-value">{{ s.value }}</div>
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
      <span>📊 ClickHouse · analytics.llm_usage_events · TTL 90d</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useApi } from '@/composables/useApi'
import { useSettingsStore } from '@/stores/settings'
import AppIcon from '@/components/AppIcon.vue'

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

const fmtTokens = n => n >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(0) + 'K' : String(n || 0)
const fmtCost = n => '$' + (n || 0).toFixed(4)
const fmtMs = n => (n || 0).toFixed(0) + 'ms'

const stats = computed(() => {
  if (!data.value) return []
  const bd = data.value.breakdown || []
  const totalTokens = bd.reduce((a, r) => a + (r.total_tokens || 0), 0)
  const totalCalls = bd.reduce((a, r) => a + (r.call_count || 0), 0)
  const avgLatency = bd.length ? bd.reduce((a, r) => a + (r.avg_latency_ms || 0), 0) / bd.length : 0
  return [
    { label: 'Общая стоимость', value: fmtCost(data.value.total_cost_usd) },
    { label: 'Токены',          value: fmtTokens(totalTokens) },
    { label: 'Avg latency',     value: fmtMs(avgLatency) },
    { label: 'Запросов',        value: String(totalCalls) },
  ]
})
</script>
