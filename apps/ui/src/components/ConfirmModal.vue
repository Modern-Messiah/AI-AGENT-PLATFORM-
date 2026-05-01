<template>
  <Teleport to="body">
    <div class="modal-overlay" @click.self="$emit('cancel')">
      <div class="modal confirm-modal" role="alertdialog" aria-modal="true">

        <div class="confirm-icon-wrap">
          <div class="confirm-icon-circle">
            <AppIcon name="trash" :size="22" />
          </div>
        </div>

        <div class="confirm-title">{{ heading }}</div>
        <div class="confirm-session-name">{{ title }}</div>

        <div class="confirm-warning">
          Все сообщения будут удалены безвозвратно
        </div>

        <div class="confirm-actions">
          <button ref="cancelBtn" class="btn btn-ghost" @click="$emit('cancel')">Отмена</button>
          <button class="btn btn-danger" @click="$emit('confirm')">Удалить</button>
        </div>

      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import AppIcon from '@/components/AppIcon.vue'

const props = defineProps({
  title:   { type: String, required: true },
  heading: { type: String, default: 'Удалить сессию?' },
})
const emit = defineEmits(['confirm', 'cancel'])

const cancelBtn = ref(null)

function onKey(e) {
  if (e.key === 'Escape') emit('cancel')
}

onMounted(() => {
  cancelBtn.value?.focus()
  document.addEventListener('keydown', onKey)
})
onUnmounted(() => {
  document.removeEventListener('keydown', onKey)
})
</script>
