<template>
  <Teleport to="body">
    <div class="modal-overlay" @click.self="$emit('cancel')">
      <div class="modal confirm-modal" role="alertdialog" aria-modal="true">

        <div class="confirm-icon-wrap">
          <div class="confirm-icon-circle">
            <AppIcon name="trash" :size="22" />
          </div>
        </div>

        <div class="confirm-title">{{ heading || t('chat.deleteSession') }}</div>
        <div class="confirm-session-name">{{ title }}</div>

        <div class="confirm-warning">
          {{ t('chat.deleteWarning') }}
        </div>

        <div class="confirm-actions">
          <button ref="cancelBtn" class="btn btn-ghost" @click="$emit('cancel')">{{ t('common.cancel') }}</button>
          <button class="btn btn-danger" @click="$emit('confirm')">{{ t('common.delete') }}</button>
        </div>

      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import { useI18n } from '@/composables/useI18n'

const props = defineProps({
  title:   { type: String, required: true },
  heading: { type: String, default: '' },
})
const emit = defineEmits(['confirm', 'cancel'])

const cancelBtn = ref(null)
const { t } = useI18n()

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
