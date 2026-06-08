function clean(value) {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}

export function resolveApiConfig({ stored = {}, env = {} } = {}) {
  const envKey = clean(env.VITE_API_KEY) || clean(env.VITE_X_API_KEY)
  const storedKey = clean(stored.apiKey)
  const envBase = clean(env.VITE_API_BASE_URL) || clean(env.VITE_API_BASE)
  const storedBase = clean(stored.base)

  const apiKey = envKey || storedKey

  return {
    apiKey,
    baseUrl: envBase || storedBase || '/api',
    keySource: envKey ? 'env' : storedKey ? 'localStorage' : 'missing',
    isKeyManagedByEnv: Boolean(envKey),
  }
}
