<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { apiFetch } from '@/services/http'
const props = defineProps<{ sessionId: string; sceneId: string; busy?: boolean }>()
const emit = defineEmits<{ ready: [image: string] }>()
const state = ref(''),
  error = ref(''),
  dynamic = ref(false),
  enabled = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
let controller: AbortController | null = null
async function load(): Promise<void> {
  controller?.abort()
  controller = new AbortController()
  const request = controller,
    scene = props.sceneId
  try {
    const response = await apiFetch(
      `/adventures/${encodeURIComponent(props.sessionId)}/dynamic-locations`,
      { signal: request.signal }
    )
    if (!response.ok) return
    const data = await response.json()
    if (request.signal.aborted || data.scene_id !== scene || props.sceneId !== scene) return
    dynamic.value = data.dynamic
    enabled.value = data.policy.generate_images
    state.value = data.image_status || ''
    if (dynamic.value && data.image_url) emit('ready', data.image_url)
    if (
      dynamic.value &&
      !data.image_url &&
      enabled.value &&
      ['generating', 'missing'].includes(state.value)
    )
      timer = setTimeout(load, 6000)
  } catch {
    /* A background image must never interrupt gameplay. */
  }
}
async function retry(): Promise<void> {
  error.value = ''
  clearTimeout(timer)
  try {
    const response = await apiFetch(
      `/adventures/${encodeURIComponent(props.sessionId)}/dynamic-locations/${encodeURIComponent(props.sceneId)}/image`,
      { method: 'POST', signal: controller?.signal }
    )
    if (!response.ok) throw new Error('Could not start background generation.')
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Request failed.'
  }
}
watch(
  () => [props.sessionId, props.sceneId, props.busy],
  () => {
    clearTimeout(timer)
    controller?.abort()
    dynamic.value = false
    error.value = ''
    if (props.sessionId && props.sceneId) void load()
  },
  { immediate: true }
)
onBeforeUnmount(() => {
  clearTimeout(timer)
  controller?.abort()
})
</script>
<template>
  <div
    v-if="dynamic && state !== 'ready'"
    class="fixed bottom-36 right-4 z-30 max-w-xs rounded-xl bg-slate-950/90 p-3 text-xs text-slate-300"
  >
    <span v-if="state === 'generating'"
      >Preparing this location's background… You can keep playing.</span
    >
    <template v-else>
      <span>{{
        state === 'failed'
          ? 'Background generation failed.'
          : 'This location has no background yet.'
      }}</span>
      <button class="ml-2 text-amber-300 underline" @click="retry">Generate background</button>
    </template>
    <p v-if="error" role="alert" class="text-rose-300">{{ error }}</p>
  </div>
</template>
