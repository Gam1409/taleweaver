<script setup lang="ts">
import { computed, ref } from 'vue'
import DebugWardrobeRecovery, { type WardrobeRecoveryPreview } from './DebugWardrobeRecovery.vue'

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
}
const props = defineProps<{
  npc: {
    id: string
    current_scene_id: string
    wardrobe?: {
      items: WardrobeItem[]
      profile_known: boolean
      recovery?: WardrobeRecoveryPreview | null
    }
  }
  scenes: { id: string; label: string }[]
  currentSceneId: string
  busy: boolean
}>()
const emit = defineEmits<{ command: [value: string] }>()
const destination = ref('')
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
function move(target: string) {
  if (!target || props.busy) return
  emit('command', `/debug move_npc ${JSON.stringify(props.npc.id)} ${JSON.stringify(target)}`)
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
  <details class="rounded-xl border border-slate-700 bg-slate-950/60 p-3 text-xs text-slate-200">
    <summary class="cursor-pointer font-bold text-cyan-300">Location and clothing</summary>
    <div class="mt-3 space-y-3">
      <p class="text-[11px] text-slate-400">
        Manual corrections affect this session only. Moving bypasses travel restrictions; visibility
        and health stay unchanged.
      </p>
      <label class="block"
        >Destination
        <select v-model="destination" class="mt-1 w-full rounded bg-slate-800 p-2" :disabled="busy">
          <option value="">Select location</option>
          <option v-for="scene in scenes" :key="scene.id" :value="scene.id">
            {{ scene.label }} [{{ scene.id }}]
          </option>
        </select>
      </label>
      <div class="flex flex-wrap gap-2">
        <button
          type="button"
          class="rounded bg-cyan-900 px-3 py-2 disabled:opacity-40"
          :disabled="busy || !destination || destination === npc.current_scene_id"
          @click="move(destination)"
        >
          Move NPC
        </button>
        <button
          type="button"
          class="rounded bg-slate-700 px-3 py-2 disabled:opacity-40"
          :disabled="busy || !currentSceneId || currentSceneId === npc.current_scene_id"
          @click="move(currentSceneId)"
        >
          Bring to player
        </button>
      </div>
      <DebugWardrobeRecovery
        :npc-id="npc.id"
        :preview="npc.wardrobe?.recovery"
        :busy="busy"
        @command="emit('command', $event)"
      />
      <h4 class="font-bold">Existing clothing</h4>
      <p v-if="!npc.wardrobe?.profile_known" class="text-amber-300">
        Worn state is not established. Missing records do not mean undressed.
      </p>
      <p v-if="!items.length" class="text-slate-400">No structured clothing items are recorded.</p>
      <div v-for="item in items" :key="item.id" class="rounded border border-slate-700 p-2">
        <div class="flex items-start justify-between gap-2">
          <span>{{ item.name || item.id }} — {{ item.worn ? 'Worn' : 'Inventory' }}</span>
          <button
            type="button"
            class="text-cyan-300 underline"
            :disabled="busy"
            @click="edit(item)"
          >
            Edit
          </button>
        </div>
        <p class="mt-1 text-slate-400">{{ item.description }}</p>
        <p v-if="item.clothing" class="text-slate-400">
          Layer {{ item.clothing.layer }} · {{ item.clothing.coverage.join(', ')
          }}{{ item.clothing.underwear ? ' · Underwear' : '' }}
        </p>
      </div>
      <form v-if="draft" class="space-y-2 border-t border-slate-700 pt-3" @submit.prevent="save">
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
          >Layer (0–4)<input
            v-model.number="draft.clothing.layer"
            type="number"
            min="0"
            max="4"
            required
            class="ml-2 w-16 rounded bg-slate-800 p-1"
        /></label>
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
          Save submits a debug command. Its result appears in chat and the clothing list refreshes.
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
  </details>
</template>
