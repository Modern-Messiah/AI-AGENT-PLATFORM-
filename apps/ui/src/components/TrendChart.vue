<template>
  <div class="trend-chart-wrap">
    <div class="chart-metric-toggle" role="group" :aria-label="t('analytics.trend')">
      <button
        v-for="m in metrics"
        :key="m.id"
        type="button"
        class="chart-metric-btn"
        :class="{ active: metric === m.id }"
        :aria-pressed="metric === m.id"
        @click="metric = m.id"
      >
        {{ t(m.labelKey) }}
      </button>
    </div>
    <div class="chart-canvas-wrap"><canvas ref="canvasRef"></canvas></div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Chart } from 'chart.js/auto'
import { useI18n } from '@/composables/useI18n'

const props = defineProps({
  days: { type: Array, default: () => [] },
})

const { t } = useI18n()
const canvasRef = ref(null)
const metric = ref('cost')

const metrics = [
  { id: 'cost', labelKey: 'analytics.metricCost', color: '#18a9c9', field: 'total_cost_usd', fill: true },
  { id: 'tokens', labelKey: 'analytics.metricTokens', color: '#7d7aec', field: 'total_tokens', fill: true },
  { id: 'latency', labelKey: 'analytics.metricLatency', color: '#dfb452', field: 'avg_latency_ms', fill: false },
]

let chart = null

function cssVar(name, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

function render() {
  if (!canvasRef.value) return
  const definition = metrics.find(m => m.id === metric.value) || metrics[0]
  const textColor = cssVar('--muted', '#8b93a7')
  const gridColor = 'rgba(139, 147, 167, 0.15)'

  const config = {
    type: 'line',
    data: {
      labels: props.days.map(day => day.dayLabel),
      datasets: [
        {
          label: t(definition.labelKey),
          data: props.days.map(day => Number(day[definition.field] || 0)),
          borderColor: definition.color,
          backgroundColor: definition.fill
            ? `${definition.color}22`
            : 'transparent',
          fill: definition.fill,
          tension: 0.3,
          pointRadius: props.days.length > 40 ? 0 : 2,
          pointHoverRadius: 4,
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: 'rgba(12, 14, 18, 0.92)',
          borderColor: gridColor,
          borderWidth: 1,
          titleColor: '#e6eaf2',
          bodyColor: '#c7cedb',
          padding: 10,
        },
      },
      scales: {
        x: {
          ticks: { color: textColor, maxRotation: 0, autoSkipPadding: 16, font: { size: 10 } },
          grid: { display: false },
        },
        y: {
          beginAtZero: true,
          ticks: { color: textColor, font: { size: 10 }, maxTicksLimit: 5 },
          grid: { color: gridColor },
        },
      },
    },
  }

  if (chart) {
    chart.destroy()
  }
  chart = new Chart(canvasRef.value, config)
}

onMounted(render)
watch([() => props.days, metric], render, { deep: false })
onBeforeUnmount(() => {
  if (chart) chart.destroy()
  chart = null
})
</script>

<style scoped>
.trend-chart-wrap {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.chart-metric-toggle {
  display: inline-flex;
  gap: 4px;
  align-self: flex-end;
  padding: 3px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: color-mix(in oklch, var(--s2) 70%, transparent);
}
.chart-metric-btn {
  padding: 4px 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--muted);
  font-family: var(--font);
  font-size: 11px;
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
.chart-metric-btn:hover { color: var(--text); }
.chart-metric-btn.active {
  background: color-mix(in oklch, var(--accent) 16%, transparent);
  color: var(--text);
}
.chart-canvas-wrap {
  position: relative;
  height: 220px;
}
</style>
