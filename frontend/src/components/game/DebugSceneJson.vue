<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { apiFetch } from '@/services/http'
import DebugToolbarButton from './DebugToolbarButton.vue'
import { Braces } from 'lucide-vue-next'

interface MessageInfo {
  id: string
  scene_id: string | null
  revision_id: string | null
  created_at: string
  excerpt: string
  snapshot_status: string
}
interface SceneDebug {
  session_id: string
  mode: string
  current_scene_id: string
  staging_status: string
  settings: Record<string, unknown>
  messages: MessageInfo[]
  selected_message: MessageInfo | null
  current_scene: Record<string, unknown> | null
  staging: Record<string, unknown> | null
  props: Record<string, unknown> | null
  snapshot: Record<string, unknown> | null
  plan_route_enabled: boolean
  cached_plans: Record<string, unknown>[]
}
const props = defineProps<{ sessionId: string }>()
const dialog = ref<HTMLDialogElement | null>(null)
const result = ref<SceneDebug | null>(null)
const selected = ref('')
const loading = ref(false)
const error = ref('')
const copyStatus = ref('')
let version = 0
let controller: AbortController | undefined
const sections = computed(() =>
  result.value
    ? [
        { title: 'Current location record', value: result.value.current_scene },
        { title: 'Current staging — poses, placement and provenance', value: result.value.staging },
        { title: 'Current placed-item records', value: result.value.props },
        { title: 'Selected message — frozen illustration snapshot', value: result.value.snapshot },
        {
          title: 'Selected message — cached visual plans and audits',
          value: result.value.cached_plans
        }
      ]
    : []
)
const json = (value: unknown) => JSON.stringify(value, null, 2)
function stop() {
  version++
  controller?.abort()
  loading.value = false
}
async function refresh(messageId = selected.value) {
  stop()
  const request = version
  controller = new AbortController()
  loading.value = true
  result.value = null
  error.value = ''
  copyStatus.value = ''
  try {
    const query = messageId ? `?message_id=${encodeURIComponent(messageId)}` : ''
    const response = await apiFetch(
      `/adventures/${encodeURIComponent(props.sessionId)}/scene-debug${query}`,
      { signal: controller.signal, cache: 'no-store' }
    )
    if (!response.ok)
      throw new Error(
        `Scene inspection failed (HTTP ${response.status}). Check session ownership and debug mode.`
      )
    const data = (await response.json()) as SceneDebug
    if (request !== version) return
    result.value = data
    selected.value = data.selected_message?.id || ''
  } catch (cause) {
    if (request === version)
      error.value = cause instanceof Error ? cause.message : 'Could not load scene JSON.'
  } finally {
    if (request === version) loading.value = false
  }
}
function open() {
  dialog.value?.showModal()
  void refresh('')
}
function download() {
  if (!result.value) return
  const url = URL.createObjectURL(new Blob([json(result.value)], { type: 'application/json' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `scene-debug-${props.sessionId}.json`
  link.click()
  URL.revokeObjectURL(url)
}
async function copy() {
  if (!result.value) return
  try {
    await navigator.clipboard.writeText(json(result.value))
    copyStatus.value = 'Copied.'
  } catch {
    copyStatus.value = 'Clipboard unavailable. Use Download JSON or select the text below.'
  }
}
watch(
  () => props.sessionId,
  () => {
    stop()
    dialog.value?.close()
    result.value = null
    selected.value = ''
  }
)
onBeforeUnmount(() => {
  stop()
  dialog.value?.close()
})
</script>
<template>
  <DebugToolbarButton
    :disabled="!sessionId"
    @click="open"
  >
    <Braces class="h-4 w-4" />
    Scene JSON
  </DebugToolbarButton>
  <Teleport to="body">
    <dialog
      ref="dialog"
      aria-label="Scene JSON"
      class="m-auto max-h-[92dvh] w-[min(70rem,calc(100vw-2rem))] overflow-y-auto rounded-2xl border border-slate-600 bg-slate-950 p-5 text-sm text-slate-200 shadow-xl backdrop:bg-black/70"
      @keydown.esc.stop
      @close="stop"
    >
      <header class="mb-4 flex items-center justify-between gap-4">
        <h2 class="text-lg font-bold">Scene JSON</h2>
        <button type="button" class="rounded bg-slate-800 px-3 py-2" @click="dialog?.close()">
          Close
        </button>
      </header>
      <p class="mb-3 text-slate-400">
        Read-only saved data. Opening this window does not call an LLM or rebuild missing facts.
        Refresh after the current turn finishes.
      </p>
      <div class="mb-4 flex flex-wrap items-center gap-2">
        <button
          type="button"
          :disabled="loading"
          class="rounded bg-cyan-800 px-3 py-2 disabled:opacity-40"
          @click="refresh()"
        >
          Refresh
        </button>
        <button
          type="button"
          :disabled="loading"
          class="rounded bg-slate-800 px-3 py-2 disabled:opacity-40"
          @click="refresh('')"
        >
          Latest narration
        </button>
        <button
          type="button"
          :disabled="!result"
          class="rounded bg-slate-800 px-3 py-2 disabled:opacity-40"
          @click="copy"
        >
          Copy JSON
        </button>
        <button
          type="button"
          :disabled="!result"
          class="rounded bg-slate-800 px-3 py-2 disabled:opacity-40"
          @click="download"
        >
          Download JSON
        </button>
      </div>
      <p v-if="copyStatus" role="status" class="mb-3 text-amber-200">{{ copyStatus }}</p>
      <p v-if="loading" role="status">Loading saved scene data…</p>
      <p v-if="error" role="alert" class="text-rose-300">{{ error }}</p>
      <div v-if="result" class="space-y-4">
        <div class="rounded-lg border border-slate-700 p-3">
          <p>Mode: {{ result.mode }} · Current scene: {{ result.current_scene_id }}</p>
          <p>
            Current staging: <strong>{{ result.staging_status }}</strong>
          </p>
          <p v-if="result.staging_status === 'disabled'" class="text-amber-200">
            Pose/placement extraction is disabled in Narration settings. This does not mean
            illustration snapshots are disabled.
          </p>
          <p v-if="result.staging_status === 'unconfirmed'" class="text-amber-200">
            The saved extraction is unconfirmed. Its JSON may include rejected counts; the original
            failure reason is not always stored.
          </p>
          <p v-if="result.mode !== 'vn'" class="text-amber-200">
            Completed-turn visual snapshots are captured by the VN pipeline. This session uses
            {{ result.mode }}.
          </p>
        </div>
        <label class="block"
          >Narrator message (latest 100)
          <select
            v-model="selected"
            class="mt-1 w-full min-w-0 rounded bg-slate-800 p-2"
            :disabled="loading || !result.messages.length"
            @change="refresh()"
          >
            <option v-for="message in result.messages" :key="message.id" :value="message.id">
              {{ message.scene_id }} · {{ message.id.slice(0, 8) }} ·
              {{ message.snapshot_status }} · {{ message.excerpt }}
            </option>
          </select>
        </label>
        <div
          v-if="result.selected_message"
          class="break-words rounded-lg border border-slate-700 p-3"
        >
          <p>
            Snapshot: <strong>{{ result.selected_message.snapshot_status }}</strong>
          </p>
          <p class="text-xs">
            Message: {{ result.selected_message.id }} · Revision:
            {{ result.selected_message.revision_id || 'not recorded' }}
          </p>
          <p v-if="result.selected_message.snapshot_status === 'missing'" class="text-amber-200">
            No saved snapshot for this message. It may predate capture support, not have completed
            capture, or have expired from the latest 100 snapshots.
          </p>
          <p v-if="result.selected_message.snapshot_status === 'stale'" class="text-amber-200">
            The stored snapshot no longer matches the message text or scene context. It is shown for
            diagnosis, not as current facts.
          </p>
          <p
            v-if="result.selected_message.snapshot_status === 'matches_message'"
            class="text-slate-400"
          >
            Source hash matches. This verifies correspondence to the message, not semantic
            correctness or the NPC's current outfit.
          </p>
        </div>
        <p v-else class="text-amber-200">No narrator message is stored in this session yet.</p>
        <p class="text-slate-400">
          Cached plans: {{ result.cached_plans.length }}. Plans are created on demand and only the
          latest 8 cache entries are retained. Stored entries are not revalidated against current
          presets here.
        </p>
        <p v-if="!result.plan_route_enabled" class="text-amber-200">
          The current illustration route does not use the visual-plan pipeline; a missing cached
          plan is expected.
        </p>
        <details
          v-for="section in sections"
          :key="section.title"
          class="rounded-lg border border-slate-700 p-3"
        >
          <summary class="cursor-pointer font-bold text-cyan-200">{{ section.title }}</summary>
          <pre
            class="mt-3 max-h-[50dvh] overflow-auto whitespace-pre-wrap break-words font-mono text-xs select-text"
            >{{ json(section.value) }}</pre>
        </details>
      </div>
    </dialog>
  </Teleport>
</template>
