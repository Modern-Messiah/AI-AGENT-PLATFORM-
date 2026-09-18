export const DEFAULT_THEME = 'graphite'

// 'auto' is a pseudo-theme: it resolves to a concrete dark/light theme from
// the OS prefers-color-scheme setting at apply time.
export const AUTO_THEME = 'auto'
export const AUTO_DARK_THEME = 'graphite'
export const AUTO_LIGHT_THEME = 'porcelain'

export const THEMES = [
  {
    id: 'graphite',
    labelKey: 'settings.themeGraphite',
    mode: 'dark',
    swatches: ['#0c0e12', '#18a9c9', '#7d7aec'],
  },
  {
    id: 'pine',
    labelKey: 'settings.themePine',
    mode: 'dark',
    swatches: ['#0b110f', '#35c98b', '#b8d96c'],
  },
  {
    id: 'plum',
    labelKey: 'settings.themePlum',
    mode: 'dark',
    swatches: ['#120d16', '#df6fa6', '#51c5d7'],
  },
  {
    id: 'porcelain',
    labelKey: 'settings.themePorcelain',
    mode: 'light',
    swatches: ['#f6f8fb', '#138c91', '#7568d9'],
  },
  {
    id: 'daylight',
    labelKey: 'settings.themeDaylight',
    mode: 'light',
    swatches: ['#f7f9ff', '#5067d9', '#e66f61'],
  },
]

const THEME_BY_ID = new Map(THEMES.map(theme => [theme.id, theme]))

export function prefersDarkMedia() {
  return typeof globalThis.matchMedia === 'function'
    ? globalThis.matchMedia('(prefers-color-scheme: dark)')
    : null
}

export function resolveAutoTheme(media = prefersDarkMedia()) {
  return media?.matches ? AUTO_DARK_THEME : AUTO_LIGHT_THEME
}

export function normalizeTheme(value) {
  if (value === AUTO_THEME) return AUTO_THEME
  return THEME_BY_ID.has(value) ? value : DEFAULT_THEME
}

export function applyTheme(value, root = globalThis.document?.documentElement, media) {
  const storedId = normalizeTheme(value)
  const themeId = storedId === AUTO_THEME ? resolveAutoTheme(media) : storedId
  const theme = THEME_BY_ID.get(themeId)

  if (root) {
    root.dataset.theme = themeId
    root.style.colorScheme = theme.mode
  }

  return themeId
}

export function persistTheme(storage, value) {
  const themeId = normalizeTheme(value)
  let config = {}

  try {
    config = JSON.parse(storage?.getItem('aap_config') || '{}')
  } catch {}

  storage?.setItem('aap_config', JSON.stringify({ ...config, theme: themeId }))
  return themeId
}
