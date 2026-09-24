import { onBeforeUnmount, onMounted, ref } from 'vue'

// Reactive (max-width: Npx) match; safely false where matchMedia is absent
// (SSR, node tests). Components render their desktop layout by default.
export function useMaxWidthMediaQuery(maxWidth) {
  const matches = ref(false)
  let mql = null
  let handler = null

  onMounted(() => {
    if (typeof globalThis.matchMedia !== 'function') return
    mql = globalThis.matchMedia(`(max-width: ${maxWidth}px)`)
    handler = (event) => {
      matches.value = event.matches
    }
    matches.value = mql.matches
    if (typeof mql.addEventListener === 'function') {
      mql.addEventListener('change', handler)
    } else if (typeof mql.addListener === 'function') {
      mql.addListener(handler)
    }
  })

  onBeforeUnmount(() => {
    if (!mql || !handler) return
    if (typeof mql.removeEventListener === 'function') {
      mql.removeEventListener('change', handler)
    } else if (typeof mql.removeListener === 'function') {
      mql.removeListener(handler)
    }
  })

  return matches
}
