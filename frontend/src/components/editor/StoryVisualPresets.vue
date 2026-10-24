<script setup lang="ts">
import { ref, watch } from 'vue'
import { apiFetch } from '@/services/http'

const props = defineProps<{ adventureId: string }>()
type Selection = Partial<Record<'simple' | 'advanced', string>>
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
    const response = await apiFetch(`/adventures/${props.adventureId}/visual-presets`)
    if (!response.ok) throw new Error('Could not load story image presets.')
    const data = await response.json()
    if (version !== loadVersion) return
    selection.value = data.selection; presets.value = data.presets; loaded.value = true
  } catch (err) { error.value = String(err) }
}, { immediate: true })
function choose(role: 'simple' | 'advanced', event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  if (value) selection.value[role] = value
  else delete selection.value[role]
  message.value = ''
}
async function save(): Promise<void> {
  saving.value = true; error.value = ''; message.value = ''
  try {
    const response = await apiFetch(`/adventures/${props.adventureId}/visual-presets`, {
      method: 'PUT', includeJson: true, body: JSON.stringify({ selection: selection.value }),
    })
    const data = await response.json()
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not save image presets.')
    message.value = 'Saved. Future image generation uses these choices; existing images are kept.'
  } catch (err) { error.value = String(err) }
  finally { saving.value = false }
}
</script>

<template>
  <details class="rounded-2xl border border-slate-700 bg-slate-900/70 p-5">
    <summary class="cursor-pointer text-sm font-semibold text-slate-200">Image generation presets</summary>
    <div class="mt-4 space-y-4">
      <p class="text-xs text-slate-400">Use the shared settings or choose ComfyUI presets for this story. Artistic style stays in Visual Atmosphere. Presets and workflows are configured by the administrator.</p>
      <div class="grid gap-4 sm:grid-cols-2">
        <label v-for="role in (['simple', 'advanced'] as const)" :key="role" class="text-sm text-slate-200">{{ role === 'simple' ? 'Standard' : 'High-Fidelity' }} preset
          <select :value="selection[role] ?? ''" :disabled="!loaded || saving" class="mt-2 block w-full rounded-lg border border-slate-700 bg-slate-950 p-3" @change="choose(role, $event)">
            <option value="">Use shared settings</option>
            <option v-if="selection[role] && !presets.some(p => p.id === selection[role])" :value="selection[role]" disabled>Unavailable preset — select another</option>
            <option v-for="preset in presets" :key="preset.id" :value="preset.id">{{ preset.name }}</option>
          </select>
        </label>
      </div>
      <button type="button" :disabled="!loaded || saving" class="rounded-lg bg-cyan-700 px-4 py-2 text-sm text-white disabled:opacity-40" @click="save">{{ saving ? 'Saving…' : 'Save image presets' }}</button>
      <p v-if="error" role="alert" class="text-sm text-rose-300">{{ error }}</p>
      <p v-if="message" role="status" class="text-sm text-emerald-300">{{ message }}</p>
    </div>
  </details>
</template>
