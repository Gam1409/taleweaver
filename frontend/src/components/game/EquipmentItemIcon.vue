<script setup lang="ts">
import { computed, ref } from 'vue'
import { getImageUrl } from '@/utils/game_icons'
import type { EquipmentDisplayItem } from '@/utils/equipmentSlots'

const props = withDefaults(
  defineProps<{ item: EquipmentDisplayItem; icon?: string; compact?: boolean }>(),
  { icon: 'ra-vest', compact: true }
)
const broken = ref('')
const image = computed(() => getImageUrl(props.item.image_url))
</script>

<template>
  <img
    v-if="image && broken !== image"
    :src="image"
    alt=""
    :class="
      compact
        ? 'h-3.5 w-3.5 rounded-sm object-contain'
        : 'h-full w-full rounded-lg object-cover object-top'
    "
    @error="broken = image"
  />
  <i v-else :class="['ra', icon, compact ? 'text-[14px]' : 'text-xl']" aria-hidden="true"></i>
</template>
