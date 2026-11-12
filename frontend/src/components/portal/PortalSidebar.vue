<script setup lang="ts">
import { nextTick, onMounted, onScopeDispose, ref, watch } from 'vue'
import { X, BookOpen, History, UserRound, Settings2, Info } from 'lucide-vue-next'

const props = defineProps<{
  isAdmin: boolean
  activeSection: 'templates' | 'sessions' | 'profile'
  isMobileOpen?: boolean
}>()

const emit = defineEmits<{
  (e: 'section', section: 'templates' | 'sessions' | 'profile'): void
  (e: 'admin'): void
  (e: 'about'): void
  (e: 'close-mobile'): void
}>()

const drawer = ref<HTMLElement>()
const desktop = ref(true)
let previousFocus: HTMLElement | null = null
onMounted(() => {
  const media = window.matchMedia('(min-width: 1024px)')
  const update = () => {
    desktop.value = media.matches
    if (desktop.value && props.isMobileOpen) emit('close-mobile')
  }
  update()
  media.addEventListener('change', update)
  onScopeDispose(() => media.removeEventListener('change', update))
})
watch(() => props.isMobileOpen, async open => {
  if (desktop.value) return
  if (!open) { previousFocus?.focus(); return }
  previousFocus = document.activeElement as HTMLElement
  await nextTick()
  drawer.value?.querySelector<HTMLButtonElement>('button')?.focus()
})
function onDrawerKey(event: KeyboardEvent) {
  if (desktop.value || !props.isMobileOpen) return
  if (event.key === 'Escape') { event.preventDefault(); emit('close-mobile'); return }
  if (event.key !== 'Tab') return
  const buttons = Array.from(drawer.value?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') || [])
  const edge = event.shiftKey ? buttons[0] : buttons.at(-1)
  if (document.activeElement !== edge) return
  event.preventDefault()
  ;(event.shiftKey ? buttons.at(-1) : buttons[0])?.focus()
}

function selectSection(section: 'templates' | 'sessions' | 'profile') {
  emit('section', section)
  emit('close-mobile')
}
</script>

<template>
  <!-- Backdrop for mobile drawer -->
  <div
    v-if="props.isMobileOpen"
    class="fixed inset-0 bg-slate-950/60 backdrop-blur-sm z-[105] lg:hidden animate-fade-in"
    @click="emit('close-mobile')"
  ></div>

  <aside
    ref="drawer"
    :inert="!desktop && !isMobileOpen"
    :role="!desktop && isMobileOpen ? 'dialog' : undefined"
    :aria-modal="!desktop && isMobileOpen ? true : undefined"
    aria-label="Workspace menu"
    @keydown="onDrawerKey"
    :class="[
      'workspace-sidebar bg-aether-background/95 backdrop-blur-2xl border-r border-white/5 flex flex-col z-[110] lg:z-20 overflow-y-auto transition-transform duration-300 ease-in-out shrink-0',
      // Mobile/Tablet: drawer behavior; Desktop: always visible sidebar
      props.isMobileOpen
        ? 'fixed inset-y-0 left-0 w-72 max-w-[85vw] translate-x-0'
        : 'fixed inset-y-0 left-0 w-72 max-w-[85vw] -translate-x-full lg:translate-x-0 lg:relative lg:inset-y-0 lg:left-0 lg:w-72'
    ]"
  >
    <div class="p-4 lg:p-5 pt-8 flex-1">
      <div class="flex items-center justify-between mb-6 lg:hidden">
        <span class="text-[10px] font-black uppercase tracking-[0.3em] text-aether-primary">Menu</span>
        <button
          @click="emit('close-mobile')"
          class="w-8 h-8 rounded-lg bg-white/5 border border-white/10 text-slate-300 hover:text-white hover:bg-white/10 transition-all flex items-center justify-center"
          title="Close menu"
          aria-label="Close menu"
        >
          <X class="w-4 h-4" />
        </button>
      </div>

      <p class="workspace-nav-label">WORKSPACE</p>
      <nav aria-label="Workspace" class="space-y-1">
        <button class="workspace-nav-item" :class="{ 'is-active': activeSection === 'sessions' }" :aria-current="activeSection === 'sessions' ? 'page' : undefined" @click="selectSection('sessions')">
          <History aria-hidden="true" /><span>Sessions</span>
        </button>
        <button class="workspace-nav-item" :class="{ 'is-active': activeSection === 'templates' }" :aria-current="activeSection === 'templates' ? 'page' : undefined" @click="selectSection('templates')">
          <BookOpen aria-hidden="true" /><span>Library</span>
        </button>
        <button class="workspace-nav-item" :class="{ 'is-active': activeSection === 'profile' }" :aria-current="activeSection === 'profile' ? 'page' : undefined" @click="selectSection('profile')">
          <UserRound aria-hidden="true" /><span>Profile</span>
        </button>
        <template v-if="isAdmin">
          <div class="workspace-nav-divider" />
          <button class="workspace-nav-item" @click="emit('admin'); emit('close-mobile')">
            <Settings2 aria-hidden="true" /><span>Administration</span>
          </button>
        </template>
      </nav>
    </div>

    <!-- Sidebar Bottom: About -->
    <div class="p-4 lg:p-5 border-t border-white/5">
      <button
        @click="emit('about'); emit('close-mobile')"
        class="workspace-nav-item"
      >
        <Info aria-hidden="true" /><span>About Archive</span>
      </button>
    </div>
  </aside>
</template>
