<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Plus, X } from 'lucide-vue-next'
import { useDialogFocus } from '@/composables/useDialogFocus'
import { createUuid } from '@/utils/uuid'
import { createNpcWithItems, generateNpcDraft, type NpcDraft } from '@/services/npcCreation'
import NpcDraftReview from './NpcDraftReview.vue'

const props = defineProps<{
  adventureId: string
  scenes: { id: string; name?: string; label?: string }[]
  initialSceneId?: string | null
  innerClothingEnabled: boolean
}>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'created', id: string): void }>()
const dialog = ref<HTMLElement | null>(null)
const brief = ref(''), sceneId = ref(''), age = ref<number | ''>('')
const includeClothing = ref(true), includeUnderwear = ref(false), includeItems = ref(true)
const busy = ref(false), saving = ref(false), error = ref('')
const draft = ref<NpcDraft | null>(null), selected = ref<boolean[]>([])
const creationId = createUuid()
let revision = 0
const validScene = computed(() => props.scenes.some(scene => scene.id === sceneId.value))
const innerAllowed = computed(() => props.innerClothingEnabled && includeClothing.value && Number.isInteger(age.value) && Number(age.value) >= 18)
const selectedDraft = computed(() => draft.value ? { ...draft.value, items: draft.value.items.filter((_, i) => selected.value[i]) } : null)
const blockedInner = computed(() => selectedDraft.value?.items.some(item => item.clothing?.underwear) && (!props.innerClothingEnabled || !Number.isInteger(draft.value?.age_years) || Number(draft.value?.age_years) < 18))
const canSave = computed(() => validScene.value && !!draft.value?.name.trim() && !!draft.value?.description.trim() && !blockedInner.value && !busy.value && !saving.value)
useDialogFocus(dialog, () => { if (!saving.value) emit('close') })

function invalidate() {
  revision++
  busy.value = false
  draft.value = null
  error.value = ''
}
watch(() => props.scenes.map(scene => scene.id), ids => {
  if (!ids.includes(sceneId.value)) sceneId.value = ids.includes(props.initialSceneId || '') ? props.initialSceneId! : (ids[0] || '')
}, { immediate: true, flush: 'sync' })
watch(() => JSON.stringify([brief.value, sceneId.value, age.value, includeClothing.value, includeUnderwear.value, includeItems.value, props.innerClothingEnabled]), invalidate, { flush: 'sync' })
watch(innerAllowed, value => { if (!value) includeUnderwear.value = false }, { flush: 'sync' })
watch(() => props.adventureId, () => { invalidate(); emit('close') }, { flush: 'sync' })
onBeforeUnmount(invalidate)

async function generate() {
  if (busy.value || saving.value || !brief.value.trim() || !validScene.value) return
  const token = ++revision
  busy.value = true
  error.value = ''
  draft.value = null
  try {
    const result = await generateNpcDraft(props.adventureId, {
      brief: brief.value.trim(), scene_id: sceneId.value, age_years: age.value === '' ? null : Number(age.value),
      include_clothing: includeClothing.value, include_underwear: includeUnderwear.value, include_items: includeItems.value,
    })
    if (token !== revision) return
    draft.value = result
    selected.value = result.items.map(() => true)
  } catch (cause) {
    if (token === revision) error.value = cause instanceof Error ? cause.message : 'NPC generation failed.'
  } finally {
    if (token === revision) busy.value = false
  }
}
async function save() {
  if (!canSave.value || !selectedDraft.value) return
  const token = ++revision
  saving.value = true
  error.value = ''
  try {
    const result = await createNpcWithItems(props.adventureId, sceneId.value, selectedDraft.value, creationId)
    if (token === revision) emit('created', result.npc_id)
  } catch (cause) {
    if (token === revision) error.value = cause instanceof Error ? cause.message : 'Could not save the NPC.'
  } finally {
    if (token === revision) saving.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <div ref="dialog" role="dialog" aria-modal="true" aria-labelledby="new-npc-title" tabindex="-1" class="authoring-modal-overlay fixed inset-0 z-[260] flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm" @click.self="!saving && emit('close')">
      <div class="authoring-dialog max-h-[90dvh] w-full max-w-3xl space-y-5 overflow-y-auto rounded-2xl border border-emerald-500/30 bg-slate-900 p-6 shadow-2xl">
        <header class="flex items-center justify-between gap-4"><h2 id="new-npc-title" class="flex items-center gap-2 text-lg font-black text-white"><Plus class="h-5 w-5 text-emerald-400" />New NPC</h2><button type="button" aria-label="Close new NPC" :disabled="saving" @click="emit('close')" class="rounded-full p-2 text-slate-400 hover:bg-white/10 hover:text-white disabled:opacity-50"><X class="h-5 w-5" /></button></header>
        <p class="text-sm text-slate-400">Describe a character, their personality, clothes and any belongings. Generate a draft, review it, then save the character and selected items together. Uses the Small / Utility model.</p>
        <fieldset :disabled="busy || saving || !validScene" class="space-y-4">
          <div class="grid gap-4 sm:grid-cols-2">
            <label class="text-sm text-slate-300">Location<select v-model="sceneId" class="mt-1 w-full rounded-xl border border-white/10 bg-slate-950 p-3 text-white"><option v-for="scene in scenes" :key="scene.id" :value="scene.id">{{ scene.name || scene.label || scene.id }}</option></select></label>
            <label class="text-sm text-slate-300">Age (optional)<input v-model.number="age" type="number" min="0" max="100000" step="1" placeholder="Established character age" class="mt-1 w-full rounded-xl border border-white/10 bg-slate-950 p-3 text-white"></label>
          </div>
          <label class="block text-sm font-bold text-emerald-300">Character description<textarea v-model="brief" maxlength="4000" rows="4" class="mt-2 w-full resize-y rounded-xl border border-white/10 bg-slate-950 p-3 font-normal text-white" placeholder="A reserved doctor seeking the cause of a mysterious illness. Dark hair, grey eyes; a white coat over a grey skirt and blouse. Carries a laboratory key. Describe any additional clothing here." /></label>
          <div class="flex flex-wrap gap-4 text-sm text-slate-300">
            <label class="flex items-center gap-2"><input v-model="includeClothing" type="checkbox" class="accent-emerald-500">Generate clothing</label>
            <label class="flex items-center gap-2"><input v-model="includeItems" type="checkbox" class="accent-emerald-500">Additional belongings</label>
            <label class="flex items-center gap-2"><input v-model="includeUnderwear" type="checkbox" :disabled="!innerAllowed" class="accent-emerald-500">Include underwear</label>
          </div>
          <p v-if="!innerAllowed" class="text-xs text-slate-400">Underwear requires an explicit adult age (18+), clothing generation, and saved mature-content and detailed-clothing settings.</p>
        </fieldset>
        <p v-if="!validScene" role="alert" class="text-sm text-amber-300">Add a scene to the adventure before creating an NPC.</p>
        <button type="button" @click="generate" :disabled="busy || saving || !validScene || !brief.trim()" class="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-bold text-white hover:bg-emerald-500 disabled:opacity-50">{{ busy ? 'Generating draft...' : draft ? 'Generate another draft' : 'Generate NPC draft' }}</button>
        <form v-if="draft" @submit.prevent="save" class="space-y-5">
          <NpcDraftReview v-model="draft" v-model:selected="selected" :disabled="saving" />
          <p v-if="blockedInner" role="alert" class="text-sm text-amber-300">Uncheck inner clothing or restore an adult age and the required saved clothing settings before saving.</p>
          <button type="submit" :disabled="!canSave" class="rounded-xl bg-emerald-600 px-5 py-3 text-sm font-bold text-white hover:bg-emerald-500 disabled:opacity-50">{{ saving ? 'Saving character...' : 'Create NPC & selected items' }}</button>
        </form>
        <p v-if="error" role="alert" class="text-sm text-red-300">{{ error }}</p>
      </div>
    </div>
  </Teleport>
</template>
