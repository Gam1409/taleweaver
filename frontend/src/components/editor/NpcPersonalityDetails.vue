<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { loadPersonalityCatalog, suggestPersonality, type PersonalityField, type PersonalityProfile } from '@/services/npcPersonality'

const props = defineProps<{
  modelValue?: PersonalityProfile
  adventureId?: string
  name: string
  description: string
  goal: string
  character: string
}>()
const emit = defineEmits<{ (e: 'update:modelValue', value: PersonalityProfile): void }>()
const dialog = ref<HTMLDialogElement | null>(null)
const fields = ref<PersonalityField[]>([])
const draft = ref<PersonalityProfile>({})
const loading = ref(false)
const suggesting = ref(false)
const error = ref('')
let request = 0
onBeforeUnmount(() => { request++ })

async function open() {
  const token = ++request
  draft.value = { ...(props.modelValue || {}) }
  error.value = ''
  loading.value = true
  dialog.value?.showModal()
  try {
    const result = await loadPersonalityCatalog()
    if (token !== request) return
    fields.value = result
    draft.value = Object.fromEntries(result.map(field => [field.key,
      field.options.some(option => option.value === draft.value[field.key]) ? draft.value[field.key] : '',
    ]))
  } catch (cause) {
    if (token === request) error.value = cause instanceof Error ? cause.message : 'Could not load options.'
  } finally {
    if (token === request) loading.value = false
  }
}

function close() {
  request++
  suggesting.value = false
  loading.value = false
  dialog.value?.close()
}
function apply() {
  emit('update:modelValue', { ...draft.value })
  close()
}
async function suggest() {
  if (!props.adventureId || !props.description.trim() || suggesting.value) return
  const token = ++request
  suggesting.value = true
  error.value = ''
  try {
    const result = await suggestPersonality(props.adventureId, {
      name: props.name, description: props.description, goal: props.goal, character: props.character,
    })
    if (token === request) draft.value = result
  } catch (cause) {
    if (token === request) error.value = cause instanceof Error ? cause.message : 'Suggestion failed.'
  } finally {
    if (token === request) suggesting.value = false
  }
}
</script>

<template>
  <button type="button" @click="open" class="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs font-bold text-emerald-300 hover:bg-emerald-500/20">
    Details · Personality
  </button>
  <Teleport to="body">
    <dialog ref="dialog" aria-label="NPC personality details" @cancel.prevent="close"
      class="m-auto w-[calc(100%_-_2rem)] max-w-2xl max-h-[85dvh] overflow-y-auto rounded-3xl border border-white/10 bg-slate-900 p-6 text-slate-200 shadow-2xl backdrop:bg-slate-950/75 backdrop:backdrop-blur-sm">
      <header class="flex items-center justify-between gap-4">
        <h3 class="text-lg font-black text-emerald-400">Personality details</h3>
        <button type="button" @click="close" aria-label="Close personality details" class="rounded-lg px-3 py-2 hover:bg-white/10">✕</button>
      </header>
      <p class="mt-3 text-sm text-slate-400">These are tendencies, not fixed actions. Biography, experiences and relationships still shape behavior. Unset fields follow the description and story.</p>
      <p v-if="loading" role="status" class="mt-4">Loading choices...</p>
      <div v-else class="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label v-for="field in fields" :key="field.key" class="block text-sm font-bold">
          {{ field.label }}
          <select v-model="draft[field.key]" :disabled="suggesting" class="mt-2 w-full rounded-xl border border-white/10 bg-slate-800 p-3 text-sm font-normal outline-none focus:border-emerald-500">
            <option value="">Not set — use description and story</option>
            <option v-for="option in field.options" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
          <span class="mt-1 block text-xs font-normal text-slate-400">{{ field.options.find(option => option.value === draft[field.key])?.help }}</span>
        </label>
      </div>
      <p v-if="error" role="alert" class="mt-4 text-sm text-red-300">{{ error }}</p>
      <div class="mt-6 flex flex-wrap justify-end gap-3">
        <button v-if="adventureId" type="button" @click="suggest" :disabled="loading || suggesting || !fields.length || !description.trim()" class="rounded-xl border border-emerald-500/30 px-4 py-2 text-sm text-emerald-300 disabled:opacity-50">
          {{ suggesting ? 'Suggesting...' : 'Fill from description' }}
        </button>
        <button type="button" @click="close" class="rounded-xl px-4 py-2 text-sm text-slate-400 hover:text-white">Cancel</button>
        <button type="button" @click="apply" :disabled="loading || suggesting || !fields.length" class="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-bold text-white hover:bg-emerald-500 disabled:opacity-50">Use traits</button>
      </div>
      <p class="mt-3 text-xs text-slate-500">Use traits updates the editor form. Save the NPC to keep your changes.</p>
    </dialog>
  </Teleport>
</template>
