function clean(value) {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}

// Deployment config resolution for the tenant API key and base URL.
//
// Priority: runtime config (window.__AAP_CONFIG__, written by the UI
// container at start from UI_API_KEY/UI_API_BASE_URL) > build-time env
// (kept for backwards compatibility — Vite inlines VITE_* vars into the
// public bundle, so it must never carry a secret) > user-entered value in
// localStorage. keySource 'env' means "managed by the deployment".
export function resolveApiConfig({ stored = {}, env = {}, runtime = {} } = {}) {
  const runtimeKey = clean(runtime.apiKey)
  const envKey = clean(env.VITE_API_KEY) || clean(env.VITE_X_API_KEY)
  const storedKey = clean(stored.apiKey)
  const runtimeBase = clean(runtime.baseUrl)
  const envBase = clean(env.VITE_API_BASE_URL) || clean(env.VITE_API_BASE)
  const storedBase = clean(stored.base)

  const injectedKey = runtimeKey || envKey
  const apiKey = injectedKey || storedKey

  return {
    apiKey,
    baseUrl: runtimeBase || envBase || storedBase || '/api',
    keySource: injectedKey ? 'env' : storedKey ? 'localStorage' : 'missing',
    isKeyManagedByEnv: Boolean(injectedKey),
  }
}
