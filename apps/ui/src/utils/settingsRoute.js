export function settingsRedirect() {
  return {
    path: '/chat',
    query: { settings: '1' },
  }
}

export function shouldOpenSettingsModal(query = {}) {
  return query.settings === '1' || query.settings === 'true' || query.settings === true
}

export function clearSettingsQuery(query = {}) {
  const next = { ...query }
  delete next.settings
  return next
}
