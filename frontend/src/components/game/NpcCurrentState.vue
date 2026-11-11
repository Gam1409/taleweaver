<script setup lang="ts">
import { computed } from 'vue'
import type { NpcCurrentState } from '@/types/npcCurrentState'
import type { EquipmentDisplay, EquipmentDisplayItem } from '@/utils/equipmentSlots'
import EquipmentSilhouette from './EquipmentSilhouette.vue'
import EquipmentList from './EquipmentList.vue'

const props = defineProps<{ state?: NpcCurrentState }>()
const equipment = computed(() => {
  const result: EquipmentDisplay = {}
  for (const item of props.state?.clothing.items || []) {
    for (const slot of item.slots || []) (result[slot] ||= []).push({ ...item, id: item.item_id })
  }
  return result
})
const allItems = computed<EquipmentDisplayItem[]>(() =>
  (props.state?.clothing.items || []).map(item => ({ ...item, id: item.item_id }))
)
const unassigned = computed(() =>
  allItems.value.filter(item => !(item.slots as string[] | undefined)?.length)
)
const kinds = {
  injury: 'Injury',
  contamination: 'Contamination',
  fluid: 'Fluid',
  pain: 'Pain',
  other: 'Physical condition'
}
const statuses = { active: 'Active', treated: 'Treated', reduced: 'Reduced' }
</script>

<template>
  <section
    v-if="state?.availability === 'present'"
    aria-label="Clothing and physical condition"
    class="grid items-start gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]"
  >
    <section class="min-w-0 space-y-3" aria-label="Clothing">
      <h3 class="font-semibold text-slate-100">Clothing</h3>
      <template v-if="state.layout?.form === 'humanoid'">
        <EquipmentSilhouette :equipment="equipment" :variant="state.layout.silhouette" />
        <EquipmentList v-if="unassigned.length" :items="unassigned" />
      </template>
      <EquipmentList v-else :items="allItems" />
    </section>
    <section class="min-w-0" aria-label="Physical condition">
      <h3 class="font-semibold text-slate-100">Physical condition</h3>
      <ul v-if="state.conditions.items.length" class="mt-3 space-y-3">
        <li
          v-for="condition in state.conditions.items"
          :key="condition.id"
          class="rounded-xl border border-rose-400/20 bg-rose-400/5 p-3"
        >
          <div class="flex flex-wrap items-center justify-between gap-2 text-xs">
            <span class="font-semibold text-rose-200"
              >{{ kinds[condition.kind] }} · {{ condition.part }}</span
            >
            <span class="rounded bg-slate-950/60 px-2 py-1 text-slate-300">{{
              statuses[condition.status]
            }}</span>
          </div>
          <p v-if="condition.target_name" class="mt-2 text-xs text-slate-400">
            {{ condition.target_name }}
          </p>
          <p class="mt-2 whitespace-pre-wrap break-words leading-relaxed text-slate-200">
            {{ condition.detail }}
          </p>
        </li>
      </ul>
    </section>
  </section>
</template>
