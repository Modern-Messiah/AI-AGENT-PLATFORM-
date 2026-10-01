<template>
  <div ref="root" :class="['protected-asset', { compact }]">
    <button
      v-if="imageUrl"
      class="asset-preview-button"
      type="button"
      :title="t('assets.openPreview')"
      @click="opened = true"
    >
      <img :src="imageUrl" :alt="alt || t('assets.previewAlt')" />
      <span v-if="pageNumber" class="asset-page">
        {{ t('assets.page', { page: pageNumber }) }}
      </span>
    </button>
    <div v-else-if="loading" class="asset-placeholder">
      <div class="spinner"></div>
      <span>{{ t('assets.loading') }}</span>
    </div>
    <div v-else class="asset-placeholder asset-error">
      {{ t('assets.unavailable') }}
    </div>

    <div v-if="opened && imageUrl" class="asset-lightbox" role="dialog" aria-modal="true" @click.self="opened = false">
      <div class="asset-lightbox-content">
        <button
          class="asset-close"
          type="button"
          :title="t('common.close')"
          @click="opened = false"
        >
          ×
        </button>
        <img :src="imageUrl" :alt="alt || t('assets.previewAlt')" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useApi } from '@/composables/useApi'
import { useI18n } from '@/composables/useI18n'

const props = defineProps({
  documentId: { type: String, required: true },
  assetId: { type: String, required: true },
  pageNumber: { type: Number, default: null },
  alt: { type: String, default: '' },
  compact: { type: Boolean, default: false },
})

const { apiRawFetch } = useApi()
const { t } = useI18n()
const imageUrl = ref('')
const loading = ref(true)
const opened = ref(false)
const root = ref(null)
const visible = ref(false)
let requestController = null
let observer = null

function releaseImage() {
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
  imageUrl.value = ''
}

async function loadImage() {
  requestController?.abort()
  if (!visible.value) {
    return
  }
  const controller = new AbortController()
  requestController = controller
  releaseImage()
  opened.value = false
  if (!props.documentId || !props.assetId) {
    loading.value = false
    return
  }
  loading.value = true
  try {
    const response = await apiRawFetch(
      `/documents/${encodeURIComponent(props.documentId)}/assets/${encodeURIComponent(props.assetId)}/content`,
      { signal: controller.signal },
    )
    const objectUrl = URL.createObjectURL(await response.blob())
    if (controller.signal.aborted || requestController !== controller) {
      URL.revokeObjectURL(objectUrl)
      return
    }
    imageUrl.value = objectUrl
  } catch (error) {
    if (error?.name === 'AbortError') return
    imageUrl.value = ''
  } finally {
    if (requestController === controller) loading.value = false
  }
}

watch(
  () => [props.documentId, props.assetId, visible.value],
  loadImage,
  { immediate: true },
)
onMounted(() => {
  if (!globalThis.IntersectionObserver) {
    visible.value = true
    return
  }
  observer = new globalThis.IntersectionObserver(
    entries => {
      if (!entries.some(entry => entry.isIntersecting)) return
      visible.value = true
      observer?.disconnect()
      observer = null
    },
    { rootMargin: '200px' },
  )
  if (root.value) observer.observe(root.value)
})
onBeforeUnmount(() => {
  observer?.disconnect()
  requestController?.abort()
  releaseImage()
})
</script>

<style scoped>
.protected-asset {
  min-width: 0;
}
.asset-preview-button {
  position: relative;
  display: block;
  width: 100%;
  padding: 0;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--s1);
  cursor: zoom-in;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}
.asset-preview-button:hover {
  border-color: color-mix(in oklch, var(--accent) 40%, var(--border));
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
}
.asset-preview-button:active {
  transform: scale(0.97);
}
.asset-preview-button img {
  display: block;
  width: 100%;
  max-height: 260px;
  object-fit: contain;
  background: color-mix(in oklch, var(--s3) 72%, transparent);
}
.compact .asset-preview-button {
  width: min(100%, 260px);
}
.compact .asset-preview-button img {
  height: 150px;
  object-fit: cover;
}
.asset-page {
  position: absolute;
  right: 8px;
  bottom: 8px;
  padding: 3px 7px;
  border: 1px solid color-mix(in oklch, white 22%, transparent);
  border-radius: 6px;
  background: color-mix(in oklch, black 74%, transparent);
  color: white;
  font-family: var(--mono);
  font-size: 10px;
}
.asset-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 110px;
  border: 1px dashed var(--border2);
  border-radius: 8px;
  color: var(--muted);
  font-size: 11px;
}
.asset-error {
  min-height: 54px;
}
.asset-lightbox {
  position: fixed;
  z-index: 1000;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 24px;
  background: color-mix(in oklch, black 70%, transparent);
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  animation: lightboxFadeIn 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}
@keyframes lightboxFadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
.asset-lightbox-content {
  position: relative;
  max-width: min(1100px, 96vw);
  max-height: 92vh;
  animation: lightboxScaleUp 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}
@keyframes lightboxScaleUp {
  from { transform: scale(0.94); opacity: 0; }
  to { transform: scale(1); opacity: 1; }
}
.asset-lightbox-content img {
  display: block;
  max-width: 100%;
  max-height: 92vh;
  border-radius: 14px;
  object-fit: contain;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(255, 255, 255, 0.1);
}
.asset-close {
  position: absolute;
  z-index: 1;
  top: 10px;
  right: 10px;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid color-mix(in oklch, white 24%, transparent);
  border-radius: 50%;
  background: color-mix(in oklch, black 60%, transparent);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  color: white;
  cursor: pointer;
  font-size: 18px;
  line-height: 1;
  transition: all 0.15s cubic-bezier(0.16, 1, 0.3, 1);
}
.asset-close:hover {
  background: color-mix(in oklch, black 80%, transparent);
  transform: scale(1.05);
}
.asset-close:active {
  transform: scale(0.92);
}
</style>
