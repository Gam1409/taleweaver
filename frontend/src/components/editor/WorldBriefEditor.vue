<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Save } from 'lucide-vue-next'
import WorldBriefFields from '@/components/create-adventure/WorldBriefFields.vue'
import { emptyWorldBrief, type WorldBrief } from '@/services/worldBrief'
import { apiFetch } from '@/services/http'

const props = defineProps<{ adventureId: string }>()
const draft = ref<WorldBrief>(emptyWorldBrief())
const saved = ref('')
const loaded = ref(false)
const busy = ref(false)
const error = ref('')
const dirty = computed(() => loaded.value && JSON.stringify(draft.value) !== saved.value)
let controller: AbortController | null = null

async function request(method: 'GET' | 'PUT') {
  controller?.abort()
  const current = new AbortController()
  controller = current
  busy.value = true
  error.value = ''
  try {
    const response = await apiFetch(`/adventures/${encodeURIComponent(props.adventureId)}/world-brief`, {
      method, signal: current.signal, includeJson: method === 'PUT',
      ...(method === 'PUT' ? { body: JSON.stringify(draft.value) } : {}),
    })
    const body = await response.json()
    if (controller !== current) return
    if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not save the world blueprint.')
    draft.value = body
    saved.value = JSON.stringify(body)
    loaded.value = true
  } catch (cause) {
    if (controller === current) error.value = cause instanceof Error ? cause.message : 'World blueprint request failed.'
  } finally {
    if (controller === current) busy.value = false
  }
}

watch(() => props.adventureId, () => { loaded.value = false; void request('GET') }, { immediate: true })
onBeforeUnmount(() => { controller?.abort(); controller = null })
</script>

<template>
  <section class="space-y-3">
    <p class="text-xs text-slate-400">These inputs apply to world generation and regeneration. Existing sessions keep their saved world. To repair a failed reference, edit its URL or paste an excerpt, save, then resume generation.</p>
    <p v-if="error" role="alert" class="text-xs text-rose-300">{{ error }} <button type="button" class="underline" :disabled="busy" @click="request('GET')">Reload</button></p>
    <fieldset :disabled="!loaded || busy" class="disabled:opacity-60"><WorldBriefFields v-model="draft" /></fieldset>
    <button type="button" :disabled="!dirty || busy" class="flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2 text-xs font-bold text-white transition hover:bg-indigo-500 disabled:opacity-40" @click="request('PUT')"><Save class="h-4 w-4" /> {{ busy ? 'Saving…' : 'Save world blueprint' }}</button>
  </section>
</template>
