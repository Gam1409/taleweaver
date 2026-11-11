<script setup lang="ts">
import { computed, getCurrentInstance, watch } from 'vue'
import {
  EQUIPMENT_SLOTS,
  BODY_ITEM_SLOTS,
  type EquipmentDisplay,
  type EquipmentDisplayItem
} from '@/utils/equipmentSlots'
import { useEquipmentHover } from '@/composables/useEquipmentHover'
import EquipmentItemIcon from './EquipmentItemIcon.vue'
import maleSilhouette from '@/assets/svg/full-body-human-silhouette.svg'
import femaleSilhouette from '@/assets/female-equipment-silhouette.png'

defineOptions({ inheritAttrs: false })

const props = withDefaults(
  defineProps<{
    equipment: EquipmentDisplay
    variant?: 'male' | 'female' | 'neutral'
    compact?: boolean
    readOnly?: boolean
    miniList?: boolean
  }>(),
  { variant: 'neutral', compact: true, readOnly: true, miniList: true }
)
const emit = defineEmits<{
  select: [slot: string, item: EquipmentDisplayItem]
  itemHover: [item: EquipmentDisplayItem, event: MouseEvent]
  itemLeave: []
  itemContextmenu: [slot: string, item: EquipmentDisplayItem, event: MouseEvent]
}>()
const hover = useEquipmentHover()
const { active, target, style } = hover
const tooltipId = `equipment-hover-${getCurrentInstance()?.uid ?? 0}`
const source = computed(() => (props.variant === 'female' ? femaleSilhouette : maleSilhouette))
const extra = computed(() => BODY_ITEM_SLOTS.filter(slot => props.equipment[slot.key]?.length))
const slots = computed(() =>
  [...EQUIPMENT_SLOTS, ...extra.value].map(slot => ({
    ...slot,
    top: slot.key === 'Legs' && extra.value.length ? '73%' : slot.top,
    items: props.equipment[slot.key] || []
  }))
)
const selected = computed(() => slots.value.find(slot => slot.key === active.value))
watch(
  () => props.equipment,
  () => {
    if (!selected.value?.items.length) hover.close()
  },
  { deep: true }
)
function enter(key: string, items: EquipmentDisplayItem[], event: MouseEvent) {
  if (props.miniList || key.startsWith('Body')) void hover.open(key, event)
  else if (items[0]) emit('itemHover', items[0], event)
}
function leave() {
  hover.leave()
  emit('itemLeave')
}
function select(key: string, items: EquipmentDisplayItem[], event: MouseEvent) {
  if (!props.readOnly && !key.startsWith('Body') && items[0]) emit('select', key, items[0])
  else if (props.miniList || key.startsWith('Body')) void hover.open(key, event, true)
}
function context(key: string, items: EquipmentDisplayItem[], event: MouseEvent) {
  if (props.readOnly || key.startsWith('Body') || !items[0]) return
  event.preventDefault()
  emit('itemContextmenu', key, items[0], event)
}
</script>

<template>
  <div
    v-bind="$attrs"
    class="equipment-silhouette relative flex w-full items-center justify-center overflow-hidden rounded-3xl border border-slate-800/60 bg-slate-950/40 shadow-inner"
    :class="compact ? 'h-[440px] sm:h-[480px]' : 'h-[360px] sm:h-[440px]'"
    :data-silhouette="variant"
  >
    <img
      :src="source"
      alt=""
      class="pointer-events-none h-full w-full object-contain opacity-35 invert"
    />
    <button
      v-for="slot in slots"
      :key="slot.key"
      type="button"
      :data-equipment-slot="slot.key"
      :style="{ top: slot.top, left: slot.left }"
      :aria-label="
        [slot.label, ...slot.items.map(item => item.name)].filter(Boolean).join(': ') || 'Contents'
      "
      :aria-describedby="
        active === slot.key && (miniList || slot.key.startsWith('Body')) ? tooltipId : undefined
      "
      class="group/slot absolute flex -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-xl border bg-slate-950/90 shadow-lg focus-visible:outline-amber-300"
      :class="[
        compact ? (slot.label ? 'h-10 w-10' : 'h-7 w-7') : 'h-12 w-12 sm:h-15 sm:w-15',
        slot.items.length
          ? 'border-amber-500/70 text-slate-200'
          : 'border-slate-700 text-slate-600',
        active === slot.key ? 'z-10 ring-2 ring-amber-400/25' : ''
      ]"
      @mouseenter="enter(slot.key, slot.items, $event)"
      @mouseleave="leave"
      @focus="(miniList || slot.key.startsWith('Body')) && hover.open(slot.key, $event)"
      @blur="hover.leave()"
      @click="select(slot.key, slot.items, $event)"
      @contextmenu="context(slot.key, slot.items, $event)"
    >
      <span v-if="compact && slot.items.length > 1" class="relative h-7 w-8" aria-hidden="true">
        <span
          class="absolute left-0 top-0 flex h-5 w-5 items-center justify-center rounded border border-slate-600 bg-slate-800"
          ><EquipmentItemIcon :item="slot.items[1]" :icon="slot.icon"
        /></span>
        <span
          class="absolute bottom-0 right-0 flex h-5 w-5 items-center justify-center rounded border border-slate-400 bg-slate-700"
          ><EquipmentItemIcon :item="slot.items[0]" :icon="slot.icon"
        /></span>
      </span>
      <EquipmentItemIcon
        v-else-if="slot.items[0]"
        :item="slot.items[0]"
        :icon="slot.icon"
        :compact="compact"
      />
      <i
        v-else
        :class="['ra', slot.icon, compact ? 'text-[14px]' : 'text-xl']"
        aria-hidden="true"
      ></i>
      <span
        v-if="slot.items.length > 1"
        class="absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded bg-amber-400 px-0.5 text-[9px] font-bold text-slate-950"
        >{{ slot.items.length }}</span
      >
      <span
        v-if="slot.label"
        class="absolute left-1/2 top-full mt-1 -translate-x-1/2 whitespace-nowrap text-[10px] text-slate-400"
        :class="
          compact ? '' : 'rounded bg-slate-950/95 px-1 opacity-0 group-hover/slot:opacity-100'
        "
        >{{ slot.label }}</span
      >
    </button>
  </div>
  <Teleport
    v-if="(miniList || active.startsWith('Body')) && active && target && selected"
    :to="target"
  >
    <div
      :id="tooltipId"
      :ref="element => (hover.popup.value = element as HTMLElement | null)"
      role="tooltip"
      :style="style"
      class="equipment-hover fixed z-[300] max-h-[min(24rem,70dvh)] min-w-40 max-w-[min(20rem,calc(100vw_-_1.25rem))] overflow-y-auto rounded-xl border border-slate-600 bg-slate-900/95 p-3 text-sm text-slate-200 shadow-2xl backdrop-blur"
      @mouseenter="hover.retain"
      @mouseleave="hover.leave"
    >
      <p v-if="selected.label" class="mb-2 text-xs font-semibold text-amber-200">
        {{ selected.label }}
      </p>
      <ul v-if="selected.items.length" class="space-y-2.5">
        <li v-for="item in selected.items" :key="item.id" class="flex items-start gap-2.5">
          <span class="mt-0.5 shrink-0"
            ><EquipmentItemIcon :item="item" :icon="selected.icon"
          /></span>
          <div class="min-w-0">
            <p class="break-words text-xs">{{ item.name }}</p>
            <p v-if="item.uncovered_regions?.length" class="mt-1 text-[10px] text-amber-200">
              Partially displaced
            </p>
          </div>
        </li>
      </ul>
      <span v-else class="text-slate-500">—</span>
    </div>
  </Teleport>
</template>
