<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import DebugWardrobePreferences, { type WardrobePreferences } from './DebugWardrobePreferences.vue'
import DebugWardrobeRecovery, { type WardrobeRecoveryPreview } from './DebugWardrobeRecovery.vue'
import DebugItemRepair from './DebugItemRepair.vue'
import { Pencil } from 'lucide-vue-next'

interface Clothing {
  category: string
  layer: number
  coverage: string[]
  opaque: boolean
  underwear: boolean
  description: string
}
interface WardrobeItem {
  id: string
  name?: string
  description?: string
  clothing: Clothing | null
  worn: boolean
  uncovered_regions?: string[]
}
const props = defineProps<{
  npc: {
    id: string
    name?: string
    wardrobe?: {
      items: WardrobeItem[]
      preferences?: WardrobePreferences
      profile_known: boolean
      recovery?: WardrobeRecoveryPreview | null
    }
  }
  busy: boolean
  sessionId?: string
}>()
const emit = defineEmits<{ command: [value: string]; repaired: [] }>()
const dialog = ref<HTMLDialogElement | null>(null)
const layers = ['Under layer', 'Base layer', 'Mid layer', 'Outer layer', 'Outermost layer']
const groups = computed(() => [
  ...layers.map((label, layer) => ({
    key: String(layer),
    label: `Layer ${layer} · ${label}`,
    items: items.value.filter(item => item.clothing?.layer === layer)
  })),
  {
    key: 'unknown',
    label: 'Unspecified layer',
    items: items.value.filter(item => !item.clothing || !layers[item.clothing.layer])
  }
])
const visibleGroups = computed(() =>
  groups.value.filter(group => group.key !== 'unknown' || group.items.length)
)
function close() {
  dialog.value?.close()
}
function resetEditor() {
  draft.value = null
  selected.value = ''
}
watch(
  () => props.npc.id,
  () => {
    close()
    resetEditor()
  }
)
onBeforeUnmount(close)
const selected = ref('')
const draft = ref<{ name: string; description: string; clothing: Clothing; worn: boolean } | null>(
  null
)
const regions = ['head', 'torso', 'arms', 'pelvis', 'legs', 'feet', 'hands']
const items = computed(() => props.npc.wardrobe?.items || [])
function edit(item: WardrobeItem) {
  selected.value = item.id
  draft.value = {
    name: item.name || item.id,
    description: item.description || '',
    clothing: item.clothing
      ? JSON.parse(JSON.stringify(item.clothing))
      : {
          category: 'clothing',
          layer: 1,
          coverage: [],
          opaque: true,
          underwear: false,
          description: ''
        },
    worn: item.worn
  }
}
function save() {
  if (!draft.value || props.busy) return
  emit(
    'command',
    `/debug npc_clothing ${JSON.stringify({ npc_id: props.npc.id, item_id: selected.value, ...draft.value })}`
  )
}
</script>
<template>
  <button
    type="button"
    class="flex-1 py-1 px-2 rounded-lg bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-500/30 text-cyan-300 text-[10px] font-bold uppercase tracking-wider transition-all cursor-pointer"
    @click="dialog?.showModal()"
  >
    Clothing
  </button>
  <Teleport to="body">
    <dialog
      ref="dialog"
      :aria-label="`Clothing — ${npc.name || npc.id}`"
      class="m-auto max-h-[85dvh] w-[min(92rem,calc(100vw-2rem))] overflow-y-auto rounded-2xl border border-slate-600 bg-slate-950 p-4 text-sm text-slate-200 shadow-xl backdrop:bg-black/70"
      @close="resetEditor"
      @keydown.esc.stop
    >
      <header class="mb-4 flex items-center justify-between gap-3">
        <h3 class="text-lg font-bold">Clothing — {{ npc.name || npc.id }}</h3>
        <button type="button" class="rounded bg-slate-800 px-3 py-2" @click="close">Close</button>
      </header>
      <p class="mb-3 text-xs text-slate-400">
        Session only · Layers 0–4: closest to body → outermost. Inventory does not mean worn.
        Missing records do not mean undressed.
      </p>
      <div class="space-y-3">
        <details
          :open="!!npc.wardrobe?.recovery"
          class="rounded-xl border border-slate-700 px-3 py-2"
        >
          <summary class="cursor-pointer text-xs font-bold text-cyan-200">
            Recovery & clothing settings
          </summary>
          <div class="mt-3 space-y-3">
            <DebugWardrobePreferences
              v-if="npc.wardrobe?.preferences"
              :npc-id="npc.id"
              :preferences="npc.wardrobe.preferences"
              :busy="busy"
              @command="emit('command', $event)"
            />
            <DebugWardrobeRecovery
              :npc-id="npc.id"
              :preview="npc.wardrobe?.recovery"
              :busy="busy"
              @command="emit('command', $event)"
            />
          </div>
        </details>
        <p v-if="!npc.wardrobe?.profile_known" class="text-amber-300">
          Worn state is not established. Missing records do not mean undressed.
        </p>
        <p v-if="!items.length" class="text-slate-400">
          No structured clothing items are recorded.
        </p>
        <div
          class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"
          :class="visibleGroups.length === 6 ? 'xl:grid-cols-6' : 'xl:grid-cols-5'"
        >
          <section
            v-for="group in visibleGroups"
            :key="group.key"
            :data-clothing-layer="group.key"
            class="min-w-0 space-y-2 rounded-xl border border-slate-800 bg-slate-900/50 p-3"
          >
            <h4 class="text-xs font-bold text-cyan-200">
              {{ group.label }} <span class="text-slate-400">({{ group.items.length }})</span>
            </h4>
            <p v-if="!group.items.length" class="text-xs text-slate-500">No recorded items.</p>
            <div
              v-for="item in group.items"
              :key="item.id"
              class="rounded border border-slate-700 p-2"
            >
              <div class="flex items-start justify-between gap-2">
                <div class="min-w-0 flex-1">
                  <p class="break-words text-xs font-bold">{{ item.name || item.id }}</p>
                  <p
                    class="mt-1 text-[10px] uppercase tracking-wider"
                    :class="item.worn ? 'text-emerald-300' : 'text-slate-400'"
                  >
                    {{ item.worn ? 'Worn' : 'Inventory' }}
                  </p>
                </div>
                <div class="flex w-20 shrink-0 flex-col gap-1.5">
                  <DebugItemRepair
                    v-if="sessionId"
                    :session-id="sessionId"
                    :item-id="item.id"
                    :name="item.name"
                    stacked
                    @repaired="emit('repaired')"
                  />
                  <button
                    type="button"
                    class="inline-flex w-full items-center justify-center gap-1 rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-cyan-300 hover:bg-cyan-500/20 disabled:opacity-40"
                    :disabled="busy"
                    @click="edit(item)"
                  >
                    <Pencil class="h-3 w-3" />Edit
                  </button>
                </div>
              </div>
              <details v-if="item.description" class="mt-2 text-xs text-slate-400">
                <summary class="cursor-pointer text-cyan-300/80">Description</summary>
                <p class="mt-2 whitespace-pre-line leading-relaxed">{{ item.description }}</p>
              </details>
              <p v-if="item.uncovered_regions?.length" class="text-amber-200">
                Partially displaced — exposed: {{ item.uncovered_regions.join(', ') }}
              </p>
              <p v-if="item.clothing" class="mt-2 text-[10px] text-slate-400">
                Layer {{ item.clothing.layer }} · {{ item.clothing.coverage.join(', ')
                }}{{ item.clothing.underwear ? ' · Underwear' : '' }}
              </p>
            </div>
          </section>
        </div>
        <form
          v-if="draft"
          class="space-y-2 border-t border-slate-700 pt-3"
          :aria-label="`Edit ${draft.name}`"
          @submit.prevent="save"
        >
          <label class="block"
            >Name<input
              v-model="draft.name"
              required
              maxlength="120"
              class="mt-1 w-full rounded bg-slate-800 p-2"
          /></label>
          <label class="block"
            >Description<textarea
              v-model="draft.description"
              maxlength="1000"
              class="mt-1 w-full rounded bg-slate-800 p-2"
            />
          </label>
          <label class="block"
            >Garment description<textarea
              v-model="draft.clothing.description"
              maxlength="400"
              class="mt-1 w-full rounded bg-slate-800 p-2"
            />
          </label>
          <label class="block"
            >Layer<select
              v-model.number="draft.clothing.layer"
              class="mt-1 w-full rounded bg-slate-800 p-2"
            >
              <option v-for="(label, layer) in layers" :key="layer" :value="layer">
                {{ layer }} · {{ label }}
              </option>
            </select></label
          >
          <fieldset>
            <legend>Coverage</legend>
            <div class="flex flex-wrap gap-2">
              <label v-for="region in regions" :key="region"
                ><input v-model="draft.clothing.coverage" type="checkbox" :value="region" />
                {{ region }}</label
              >
            </div>
          </fieldset>
          <div class="flex flex-wrap gap-3">
            <label><input v-model="draft.worn" type="checkbox" /> Worn</label>
            <label><input v-model="draft.clothing.opaque" type="checkbox" /> Opaque</label>
            <label><input v-model="draft.clothing.underwear" type="checkbox" /> Underwear</label>
          </div>
          <p class="text-slate-400">
            Save submits a debug command. Its result appears in chat and the clothing list
            refreshes.
          </p>
          <button
            type="submit"
            :disabled="busy || !draft.clothing.coverage.length"
            class="rounded bg-cyan-800 px-3 py-2 disabled:opacity-40"
          >
            Save clothing
          </button>
          <button type="button" class="ml-2 text-slate-400" @click="draft = null">
            Close editor
          </button>
        </form>
      </div>
    </dialog>
  </Teleport>
</template>
