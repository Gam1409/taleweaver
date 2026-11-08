<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Shirt } from 'lucide-vue-next'
import { generateCharacterOutfit, loadCharacterOutfit, type CharacterOutfitDraft, type OutfitContext } from '@/services/characterOutfits'
import type { NpcItemDraft } from '@/services/npcCreation'
import NpcDraftItems from './NpcDraftItems.vue'

const props = defineProps<{
  adventureId: string; targetType: string; targetId: string
  name: string; description: string; character: string; goal: string
  contextVersion?: string; inventoryIds?: string[]; disabled?: boolean
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: CharacterOutfitDraft | null): void
  (e: 'busy', value: boolean): void
}>()
const open = ref(false), busy = ref(false), error = ref(''), brief = ref(''), includeUnderwear = ref(false)
const context = ref<OutfitContext | null>(null), draft = ref<CharacterOutfitDraft | null>(null)
const items = ref<NpcItemDraft[]>([]), selected = ref<boolean[]>([]), notes = ref<string[]>([])
let revision = 0
const target = () => ({ adventureId: props.adventureId, targetType: props.targetType, targetId: props.targetId })
const selectedDraft = computed(() => draft.value ? {
  appearance: draft.value.appearance,
  outfit: items.value.flatMap((item, i) => selected.value[i] && item.clothing ? [{
    item_id: draft.value!.outfit[i]?.item_id, name: item.name, description: item.description,
    wearable_slots: [...item.wearable_slots], clothing: item.clothing,
  }] : []),
} : null)
watch(selectedDraft, value => emit('update:modelValue', value), { deep: true })

function clearDraft() {
  revision++
  busy.value = false
  error.value = ''
  draft.value = null
  items.value = []
  selected.value = []
  notes.value = []
  emit('update:modelValue', null)
  emit('busy', false)
}
watch(() => JSON.stringify([props.adventureId, props.targetType, props.targetId]), () => {
  clearDraft()
  context.value = null
  if (open.value) void load()
}, { flush: 'sync' })
watch(() => JSON.stringify([props.name, props.description, props.character, props.goal, props.contextVersion, props.inventoryIds]), () => {
  clearDraft()
  if (open.value && !context.value) void load()
}, { flush: 'sync' })
watch(() => JSON.stringify([brief.value, includeUnderwear.value]), clearDraft, { flush: 'sync' })
watch(() => context.value?.allow_underwear, allowed => {
  if (allowed === false) includeUnderwear.value = false
}, { flush: 'sync' })
onBeforeUnmount(clearDraft)

async function load() {
  const token = ++revision
  busy.value = true
  error.value = ''
  emit('busy', true)
  try {
    const result = await loadCharacterOutfit(target())
    if (token !== revision) return
    context.value = result
  } catch (cause) {
    if (token === revision) error.value = cause instanceof Error ? cause.message : 'Could not read existing clothing.'
  } finally {
    if (token === revision) { busy.value = false; emit('busy', false) }
  }
}
function toggle() {
  if (props.disabled || busy.value) return
  open.value = !open.value
  if (open.value && !context.value) void load()
}
async function generate() {
  if (props.disabled || busy.value || !context.value) return
  clearDraft()
  const token = ++revision
  busy.value = true
  emit('busy', true)
  try {
    const result = await generateCharacterOutfit(target(), {
      brief: brief.value.trim(), include_underwear: includeUnderwear.value,
      name: props.name, description: props.description, character: props.character, goal: props.goal,
      inventory_ids: props.inventoryIds || [],
    })
    if (token !== revision) return
    context.value = result.context
    draft.value = result.draft
    items.value = result.draft.outfit.map(item => ({ ...item, item_type: 'WEARABLE', is_portable: true, text_log_content: '', worn: true }))
    selected.value = items.value.map(() => true)
    notes.value = result.notes
  } catch (cause) {
    if (token === revision) error.value = cause instanceof Error ? cause.message : 'Clothing generation failed.'
  } finally {
    if (token === revision) { busy.value = false; emit('busy', false) }
  }
}
</script>

<template>
  <section aria-label="Generate character clothing" class="space-y-3 rounded-2xl border border-emerald-500/20 bg-emerald-500/5 p-4">
    <button type="button" :disabled="disabled || busy" :aria-expanded="open" @click="toggle" class="flex items-center gap-2 rounded-xl border border-emerald-500/30 px-4 py-2 text-xs font-bold text-emerald-300 hover:bg-emerald-500/10 disabled:opacity-50"><Shirt class="h-4 w-4" />Generate clothing</button>
    <div v-if="open" class="space-y-4">
      <p class="text-xs text-slate-400">Complete this character's outfit using their description and existing clothes. Worn and carried items are checked first. Review the suggestions, then save the character to add selected garments.</p>
      <div v-if="context" class="space-y-2 text-xs text-slate-300">
        <h4 class="font-bold text-emerald-300">Already owned ({{ context.owned.length }})</h4>
        <ul class="max-h-36 space-y-1 overflow-y-auto"><li v-for="item in context.owned" :key="item.id">{{ item.name }} · {{ item.worn ? 'Worn' : item.pending ? 'Added in this card' : 'Carried' }}<template v-if="item.clothing"> · Layer {{ item.clothing.layer }}</template></li></ul>
        <p v-if="!context.owned.length" class="text-slate-500">No registered clothing.</p>
      </div>
      <fieldset :disabled="disabled || busy" class="space-y-3">
        <label class="block text-sm text-slate-300">Clothing preferences (optional)<textarea v-model="brief" maxlength="2000" rows="2" class="mt-1 w-full resize-y rounded-xl border border-white/10 bg-slate-950 p-3" placeholder="Fill missing everyday clothing. Keep the existing coat and reuse suitable clothes from the inventory." /></label>
        <label class="flex items-center gap-2 text-sm text-slate-300"><input v-model="includeUnderwear" type="checkbox" :disabled="!context?.allow_underwear" class="accent-emerald-500">Include underwear</label>
        <p v-if="context && !context.allow_underwear" class="text-xs text-slate-500">Inner clothing requires a saved adult age (18+), mature-content and detailed-clothing settings.</p>
        <button type="button" :disabled="!context || disabled || busy" @click="generate" class="rounded-xl bg-emerald-600 px-4 py-2 text-xs font-bold text-white hover:bg-emerald-500 disabled:opacity-50">{{ busy ? 'Preparing clothing...' : 'Generate outfit draft' }}</button>
      </fieldset>
      <p v-if="busy" role="status" class="text-xs text-slate-300">Preparing clothing...</p>
      <NpcDraftItems v-if="draft" v-model:items="items" v-model:selected="selected" :disabled="disabled || busy" :allow-wear-selection="false"
        :readonly-indices="draft.outfit.flatMap((item, index) => item.item_id ? [index] : [])" />
      <p v-for="note in notes" :key="note" class="text-xs text-slate-400">{{ note }}</p>
      <p v-if="draft" role="status" class="text-xs text-emerald-300">{{ selected.filter(Boolean).length }} garment(s) selected. Save the character to apply. Existing clothes and belongings are kept; images are generated separately.</p>
      <p v-if="error" role="alert" class="text-sm text-red-300">{{ error }} <button type="button" :disabled="busy || disabled" class="underline" @click="load">Reload existing clothing</button></p>
    </div>
  </section>
</template>
