<script setup lang="ts">
import type { ClothingDraft } from '@/services/clothingAuthoring'
import type { NpcItemDraft } from '@/services/npcCreation'
import ClothingItemFields from './ClothingItemFields.vue'

const props = defineProps<{ items: NpcItemDraft[]; selected: boolean[]; disabled: boolean }>()
const emit = defineEmits<{
  (e: 'update:items', value: NpcItemDraft[]): void
  (e: 'update:selected', value: boolean[]): void
}>()
function update(index: number, patch: Partial<NpcItemDraft>) {
  emit('update:items', props.items.map((item, i) => i === index ? { ...item, ...patch } : item))
}
function select(index: number, event: Event) {
  emit('update:selected', props.selected.map((checked, i) => i === index ? (event.target as HTMLInputElement).checked : checked))
}
function updateClothing(index: number, clothing: ClothingDraft) {
  update(index, { clothing: { ...props.items[index]!.clothing!, ...clothing } })
}
</script>

<template>
  <section aria-label="NPC clothing and belongings" class="space-y-3">
    <h3 class="font-bold text-emerald-300">Clothing &amp; belongings ({{ selected.filter(Boolean).length }}/{{ items.length }})</h3>
    <p class="text-xs text-slate-400">Only checked items will be created. Worn clothes keep their layers; other items are carried by this NPC. Images can be generated after saving.</p>
    <p v-if="!items.length" class="text-sm text-slate-400">No clothing or belongings proposed.</p>
    <details v-for="(item, index) in items" :key="index" class="rounded-xl border border-white/10 bg-slate-950/60 p-3">
      <summary class="flex cursor-pointer items-center gap-3 text-sm">
        <input type="checkbox" :aria-label="`Include ${item.name}`" :checked="selected[index]" :disabled="disabled" @click.stop @change="select(index, $event)" class="accent-emerald-500">
        <span class="flex-1 font-bold text-white">{{ item.name }}</span>
        <span class="text-xs text-slate-400">{{ item.worn ? 'Worn' : 'Carried' }}<template v-if="item.clothing"> · Layer {{ item.clothing.layer }}</template></span>
      </summary>
      <fieldset :disabled="disabled || !selected[index]" class="mt-4 space-y-3 disabled:opacity-50">
        <label class="block text-sm text-slate-300">Item name
          <input :value="item.name" maxlength="50" required @input="update(index, { name: ($event.target as HTMLInputElement).value })" class="mt-1 w-full rounded-xl border border-white/10 bg-slate-800 p-3">
        </label>
        <label class="block text-sm text-slate-300">Item description
          <textarea :value="item.description" :maxlength="item.item_type === 'READABLE' ? 200 : 1000" rows="3" required @input="update(index, { description: ($event.target as HTMLTextAreaElement).value })" class="mt-1 w-full resize-y rounded-xl border border-white/10 bg-slate-800 p-3" />
        </label>
        <label v-if="item.clothing" class="flex items-center gap-2 text-sm text-slate-300">
          <input type="checkbox" :checked="item.worn" @change="update(index, { worn: ($event.target as HTMLInputElement).checked })" class="accent-emerald-500">Worn by this NPC
        </label>
        <p v-if="item.clothing?.underwear" class="text-xs text-slate-400">Inner clothing. Opaque outer layers hide it from other characters.</p>
        <ClothingItemFields v-if="item.clothing" :model-value="item.clothing" :name="item.name" :description="item.description" :slots="item.wearable_slots" :disabled="disabled || !selected[index]" @update:model-value="updateClothing(index, $event)" />
        <label v-if="item.item_type === 'READABLE'" class="block text-sm text-slate-300">Readable text
          <textarea :value="item.text_log_content" maxlength="1000" rows="3" @input="update(index, { text_log_content: ($event.target as HTMLTextAreaElement).value })" class="mt-1 w-full rounded-xl border border-white/10 bg-slate-800 p-3" />
        </label>
      </fieldset>
    </details>
  </section>
</template>
