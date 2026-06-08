export const SIDEBAR_COLLAPSED_STORAGE_KEY = 'mainSidebarCollapsed'

export function readStoredSidebarCollapsed(storage, key = SIDEBAR_COLLAPSED_STORAGE_KEY) {
  if (!storage) return false

  try {
    return storage.getItem(key) === '1'
  } catch {
    return false
  }
}

export function storeSidebarCollapsed(storage, collapsed, key = SIDEBAR_COLLAPSED_STORAGE_KEY) {
  if (!storage) return

  try {
    storage.setItem(key, collapsed ? '1' : '0')
  } catch {}
}

export function toggleSidebarCollapsed(current, storage, key = SIDEBAR_COLLAPSED_STORAGE_KEY) {
  const next = !current
  storeSidebarCollapsed(storage, next, key)
  return next
}
