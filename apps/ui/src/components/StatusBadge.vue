<template>
  <span :class="['badge', s.cls]">
    <span v-if="s.pulse" class="dot-pulse"></span>
    {{ s.label }}
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ status: String })

const STATUS_MAP = {
  done:       { cls: 'badge-green',  label: 'done' },
  completed:  { cls: 'badge-green',  label: 'completed' },
  processing: { cls: 'badge-blue',   label: 'processing', pulse: true },
  running:    { cls: 'badge-blue',   label: 'running',    pulse: true },
  pending:    { cls: 'badge-muted',  label: 'pending',    pulse: true },
  failed:     { cls: 'badge-red',    label: 'failed' },
  hitl:       { cls: 'badge-yellow', label: 'awaiting approval', pulse: true },
  cache_hit:  { cls: 'badge-purple', label: 'cache hit' },
}

const s = computed(() => STATUS_MAP[props.status] || { cls: 'badge-muted', label: props.status })
</script>
