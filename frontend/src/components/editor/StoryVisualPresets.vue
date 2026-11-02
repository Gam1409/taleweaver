<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { apiFetch } from '@/services/http'

const props = defineProps<{ adventureId: string; session?: boolean; embedded?: boolean }>()
type Selection = Partial<Record<'simple' | 'advanced', string>>
const source = ref<'saved' | 'current'>('saved')
const endpoint = computed(() => `/adventures/${props.adventureId}/${props.session ? 'session-visual-presets' : 'visual-presets'}`)
const selection = ref<Selection>({})
const presets = ref<{ id: string; name: string }[]>([])
const saving = ref(false)
const message = ref('')
const error = ref('')
const loaded = ref(false)

let loadVersion = 0
watch(() => props.adventureId, async () => {
  const version = ++loadVersion
  loaded.value = false; selection.value = {}; error.value = ''; message.value = ''
  try {
    const response = await apiFetch(endpoint.value)
    if (!response.ok) throw new Error('Could not load story image presets.')
    const data = await response.json()
    if (version !== loadVersion) return
    source.value = data.source ?? 'saved'; selection.value = data.selection; presets.value = data.presets; loaded.value = true
  } catch (err) { error.value = String(err) }
}, { immediate: true })
function choose(role: 'simple' | 'advanced', event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  if (value) selection.value[role] = value
  else delete selection.value[role]
  message.value = ''
}
async function save(): Promise<boolean> {
  if (!loaded.value || saving.value) return false
  saving.value = true; error.value = ''; message.value = ''
  try {
    const response = await apiFetch(endpoint.value, {
      method: 'PUT', includeJson: true, body: JSON.stringify({ selection: selection.value, source: source.value }),
    })
    const data = await response.json()
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not save image presets.')
    message.value = 'Saved. Future image generation uses these choices; existing images are kept.'
    return true
  } catch (err) { error.value = String(err); return false }
  finally { saving.value = false }
}
defineExpose({ save })
</script>

<template>
  <details class="rounded-2xl border border-slate-700 bg-slate-900/70 p-5">
    <summary class="cursor-pointer text-sm font-semibold text-slate-200">Image generation presets</summary>
    <div class="mt-4 space-y-4">
      <p class="text-xs text-slate-400">Use the shared settings or choose ComfyUI presets for this story. Artistic style stays in Visual Atmosphere. Presets and workflows are configured by the administrator.</p>
      <label class="block text-sm text-slate-200">Preset source
        <select v-model="source" :disabled="!loaded || saving" class="mt-2 block w-full rounded-lg border border-slate-700 bg-slate-950 p-3">
          <option value="current">Use current global settings</option>
          <option value="saved">Use saved preset selection</option>
        </select>
      </label>
      <p class="text-xs text-slate-400">Current settings follow the administrator's latest profile assignments. Saved selection keeps the presets chosen here; their workflows still come from the current preset library.</p>
      <p v-if="!session" class="text-xs text-slate-400">These choices apply to this adventure and new sessions. Change an existing session in its own settings.</p>
      <div v-if="source === 'saved'" class="grid gap-4 sm:grid-cols-2">
        <label v-for="role in (['simple', 'advanced'] as const)" :key="role" class="text-sm text-slate-200">{{ role === 'simple' ? 'Standard' : 'High-Fidelity' }} preset
          <select :value="selection[role] ?? ''" :disabled="!loaded || saving" class="mt-2 block w-full rounded-lg border border-slate-700 bg-slate-950 p-3" @change="choose(role, $event)">
            <option value="">Use shared settings</option>
            <option v-if="selection[role] && !presets.some(p => p.id === selection[role])" :value="selection[role]" disabled>Unavailable preset — select another</option>
            <option v-for="preset in presets" :key="preset.id" :value="preset.id">{{ preset.name }}</option>
          </select>
        </label>
      </div>
      <button v-if="!embedded" type="button" :disabled="!loaded || saving" class="rounded-lg bg-cyan-700 px-4 py-2 text-sm text-white disabled:opacity-40" @click="save">{{ saving ? 'Saving…' : 'Save image presets' }}</button>
      <p v-if="error" role="alert" class="text-sm text-rose-300">{{ error }}</p>
      <p v-if="message" role="status" class="text-sm text-emerald-300">{{ message }}</p>
    </div>
  </details>
</template>
