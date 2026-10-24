<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { apiFetch } from '@/services/http'
const props = defineProps<{ sessionId: string; embedded?: boolean }>()
interface Policy {
  enabled: boolean
  scale: 'auto' | 'regional' | 'building'
  generate_images: boolean
}
const policy = ref<Policy>({ enabled: false, scale: 'auto', generate_images: true })
const busy = ref(false),
  loaded = ref(false),
  error = ref(''),
  saved = ref(false)
let controller: AbortController | null = null
watch(
  () => props.sessionId,
  async id => {
    controller?.abort()
    controller = new AbortController()
    const request = controller
    loaded.value = false
    error.value = ''
    saved.value = false
    try {
      const response = await apiFetch(`/adventures/${encodeURIComponent(id)}/dynamic-locations`, {
        signal: request.signal
      })
      if (!response.ok) throw new Error('Could not load exploration settings.')
      const data = await response.json()
      if (!request.signal.aborted) {
        policy.value = data.policy
        loaded.value = true
      }
    } catch (e) {
      if (!request.signal.aborted) error.value = e instanceof Error ? e.message : 'Request failed.'
    }
  },
  { immediate: true }
)
async function save(): Promise<boolean> {
  if (!loaded.value || busy.value) return false
  busy.value = true
  error.value = ''
  saved.value = false
  const id = props.sessionId
  try {
    const response = await apiFetch(`/adventures/${encodeURIComponent(id)}/dynamic-locations`, {
      method: 'PATCH',
      includeJson: true,
      body: JSON.stringify(policy.value),
      signal: controller?.signal
    })
    if (!response.ok) throw new Error('Could not save exploration settings.')
    if (id === props.sessionId) saved.value = true
    return id === props.sessionId
  } catch (e) {
    if (id === props.sessionId) error.value = e instanceof Error ? e.message : 'Request failed.'
    return false
  } finally {
    busy.value = false
  }
}
defineExpose({ save })
onBeforeUnmount(() => controller?.abort())
</script>
<template>
  <details class="rounded-xl border border-white/10 p-3 text-sm">
    <summary class="cursor-pointer font-bold">Dynamic exploration (experimental)</summary>
    <p class="mt-2 text-xs text-slate-400">
      Create local places only when you enter them. Applies to this session; authored maps stay
      unchanged.
    </p>
    <fieldset
      :disabled="!loaded || busy"
      class="mt-3 space-y-3 disabled:opacity-50"
      @change="saved = false"
    >
      <label class="flex gap-2"
        ><input v-model="policy.enabled" type="checkbox" /> Allow new local places</label
      >
      <label class="block"
        >Adventure scale
        <select v-model="policy.scale" class="mt-1 w-full rounded bg-slate-800 p-2">
          <option value="auto">Auto — infer from the original world</option>
          <option value="regional">World / region — places and buildings</option>
          <option value="building">House / investigation — individual rooms</option>
        </select>
      </label>
      <p class="text-xs text-slate-400">
        Ordinary corners and minor rooms stay scenery. Overnight rooms and investigation locations
        can become scenes. Auto may need correction with smaller models.
      </p>
      <label class="flex gap-2"
        ><input v-model="policy.generate_images" type="checkbox" /> Generate backgrounds in the
        background</label
      >
      <button
        v-if="!embedded"
        type="button"
        class="rounded bg-amber-400 px-3 py-2 font-bold text-slate-950"
        @click="save"
      >
        {{ busy ? 'Saving…' : 'Save exploration settings' }}
      </button>
    </fieldset>
    <p v-if="error" role="alert" class="mt-2 text-rose-300">{{ error }}</p>
    <p v-if="saved" role="status" class="mt-2 text-emerald-300">Exploration settings saved.</p>
  </details>
</template>
