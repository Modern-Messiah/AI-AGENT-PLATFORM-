<template>
  <svg :width="size" :height="size" viewBox="0 0 16 16" fill="none" v-if="name === 'chat'">
    <path d="M14 2H2a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h2v3l3-3h7a1 1 0 0 0 1-1V3a1 1 0 0 0-1-1z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>
  </svg>
  <svg :width="size" :height="size" viewBox="0 0 16 16" fill="none" v-else-if="name === 'docs'">
    <path d="M9 1H4a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V5L9 1z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>
    <path d="M9 1v4h4M5 9h6M5 11.5h4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
  </svg>
  <svg :width="size" :height="size" viewBox="0 0 16 16" fill="none" v-else-if="name === 'analytics'">
    <rect x="1" y="9" width="3" height="6" rx="1" stroke="currentColor" stroke-width="1.3"/>
    <rect x="6" y="5" width="3" height="10" rx="1" stroke="currentColor" stroke-width="1.3"/>
    <rect x="11" y="2" width="3" height="13" rx="1" stroke="currentColor" stroke-width="1.3"/>
  </svg>
  <svg :width="size" :height="size" viewBox="0 0 16 16" fill="none" v-else-if="name === 'workflows'">
    <circle cx="3" cy="3" r="2" stroke="currentColor" stroke-width="1.3"/>
    <circle cx="13" cy="8" r="2" stroke="currentColor" stroke-width="1.3"/>
    <circle cx="3" cy="13" r="2" stroke="currentColor" stroke-width="1.3"/>
    <path d="M5 3.5l6 3.5M5 12.5l6-3.5" stroke="currentColor" stroke-width="1.3"/>
  </svg>
  <svg :width="size" :height="size" viewBox="0 0 16 16" fill="none" v-else-if="name === 'settings'">
    <circle cx="8" cy="8" r="2.5" stroke="currentColor" stroke-width="1.3"/>
    <path d="M8 1v2M8 13v2M1 8h2M13 8h2M3.05 3.05l1.42 1.42M11.53 11.53l1.42 1.42M3.05 12.95l1.42-1.42M11.53 4.47l1.42-1.42" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
  </svg>
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" v-else-if="name === 'send'">
    <path d="M12.5 1.5L6.5 7.5M12.5 1.5L8.5 12.5L6.5 7.5L1.5 5.5L12.5 1.5Z" stroke="white" stroke-width="1.4" stroke-linejoin="round"/>
  </svg>
  <svg :width="size" :height="size" viewBox="0 0 20 20" fill="none" v-else-if="name === 'upload'">
    <path d="M10 13V4M6 8l4-4 4 4M4 16h12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>
  <svg :width="size" :height="size" viewBox="0 0 13 13" fill="none" v-else-if="name === 'plus'">
    <path d="M6.5 1v11M1 6.5h11" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
  </svg>
  <svg :width="size" :height="size" viewBox="0 0 13 13" fill="none" v-else-if="name === 'trash'">
    <path d="M2 3h9M5 3V2h3v1M3 3l.7 8h5.6L10 3" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>
  <svg :width="size" :height="size" viewBox="0 0 13 13" fill="none" v-else-if="name === 'copy'">
    <rect x="4" y="4" width="8" height="8" rx="1.5" stroke="currentColor" stroke-width="1.3"/>
    <path d="M4 4V2.5A1.5 1.5 0 0 0 2.5 1H2a1 1 0 0 0-1 1v7.5A1.5 1.5 0 0 0 2.5 11H4" stroke="currentColor" stroke-width="1.3"/>
  </svg>
  <svg :width="size" :height="size" viewBox="0 0 16 16" fill="none" v-else-if="name === 'refresh'">
    <path d="M13.5 8A5.5 5.5 0 1 1 8 2.5c1.8 0 3.4.87 4.4 2.2M13.5 2v3h-3" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>
  <span v-else-if="name === 'agent'">A</span>
  <span v-else-if="name === 'user'">U</span>
</template>

<script setup>
defineProps({
  name: { type: String, required: true },
  size: { type: Number, default: 16 }
})
</script>
