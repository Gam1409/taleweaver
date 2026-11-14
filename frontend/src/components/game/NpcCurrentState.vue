<script setup lang="ts">
import { computed, ref } from 'vue'
import type { NpcCurrentState } from '@/types/npcCurrentState'
import { BODY_ITEM_SLOTS, unassessedLayoutSlots, type EquipmentCondition, type EquipmentDisplay, type EquipmentDisplayItem } from '@/utils/equipmentSlots'
import EquipmentSilhouette from './EquipmentSilhouette.vue'
import EquipmentList from './EquipmentList.vue'

const props = defineProps<{ state?: NpcCurrentState; compact?: boolean }>()
const showEmpty = ref(false)
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
type DisplayPlacement = { key: string; status: 'empty' | 'occupied' | 'unconfirmed' | 'unassessed' }
const placementSlots = computed(() => {
  const slots: DisplayPlacement[] = [...(props.state?.clothing.placement_slots ?? [])]
  const layout = props.state?.layout
  if ((!props.compact || showEmpty.value) && layout?.form === 'humanoid' && props.state?.clothing.placement_status === 'unassessed') {
    for (const slot of unassessedLayoutSlots(layout.silhouette)) {
      if (!slots.some(row => row.key === slot.key)) slots.push({ key: slot.key, status: 'unassessed' })
    }
  }
  return slots.filter(slot => slot.status !== 'empty' || !props.compact || showEmpty.value || props.state?.conditions.items.some(condition => condition.display_slots?.includes(slot.key)))
})
const bodyConditions = computed(() => {
  const result: Record<string, EquipmentCondition[]> = {}
  for (const condition of props.state?.conditions.items ?? []) {
    if (allItems.value.some(item => item.id === condition.target_id)) continue
    for (const slot of condition.display_slots ?? []) (result[slot] ??= []).push(condition)
  }
  return result
})
const itemConditions = computed(() => {
  const result: Record<string, EquipmentCondition[]> = {}
  for (const condition of props.state?.conditions.items ?? []) {
    if (allItems.value.some(item => item.id === condition.target_id)) (result[condition.target_id] ??= []).push(condition)
  }
  return result
})
function slotLabel(key: string) { return BODY_ITEM_SLOTS.find(slot => slot.key === key)?.label ?? 'Placement area' }
const kinds = {
  injury: 'Injury',
  contamination: 'Contamination',
  fluid: 'Fluid',
  pain: 'Pain',
  other: 'Physical condition',
  item_state: 'Item state'
}
const statuses = { active: 'Active', treated: 'Treated', reduced: 'Reduced' }
</script>

<template>
  <section
    v-if="state?.availability === 'present'"
    aria-label="Clothing and physical condition"
    class="npc-current-state grid items-start gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]"
  >
    <section class="min-w-0 space-y-3" aria-label="Clothing">
      <h3 class="font-semibold text-slate-100">Clothing</h3>
      <label v-if="compact && (state.layout?.form === 'humanoid' || state.clothing.placement_slots?.length)" class="flex items-center gap-2 text-xs text-slate-400"><input v-model="showEmpty" type="checkbox" class="accent-amber-400" />Show empty slots</label>
      <template v-if="state.layout?.form === 'humanoid'">
        <EquipmentSilhouette :equipment="equipment" :variant="state.layout.silhouette" :body-slots="placementSlots.map(slot => slot.key)" :unconfirmed-body-slots="placementSlots.filter(slot => slot.status === 'unconfirmed').map(slot => slot.key)" :unassessed-body-slots="placementSlots.filter(slot => slot.status === 'unassessed').map(slot => slot.key)" :body-conditions="bodyConditions" :item-conditions="itemConditions" :data-hide-empty="compact && !showEmpty" />
        <EquipmentList v-if="unassigned.length" :items="unassigned" />
      </template>
      <EquipmentList v-else :items="allItems" />
      <ul v-if="placementSlots.length" class="space-y-1.5 text-xs" aria-label="Additional placement areas"><li v-for="slot in placementSlots" :key="slot.key" class="flex flex-wrap justify-between gap-2 rounded-lg border border-slate-700/70 px-3 py-2"><span class="text-slate-300">{{ slotLabel(slot.key) }}</span><span :class="slot.status === 'unconfirmed' ? 'text-amber-200' : 'text-slate-400'">{{ slot.status === 'occupied' ? 'Item recorded' : slot.status === 'unconfirmed' ? 'Placement needs confirmation' : slot.status === 'unassessed' ? 'Not assessed' : 'No recorded item' }}</span></li></ul>
      <p v-if="state.clothing.placement_status === 'unassessed'" class="text-xs leading-relaxed text-slate-400">Additional area availability is not fully assessed. Only established areas are shown.</p>
      <p v-else-if="state.clothing.placement_status === 'unavailable'" class="text-xs leading-relaxed text-slate-400">No additional placement areas are available in the recorded body layout.</p>
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
          <p v-if="condition.visibility === 'private'" class="mt-2 text-xs text-amber-200" title="Known to you from narration; this does not make the fact shared knowledge.">Known from narration</p>
          <p class="mt-2 whitespace-pre-wrap break-words leading-relaxed text-slate-200">
            {{ condition.detail }}
          </p>
        </li>
      </ul>
    </section>
  </section>
</template>
