export const CHAT_HISTORY_MIN_WIDTH = 180
export const CHAT_HISTORY_MAX_WIDTH = 420
export const CHAT_HISTORY_DEFAULT_WIDTH = 260
export const CHAT_HISTORY_STORAGE_KEY = 'chatHistoryWidth'

export function clampPaneWidth(width, min = CHAT_HISTORY_MIN_WIDTH, max = CHAT_HISTORY_MAX_WIDTH) {
  const numeric = Number(width)
  if (!Number.isFinite(numeric)) return min
  return Math.min(Math.max(Math.round(numeric), min), max)
}

export function readStoredPaneWidth(storage, key = CHAT_HISTORY_STORAGE_KEY) {
  if (!storage) return CHAT_HISTORY_DEFAULT_WIDTH

  try {
    const parsed = Number(storage.getItem(key))
    if (!Number.isFinite(parsed)) return CHAT_HISTORY_DEFAULT_WIDTH
    if (parsed < CHAT_HISTORY_MIN_WIDTH || parsed > CHAT_HISTORY_MAX_WIDTH) {
      return CHAT_HISTORY_DEFAULT_WIDTH
    }
    return Math.round(parsed)
  } catch {
    return CHAT_HISTORY_DEFAULT_WIDTH
  }
}

export function storePaneWidth(storage, width, key = CHAT_HISTORY_STORAGE_KEY) {
  if (!storage) return

  try {
    storage.setItem(key, String(clampPaneWidth(width)))
  } catch {}
}
