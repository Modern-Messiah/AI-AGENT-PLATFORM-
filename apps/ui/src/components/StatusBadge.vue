<template>
  <span :class="['badge', s.cls]">
    <span v-if="s.pulse" class="dot-pulse"></span>
    {{ s.label }}
  </span>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from '@/composables/useI18n'

const props = defineProps({ status: String })
const { t } = useI18n()

const STATUS_MAP = {
  done:       { cls: 'badge-green' },
  completed:  { cls: 'badge-green' },
  processing: { cls: 'badge-blue', pulse: true },
  running:    { cls: 'badge-blue', pulse: true },
  pending:    { cls: 'badge-muted', pulse: true },
  failed:     { cls: 'badge-red' },
  hitl:       { cls: 'badge-yellow', pulse: true },
  cache_hit:  { cls: 'badge-purple' },
}

const s = computed(() => {
  const status = STATUS_MAP[props.status]
  if (!status) return { cls: 'badge-muted', label: props.status }
  return { ...status, label: t(`status.${props.status}`) }
})
</script>
