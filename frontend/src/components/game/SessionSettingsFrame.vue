<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { BookOpen, BrainCircuit, SlidersHorizontal, Users, X } from 'lucide-vue-next'
import { useDialogFocus } from '@/composables/useDialogFocus'

type Section = 'story' | 'memory' | 'characters'
const props = defineProps<{ section: Section; saving?: boolean }>()
const emit = defineEmits<{ 'update:section': [value: Section]; close: []; save: [] }>()
const dialog = ref<HTMLElement | null>(null)
const content = ref<HTMLElement>()
const wide = ref(false)
let media: MediaQueryList | undefined
const sections = [
  {
    id: 'story' as const,
    label: 'Story & world',
    hint: 'Narration and exploration',
    icon: BookOpen
  },
  {
    id: 'memory' as const,
    label: 'Memory & audio',
    hint: 'Context and speech',
    icon: BrainCircuit
  },
  { id: 'characters' as const, label: 'Characters', hint: 'Behavior and portraits', icon: Users }
]
useDialogFocus(dialog, () => emit('close'))
watch(
  () => props.section,
  async () => {
    await nextTick()
    if (content.value) content.value.scrollTop = 0
  }
)
function syncLayout() {
  wide.value = !!media?.matches
}
onMounted(() => {
  media = window.matchMedia('(min-width: 768px)')
  syncLayout()
  media.addEventListener('change', syncLayout)
})
onBeforeUnmount(() => media?.removeEventListener('change', syncLayout))
async function select(value: Section, focus = false) {
  emit('update:section', value)
  await nextTick()
  if (content.value) content.value.scrollTop = 0
  if (focus)
    dialog.value?.querySelector<HTMLButtonElement>(`[data-settings-tab="${value}"]`)?.focus()
}
function onNavKey(event: KeyboardEvent) {
  const index = sections.findIndex(section => section.id === props.section)
  if (!['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key))
    return
  event.preventDefault()
  const delta = ['ArrowDown', 'ArrowRight'].includes(event.key) ? 1 : -1
  const next =
    event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? sections.length - 1
        : (index + delta + sections.length) % sections.length
  void select(sections[next]!.id, true)
}
async function revealErrors() {
  await nextTick()
  const panel = dialog.value?.querySelector<HTMLElement>(`#settings-panel-${props.section}`)
  const alert = panel?.querySelector<HTMLElement>('[role="alert"]')
  if (!alert) return
  let ancestor = alert.parentElement
  while (ancestor && ancestor !== panel) {
    if (ancestor instanceof HTMLDetailsElement) ancestor.open = true
    ancestor = ancestor.parentElement
  }
  alert.setAttribute('tabindex', '-1')
  alert.focus({ preventScroll: true })
  alert.scrollIntoView({ block: 'center', behavior: 'instant' })
}
defineExpose({ revealErrors })
</script>

<template>
  <Teleport to="body">
    <div class="session-settings-overlay" @click.self="emit('close')">
      <div
        ref="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="session-settings-title"
        tabindex="-1"
        class="session-settings-window"
      >
        <header class="settings-heading">
          <div>
            <span class="settings-eyebrow"
              ><SlidersHorizontal aria-hidden="true" />CURRENT SESSION</span
            >
            <h2 id="session-settings-title">Session settings</h2>
            <p>Story, memory and character behavior for this session.</p>
          </div>
          <button
            type="button"
            class="settings-close"
            aria-label="Close session settings"
            @click="emit('close')"
          >
            <X aria-hidden="true" />
          </button>
        </header>
        <div class="settings-workspace">
          <nav
            class="settings-navigation"
            role="tablist"
            aria-label="Settings sections"
            :aria-orientation="wide ? 'vertical' : 'horizontal'"
            @keydown="onNavKey"
          >
            <button
              v-for="item in sections"
              :id="`settings-tab-${item.id}`"
              :key="item.id"
              type="button"
              role="tab"
              :data-settings-tab="item.id"
              :aria-selected="section === item.id"
              :aria-controls="`settings-panel-${item.id}`"
              :tabindex="section === item.id ? 0 : -1"
              @click="select(item.id)"
            >
              <component :is="item.icon" aria-hidden="true" /><span
                ><strong>{{ item.label }}</strong
                ><small>{{ item.hint }}</small></span
              >
            </button>
            <p class="settings-navigation-note">Choose a section.<br />Save when you are ready.</p>
          </nav>
          <main ref="content" class="settings-content">
            <section
              v-for="item in sections"
              v-show="section === item.id"
              :id="`settings-panel-${item.id}`"
              :key="item.id"
              role="tabpanel"
              :aria-labelledby="`settings-tab-${item.id}`"
              :aria-hidden="section !== item.id"
              class="settings-section"
            >
              <div class="settings-section-heading">
                <component :is="item.icon" aria-hidden="true" />
                <div>
                  <h3>{{ item.label }}</h3>
                  <p>{{ item.hint }}</p>
                </div>
              </div>
              <div :class="{ 'settings-section-widgets': item.id !== 'memory' }">
                <slot :name="item.id" />
              </div>
            </section>
          </main>
        </div>
        <footer class="settings-footer">
          <span>Settings for the current session</span>
          <div>
            <button type="button" class="settings-cancel" @click="emit('close')">Cancel</button
            ><button
              type="button"
              class="settings-save"
              :disabled="saving"
              :aria-busy="saving"
              @click="emit('save')"
            >
              <span v-if="saving" class="settings-spinner" aria-hidden="true" />{{
                saving ? 'Saving…' : 'Save Settings'
              }}
            </button>
          </div>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<style scoped src="./SessionSettingsFrame.css"></style>
