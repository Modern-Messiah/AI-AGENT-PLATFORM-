<template>
  <div :class="['toast', type]">
    <span class="toast-icon">{{ icon }}</span>
    <span class="toast-msg">{{ msg }}</span>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'

const props = defineProps({
  msg: String,
  type: { type: String, default: 'info' }
})
const emit = defineEmits(['done'])

const icon = computed(() => ({ success: '✓', error: '✕', info: 'ℹ' }[props.type] || 'ℹ'))

onMounted(() => {
  setTimeout(() => emit('done'), 3200)
})
</script>
