<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { prepareClothing, type ClothingDraft } from '@/services/clothingAuthoring'

const props = defineProps<{
  modelValue?: ClothingDraft | null
  adventureId?: string
  name: string
  description: string
  slots: string[]
  disabled?: boolean
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: ClothingDraft): void
  (e: 'busy', value: boolean): void
}>()
const regions = ['head', 'torso', 'arms', 'pelvis', 'legs', 'feet', 'hands']
const value = computed(() => props.modelValue && typeof props.modelValue === 'object' ? props.modelValue : {})
const coverage = computed(() => Array.isArray(value.value.coverage) ? value.value.coverage : [])
const category = computed(() => value.value.category || 'clothing')
const busy = ref(false)
const error = ref('')
const prepared = ref(false)
let disposed = false
onBeforeUnmount(() => { disposed = true; emit('busy', false) })

function update(patch: ClothingDraft) {
  emit('update:modelValue', { ...value.value, ...patch })
}
function toggleRegion(region: string, event: Event) {
  const selected = new Set(coverage.value)
  if ((event.target as HTMLInputElement).checked) selected.add(region)
  else selected.delete(region)
  update({ coverage: [...selected] })
}
function source() {
  return { name: props.name, description: props.description, wearable_slots: props.slots, clothing: value.value }
}
async function prepare() {
  if (!props.adventureId || !props.name.trim() || busy.value || props.disabled) return
  const input = JSON.stringify(source())
  busy.value = true
  error.value = ''
  prepared.value = false
  emit('busy', true)
  try {
    const result = await prepareClothing(props.adventureId, JSON.parse(input))
    if (disposed) return
    if (JSON.stringify(source()) !== input) {
      error.value = 'The item changed during preparation. Please prepare again.'
      return
    }
    emit('update:modelValue', result)
    prepared.value = true
  } catch (cause) {
    if (!disposed) error.value = cause instanceof Error ? cause.message : 'Clothing preparation failed.'
  } finally {
    if (!disposed) {
      busy.value = false
      emit('busy', false)
    }
  }
}
</script>

<template>
  <section aria-label="Clothing properties" class="space-y-3 rounded-2xl border border-emerald-500/20 bg-emerald-500/5 p-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h4 class="text-xs font-black uppercase tracking-widest text-emerald-400">Clothing properties</h4>
      <button v-if="adventureId" type="button" @click="prepare" :disabled="disabled || busy || !name.trim()"
        class="rounded-xl border border-emerald-500/30 px-3 py-2 text-xs font-bold text-emerald-300 hover:bg-emerald-500/10 disabled:opacity-50">
        {{ busy ? 'Preparing...' : 'Prepare missing clothing data' }}
      </button>
    </div>
    <p class="text-xs text-slate-400">Equipment slots tell where an item can be equipped. These properties tell the story and illustrations how it is worn. Preparation keeps existing values. Review before saving; ownership alone does not put it on.</p>
    <fieldset :disabled="disabled || busy" class="space-y-3">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label class="block text-xs font-bold text-slate-300">Category
          <select aria-label="Clothing category" :value="category" @change="update({ category: ($event.target as HTMLSelectElement).value as ClothingDraft['category'] })" class="mt-1 w-full rounded-xl border border-white/10 bg-slate-800 p-3 text-sm">
            <option value="clothing">Clothing</option><option value="armor">Armor</option><option value="accessory">Accessory</option>
          </select>
        </label>
        <label class="block text-xs font-bold text-slate-300">Layer
          <select aria-label="Clothing layer" :value="value.layer ?? ''" @change="update({ layer: Number(($event.target as HTMLSelectElement).value) })" class="mt-1 w-full rounded-xl border border-white/10 bg-slate-800 p-3 text-sm">
            <option value="" disabled>Select a layer</option>
            <option :value="0">0 · Innermost</option><option :value="1">1 · Inner</option><option :value="2">2 · Main</option><option :value="3">3 · Outer</option><option :value="4">4 · Outermost</option>
          </select>
        </label>
      </div>
      <p class="text-xs text-slate-400">Higher layers sit above lower layers. For example, a shirt can use 2 and an overcoat 3. Armor category does not add combat bonuses.</p>
      <fieldset>
        <legend class="mb-2 text-xs font-bold text-slate-300">{{ category === 'accessory' ? 'Placement regions' : 'Covered regions' }}</legend>
        <div class="flex flex-wrap gap-2">
          <label v-for="region in regions" :key="region" class="flex items-center gap-2 rounded-lg border border-white/10 bg-slate-800 px-3 py-2 text-xs capitalize">
            <input type="checkbox" :checked="coverage.includes(region)" @change="toggleRegion(region, $event)" class="accent-emerald-500">{{ region }}
          </label>
        </div>
      </fieldset>
      <p v-if="category === 'accessory'" class="text-xs text-emerald-300">Accessories never hide lower clothing. Placement only locates them: necklace → torso, ring → hands. A higher opaque garment can hide an accessory underneath.</p>
      <label v-else class="flex items-center gap-2 text-sm text-slate-300">
        <input type="checkbox" :checked="value.opaque !== false" @change="update({ opaque: ($event.target as HTMLInputElement).checked })" class="accent-emerald-500">Hides lower layers in covered regions
      </label>
    </fieldset>
    <p v-if="error" role="alert" class="text-sm text-red-300">{{ error }}</p>
    <p v-if="prepared" role="status" class="text-sm text-emerald-300">Properties prepared. Review them and save the item to keep these changes.</p>
  </section>
</template>
