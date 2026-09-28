<template>
  <div class="login-screen">
    <div class="login-card">
      <div class="login-logo">
        <div class="logo-mark">A</div>
      </div>
      <div class="login-title">{{ t('login.title') }}</div>
      <div class="login-sub">{{ t('login.sub') }}</div>

      <!-- ── Email + password ─────────────────────────────────── -->
      <template v-if="mode === 'email'">
        <div class="login-mode" role="tablist">
          <button
            v-for="m in emailModes"
            :key="m.id"
            type="button"
            role="tab"
            :class="['login-mode-btn', { active: emailMode === m.id }]"
            :aria-selected="emailMode === m.id"
            @click="emailMode = m.id; error = ''"
          >
            {{ t(m.labelKey) }}
          </button>
        </div>

        <div class="form-group">
          <label class="form-label">{{ t('login.email') }}</label>
          <input
            v-model="email"
            type="email"
            class="form-input"
            placeholder="name@example.com"
            :disabled="busy"
            @keyup.enter="submit"
          />
        </div>
        <div v-if="emailMode === 'register'" class="form-group">
          <label class="form-label">{{ t('login.name') }}</label>
          <input
            v-model="name"
            class="form-input"
            :placeholder="t('login.namePlaceholder')"
            :disabled="busy"
            @keyup.enter="submit"
          />
        </div>
        <div class="form-group">
          <label class="form-label">{{ t('login.password') }}</label>
          <input
            v-model="password"
            type="password"
            class="form-input"
            :placeholder="t('login.passwordPlaceholder')"
            :disabled="busy"
            @keyup.enter="submit"
          />
        </div>

        <div v-if="error" class="login-error">{{ error }}</div>

        <button class="btn btn-primary login-main-btn" :disabled="busy || !canSubmit" @click="submit">
          <div v-if="busy" class="spinner" style="width: 13px; height: 13px; border-width: 1.5px"></div>
          {{ busy ? t('settings.validating') : submitLabel }}
        </button>

        <div class="login-divider"><span>{{ t('login.or') }}</span></div>
        <button class="btn btn-ghost login-alt-btn" :disabled="!loginUrl" @click="startGoogle">
          <svg width="15" height="15" viewBox="0 0 18 18" aria-hidden="true">
            <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62Z"/>
            <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18Z"/>
            <path fill="#FBBC05" d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.95H.96a9 9 0 0 0 0 8.1l3.01-2.33Z"/>
            <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.9 11.42 0 9 0A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58Z"/>
          </svg>
          {{ t('login.google') }}
        </button>
        <div v-if="notConfigured" class="login-hint">{{ t('login.googleOnlyHint') }}</div>
      </template>

      <!-- ── Google only ───────────────────────────────────────── -->
      <template v-else>
        <button v-if="!checking" class="btn btn-primary login-main-btn" :disabled="!loginUrl" @click="startGoogle">
          <svg width="16" height="16" viewBox="0 0 18 18" aria-hidden="true">
            <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62Z"/>
            <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18Z"/>
            <path fill="#FBBC05" d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.95H.96a9 9 0 0 0 0 8.1l3.01-2.33Z"/>
            <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.9 11.42 0 9 0A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58Z"/>
          </svg>
          {{ t('login.google') }}
        </button>
        <div v-else class="login-busy"><div class="spinner"></div></div>
        <div v-if="notConfigured" class="login-hint">{{ t('login.notConfigured') }}</div>

        <div class="login-divider"><span>{{ t('login.or') }}</span></div>
        <button class="btn btn-ghost login-alt-btn" @click="mode = 'email'">
          {{ t('login.byEmail') }}
        </button>
      </template>

      <div class="login-footer-hint">{{ t('login.footerHint') }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { parseSessionHash, useSessionStore } from '@/stores/session'
import { useSettingsStore } from '@/stores/settings'
import { useI18n } from '@/composables/useI18n'

const router = useRouter()
const session = useSessionStore()
const settings = useSettingsStore()
const { t } = useI18n()

const emailModes = [
  { id: 'login', labelKey: 'login.modeEmailLogin' },
  { id: 'register', labelKey: 'login.modeEmailRegister' },
]

const mode = ref('email')
const emailMode = ref('login')
const email = ref('')
const name = ref('')
const password = ref('')
const busy = ref(false)
const error = ref('')

const checking = ref(false)
const loginUrl = ref('')
const notConfigured = ref(false)

const canSubmit = computed(() => email.value.trim() && password.value.length >= 8)
const submitLabel = computed(() => (
  emailMode.value === 'register' ? t('login.register') : t('login.connect')
))

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

  if (session.isAuthenticated) {
    router.replace(session.isAdmin ? '/admin' : '/chat')
    return
  }

  checking.value = true
  try {
    const base = settings.baseUrl || '/api'
    const redirect = `${window.location.origin}/login`
    const res = await fetch(`${base}/auth/google/url?redirect=${encodeURIComponent(redirect)}`)
    if (res.status === 503) {
      notConfigured.value = true
    } else if (res.ok) {
      loginUrl.value = (await res.json()).url
    }
  } catch {
    notConfigured.value = true
  } finally {
    checking.value = false
  }
})

function startGoogle() {
  if (loginUrl.value) window.location.href = loginUrl.value
}

async function submit() {
  if (!canSubmit.value || busy.value) return
  busy.value = true
  error.value = ''
  const base = settings.baseUrl || '/api'
  const path = emailMode.value === 'register' ? '/auth/register' : '/auth/login'
  try {
    const res = await fetch(`${base}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: email.value.trim(),
        password: password.value,
        name: name.value.trim(),
      }),
    })
    if (res.status === 401) {
      error.value = t('login.invalidCredentials')
      return
    }
    if (res.status === 403) {
      error.value = t('login.notAllowedEmail')
      return
    }
    if (res.status === 409) {
      error.value = t('login.emailTaken')
      return
    }
    if (res.status === 503) {
      error.value = t('login.emailNotConfigured')
      return
    }
    if (!res.ok) {
      const detail = await res.json().catch(() => null)
      error.value = detail?.detail?.[0]?.msg
        ? `${t('login.weakPassword')} (${detail.detail[0].msg})`
        : t('login.urlError', { status: res.status })
      return
    }
    const data = await res.json()
    if (session.setToken(data.token)) {
      router.replace(session.isAdmin ? '/admin' : '/chat')
    } else {
      error.value = t('login.invalidToken')
    }
  } catch {
    error.value = t('settings.connectionError')
  } finally {
    busy.value = false
  }
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
  width: 390px;
  max-width: 100%;
  padding: 32px 32px 24px;
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
  margin: 8px 0 18px;
  color: var(--muted);
  font-size: 12.5px;
  line-height: 1.5;
}
.login-mode {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  padding: 4px;
  margin-bottom: 16px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--s2);
}
.login-mode-btn {
  min-height: 34px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--muted2);
  cursor: pointer;
  font-family: var(--font);
  font-size: 12.5px;
  font-weight: 600;
}
.login-mode-btn.active {
  background: var(--s3);
  color: var(--text);
  box-shadow: inset 0 0 0 1px var(--border2);
}
.form-group { text-align: left; margin-bottom: 13px; }
.login-main-btn,
.login-alt-btn {
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
  margin-bottom: 13px;
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
  margin: 16px 0 14px;
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
.login-footer-hint {
  margin-top: 18px;
  color: var(--muted);
  font-size: 10.5px;
  line-height: 1.5;
}
</style>
