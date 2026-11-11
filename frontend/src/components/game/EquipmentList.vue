<script setup lang="ts">
import type { EquipmentDisplayItem } from '@/utils/equipmentSlots'
import EquipmentItemIcon from './EquipmentItemIcon.vue'
defineProps<{ items: EquipmentDisplayItem[] }>()
</script>

<template>
  <ul class="space-y-2.5">
    <li
      v-for="item in items"
      :key="item.id"
      class="flex min-w-0 items-start gap-3 rounded-xl border border-slate-700/70 bg-slate-950/30 p-3"
    >
      <span class="mt-0.5 shrink-0"><EquipmentItemIcon :item="item" /></span>
      <div class="min-w-0">
        <p class="break-words text-sm text-slate-200">{{ item.name }}</p>
        <p v-if="item.uncovered_regions?.length" class="mt-1 text-xs text-amber-200">
          Partially displaced
        </p>
      </div>
    </li>
  </ul>
</template>
