<script setup lang="ts">
import DebugItemRepair from './DebugItemRepair.vue'
import { Pencil } from 'lucide-vue-next'

export interface Clothing {
  category: string
  layer: number
  coverage: string[]
  opaque: boolean
  underwear: boolean
  description: string
}
export interface WardrobeItem {
  id: string
  name?: string
  description?: string
  clothing: Clothing | null
  worn: boolean
  uncovered_regions?: string[]
  attachment_slot?: 'vaginal' | 'anal' | null
  spatial_position?: string
  location?: 'scene'
}
defineProps<{ item: WardrobeItem; busy: boolean; sessionId?: string }>()
const emit = defineEmits<{
  edit: [item: WardrobeItem]
  remove: [item: WardrobeItem]
  wear: [item: WardrobeItem]
  carry: [item: WardrobeItem]
  place: [item: WardrobeItem]
  repaired: []
}>()
</script>

<template>
  <article
    class="rounded border border-slate-700 bg-slate-900/50 p-2"
    :data-wardrobe-item="item.id"
  >
    <div class="flex items-start justify-between gap-2">
      <div class="min-w-0 flex-1">
        <p class="break-words text-xs font-bold">{{ item.name || item.id }}</p>
        <p
          class="mt-1 text-[10px] uppercase tracking-wider"
          :class="item.worn ? 'text-emerald-300' : 'text-slate-400'"
        >
          {{
            item.location === 'scene'
              ? 'In room'
              : item.attachment_slot
                ? 'Placed on body'
                : item.worn
                  ? 'Worn'
                  : 'Inventory'
          }}
        </p>
        <p v-if="item.location === 'scene'" class="mt-1 text-xs text-cyan-200">
          {{ item.spatial_position || 'Position unspecified' }}
        </p>
        <p v-if="!item.clothing && !item.attachment_slot" class="mt-1 text-xs text-amber-200">
          Repair clothing metadata before putting this item on.
        </p>
      </div>
      <div class="flex w-24 shrink-0 flex-col gap-1.5 text-[10px]">
        <DebugItemRepair
          v-if="sessionId"
          :session-id="sessionId"
          :item-id="item.id"
          :name="item.name"
          stacked
          @repaired="emit('repaired')"
        />
        <button
          v-if="item.worn"
          type="button"
          :disabled="busy"
          class="rounded-full border border-amber-500/30 px-2 py-1 text-amber-200 disabled:opacity-40"
          @click="emit('remove', item)"
        >
          {{ item.attachment_slot ? 'Remove item' : 'Take off' }}
        </button>
        <button
          v-else-if="item.clothing"
          type="button"
          :disabled="busy"
          class="rounded-full border border-emerald-500/30 px-2 py-1 text-emerald-200 disabled:opacity-40"
          @click="emit('wear', item)"
        >
          Put on
        </button>
        <button
          v-if="item.location === 'scene'"
          type="button"
          :disabled="busy"
          class="rounded-full border border-cyan-500/30 px-2 py-1 text-cyan-200 disabled:opacity-40"
          @click="emit('carry', item)"
        >
          Take into inventory
        </button>
        <button
          v-else
          type="button"
          :disabled="busy"
          class="rounded-full border border-cyan-500/30 px-2 py-1 text-cyan-200 disabled:opacity-40"
          @click="emit('place', item)"
        >
          Place in room…
        </button>
        <button
          v-if="!item.attachment_slot && item.location !== 'scene'"
          type="button"
          :disabled="busy"
          class="inline-flex items-center justify-center gap-1 rounded-full border border-cyan-500/30 px-2 py-1 text-cyan-300 disabled:opacity-40"
          @click="emit('edit', item)"
        >
          <Pencil class="h-3 w-3" />Edit
        </button>
      </div>
    </div>
    <details v-if="item.description" class="mt-2 text-[11px] text-slate-400">
      <summary class="cursor-pointer text-cyan-300">Description</summary>
      <p class="mt-1 whitespace-pre-wrap">{{ item.description }}</p>
    </details>
    <p v-if="item.uncovered_regions?.length" class="mt-2 text-[10px] text-amber-200">
      Partially displaced — exposed: {{ item.uncovered_regions.join(', ') }}
    </p>
  </article>
</template>
