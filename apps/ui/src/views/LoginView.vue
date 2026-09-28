<template>
  <div class="login-screen">
    <div class="login-card">
      <div class="login-logo">
        <div class="logo-mark">A</div>
      </div>
      <div class="login-title">{{ t('login.title') }}</div>
      <div class="login-sub">{{ t('login.sub') }}</div>

      <div v-if="error" class="login-error">{{ error }}</div>

      <button
        v-if="!busy"
        class="btn btn-primary login-google-btn"
        :disabled="!loginUrl && !checking"
        @click="startLogin"
      >
        <svg width="16" height="16" viewBox="0 0 18 18" aria-hidden="true">
          <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62Z"/>
          <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18Z"/>
          <path fill="#FBBC05" d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.95H.96a9 9 0 0 0 0 8.1l3.01-2.33Z"/>
          <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.9 11.42 0 9 0A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58Z"/>
        </svg>
        {{ t('login.google') }}
      </button>
      <div v-else class="login-busy"><div class="spinner"></div></div>

      <div v-if="notConfigured" class="login-hint">
        {{ t('login.notConfigured') }}
      </div>

      <div class="login-divider"><span>{{ t('login.or') }}</span></div>

      <RouterLink class="btn btn-ghost login-key-btn" to="/chat">
        {{ t('login.useApiKey') }}
      </RouterLink>
      <div class="login-key-hint">{{ t('login.useApiKeyHint') }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { parseSessionHash, useSessionStore } from '@/stores/session'
import { useSettingsStore } from '@/stores/settings'
import { useI18n } from '@/composables/useI18n'

const router = useRouter()
const session = useSessionStore()
const settings = useSettingsStore()
const { t } = useI18n()

const busy = ref(false)
const checking = ref(true)
const loginUrl = ref('')
const notConfigured = ref(false)
const error = ref('')

onMounted(async () => {
  // OAuth return: #token=… (success) or #error=… (denied/expired)
  const parsed = parseSessionHash(window.location.hash)
  if (parsed.token) {
    if (session.setToken(parsed.token)) {
      history.replaceState(null, '', window.location.pathname)
      router.replace(session.isAdmin ? '/admin' : '/chat')
      return
    }
    error.value = t('login.invalidToken')
  } else if (parsed.error) {
    error.value = t('login.googleError', { message: parsed.error })
    history.replaceState(null, '', window.location.pathname)
  }

  // Already logged in? Go to the right cabinet.
  if (session.isAuthenticated) {
    router.replace(session.isAdmin ? '/admin' : '/chat')
    return
  }

  // Ask the API for the consent URL (503 => OAuth not configured).
  checking.value = true
  try {
    const base = settings.baseUrl || '/api'
    const redirect = `${window.location.origin}/login`
    const res = await fetch(`${base}/auth/google/url?redirect=${encodeURIComponent(redirect)}`)
    if (res.status === 503) {
      notConfigured.value = true
    } else if (res.ok) {
      loginUrl.value = (await res.json()).url
    } else {
      error.value = t('login.urlError', { status: res.status })
    }
  } catch {
    error.value = t('settings.connectionError')
  } finally {
    checking.value = false
  }
})

function startLogin() {
  if (loginUrl.value) window.location.href = loginUrl.value
}
</script>

<style scoped>
.login-screen {
  position: absolute;
  inset: 0;
  z-index: 30;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg);
  padding: 20px;
}
.login-card {
  width: 380px;
  max-width: 100%;
  padding: 34px 32px 28px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--s1);
  text-align: center;
}
.login-logo {
  display: flex;
  justify-content: center;
  margin-bottom: 14px;
}
.logo-mark {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: linear-gradient(135deg, var(--accent), var(--purple));
  color: var(--on-accent);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 20px;
}
.login-title {
  font-size: 17px;
  font-weight: 700;
  color: var(--text);
}
.login-sub {
  margin: 8px 0 22px;
  color: var(--muted);
  font-size: 12.5px;
  line-height: 1.5;
}
.login-google-btn {
  width: 100%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 11px 16px;
}
.login-busy {
  display: flex;
  justify-content: center;
  padding: 12px 0;
}
.login-error {
  margin-bottom: 14px;
  padding: 10px 12px;
  border: 1px solid color-mix(in oklch, var(--red) 30%, transparent);
  border-radius: 10px;
  background: color-mix(in oklch, var(--red) 10%, transparent);
  color: var(--red);
  font-size: 12px;
}
.login-hint {
  margin-top: 12px;
  color: var(--yellow);
  font-size: 11.5px;
  line-height: 1.5;
}
.login-divider {
  position: relative;
  margin: 20px 0 14px;
  color: var(--muted);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.login-divider::before,
.login-divider::after {
  content: '';
  position: absolute;
  top: 50%;
  width: calc(50% - 30px);
  height: 1px;
  background: var(--border);
}
.login-divider::before { left: 0; }
.login-divider::after { right: 0; }
.login-key-btn {
  width: 100%;
  padding: 10px 16px;
}
.login-key-hint {
  margin-top: 10px;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.5;
}
</style>
