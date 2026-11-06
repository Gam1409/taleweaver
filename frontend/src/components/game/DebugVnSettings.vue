<script setup lang="ts">
import { nextTick, onScopeDispose, ref } from 'vue'
import { apiFetch } from '@/services/http'
import SessionContentSettings from './SessionContentSettings.vue'
import DebugToolbarButton from './DebugToolbarButton.vue'
import { SlidersHorizontal } from 'lucide-vue-next'

const props = defineProps<{ sessionId: string }>()
const dialog = ref<HTMLDialogElement | null>(null)
const content = ref<InstanceType<typeof SessionContentSettings> | null>(null)
const opened = ref(false)
const loading = ref(false)
const saving = ref(false)
const saved = ref(false)
const diagnostics = ref<{ title: string; data?: unknown; error?: string }[]>([])
let controller: AbortController | null = null
async function refresh() {
  controller?.abort()
  const current = new AbortController()
  controller = current
  loading.value = true
  const sections = [
    { title: 'Concordia / Living World', endpoint: 'living-world' },
    { title: 'NPC Personality', endpoint: 'chpm' }
  ]
  const rows = await Promise.all(
    sections.map(async section => {
      try {
        const response = await apiFetch(
          `/adventures/${encodeURIComponent(props.sessionId)}/${section.endpoint}`,
          { signal: current.signal, timeoutMs: 15000 }
        )
        const data = await response.json()
        if (!response.ok)
          throw new Error(
            typeof data.detail === 'string' ? data.detail : 'Could not load diagnostics.'
          )
        return { title: section.title, data }
      } catch (cause) {
        return {
          title: section.title,
          error: cause instanceof Error ? cause.message : 'Could not load diagnostics.'
        }
      }
    })
  )
  if (controller !== current) return
  diagnostics.value = rows
  loading.value = false
}
async function open() {
  saved.value = false
  opened.value = true
  await nextTick()
  dialog.value?.showModal()
  void refresh()
}
function close() {
  controller?.abort()
  controller = null
  opened.value = false
}
async function save() {
  if (!content.value?.loaded || content.value.busy || saving.value) return
  saving.value = true
  try {
    saved.value = await content.value.save()
  } finally {
    saving.value = false
  }
}
onScopeDispose(close)
</script>

<template>
  <DebugToolbarButton :disabled="!sessionId" @click="open"
    ><SlidersHorizontal class="h-4 w-4" />VN Settings</DebugToolbarButton
  >
  <Teleport to="body">
    <dialog
      ref="dialog"
      aria-labelledby="debug-vn-title"
      class="m-auto max-h-[90dvh] w-[min(72rem,calc(100vw-2rem))] overflow-y-auto rounded-2xl border border-slate-600 bg-slate-950 p-5 text-slate-200 shadow-xl backdrop:bg-black/80"
      @close="close"
      @keydown.esc.stop
    >
      <template v-if="opened">
        <header class="mb-5 flex items-center justify-between gap-4">
          <div>
            <h2 id="debug-vn-title" class="text-lg font-bold">VN Settings & Diagnostics</h2>
            <p class="mt-1 text-xs text-slate-400">
              Current session only. Diagnostics may include private NPC state available to your
              account.
            </p>
          </div>
          <button
            type="button"
            class="rounded-lg bg-slate-800 px-3 py-2 text-sm"
            @click="dialog?.close()"
          >
            Close
          </button>
        </header>
        <div class="grid gap-5 lg:grid-cols-3">
          <section class="min-w-0 space-y-4">
            <h3 class="font-bold text-pink-200">Content settings</h3>
            <SessionContentSettings ref="content" :session-id="sessionId" /><button
              type="button"
              :disabled="!content?.loaded || content?.busy || saving"
              class="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-bold text-slate-950 disabled:opacity-40"
              @click="save"
            >
              {{ saving ? 'Saving…' : 'Save content settings' }}
            </button>
            <p v-if="saved" role="status" class="text-xs text-emerald-300">
              Saved for future replies and supported images.
            </p>
          </section>
          <section v-for="section in diagnostics" :key="section.title" class="min-w-0 space-y-3">
            <h3 class="font-bold text-cyan-200">{{ section.title }}</h3>
            <p v-if="section.error" role="alert" class="text-sm text-rose-300">
              {{ section.error }}
            </p>
            <pre
              v-else
              class="max-h-[60dvh] overflow-auto rounded-xl border border-slate-700 bg-slate-900 p-3 text-[11px] leading-relaxed"
              >{{ JSON.stringify(section.data, null, 2) }}</pre>
          </section>
        </div>
        <button
          type="button"
          :disabled="loading"
          class="mt-5 rounded-lg border border-slate-600 px-4 py-2 text-sm disabled:opacity-40"
          @click="refresh"
        >
          {{ loading ? 'Loading diagnostics…' : 'Refresh diagnostics' }}
        </button>
      </template>
    </dialog>
  </Teleport>
</template>
