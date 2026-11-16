<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/composables/useApi'
import { authState, setToken } from '@/store/auth'
import { configState, refreshConfig } from '@/store/config'
import BackgroundSlideshow from '@/components/common/BackgroundSlideshow.vue'
import RecoveryCodeForm from '@/components/auth/RecoveryCodeForm.vue'
import PortalFooter from '@/components/portal/PortalFooter.vue'
import { useWorkspaceTheme } from '@/composables/useWorkspaceTheme'
import loginArtwork from '@/assets/branding/visualnovel.png'

useWorkspaceTheme()

const backgroundImages = [1, 2, 3, 4, 5, 6, 7, 8, 9].map(
  (n) => `${import.meta.env.BASE_URL}assets/background/background${n}.jpg`,
)

const router = useRouter()
const username = ref('')
const password = ref('')
const error = ref('')
const isLoggingIn = ref(false)
const rememberMe = ref(false)
const showPassword = ref(false)
const isRecovering = ref(false)

onMounted(() => {
  const savedUsername = localStorage.getItem('remembered_username')
  if (savedUsername) {
    username.value = savedUsername
    rememberMe.value = true
  }
})

async function handleLogin() {
  if (!username.value || !password.value) return
  
  isLoggingIn.value = true
  error.value = ''
  
  try {
    const res = await api.login(username.value, password.value)
    await completeSignIn(res.access_token)
  } catch (err: any) {
    error.value = err?.status === 429
      ? 'Too many failed attempts. Please wait a minute and try again.'
      : 'Invalid credentials. Please try again.'
    console.error('Login failed:', err)
  } finally {
    isLoggingIn.value = false
  }
}

async function completeSignIn(token: string) {
  setToken(token, rememberMe.value)

  if (rememberMe.value) {
    localStorage.setItem('remembered_username', username.value)
  } else {
    localStorage.removeItem('remembered_username')
  }

  authState.user = await api.getMe()
  authState.isAuthenticated = true
  authState.isInitialized = true

  // Fetch settings/config since we now have a token
  try {
    await refreshConfig()
  } catch (confErr) {
    console.error('Failed to refresh config after login:', confErr)
  }

  router.push('/')
}

async function handleRecovered(token: string, recoveredUsername: string) {
  username.value = recoveredUsername
  try {
    await completeSignIn(token)
  } catch (err) {
    console.error('Sign-in after recovery failed:', err)
    isRecovering.value = false
    error.value = 'Password was reset. Please sign in with your new password.'
  }
}
</script>

<template>
  <div role="region" aria-label="Account access" class="workspace-view login-view h-full min-h-0 overflow-y-auto overflow-x-hidden relative bg-[#080e18]">
    <BackgroundSlideshow :images="backgroundImages" />

    <!-- Animated Background Orbs -->
    <div class="absolute inset-0 overflow-hidden pointer-events-none" aria-hidden="true">
    <div class="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-aether-primary/10 rounded-full blur-[120px] animate-pulse"></div>
    <div class="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-purple-500/10 rounded-full blur-[120px] animate-pulse" style="animation-delay: 2s"></div>
    </div>

    <main class="login-content relative z-10 flex min-h-full w-full flex-col items-center justify-center px-4 py-8 sm:px-6 sm:py-12">
    <div class="login-card w-full max-w-md rounded-2xl border border-slate-700/70 bg-slate-900/85 p-6 shadow-2xl backdrop-blur-xl sm:p-8">
      <div class="text-center mb-8">
        <div class="inline-block mb-4">
          <img :src="loginArtwork" class="login-artwork object-contain" alt="VisualNovel — golden quill and open book" width="1254" height="1254" />
        </div>
        <h1 class="text-5xl font-black text-white font-display tracking-tighter mb-2">TaleWeaver</h1>
        <p class="text-lg font-medium tracking-wide text-slate-300 mb-2">Visual Novel</p>
        <p class="text-amber-200/70 text-xxs font-bold uppercase tracking-[0.4em]">Chronicle Intelligence v{{ configState.appVersion }}</p>
      </div>

      <RecoveryCodeForm
        v-if="isRecovering"
        :initial-username="username"
        @recovered="handleRecovered"
        @cancel="isRecovering = false"
      />

      <form v-else @submit.prevent="handleLogin" class="space-y-6">
        <div class="space-y-2">
          <label for="login-username" class="text-xxs font-black text-slate-500 uppercase tracking-widest ml-1">Username</label>
          <div class="relative">
            <i aria-hidden="true" class="ra ra-person absolute left-4 top-1/2 -translate-y-1/2 text-slate-500"></i>
            <input 
              v-model="username"
              id="login-username"
              autocomplete="username"
              type="text" 
              required
              class="w-full bg-white/5 border border-white/10 rounded-xl py-3.5 pl-12 pr-4 text-white focus:outline-none focus:border-aether-primary/50 focus:ring-1 focus:ring-aether-primary/20 transition-all"
              placeholder="Your chronicles name..."
            />
          </div>
        </div>

        <div class="space-y-2">
          <label for="login-password" class="text-xxs font-black text-slate-500 uppercase tracking-widest ml-1">Password</label>
          <div class="relative">
            <i aria-hidden="true" class="ra ra-hood absolute left-4 top-1/2 -translate-y-1/2 text-slate-500"></i>
            <input 
              v-model="password"
              id="login-password"
              autocomplete="current-password"
              :type="showPassword ? 'text' : 'password'" 
              required
              class="w-full bg-white/5 border border-white/10 rounded-xl py-3.5 pl-12 pr-4 text-white focus:outline-none focus:border-aether-primary/50 focus:ring-1 focus:ring-aether-primary/20 transition-all"
              placeholder="Your password..."
            />
          </div>
        </div>

        <!-- Remember Me & Show Password Checkboxes -->
        <div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-3 px-1 text-xxs font-bold uppercase tracking-wider text-slate-400 select-none">
          <label class="flex items-center gap-2 cursor-pointer hover:text-aether-primary transition-colors">
            <input 
              v-model="rememberMe" 
              type="checkbox" 
              class="rounded border-white/10 bg-white/5 text-aether-primary focus:ring-0 focus:ring-offset-0 accent-aether-primary h-4 w-4 cursor-pointer"
            />
            Remember Me
          </label>
          <label class="flex items-center gap-2 cursor-pointer hover:text-aether-primary transition-colors">
            <input 
              v-model="showPassword" 
              type="checkbox" 
              class="rounded border-white/10 bg-white/5 text-aether-primary focus:ring-0 focus:ring-offset-0 accent-aether-primary h-4 w-4 cursor-pointer"
            />
            Show Password
          </label>
        </div>

        <div v-if="error" class="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-xs font-bold text-center animate-shake">
          {{ error }}
        </div>

        <button 
          type="submit" 
          :disabled="isLoggingIn"
          class="btn-primary w-full !py-4 flex items-center justify-center gap-3 shadow-ambient-emerald/20 disabled:opacity-50"
        >
          <i v-if="isLoggingIn" class="ra ra-cycle animate-spin"></i>
          <span v-else>Begin Journey</span>
        </button>

        <button
          type="button"
          class="w-full text-xxs font-black uppercase tracking-widest text-slate-500 hover:text-aether-primary transition-colors"
          @click="isRecovering = true; error = ''"
        >
          Forgot your password?
        </button>
      </form>

    </div>
    <div class="login-attribution mt-6 w-full max-w-2xl text-center">
      <p class="text-sm text-slate-400">Original developer: <span class="text-slate-300">Jean Schmitz</span> · Fork creator: <span class="text-slate-300">Anton Kuprin</span></p>
      <PortalFooter />
    </div>
    </main>
  </div>
</template>

<style scoped>
.login-card { flex-shrink: 0; }
.login-artwork { width: min(42vw, 168px); height: auto; margin-inline: auto; }
.login-view h1 { font-family: inherit; font-size: 38px; font-weight: 600; letter-spacing: -.025em; }
.login-view :is(label, .text-xxs) { font-size: 14px; letter-spacing: .015em; line-height: 1.4; }
.login-view :deep(label) { color: #a8b5c6; }
.login-view :is(input, button) { font-size: 15px; }
.login-view :is(input, button):focus-visible { outline: 2px solid #d6b46f; outline-offset: 3px; }
.login-view input { border-color: #334155; }
.login-view input:focus { border-color: #d6b46f88; box-shadow: 0 0 0 1px #d6b46f22; }
.login-view :deep(.btn-primary) { background: #d6b46f; color: #151b25; font-size: 15px; text-transform: none; letter-spacing: .025em; box-shadow: none; }
.login-view :deep(.btn-primary:hover) { background: #e6c98d; }
.login-view :deep(.workspace-footer) { margin-top: 18px; padding-block: 18px 0; }
.login-view :deep(.workspace-footer p) { font-size: 12px; font-weight: 400; text-transform: none; letter-spacing: .01em; line-height: 1.6; }
.login-view :deep(.text-xxs) { font-size: 14px; }
.login-view :deep(h2) { font-size: 22px; font-weight: 600; }
@media (max-width: 639px) {
  .login-content { padding-block: 24px; }
  .login-card { padding: 24px 20px; }
  .login-view h1 { font-size: 34px; }
}
.animate-shake {
  animation: shake 0.5s cubic-bezier(.36,.07,.19,.97) both;
}

@keyframes shake {
  10%, 90% { transform: translate3d(-1px, 0, 0); }
  20%, 80% { transform: translate3d(2px, 0, 0); }
  30%, 50%, 70% { transform: translate3d(-4px, 0, 0); }
  40%, 60% { transform: translate3d(4px, 0, 0); }
}
@media (prefers-reduced-motion: reduce) { .animate-shake, .animate-pulse { animation: none; } }
</style>

