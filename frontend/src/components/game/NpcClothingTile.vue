<script setup lang="ts">
import { computed, ref } from 'vue'
import type { NpcVisibleGarment } from '@/types/npcCurrentState'
import { getImageUrl } from '@/utils/game_icons'
import ItemImagePlaceholder from './ItemImagePlaceholder.vue'

const props = defineProps<{ item: NpcVisibleGarment }>()
const brokenImage = ref('')
const image = computed(() => getImageUrl(props.item.image_url))
</script>

<template>
  <li class="min-w-0 overflow-hidden rounded-xl border border-slate-700 bg-slate-950/50">
    <div class="relative aspect-square bg-black/15 p-2">
      <img
        v-if="image && brokenImage !== image"
        :src="image"
        :alt="item.name"
        loading="lazy"
        class="h-full w-full rounded-lg object-contain"
        @error="brokenImage = image"
      />
      <ItemImagePlaceholder v-else />
      <span
        class="absolute bottom-2 left-2 rounded-md border border-emerald-400/30 bg-slate-950/90 px-2 py-1 text-[10px] font-semibold text-emerald-200"
        >Visible · Layer {{ item.layer }}</span
      >
    </div>
    <div class="space-y-2 p-3">
      <p class="break-words text-sm font-semibold text-slate-100">
        {{ item.name || 'Unnamed garment' }}
      </p>
      <span
        v-if="item.uncovered_regions.length"
        class="inline-block rounded border border-amber-400/30 bg-amber-400/10 px-2 py-1 text-xs text-amber-100"
        >Partially displaced</span
      >
      <p class="text-xs text-slate-400">Visible on: {{ item.visible_regions.join(', ') }}</p>
      <details v-if="item.description" class="text-xs text-slate-300">
        <summary class="cursor-pointer text-slate-400">Description</summary>
        <p class="mt-2 whitespace-pre-wrap break-words leading-relaxed">{{ item.description }}</p>
      </details>
    </div>
  </li>
</template>
