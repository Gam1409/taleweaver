<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ImagePlus, LoaderCircle } from 'lucide-vue-next'
import { apiFetch } from '@/services/http'
import { runVisualJob } from '@/services/visualJobs'
import { getOriginalImageUrl } from '@/utils/game_icons'

const props = defineProps<{ sessionId: string; messageId: string; canGenerate: boolean }>()
interface MomentState {
  available: boolean
  reason: string | null
  image_url: string | null
}
const state = ref<MomentState | null>(null)
const loading = ref(false)
const generating = ref(false)
const error = ref('')
const imageUrl = computed(() =>
  state.value?.image_url ? getOriginalImageUrl(state.value.image_url) : ''
)
let controller: AbortController | null = null
let revision = 0

async function load(): Promise<void> {
  controller?.abort()
  const request = new AbortController()
  controller = request
  const token = ++revision
  loading.value = true
  generating.value = false
  error.value = ''
  state.value = null
  const timeout = window.setTimeout(() => request.abort(), 15000)
  try {
    const response = await apiFetch(
      `/adventures/${encodeURIComponent(props.sessionId)}/illustrations?message_id=${encodeURIComponent(props.messageId)}`,
      { signal: request.signal }
    )
    if (!response.ok) throw new Error('Could not load the illustration for this moment.')
    const data = (await response.json()) as MomentState
    if (revision === token) state.value = data
  } catch (cause) {
    if (revision === token)
      error.value =
        cause instanceof Error && cause.name !== 'AbortError'
          ? cause.message
          : 'Loading the illustration timed out.'
  } finally {
    window.clearTimeout(timeout)
    if (revision === token) loading.value = false
  }
}

async function generate(): Promise<void> {
  if (!props.canGenerate || generating.value || !state.value?.available) return
  controller?.abort()
  const request = new AbortController()
  controller = request
  const token = ++revision
  generating.value = true
  error.value = ''
  try {
    const result = await runVisualJob(
      'session_illustration',
      { message_id: props.messageId },
      undefined,
      request.signal,
      props.sessionId
    )
    if (revision === token && state.value) {
      if (typeof result.image_url !== 'string')
        throw new Error('The image job finished without an illustration.')
      state.value.image_url = result.image_url
    }
  } catch (cause) {
    if (revision === token)
      error.value = cause instanceof Error ? cause.message : 'Illustration failed. Please retry.'
  } finally {
    if (revision === token) generating.value = false
  }
}
watch(
  () => [props.sessionId, props.messageId],
  () => {
    void load()
  },
  { immediate: true }
)
onBeforeUnmount(() => {
  revision++
  controller?.abort()
})
</script>

<template>
  <section
    v-if="canGenerate || imageUrl || generating || error"
    aria-label="Moment illustration"
    class="space-y-2 rounded-xl border border-rose-300/15 bg-slate-950/40 p-3"
  >
    <a
      v-if="imageUrl"
      :href="imageUrl"
      target="_blank"
      rel="noopener noreferrer"
      class="block w-fit"
      aria-label="Open this moment's illustration"
    >
      <img
        :src="imageUrl"
        alt="Illustration of this story moment"
        class="max-h-80 rounded-lg object-contain"
      />
    </a>
    <p v-if="imageUrl" class="text-xs text-slate-400">
      Saved with this reply. Later changes to the scene do not update this image.
    </p>
    <p v-if="loading" role="status" class="text-xs text-slate-400">Loading illustration…</p>
    <button
      v-if="canGenerate && state?.available"
      type="button"
      :disabled="generating"
      class="flex items-center gap-2 rounded-lg border border-rose-300/30 px-3 py-2 text-sm text-rose-200 hover:bg-rose-400/10 disabled:opacity-60"
      @click="generate"
    >
      <LoaderCircle v-if="generating" class="h-4 w-4 animate-spin" /><ImagePlus
        v-else
        class="h-4 w-4"
      />
      {{
        generating
          ? 'Illustrating…'
          : imageUrl
            ? 'Regenerate this moment'
            : 'Illustrate this moment'
      }}
    </button>
    <p v-if="canGenerate && state && !state.available" class="text-xs text-slate-400">
      {{
        state.reason ||
        'This older reply has no saved visual snapshot. Continue the story to illustrate a new moment.'
      }}
    </p>
    <p v-if="error" role="alert" class="text-sm text-rose-300">
      {{ error }} <button v-if="!state" type="button" class="underline" @click="load">Retry</button>
    </p>
  </section>
</template>
